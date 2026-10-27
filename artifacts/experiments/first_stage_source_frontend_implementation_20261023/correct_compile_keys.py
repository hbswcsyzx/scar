"""Correct an earlier metadata criterion; no source/graph/CodeType is loaded."""
from collections import Counter
import __future__
import gzip
from hashlib import sha256
import json
from pathlib import Path

from scar.analysis.call_compilation import compile_cache_key
from scar.ir.program.compilation import CallCompilationProfile
from scar.ir.record_codec import encode

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EX = ROOT / 'artifacts/experiments'
OLD = ROOT / 'artifacts/analysis/source_frontend_worklist_20261023'


def receipt(path):
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': sha256(raw).hexdigest(), 'bytes': len(raw)}


manifest_path = EX / 'first_stage_full_inventory_restored_20261023/result/manifest.json'
manifest = json.loads(manifest_path.read_text())
source_ref = manifest['components']['call_sources']
source_path = manifest_path.parent / source_ref['uri']
stored = source_path.read_bytes(); decoded = gzip.decompress(stored)
assert sha256(stored).hexdigest() == source_ref['physical_sha256']
assert sha256(decoded).hexdigest() == source_ref['decoded_sha256']
source_model = json.loads(decoded)['value']['model']
links = {row['code']: row for row in source_model['code_links']}
binding_path = EX / 'first_stage_current_source_gate_20261023/result/source/bindings.json'
binding_document = json.loads(binding_path.read_text())
binding_receipt = receipt(binding_path)
witness_path = EX / 'first_stage_partitioned_operand_routes_20261023/result/code-witnesses/manifest.json'
witness = json.loads(witness_path.read_text())
rows_path = OLD / 'missing-bodies.jsonl.gz'
rows = [json.loads(line) for line in gzip.open(rows_path, 'rt')]
old_mask = 0
for name in __future__.all_feature_names:
    old_mask |= getattr(__future__, name).compiler_flag
