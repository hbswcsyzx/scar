"""One pure-declaration counterexample: all-Unknown native invocation binding.

No capture/database/chunk is opened and no owned native evidence is constructed.
"""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
FROZEN = ROOT / 'artifacts/experiments/native_capture_batch_attempt02_20261025/review-candidate01'
receipts = json.loads((FROZEN / 'source-receipt.json').read_bytes())['files']


def unchanged():
    for row in receipts:
        original = (FROZEN / row['path']).read_bytes()
        assert sha256(original).hexdigest() == row['sha256']
        assert (ROOT / row['path']).read_bytes() == original


unchanged()
from scar.ir.record_codec import encode
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.execution.coordinates import ExecutionRun, ProcessInstance, HostThreadInstance
from scar.ir.execution.ids import RunID, ProcessInstanceID, HostThreadInstanceID
from scar.ir.execution.common import Unresolved
from scar.ir.execution.native_port_protocol import PROFILE_V2, replay_batch_interfaces, _native_port_order_errors
from scar.ir.execution.snapshot import snapshot_for, external_bytes
from scar.ir.execution.validation import validate
from scar.ir.execution.codec import dumps as execution_dumps, loads as execution_loads
from scar.ir.v2.ids import OperationInstanceID, OperationDefinitionID
from scar.ir.v2.values import ValueGraph
from scar.ir.v2.evidence import EvidenceGraph, OperationInstance
from scar.trace.native_protocol import _build_program, _build_execution
from scar.trace.native_schema import PROVIDER_REVISION


def artifact(uri, raw, schema):
    return ProviderArtifact(uri, sha256(raw).hexdigest(), len(raw), schema)


def box(values=(), types=(), shapes=(), strides=()):
    return {k: list(v) for k, v in zip(('values', 'types', 'shapes', 'strides'),
        (values, types, shapes, strides), strict=True)}


def attrs(tid, rf, schema=''):
    return [{'name': name, 'value': value} for name, value in
        [('tid', tid), ('rf_id', rf), ('op_schema', schema)]]


run_name, pid, nonce = 'capture:pure-v2-review', 7, 'review'
span, out = f'scar-dispatch:{nonce}:{pid}:1:span', f'scar-dispatch:{nonce}:{pid}:1:output'
native_input, native_output = [100, 200, 0, 1, 8, 'cpu'], [101, 201, 0, 1, 8, 'cpu']
schema = 'example::echo(Tensor x) -> Tensor'
nodes = [
    {'id': 11, 'name': 'example::echo', 'ctrl_deps': 10, 'attrs': attrs(1, 11, schema),
     'inputs': box([native_input], ['Tensor(double)'], [[]], [[]]),
     'outputs': box([native_output], ['Tensor(double)'], [[]], [[]])},
    {'id': 12, 'name': out, 'ctrl_deps': 10, 'attrs': attrs(1, 12), 'inputs': box(), 'outputs': box()},
    {'id': 10, 'name': span, 'ctrl_deps': 1, 'attrs': attrs(1, 10), 'inputs': box(), 'outputs': box()},
    {'id': 1, 'name': '[pytorch|profiler|execution_trace|process]', 'ctrl_deps': 1,
     'attrs': attrs(0, 0), 'inputs': box(), 'outputs': box()},
]
eto = artifact('memory:review-eto', b'synthetic-eto', 'pytorch.execution-trace.v1')
dispatch = artifact('memory:review-dispatch', b'synthetic-dispatch', 'scar.dispatch-observation.events.v1')
physical = artifact('memory:review-physical', b'synthetic-physical', 'scar.tensor-physical-observation.v1')
observation = {'process_id': pid, 'native_tid': pid, 'python_ident': 77, 'tensor_references': []}
rows = [
    {'index': 1, 'sequence': 1, 'process_id': pid, 'kind': 'DISPATCH_BEGIN', 'marker': span,
     'operator': 'example.echo.default', 'slot_gaps': [], 'observation': observation},
    {'index': 2, 'sequence': 1, 'process_id': pid, 'kind': 'DISPATCH_OUTPUT', 'marker': out,
     'slot_gaps': [], 'observation': observation},
    {'index': 3, 'sequence': 1, 'process_id': pid, 'kind': 'DISPATCH_END', 'outcome': 'RETURNED',
     'span_enter_returned': True, 'output_marker': out},
]
source = {'reference_profile': PROFILE_V2, 'provider_revision': PROVIDER_REVISION,
    'run': run_name, 'pid': pid, 'nonce': nonce, 'owner_native_tid': pid, 'owner_python_ident': 77,
    'native_scope': 'native:pure-v2-review', 'physical_scope': 'physical:pure-v2-review',
    'physical_profile': 'scar.tensor-physical-event-tree-v1', 'first_sequence': 1, 'max_sequences': 1,
    'artifacts': {'eto': encode(eto), 'dispatch': encode(dispatch), 'physical': encode(physical)},
    'nodes': nodes, 'root_node': nodes[-1], 'node_ordinals': {str(n['id']): i for i, n in enumerate(nodes)},
    'dispatch': rows, 'physical': [], 'object_records': {}, 'geometry_records': {}}
