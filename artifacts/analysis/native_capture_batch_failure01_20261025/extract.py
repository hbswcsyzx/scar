"""Read-only terminal diagnosis: saved metadata and SQLite navigation only.

No SCAR import, raw trace/chunk read, owner reconstruction or gate execution.
The saved SQLite MAC key is unavailable; extracted rows are diagnostic data.
"""
from collections import Counter
from hashlib import sha256
import itertools
import json
from pathlib import Path
import sqlite3

BASE = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
GATE = BASE / 'artifacts/experiments/native_capture_batch_20261025'
DB = GATE / 'result/private/navigation.sqlite'


def load(path):
    return json.loads(path.read_bytes())


def fingerprint(path):
    data = path.read_bytes()
    return {'path': str(path.relative_to(BASE)), 'bytes': len(data), 'sha256': sha256(data).hexdigest()}


def attrs(node):
    return {row['name']: row['value'] for row in node['attrs']}


def stat(path):
    s = path.stat()
    return {'size_bytes': s.st_size, 'mtime_ns': s.st_mtime_ns, 'inode': s.st_ino}


failure = load(GATE / 'result/failure.json')
candidate_position = failure['classified_actual_groups'] + 1
with (GATE / 'result/observed-dispatches.jsonl').open() as stream:
    line = next(itertools.islice(stream, candidate_position - 1, candidate_position))
observed = json.loads(line)
seq = observed['sequence']
assert seq == 3182 and observed['operator'] == 'aten.mul_.Tensor'
before = stat(DB)
connection = sqlite3.connect('file:' + str(DB.resolve()) + '?mode=ro&immutable=1', uri=True)
selected = []


def record(kind, key):
    row = connection.execute('SELECT ordinal,payload FROM records WHERE kind=? AND key=?', (kind, str(key))).fetchone()
    assert row is not None, (kind, key)
    ordinal, raw = row
    doc = json.loads(raw)
    selected.append({'kind': kind, 'key': str(key), 'ordinal': ordinal,
                     'payload_bytes': len(raw), 'payload_sha256': sha256(raw).hexdigest(), 'record': doc})
    return ordinal, doc


dispatch = {}
for role, witnesses in observed['source_rows'].items():
    assert len(witnesses) == 1
    _, dispatch[role] = record('dispatch', witnesses[0]['index'])
assert sorted(row['index'] for row in dispatch.values()) == [9544, 9545, 9546]
native_ids = [24611, 24614, 24615, 24616, 24619, 24620, 24621, 24624, 24625]
nodes = {node_id: record('node', node_id) for node_id in native_ids}
physical = {index: record('physical', index)[1] for index in range(9687, 9695)}
span, native, output = (nodes[n][1] for n in (24615, 24616, 24625))
assert span['name'] == dispatch['DISPATCH_BEGIN']['marker']
assert output['name'] == dispatch['DISPATCH_OUTPUT']['marker'] == dispatch['DISPATCH_END']['output_marker']
assert native['ctrl_deps'] == output['ctrl_deps'] == span['id']
assert attrs(span)['tid'] == attrs(native)['tid'] == attrs(output)['tid']
assert attrs(native)['op_schema'] == 'aten::mul_.Tensor(Tensor(a!) self, Tensor other) -> Tensor(a!)'
assert native['inputs']['values'][0] == span['inputs']['values'][0] == output['inputs']['values'][0] == native['outputs']['values'][0]
begin_refs = dispatch['DISPATCH_BEGIN']['observation']['tensor_references']
end_refs = dispatch['DISPATCH_OUTPUT']['observation']['tensor_references']
assert [r['path'] for r in begin_refs] == [[0, 0]] and [r['path'] for r in end_refs] == [[]]
assert begin_refs[0]['ref'] == end_refs[0]['ref']
assert native['inputs']['types'] == ['Tensor(float)', 'Tensor(double)']
assert native['inputs']['shapes'][1] == native['inputs']['strides'][1] == []
assert native['inputs']['values'][1] == [24617, 24618, 0, 1, 8, 'cpu']
for marker, role in ((physical[9688], 'DISPATCH_BEGIN'), (physical[9693], 'DISPATCH_OUTPUT')):
    row = dispatch[role]
    node = span if role == 'DISPATCH_BEGIN' else output
    assert marker['marker'] == row['marker'] and marker['dispatch_source_line'] == row['index']
    assert marker['sequence'] == seq and not marker['gaps']
    assert marker['event']['correlation_id'] == attrs(node)['rf_id']
    assert marker['event']['record_function_thread_token'] == attrs(node)['tid']
    assert marker['expected_argument_count'] == len(marker['arguments']) == 1
    assert marker['arguments'][0]['argument_ordinal'] == marker['arguments'][0]['dispatch_reference_ordinal'] == 0
for node_id in (24611, 24614, 24615, 24616, 24625):
    ordinal, archived = record('archive:instances', node_id)
    assert ordinal == nodes[node_id][0] == archived['ordinal']
    assert archived['record']['metadata']['node_id'] == node_id