changes = []
missing_compile_requests = {}
preferred_compile_requests = {}
new_counts, new_files, new_calls = Counter(), {}, Counter()
for row in rows:
    category = row['metadata_category']
    if category in ('SYNC_FUNCTION_MODULE_VARIANT_PRESENT', 'SYNC_FUNCTION_MODULE_VARIANT_MISSING'):
        matches = []
        key_records = []
        for code in row['code_variants']:
            link = links[code['key']]
            for level in link['optimize_levels']:
                key = encode(compile_cache_key(Path(link['snapshot']['path']), link['snapshot']['fingerprint'],
                    CallCompilationProfile.RECORDED_FUTURE_FLAGS, code['flags'], level,
                    compile_filename=code['filename']))
                old_key = {**key, 'future_flags': code['flags'] & old_mask}
                digest = lambda value: sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                    separators=(',', ':')).encode()).hexdigest()
                found = witness['modules'].get(digest(key))
                if found is not None and found['compile_key'] == key and found['snapshot'] == row['snapshot']:
                    matches.append(digest(key))
                key_records.append({'captured': code, 'old_invalid_metadata_criterion': old_key,
                    'old_criterion_key_sha256': digest(old_key), 'correct_compile_cache_key': key,
                    'correct_key_sha256': digest(key), 'correct_module_present': found is not None,
                    'correct_module_ref': found['artifact'] if found is not None else None})
        updated = 'SYNC_FUNCTION_MODULE_VARIANT_PRESENT' if matches else 'SYNC_FUNCTION_MODULE_VARIANT_MISSING'
        if not matches:
            for request in key_records:
                key = request['correct_key_sha256']
                entry = missing_compile_requests.setdefault(key, {'compile_key_sha256': key,
                    'compile_key': request['correct_compile_cache_key'], 'snapshot': row['snapshot'],
                    'body_references': [], 'captured_descriptors': []})
                entry['body_references'].append({'file_index': row['file_index'], 'body_index': row['body_index'],
                    'definition': row['definition'], 'current_calls': row['current_calls']})
                if request['captured'] not in entry['captured_descriptors']:
                    entry['captured_descriptors'].append(request['captured'])
            for code in row['code_variants']:
                alternatives = [request for request in key_records if request['captured'] == code]
                preferred = min(alternatives, key=lambda request: request['correct_compile_cache_key']['optimize'])
                key = preferred['correct_key_sha256']
                entry = preferred_compile_requests.setdefault(key, {'compile_key_sha256': key,
                    'compile_key': preferred['correct_compile_cache_key'], 'snapshot': row['snapshot'],
                    'body_references': []})
                entry['body_references'].append({'file_index': row['file_index'], 'body_index': row['body_index'],
                    'definition': row['definition'], 'captured': code, 'current_calls': row['current_calls']})
        if updated != category:
            fi, bi = row['file_index'], row['body_index']
            file_ref = manifest['files'][fi]; file_path = manifest_path.parent / file_ref['uri']
            raw = file_path.read_bytes(); payload = gzip.decompress(raw)
            assert sha256(raw).hexdigest() == file_ref['physical_sha256']
            assert sha256(payload).hexdigest() == file_ref['decoded_sha256']
            source_file = json.loads(payload)['file']
            body = source_file['bodies'][bi]
            assert body['definition'] == row['definition']
            changes.append({'old_category': category, 'correct_category': updated,
                'body_locator': {'artifact': {**file_ref, 'uri': str(file_path)}, 'pointer': f'#/file/bodies/{bi}'},
                'snapshot': row['snapshot'], 'context': row['context'], 'definition': row['definition'],
                'current_calls': row['current_calls'], 'current_groups': row['current_groups'],
                'compile_keys': key_records, 'source_shard_receipt': receipt(file_path),
                'current_binding_locators': [{'artifact': binding_receipt, 'pointer': f"#/bindings/{binding['binding_index']}",
                    'process_id': binding['process_id'], 'entered_invocations': binding['entered_invocations'],
                    'code': binding['code']} for binding in binding_document['bindings']
                    if binding['code'] in {code['key'] for code in row['code_variants']}]})
        category = updated
    new_counts[category] += 1
    new_calls[category] += row['current_calls']
    new_files.setdefault(category, set()).add(row['snapshot']['path'])
result = {'schema': 'scar.source-worklist-metadata-correction', 'schema_version': 1,
    'scope': 'original pre-publication immutable metadata only; not the later actual worklist plan',
    'cause': '__future__.nested_scopes.compiler_flag overlaps structural CO_NESTED=0x10; original criterion did not exclude structural flags',
    'rule': 'existing compile_cache_key RECORDED_FUTURE_FLAGS_V1, exact full key; never raw OR of future flags',
    'old_counts': {'present_bodies': 77, 'present_calls': 2751, 'missing_bodies': 12, 'missing_calls': 104},
    'correct_categories': dict(new_counts), 'correct_current_calls': dict(new_calls),
    'correct_source_files': {key: len(value) for key, value in new_files.items()},
    'changed_rows': changes, 'denominators': {'static_bodies': 2217, 'missing_bodies': len(rows),
        'current_groups': 817, 'current_calls': 100438},
    'missing_compile_requests': list(missing_compile_requests.values()),
    'preferred_compile_requests': list(preferred_compile_requests.values()),
    'preferred_selection': 'one lowest recorded matching optimize level per complete captured-code request; deduplicate exact compile key; alternatives are not all mandatory',
    'inputs': [receipt(path) for path in (OLD/'metadata.py', OLD/'summary.json', rows_path,
        manifest_path, source_path, witness_path, binding_path)],
    'original_artifacts_modified': False, 'source_or_graph_loaded': False, 'code_compiled_or_loaded': False,
    'complete_nested_codetype_verified': False}
(HERE/'metadata-correction.final.json').write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps({'changed_rows':len(changes), 'categories':dict(new_counts),
    'calls':dict(new_calls), 'files':result['correct_source_files']}, indent=2))