interfaces, frontiers = replay_batch_interfaces(source)
assert len(interfaces) == 1 and not frontiers
sig = interfaces[0]['signature_id']
definitions = {sig: interfaces[0]['signature']}
interface_doc = {'schema': 'scar.pinned-torch-protocol-interface', 'schema_version': 1,
    'profile': PROFILE_V2, 'interfaces': definitions,
    'effect_contract': 'UNKNOWN outside partial provider schema annotations', 'content_version_claimed': False}
canonical = lambda value: json.dumps(value, sort_keys=True, ensure_ascii=False,
    separators=(',', ':'), allow_nan=False).encode()
interface_bytes = canonical(interface_doc)
interface_artifact = artifact('memory:review-interface', interface_bytes, interface_doc['schema'])
program, layouts = _build_program(interfaces, source, interface_artifact)
fact = ProviderFactReference(dispatch, '#line/1')
run = ExecutionRun(RunID(run_name), fact)
process = ProcessInstance(ProcessInstanceID('pure-v2-process'), run.id, pid, fact)
thread = HostThreadInstance(HostThreadInstanceID('pure-v2-thread'), process.id, pid, fact)
coordinates = SimpleNamespace(run=run, processes=(process,), threads=(thread,), target_process=process,
    thread_for=lambda *args: thread)
vg, eeg = ValueGraph(), EvidenceGraph()
native = OperationInstanceID(source['native_scope'] + ':eto:11')
eeg.add_instance(OperationInstance(native, OperationDefinitionID('pure-v2-native-definition'), pid, 'eto-thread:1'))
va = artifact('memory:review-values', external_bytes(vg), vg.SCHEMA)
ea = artifact('memory:review-evidence', external_bytes(eeg), eeg.SCHEMA)
model = _build_execution(program, layouts, interfaces, source, coordinates,
    snapshot_for(program, 'memory:review-program').artifact, va, ea)
assert len(model.denotations) == 2 and all(type(d.identity) is Unresolved for d in model.denotations)
assert len(model.evidence_bindings) == 1
scope = dict(definition_signatures=definitions, profile=PROFILE_V2, source=source, value_artifact=va)
catalogs = dict(value_graphs={va.sha256: vg}, evidence_graphs={ea.sha256: eeg},
    artifact_bytes={interface_artifact.sha256: interface_bytes})
baseline = validate(model, program, **catalogs)
assert baseline.valid, [encode(i) for i in baseline.issues]
assert not _native_port_order_errors(program, model, interfaces, run_name, **scope)
candidate = execution_loads(execution_dumps(replace(model, evidence_bindings=())))
generic = validate(candidate, program, **catalogs)
errors = _native_port_order_errors(program, candidate, interfaces, run_name, **scope)
assert generic.valid and not errors
unchanged()
result = {'status': 'PURE_DECLARATION_COUNTEREXAMPLE_CONFIRMED',
    'reviewed_source_sha256': {r['path']: r['sha256'] for r in receipts},
    'all_native_tensor_denotations_unresolved': True, 'baseline_native_bindings': len(model.evidence_bindings),
    'candidate_native_bindings': len(candidate.evidence_bindings), 'candidate_generic_validation_valid': generic.valid,
    'candidate_native_order_errors': list(errors),
    'finding': 'A complete all-Unknown native interface can erase its original ETO OperationInstance binding without rejection',
    'raw_reads': 0, 'sqlite_reads': 0, 'archive_chunk_reads': 0, 'owned_native_evidence_constructed': False,
    'full_gate_run': False, 'target_executed': False, 'production_files_changed': False}
with (HERE / 'counterexample.json').open('x') as stream:
    json.dump(result, stream, sort_keys=True, indent=2); stream.write('\n')
print(json.dumps(result, sort_keys=True))
