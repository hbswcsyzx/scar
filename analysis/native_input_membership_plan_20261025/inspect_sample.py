"""One bounded read of the saved new CPU sample; design facts, no authority."""
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import sys

from scar.ir.execution.native_port_protocol import attributes, flat_native

B = Path(__file__).resolve().parents[2]
O = Path(__file__).resolve().parent
S = B / 'artifacts/experiments/native_tensor_inputs_probe_20261025'
trace = S / 'trace'
cache, receipts = {}, []
pins = {row['path']: row for row in json.loads((S / 'staging-manifest.json').read_bytes())['files']}


def read(path):
    path = Path(path)
    if path not in cache:
        raw = path.read_bytes()
        assert len(raw) <= 1000000
        pin = pins[str(path.relative_to(B))]
        assert len(raw) == pin['bytes'] and sha256(raw).hexdigest() == pin['sha256']
        cache[path] = raw
        receipts.append({'path': str(path), 'sha256': pin['sha256'], 'bytes': len(raw), 'reads': 1})
    return cache[path]


manifest_path = next(trace.glob('native-tensor-inputs.*/manifest.json'))
manifest = json.loads(read(manifest_path))
rows = []
for chunk in manifest['chunks']:
    raw = read(manifest_path.parent / chunk['path'])
    assert len(raw) == chunk['raw_bytes'] and sha256(raw).hexdigest() == chunk['raw_sha256']
    rows.extend(json.loads(line) for line in raw.splitlines())
eto_path = next(trace.glob('execution-trace.*.json'))
chrome_path = next(trace.glob('kineto.*.json'))
eto, chrome = json.loads(read(eto_path)), json.loads(read(chrome_path))
assert len(rows) == manifest['retained_rows'] == 43
pid = eto['pid']
cpu, rf_nodes = defaultdict(list), defaultdict(list)
categories = Counter()
for index, event in enumerate(chrome['traceEvents']):
    categories[str(event.get('cat'))] += 1
    args = event.get('args', {})
    external = args.get('External id')
    if (event.get('ph') == 'X' and event.get('cat') in ('cpu_op', 'user_annotation')
            and event.get('pid') == pid and type(external) is int and external > 0):
        cpu[external].append((index, event))
for ordinal, node in enumerate(eto['nodes']):
    attrs = attributes(node)
    rf = attrs.get('rf_id')
    if type(rf) is int and rf > 0:
        rf_nodes[rf].append((ordinal, node))

