"""One synthetic held-marker fixture; no capture owner or actual qualification.

Adapts the existing native_v2_readonly_review synthetic source structure. Root
reviews before running. No raw, SQLite, old shard, target or collector is read.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

O = Path(__file__).resolve().parent
B = O.parents[1]
freeze = json.loads((O / 'freeze.json').read_bytes())
for row in freeze['sources'] + freeze['runner']:
    raw = (B / row['path']).read_bytes()
    assert len(raw) == row['bytes'] and sha256(raw).hexdigest() == row['sha256'], row['path']

from scar.ir.execution.native_port_protocol import PROFILE_V2, replay_interfaces, replay_batch_interfaces
from scar.trace.native_capture_batch import _check_group_identity
from scar.trace.native_schema import PROVIDER_REVISION


def box(tensor=True):
    return {'values': [[100, 200, 0, 1, 8, 'cpu']] if tensor else [],
        'types': ['Tensor(double)'] if tensor else [],
        'shapes': [[]] if tensor else [], 'strides': [[]] if tensor else []}


def node(identifier, name, parent, rf, schema='', tensor=True, tid=1):
    return {'id': identifier, 'name': name, 'ctrl_deps': parent,
        'attrs': [{'name': k, 'value': v} for k, v in [('tid', tid), ('rf_id', rf), ('op_schema', schema)]],
        'inputs': box(tensor), 'outputs': box(tensor if schema else False)}


pid, nonce, weak = 7, 'a' * 32, 'weak:7:1'
span, output = [f'scar-dispatch:{nonce}:{pid}:1:{phase}' for phase in ('span', 'output')]
schema = 'aten::alias(Tensor(a) self) -> Tensor(a)'
nodes = [node(11, 'aten::alias', 10, 42, schema), node(12, output, 10, 43),
    node(10, span, 1, 41), node(1, '[pytorch|profiler|execution_trace|process]', 1, 0, tensor=False, tid=0)]
obs = lambda path: {'process_id': pid, 'native_tid': pid, 'python_ident': 77,
    'tensor_references': [{'path': path, 'ref': weak, 'identity_qualified': True}]}
rows = [{'index': 1, 'sequence': 1, 'process_id': pid, 'kind': 'DISPATCH_BEGIN',
    'marker': span, 'operator': 'aten.alias.default', 'slot_gaps': [], 'observation': obs([0, 0])},
    {'index': 2, 'sequence': 1, 'process_id': pid, 'kind': 'DISPATCH_OUTPUT',
    'marker': output, 'slot_gaps': [], 'observation': obs([])},
    {'index': 3, 'sequence': 1, 'process_id': pid, 'kind': 'DISPATCH_END',
    'outcome': 'RETURNED', 'span_enter_returned': True, 'output_marker': output}]
metadata = {'status': 'OBSERVED', 'gaps': [], 'impl_ptr': 1000, 'storage_data_ptr': 2000,
    'provider_tensor_id': 0, 'provider_allocation_id': 1, 'device': {'text': 'cpu'},
    'dtype': 'torch.float64', 'layout': 'strided', 'sizes': [], 'strides': []}
physical = []
for index, marker in enumerate((span, output), 1):
    physical.append({'kind': 'MARKER', 'index': index, 'marker': marker, 'sequence': 1,
        'phase': 'span' if index == 1 else 'output', 'gaps': [],
        'binding_status': 'PROVISIONAL_REQUIRES_FINAL_METADATA', 'dispatch_source_line': index,
        'dispatch_native_tid': pid, 'dispatch_python_ident': 77, 'expected_argument_count': 1,
        'event': {'record_function_thread_token': 1, 'correlation_id': index},
        'arguments': [{'argument_ordinal': 0, 'dispatch_reference_ordinal': 0, 'metadata': metadata}]})
physical.append({'kind': 'ALLOCATION', 'index': 3, 'device': {'text': 'cpu'},
    'provider_allocation_id': 1, 'alloc_size': 8})
source = {'reference_profile': PROFILE_V2, 'provider_revision': PROVIDER_REVISION, 'run': 'synthetic',
    'pid': pid, 'nonce': nonce, 'owner_native_tid': pid, 'owner_python_ident': 77,
    'native_scope': 'native:synthetic', 'physical_scope': 'physical:synthetic',
    'first_sequence': 1, 'max_sequences': 1, 'nodes': nodes, 'root_node': nodes[-1],
    'node_ordinals': {str(n['id']): i for i, n in enumerate(nodes)}, 'dispatch': rows, 'physical': physical,
    'artifacts': {k: {'uri': 'memory:synthetic-' + k, 'sha256': letter * 64, 'size_bytes': 0}
        for k, letter in [('eto', 'e'), ('physical', 'f')]},
    'object_records': {weak: {'metadata': {'weak_token': weak, 'process_id': pid}}}, 'geometry_records': {}}
allocation = {'id': 'allocation:synthetic', 'device': 'cpu', 'nbytes': 8,
    'lifetime_scope': source['physical_scope'], 'metadata': {'provider_allocation_id': 1, 'address': 2000}}
for index, marker_node in ((1, nodes[2]), (2, nodes[1])):
    ordinal = source['node_ordinals'][str(marker_node['id'])]
    region = {'id': 'region:synthetic:' + str(index), 'allocation': allocation['id'], 'offset': 0,
        'shape': [], 'strides': [], 'dtype': metadata['dtype'], 'device': 'cpu', 'layout': metadata['layout'],
        'metadata': {'physical_observation': 'sha256:' + 'f' * 64 + f'#line/{index}/arguments/0',
            'eto_reference': 'sha256:' + 'e' * 64 + f'#/nodes/{ordinal}/inputs/values/0',
            'marker_instance': 'opinst:native:synthetic:eto:' + str(marker_node['id']),
            'impl_ptr': 1000, 'provider_tensor_id': 0}}
    source['geometry_records'][f'{index}:0'] = {'region': {'record': region}, 'allocation': {'record': allocation}}

assert _check_group_identity(source) is None
v2, frontier = replay_batch_interfaces(source)
assert len(v2) == 1 and not frontier
assert all(p['geometry']['status'] == 'QUALIFIED' for ports in v2[0]['ports'].values() for p in ports)
legacy = {k: v for k, v in source.items() if k != 'reference_profile'}
v1, frontier = replay_interfaces(legacy)
assert len(v1) == 1 and not frontier
# Same fixture, one changed owned marker. Numeric ID handling cannot waive it.
bad = deepcopy(source)
bad['dispatch'][0]['marker'] = 'scar-dispatch:' + 'b' * 32 + f':{pid}:1:span'
rejected = []
for check in (_check_group_identity, replay_batch_interfaces, replay_interfaces):
    try:
        check(bad)
    except ValueError as error:
        rejected.append(str(error))
    else:
        raise AssertionError('changed nonce marker accepted by ' + check.__name__)
assert all('marker' in error for error in rejected)
result = {'status': 'PURE_METADATA_DISTINCT_IDS_MARKER_CHAIN_CHECK_PASSED',
    'correlation_ids': [1, 2], 'ETO_RF_IDs': [41, 43], 'ids_distinct': True,
    'checks': ['batch identity', 'V2 exact ordered held slots and declared point geometry', 'V1 exact ordered held slots'],
    'changed_marker_rejections': rejected, 'owned_native_evidence_constructed': False,
    'synthetic_only_no_actual_C_qualification': True, 'raw_DB_shard_reads': 0,
    'target_or_collector_runs': 0, 'full_native_runs': 0}
with (O / 'tiny-result.json').open('x') as target:
    json.dump(result, target, indent=2, sort_keys=True)
    target.write('\n')
print(json.dumps(result), flush=True)
