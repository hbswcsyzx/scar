"""Read only bounded headers/bindings/manifest; no code, graph or source load."""
from collections import Counter, defaultdict
import __future__
import gzip
from hashlib import sha256
import inspect
import json
from pathlib import Path
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EX = ROOT / 'artifacts/experiments'
MANIFEST = EX / 'first_stage_full_inventory_restored_20261023/result/manifest.json'
REPORT = EX / 'first_stage_current_source_gate_20261023/result/source/report.json'
BINDINGS = REPORT.with_name('bindings.json')
WITNESSES = EX / 'first_stage_partitioned_operand_routes_20261023/result/code-witnesses/manifest.json'
started = time.perf_counter()
receipts = []


def read(path, expected=None):
    raw = path.read_bytes()
    stored = {'path': str(path), 'sha256': sha256(raw).hexdigest(), 'bytes': len(raw)}
    decoded = gzip.decompress(raw) if path.suffix == '.gz' else raw
    if expected is not None:
        assert stored['sha256'] == expected['physical_sha256'] and len(raw) == expected['physical_bytes']
        assert sha256(decoded).hexdigest() == expected['decoded_sha256'] and len(decoded) == expected['decoded_bytes']
    receipts.append(stored)
    return json.loads(decoded)


manifest = read(MANIFEST)
report = read(REPORT)
bindings = read(BINDINGS)
assert receipts[-1]['sha256'] == report['bindings']['raw_sha256']
assert receipts[-1]['bytes'] == report['bindings']['raw_bytes']
witness = read(WITNESSES)
component = manifest['components']['call_sources']
source_model = read(MANIFEST.parent / component['uri'], component)['value']['model']
descriptors = {}
for capture in source_model['codes']:
    code = capture['code']
    assert code['key'] not in descriptors or descriptors[code['key']] == code
    descriptors[code['key']] = code
links = {row['code']: row for row in source_model['code_links']}
future_mask = 0
for name in __future__.all_feature_names:
    future_mask |= getattr(__future__, name).compiler_flag
suspended_mask = inspect.CO_GENERATOR | inspect.CO_COROUTINE | inspect.CO_ASYNC_GENERATOR | inspect.CO_ITERABLE_COROUTINE
modules = list(witness['modules'].values())


def module_variant(code, link):
    if link is None or link['status'] != 'VERIFIED' or not link['optimize_levels']:
        return False
    return any(row['snapshot'] == link['snapshot']
        and row['compile_key']['profile'] == 'RECORDED_FUTURE_FLAGS_V1'
        and row['compile_key']['compile_filename'] == code['filename']
        and row['compile_key']['future_flags'] == code['flags'] & future_mask
        and row['compile_key']['optimize'] in link['optimize_levels']
        and row['compile_key']['dont_inherit'] is True and row['compile_key']['mode'] == 'exec'
        for row in modules)


definitions = {}
body_rows = []
statuses, kinds, status_kinds = Counter(), Counter(), Counter()
for fi, ref in enumerate(manifest['files']):
    path = Path(ref['uri']) if ref['external'] else MANIFEST.parent / ref['uri']
    file = read(path, ref)['file']
    declared = {row['id']['wire']: row for row in file['definitions']}
    for bi, body in enumerate(file['bodies']):
        definition = declared[body['definition']['wire']]
        key = file['snapshot']['path'], file['snapshot']['fingerprint'], file['context']['namespace_root'], definition['id']['wire']
        assert key not in definitions
        item = {'file_index': fi, 'body_index': bi, 'definition': definition, 'snapshot': file['snapshot'],
            'context': file['context'], 'body_status': body['status']}
        definitions[key] = item
        body_rows.append(item)
        statuses[body['status']] += 1
        kinds[definition['kind']] += 1
        status_kinds[body['status'] + ':' + definition['kind']] += 1

