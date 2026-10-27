"""Receipt-bound raw accounting only; no language admission of old graphs."""
from pathlib import Path
from hashlib import sha256
import gzip
import json

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
receipts = []
def load(path):
    path = Path(path).resolve(); raw = path.read_bytes()
    decoded = gzip.decompress(raw) if path.suffix == '.gz' else raw
    receipts.append({'path': str(path), 'sha256': sha256(raw).hexdigest(), 'bytes': len(raw),
                     'decoded_sha256': sha256(decoded).hexdigest(), 'decoded_bytes': len(decoded)})
    return json.loads(decoded)
def member(root, ref):
    path = Path(ref['uri']) if ref['external'] else root / ref['uri']
    value = load(path); got = receipts[-1]
    if (got['sha256'], got['bytes'], got['decoded_sha256'], got['decoded_bytes']) != (
            ref['physical_sha256'], ref['physical_bytes'], ref['decoded_sha256'], ref['decoded_bytes']):
        raise ValueError('original artifact stored/decoded receipt differs')
    return value
def stats(fields):
    graph, model = fields.get('graph'), fields.get('structured')
    return {'graph_present': int(graph is not None), 'operations': len(graph['operations']) if graph else 0,
        'values': len(graph['values']) if graph else 0, 'regions': len(graph['regions']) if graph else 0,
        'locations': len(graph['locations']) if graph else 0,
        'ordered_uses': sum(len(op['uses']) for op in graph['operations']) if graph else 0,
        'bound_interface': int(fields.get('interface') is not None), 'structured_body': int(model is not None),
        'protocols': len(model['protocols']) if model else 0, 'loops': len(model['loops']) if model else 0}

comp_path = ROOT / 'artifacts/experiments/first_stage_source_publication_current_20261023/result/composition/index.json.gz'
composition = load(comp_path)
manifest_path = Path(composition['inventory']['path']); manifest = load(manifest_path)
if (receipts[-1]['sha256'], receipts[-1]['bytes']) != (
        composition['inventory']['raw_sha256'], composition['inventory']['raw_bytes']):
    raise ValueError('actual parent inventory differs from composition')
interfaces = member(manifest_path.parent, manifest['components']['interfaces'])['value']
structured = member(manifest_path.parent, manifest['components']['structured'])['value']
header = member(manifest_path.parent, manifest['components']['header'])['value']
new_paths = (
    ROOT / 'artifacts/experiments/first_stage_tuple_key_bodies_20261023/attempt-02/source-program5.json.gz',
    ROOT / 'artifacts/experiments/first_stage_tuple_key_heap_attempt02_20261023/source-program5.json.gz',
)
pairs = []
for new_path in new_paths:
    new = load(new_path); new_receipt = receipts[-1]
    fi, = [i for i, file in enumerate(composition['files']) if file['snapshot'] == new['metadata']['source']]
    bi, = [i for i, body in enumerate(composition['files'][fi]['bodies'])
           if body['definition'] == new['interface']['definition']['wire']]
    file = member(manifest_path.parent, manifest['files'][fi])['file']; old_body = file['bodies'][bi]
    cp_ref = old_body['checkpoint']
    cp = member(manifest_path.parent, cp_ref)
    if cp['schema_version'] == 2:
        old = member(Path(cp_ref['uri']).parent, cp['source_program'])
    else:
        old = cp
    old_stats, new_stats = stats(old), stats(new)
    pair = {'definition': new['interface']['definition'], 'snapshot': new['metadata']['source'],
        'file_index': fi, 'body_index': bi, 'old_status': old_body['status'],
        'old_checkpoint': cp_ref, 'old_namespace': composition['files'][fi]['bodies'][bi].get('namespace'),
        'old_raw_stats': old_stats, 'new_raw_stats': new_stats,
        'stats_delta': {key: new_stats[key] - old_stats[key] for key in old_stats},
        'old_construction_operations': old_body['construction_operations'],
        'new_construction_operations_from_source_program': None,
        'new_program_receipt': new_receipt,
        'old_graph_was_not_new_language_validated': True}
    for name, refs in (('interfaces', interfaces['bodies']), ('structured', structured)):
        normalized = lambda ref: {**ref, 'uri': str(Path(ref['uri']).resolve()) if ref['external']
                                  else str((manifest_path.parent / ref['uri']).resolve()), 'external': True}
        target = normalized(cp_ref)
        pair['old_active_' + name + '_positions'] = [i for i, ref in enumerate(refs) if normalized(ref) == target]
    pairs.append(pair)
aggregate = {key: sum(row['stats_delta'][key] for row in pairs) for key in pairs[0]['stats_delta']}
report = {'schema': 'scar.source-body-revision-accounting-audit', 'schema_version': 1,
    'scope': 'IMMUTABLE_RAW_ACCOUNTING_ONLY_NOT_OLD_MODEL_LEGALITY', 'pairs': pairs,
    'aggregate_delta': aggregate, 'parent_manifest_counts': manifest['counts'],
    'parent_header_summary': header['summary'], 'input_receipts': receipts,
    'prepare_compile_target_execution_performed': False, 'new_publication_performed': False}
(HERE / 'raw-counts.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'pairs': len(pairs), 'aggregate_delta': aggregate,
                  'old_costs': [row['old_construction_operations'] for row in pairs]}))