record('archive:objects', begin_refs[0]['ref'])
physical_artifact = next(r['artifact'] for r in failure['raw_reads'] if r['artifact']['schema'] == 'scar.tensor-physical-observation.v1')
allocations = set()
for index in (9688, 9693):
    key = 'sha256:' + physical_artifact['sha256'] + '#line/' + str(index) + '/arguments/0:0'
    _, archived = record('archive:regions', key)
    allocations.add(archived['record']['allocation']['value'])
for allocation in sorted(allocations):
    record('archive:allocations', allocation)
connection.close()
assert stat(DB) == before
progress = [json.loads(line) for line in (GATE / 'progress.jsonl').read_text().splitlines()]
table_receipts = [r for r in progress if r['stage'] == 'archive_table_indexed']
domain = next(r for r in progress if r['stage'] == 'dispatch_domain_enumerated')
assert sum(r['chunks'] for r in table_receipts) == 95
cost = load(GATE / 'actual-io.json')
cost_sums = {phase: {kind: sum(r['bytes'] for r in cost if r['phase'] == phase and r['kind'] == kind)
                     for kind in ('decoded', 'stored')} for phase in sorted({r['phase'] for r in cost})}
evidence = {'status': 'READ_ONLY_SAVED_METADATA_EXTRACTION', 'observed_dispatch': observed,
    'observed_line_bytes': len(line.encode()), 'observed_line_sha256': sha256(line.encode()).hexdigest(),
    'selected_sqlite_rows': selected, 'sqlite_stat_before_and_after': before,
    'sqlite_open_mode': 'mode=ro&immutable=1', 'sqlite_mac_reverified': False,
    'sqlite_wholefile_sha_recomputed': False, 'runtime_authority_recreated': False,
    'original_raw_files_opened': 0, 'original_archive_chunks_opened': 0,
    'raw_source_artifacts_from_terminal_receipt': failure['raw_reads']}
diagnosis = {'status': 'FAILURE01_DIAGNOSIS_ONLY_NOT_SOURCE_MODEL_PASS',
    'failure_sequence': seq, 'operator': observed['operator'],
    'dispatch_lines': {role: row['index'] for role, row in dispatch.items()},
    'native_node': {'id': native['id'], 'ordinal': nodes[native['id']][0], 'schema': attrs(native)['op_schema']},
    'native_input_tensor_paths': [[0], [1]], 'python_held_input_paths': [[0, 0]],
    'python_held_input_formal_paths': [[0]], 'missing_held_native_paths': [[1]],
    'native_only_input': {'path': [1], 'type': native['inputs']['types'][1], 'tuple': native['inputs']['values'][1],
                          'shape': [], 'strides': [], 'numel': 1, 'element_bytes': 8},
    'known_held_self_consistent_in_selected_records': True,
    'known_marker_parent_RF_thread_inconsistency_detected': False,
    'dispatch_nonTensor_kind_or_value_retained': False,
    'dispatch_complete_args_kwargs_tree_retained': False,
    'observed_interpretation': 'V1 held-reference inventory is a strict subset of the actual native Tensor inputs. The unmatched Tensor input has no observed Python WeakRef/ObjectIdentity.',
    'inferred_explanation': 'Versioned wrapped-number Tensor -> Python primitive -> newly boxed native Tensor is strongly consistent with outer/PythonDispatchMode/inner records. Actual primitive kind/value and wrapped bit were not saved, so the particular conversion is inference.',
    'unsafe_conclusions_excluded': ['no invented WeakRef/ObjectID for native-only input', 'no scalar literal or content equality inferred',
                                    'no identity granted by zero-dimensional shape, dtype or nearby allocation', 'no whole-domain/model PASS'],
    'terminal_cost': {'actual_exit_status': 1, 'GNU_whole_wall_seconds': 196.92, 'gate_in_process_wall_seconds': 195.47038940299535,
                      'native_batch_wall_seconds': failure['wall_seconds'], 'max_RSS_KiB': 910204},
    'completed_acquisition_scope': {'raw_sources': 3, 'raw_bytes': sum(r['raw_bytes_read'] for r in failure['raw_reads']),
                                    'archive_tables': table_receipts, 'path_API_IO_by_phase': cost_sums,
                                    'additional_verified_BytesIO_chunk_decoded_bytes': sum(r['decoded_bytes'] for r in table_receipts)},
    'domain_cardinality_record': domain, 'classified_actual_groups_before_failure': failure['classified_actual_groups'],
    'program_published': (GATE / 'result/program.json').exists(), 'execution_shards_published': (GATE / 'result/shards').exists(),
    'whole_program_model_established': False, 'producer_modified_by_diagnosis': False,
    'second_gate_or_retry_started': False,
    'terminal_input_fingerprints': [fingerprint(GATE / p) for p in
        ('freeze.json', 'gate-failure.json', 'result/failure.json', 'progress.jsonl', 'time.txt', 'actual-io.json')]}
for name, document in (('evidence.json', evidence), ('diagnosis.json', diagnosis)):
    with (OUT / name).open('x') as stream:
        json.dump(document, stream, sort_keys=True, indent=2)
        stream.write('\n')
print(json.dumps({'status': diagnosis['status'], 'sequence': seq, 'selected_sqlite_rows': len(selected),
                  'native_only_input': diagnosis['native_only_input'], 'cost': diagnosis['terminal_cost']}, indent=2))