static_recovery = Counter()
current_groups, current_calls = Counter(), Counter()
entry_groups, entry_calls = Counter(), Counter()
missing_items = []
observed_by_body = defaultdict(list)
for row in bindings['bindings']:
    count = row['entered_invocations']
    reference = row['definition']
    if row['body'] is not None:
        category = 'CURRENT_BODY_LINKED'
    elif reference is None:
        category = 'CURRENT_SOURCE_DEFINITION_UNRESOLVED'
    elif row.get('composition_element') is None:
        category = 'CURRENT_EXTERNAL_SOURCE_ONLY_NEEDS_ENTRY_CATALOG_AND_ADMISSION_SCOPE'
    else:
        key = reference['snapshot']['path'], reference['snapshot']['fingerprint'], reference['context']['namespace_root'], reference['definition']['wire']
        assert key in definitions
        item = definitions[key]
        observed_by_body[key].append(row)
        category = 'CURRENT_PROJECT_SOURCE_ONLY_' + item['body_status']
        kind = item['definition']['kind']
        code = row['code_capture']['code']
        if kind != 'FUNCTION':
            entry = 'ENTRY_ADAPTER_MISSING:' + kind
        elif code['flags'] & suspended_mask:
            entry = 'ENTRY_ADAPTER_MISSING:RESUMABLE_FUNCTION'
        else:
            link = links.get(code['key'])
            assert link is not None and descriptors[code['key']] == code
            assert link['snapshot'] == item['snapshot'] and link['definition'] == item['definition']['id']
            assert link['source'] == item['definition']['source']
            entry = 'SYNC_FUNCTION_MODULE_VARIANT_PRESENT' if module_variant(code, link) else 'SYNC_FUNCTION_MODULE_VARIANT_MISSING'
        entry_groups[entry] += 1
        entry_calls[entry] += count
    current_groups[category] += 1
    current_calls[category] += count

by_definition = defaultdict(list)
for code, link in links.items():
    if link['status'] == 'VERIFIED' and link['definition'] is not None and link['source'] is not None:
        by_definition[(link['snapshot']['path'], link['snapshot']['fingerprint'], link['definition']['wire'])].append((descriptors[code], link))
for key, item in definitions.items():
    if item['body_status'] == 'LOWERED_WITH_GAPS':
        continue
    kind = item['definition']['kind']
    matched = [(code, link) for code, link in by_definition[key[0], key[1], key[3]]
               if link['snapshot'] == item['snapshot'] and link['source'] == item['definition']['source']]
    if kind != 'FUNCTION':
        category = 'ENTRY_ADAPTER_MISSING:' + kind
    elif not matched:
        category = 'FUNCTION_WITHOUT_COMPLETE_CAPTURED_CODE_SOURCE_WITNESS'
    elif any(code['flags'] & suspended_mask for code, _ in matched):
        category = 'ENTRY_ADAPTER_MISSING:RESUMABLE_FUNCTION'
    elif any(module_variant(code, link) for code, link in matched):
        category = 'SYNC_FUNCTION_MODULE_VARIANT_PRESENT'
    else:
        category = 'SYNC_FUNCTION_MODULE_VARIANT_MISSING'
    static_recovery[category] += 1
    missing_items.append({'file_index': item['file_index'], 'body_index': item['body_index'],
        'snapshot': item['snapshot'], 'context': item['context'], 'definition': item['definition']['id'],
        'entry_kind': kind, 'body_status': item['body_status'], 'metadata_category': category,
        'code_variants': [code for code, _ in matched],
        'current_groups': len(observed_by_body[key]),
        'current_calls': sum(row['entered_invocations'] for row in observed_by_body[key])})
assert len(bindings['bindings']) == 817 and sum(current_calls.values()) == 100438
assert len(definitions) == 2217 and sum(static_recovery.values()) == 1377
result = {'scope': 'stdlib metadata projection only; no new modeling gate', 'source_files': len(manifest['files']),
    'definitions': len(definitions), 'static_statuses': dict(statuses), 'definition_kinds': dict(kinds),
    'status_by_kind': dict(sorted(status_kinds.items())), 'missing_body_categories': dict(sorted(static_recovery.items())),
    'current_run': report['run'], 'current_groups': dict(sorted(current_groups.items())),
    'current_calls': dict(sorted(current_calls.items())), 'current_source_only_entry_groups': dict(sorted(entry_groups.items())),
    'current_source_only_entry_calls': dict(sorted(entry_calls.items())),
    'code_witness_modules': len(witness['modules']), 'code_witness_sources': len(witness['sources']),
    'module_variant_present_is_complete_codetype_proof': False,
    'source_or_graph_loaded': False, 'source_prepared': False, 'code_compiled_or_loaded': False,
    'elapsed_s': time.perf_counter()-started, 'inputs': receipts, 'first_stage_complete': False}
(HERE / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
with gzip.open(HERE / 'missing-bodies.jsonl.gz', 'wt') as stream:
    for row in missing_items:
        stream.write(json.dumps(row, sort_keys=True) + '\n')
print(json.dumps({key: result[key] for key in ('static_statuses', 'status_by_kind', 'missing_body_categories',
    'current_groups', 'current_calls', 'current_source_only_entry_groups', 'current_source_only_entry_calls', 'elapsed_s')}, indent=2))