counts, opaque_types, scalar_types = Counter(), Counter(), Counter()
issues, joins, tree_matches = [], [], {}
for row in rows:
    counts['tree_rows'] += 1
    candidates = cpu.get(row['event']['correlation_id'], [])
    if len(candidates) != 1:
        issues.append({'index': row['index'], 'code': 'CPU_EXTERNAL_ID_MISSING_OR_NONUNIQUE', 'candidates': len(candidates)})
        continue
    event_index, event = candidates[0]
    rf = event['args'].get('Record function id')
    native = rf_nodes.get(rf, [])
    if len(native) != 1:
        issues.append({'index': row['index'], 'code': 'ETO_RF_MISSING_OR_NONUNIQUE', 'candidates': len(native)})
        continue
    ordinal, node = native[0]
    attrs = attributes(node)
    if row['event']['record_function_thread_token'] != attrs.get('tid'):
        issues.append({'index': row['index'], 'code': 'RF_THREAD_CONTRADICTION'})
    if row['name'] != node['name'] or event['name'] != node['name']:
        issues.append({'index': row['index'], 'code': 'ALREADY_KEY_JOINED_NAME_CONTRADICTION'})
    if len(row['inputs']['slots']) != len(node['inputs']['values']):
        issues.append({'index': row['index'], 'code': 'TOP_LEVEL_ARITY_CONTRADICTION'})
    schema = attrs.get('op_schema')
    has_schema = type(schema) is str and bool(schema)
    counts['schema_available' if has_schema else 'schema_unavailable'] += 1
    counts['correlation_numerically_equals_RF'] += row['event']['correlation_id'] == rf
    counts['RF_thread_matches'] += row['event']['record_function_thread_token'] == attrs.get('tid')
    native_ports = flat_native(node['inputs'])
    tensors = {tuple(port['path']): port for port in native_ports if port['tensor']}
    metadata = []
    for slot in row['inputs']['slots']:
        counts['slot_' + slot['kind']] += 1
        if slot['kind'] == 'TENSOR':
            metadata.append(slot)
        elif slot['kind'] == 'TENSOR_LIST':
            metadata.extend(slot['items'])
            if not slot['items']:
                counts['empty_tensor_lists'] += 1
        elif slot['kind'] == 'OPAQUE':
            opaque_types[node['inputs']['types'][slot['ordinal']]] += 1
        elif slot['kind'] == 'SCALAR_OPAQUE':
            scalar_types[node['inputs']['types'][slot['ordinal']]] += 1
    observed_paths = set()
    for item in metadata:
        path = tuple(item['path'])
        observed_paths.add(path)
        port = tensors.get(path)
        if port is None:
            issues.append({'index': row['index'], 'code': 'METADATA_NOT_AT_NATIVE_TENSOR_PATH', 'path': list(path)})
            continue
        meta = item['metadata']
        if not (meta['sizes'] == port['shape'] and meta['strides'] == port['strides']
                and meta['device']['text'] == port['value'][5]):
            issues.append({'index': row['index'], 'code': 'ALREADY_PATH_JOINED_GEOMETRY_CONTRADICTION', 'path': list(path)})
        counts['tensor_metadata_paths'] += 1
        counts['tensor_metadata_paths_with_schema' if has_schema else 'tensor_metadata_paths_without_schema'] += 1
    missing = set(tensors) - observed_paths
    counts['native_tensor_paths_without_metadata'] += len(missing)
    tree_matches[row['event']['result_id']] = node['id']
    joins.append({'tree_index': row['index'], 'tree_result_id': row['event']['result_id'],
        'tree_parent_result_id': row['event']['parent_result_id'], 'correlation_id': row['event']['correlation_id'],
        'kineto_event_ordinal': event_index, 'Record_function_id': rf,
        'eto_node_id': node['id'], 'eto_original_node_ordinal': ordinal,
        'eto_parent_node_id': node['ctrl_deps'], 'RF_thread_token': attrs.get('tid'),
        'kineto_host_tid_separate_namespace': event['tid'], 'schema_available': has_schema,
        'tensor_paths': [list(path) for path in sorted(observed_paths)],
        'missing_metadata_tensor_paths': [list(path) for path in sorted(missing)]})
for join in joins:
    parent = join['tree_parent_result_id']
    if parent in tree_matches:
        counts['mapped_parent_checks'] += 1
        if tree_matches[parent] != join['eto_parent_node_id']:
            issues.append({'index': join['tree_index'], 'code': 'MAPPED_PARENT_CONTRADICTION'})
    else:
        counts['parent_outside_exported_TorchOp_boundary'] += 1

assert 'torch' not in sys.modules
counts['unique_key_joins'] = len(joins)
counts['eto_nodes'] = len(eto['nodes'])
counts['eto_positive_RF_nodes'] = sum(map(len, rf_nodes.values()))
counts['CPU_external_records'] = sum(map(len, cpu.values()))
duplicates = {'CPU_external_keys': sum(len(value) > 1 for value in cpu.values()),
    'ETO_positive_RF_keys': sum(len(value) > 1 for value in rf_nodes.values()),
    'tree_correlation_keys': len(rows) - len({row['event']['correlation_id'] for row in rows})}
result = {'schema': 'scar.native-input-small-sample-design-audit', 'schema_version': 1,
    'status': 'BOUNDED_SAMPLE_INSPECTED_NOT_QUALIFIED', 'counts': dict(counts), 'duplicates': duplicates,
    'issues': issues, 'opaque_ETO_type_inventory': dict(opaque_types), 'scalar_opaque_ETO_type_inventory': dict(scalar_types),
    'chrome_category_inventory': dict(categories), 'joins': joins, 'inputs': receipts,
    'read_bytes': sum(row['bytes'] for row in receipts), 'read_files': len(receipts),
    'Torch_imported': False, 'target_capture_runs': 0, 'old_LeWM_raw_DB_reads': 0,
    'ordinary_membership_created': False, 'IR_modified': False, 'old1901_qualified': 0,
    'sample_run_boundary': 'Original CPU probe exit1; no owned OS/operand/run-success records. Ordinary retained-capture profile is not qualified by this sample.',
    'source_helpers': ['scar.ir.execution.native_port_protocol.attributes', 'scar.ir.execution.native_port_protocol.flat_native']}
with (O / 'sample-audit.json').open('x') as target:
    json.dump(result, target, indent=2, sort_keys=True)
    target.write('\n')
print(json.dumps({k: value for k, value in result.items() if k not in ('joins', 'inputs')}))
