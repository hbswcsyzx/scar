"""Occurrence-scoped native Tensor content reads, with explicit static guards.

Normal immutable input/execution ports supply coordinates and state transport.
The pinned copy protocol supplies a conditional content dependency, never an
observed memory trace, mutable-object snapshot, readiness or lifetime proof.
"""
from hashlib import sha256
from pathlib import Path
import json

from scar.analysis.native_input_storage_bridge import query_native_input_allocation
from scar.analysis.native_completion import query_native_normal_completion
from scar.analysis.tensor_storage_query import _Meter, _need
from scar.ir.record_codec import decode, encode, loads as strict_json
from scar.ir.program.codec import loads as load_program
from scar.ir.program.model import StateVersionValue, UseRole
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.execution.codec import loads as load_execution
from scar.ir.execution.common import EvidencePoint, Unresolved
from scar.ir.execution.content import ContentRead, HostConsumer, NativeInputRef, ProtocolInterval, VersionRef
from scar.ir.execution.coordinates import OccurrencePoint, OccurrencePhase, UseRef
from scar.ir.execution.ids import ContentReadID, RunID, ProcessInstanceID, ValueOccurrenceID, HostThreadInstanceID
from scar.ir.execution.native_tensor_reads import NativeReadCondition, NativeTensorRead
from scar.ir.execution.resources import AllocationTarget
from scar.ir.execution.work import ActualCompletionState, InvokeBoundaryStateEffect
from scar.ir.v2.codec import values_from_dict
from scar.ir.v2.ids import LogicalValueID, ProvenanceID, ValueVersionID
from scar.ir.v2.values import (LogicalValue, ValueGraph, ValueVersion, ProvenanceRecord,
                               ProvenanceRelation, EquivalenceClaim)


PROFILE = 'PINNED_CPU_COPY_SRC_READ_V1'
SCHEMA = 'scar.native-tensor-read'
_PROVIDER = 'cf30153c4c131c8164ee7798e5022d810682e2cb'
_COPY_SCHEMA = 'aten::copy_(Tensor(a!) self, Tensor src, bool non_blocking=False) -> Tensor(a!)'
_PROTOCOL = {'schema': 'scar.native-tensor-read-protocol', 'schema_version': 1,
    'profile': PROFILE, 'provider_revision': _PROVIDER, 'operator_schema': _COPY_SCHEMA,
    'source_position': 1, 'semantic_relation': 'conditional read of src logical payload',
    'meaning': 'the symbolic payload read by this operation, not the input object or storage identity',
    'implementation': 'https://github.com/pytorch/pytorch/blob/' + _PROVIDER + '/aten/src/ATen/native/Copy.cpp#L125',
    'conditions': [c.value for c in NativeReadCondition],
    'exclusions': 'ZeroTensor, same-data and empty fast paths are not proof of an observed storage read; concurrent/foreign writes remain unresolved'}


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode()


def _write(path, value, schema):
    raw = _canonical(value)
    with path.open('xb') as f:
        f.write(raw)
    return ProviderArtifact(str(path), sha256(raw).hexdigest(), len(raw), schema)


def _read_json(artifact, meter, maximum=32_000_000):
    raw = meter.artifact(artifact, maximum); meter.charge(decoded=len(raw))
    return strict_json(raw.decode('utf8'))


def _normal(view, meter):
    execution_artifact = decode(ProviderArtifact, view['canonical_parent']['execution'])
    program_artifact = decode(ProviderArtifact, view['canonical_parent']['program_snapshot']['artifact'])
    raw = meter.artifact(execution_artifact, 32_000_000); meter.charge(decoded=len(raw))
    execution = load_execution(raw.decode('utf8'))
    raw = meter.artifact(program_artifact, 32_000_000); meter.charge(decoded=len(raw))
    program = load_program(raw.decode('utf8'))
    occurrence = next(o for o in execution.operations if encode(o.id) == view['operation_occurrence']['id'])
    operation = next(o for o in program.operations if o.id == occurrence.operation)
    _need(operation.label == _COPY_SCHEMA and view['native_input']['position'] == 1,
          'profile requires exact registered copy_ schema and original src signature position')
    metadata = view['observed_metadata']
    _need(metadata['device']['type'] == 'cpu' and metadata['layout'] == 'torch.strided',
          'CPU read profile cannot be used for accelerator/meta/other layout')
    signature = decode(ProviderFactReference, view['native_operation']['signature'])
    doc = _read_json(signature.artifact, meter, 1_000_000)
    iface = doc['interfaces'][signature.locator.split('/')[-1]]
    _need(iface['provider_revision'] == _PROVIDER and iface['schema'] == _COPY_SCHEMA,
          'native interface provider revision/schema differs')
    input_ref = decode(UseRef, {'operation': encode(occurrence.id), 'use': view['actual_use_occurrence']['use']})
    values = {v.id: v for v in program.values}
    states = [u for u in operation.uses if u.id in operation.invoke_arguments
              and u.role is UseRole.STATE_CONTENT and type(values[u.value]) is StateVersionValue]
    _need(len(states) == 1, 'read requires a unique original world/state input')
    state_use = states[0]
    state_actual = [u for u in execution.uses if u.operation == occurrence.id and u.use == state_use.id]
    _need(len(state_actual) == 1 and any(v.id == state_actual[0].value and v.value == state_use.value
          for v in execution.values), 'original state input occurrence is unresolved')
    normal = query_native_normal_completion(program, execution, occurrence.id)
    _need(normal.state_interface_status == 'ONE_SELECTED_NORMAL_STATE_CONTINUATION'
          and type(normal.state_effect) is InvokeBoundaryStateEffect
          and type(normal.state_effect.post) is ActualCompletionState
          and normal.state_output is not None,
          'CPU read needs an exact normal state continuation')
    port = [p for p in normal.input_ports if p.reference == decode(NativeInputRef, view['native_input'])]
    _need(len(port) == 1 and port[0].use.operation == input_ref.operation
          and port[0].use.use == input_ref.use
          and encode(port[0].value.id) == view['value_occurrence'],
          'normal completion and read select different original input ports')
    _need(normal.state_input == state_actual[0]
          and normal.state_effect.state_input == UseRef(occurrence.id, state_use.id)
          and normal.state_effect.post.formal == normal.state_output.id,
          'normal completion and content read use different original state transport')
    original_visit = next(v for v in execution.visits if v.id == occurrence.visit)
    segment = next(s for s in execution.segments if s.id == original_visit.segment)
    activation = next(a for a in execution.activations if a.id == segment.activation)
    process = next(p for p in execution.processes if p.id == activation.process)
    _need(encode(process.id) == view['process'] and encode(process.run) == view['run'],
          'read actor/source has another Run or process')
    _need(state_actual[0].value in {v.id for v in execution.values if v.origin == occurrence.visit},
          'read does not retain the current entry state incarnation')
    if type(segment.host_thread) is HostThreadInstanceID:
        actors = [t for t in execution.threads if t.id == segment.host_thread]
        _need(len(actors) == 1 and actors[0].process == process.id, 'read actor belongs to another process')
    return (execution, input_ref, state_actual[0].value, normal.state_effect,
            segment.host_thread, normal.normal_return, normal.completion_evidence.source)



def _derive(view, meter, protocol_artifact, values_path):
    execution, subject, state, effect, actor, returned, normal_source = _normal(view, meter)
    namespace = {'execution': view['canonical_parent']['execution'],
        'snapshot': view['canonical_parent']['program_snapshot'], 'native_input': view['native_input'],
        'source': view['original_input'], 'subject': encode(subject), 'state': encode(state), 'profile': PROFILE}
    token = sha256(_canonical(namespace)).hexdigest()
    read_id = ContentReadID('native-tensor-read:' + token)
    logical = LogicalValueID('native-read-content:' + token)
    version = ValueVersionID(logical, 0)
    graph = ValueGraph()
    graph.add_logical_value(LogicalValue(logical, 'torch.tensor.read-content',
        'Payload of this conditional read occurrence; numeric values and cross-read equality unknown.',
        {'dtype': view['observed_metadata']['dtype'], 'shape': view['observed_metadata']['sizes'],
         'identity_semantics': 'original read occurrence, not object/storage identity',
         'source_read': read_id.wire, 'profile': PROFILE}))
    origin = ProvenanceID('native-read-root:' + token)
    graph.add_provenance(ProvenanceRecord(origin, ProvenanceRelation.ORIGIN, (), (version,),
        producer=None, equivalence=EquivalenceClaim.UNKNOWN, evidence='Inferred',
        metadata={'origin_semantics': 'read-local symbolic root; not a claim of physical data genesis',
                  'source_read': read_id.wire, 'upstream_origin_established': False}))
    graph.add_version(ValueVersion(version, provenance_id=origin, metadata={'identity_semantics': 'read-local symbol',
        'revision_semantics': '0 is a local identity label, not Tensor._version or a global timeline',
        'numeric_contents_observed': False, 'upstream_content_origin': 'unresolved'}))
    graph.assert_valid()
    values_raw = _canonical(graph.to_dict())
    values_artifact = ProviderArtifact(str(values_path), sha256(values_raw).hexdigest(), len(values_raw), ValueGraph.SCHEMA)
    reference = ProviderFactReference(protocol_artifact, '#/semantic_relation')
    point = EvidencePoint(decode(RunID, view['run']),
        decode(ProcessInstanceID, view['process']), decode(ProviderFactReference, view['original_input']))
    before = OccurrencePoint(subject.operation, OccurrencePhase.BEFORE)
    interval = ProtocolInterval(before, OccurrencePoint(returned.id, OccurrencePhase.BEFORE),
        reference, normal_source)
    read = ContentRead(read_id, HostConsumer(subject, interval),
        Unresolved('allocation observation is not an admitted logical content materialization', point),
        effect, before, (state,), decode(NativeInputRef, view['native_input']), reference)
    record = NativeTensorRead(decode(ProviderArtifact, view['canonical_parent']['execution']),
        execution.snapshot, point.run, point.process, actor, read,
        decode(ValueOccurrenceID, view['value_occurrence']), VersionRef(values_artifact, version),
        decode(AllocationTarget, view['allocation_target']), tuple(NativeReadCondition))
    return graph, record


def build_native_tensor_read(navigation: ProviderArtifact, storage_index: ProviderArtifact, out_dir, *,
        row=None, path=None, native_input=None, value_occurrence=None, execution=None,
        max_input_bytes=256_000_000, max_seconds=60):
    """Create one real-port, guarded read -> fresh symbolic version association."""
    root = Path(out_dir).absolute(); _need(not root.exists(), 'fresh native read output required')
    meter = _Meter(max_input_bytes, max_seconds)
    view = query_native_input_allocation(navigation, storage_index, row=row, path=path,
        native_input=native_input, value_occurrence=value_occurrence, execution=execution,
        max_input_bytes=max_input_bytes, max_seconds=max_seconds)
    meter.charge(stored=view['measurements']['stored_bytes'], decoded=view['measurements']['decoded_bytes'])
    root.mkdir(parents=True)
    protocol = _write(root/'protocol.json', _PROTOCOL, 'scar.native-tensor-read-protocol')
    graph, record = _derive(view, meter, protocol, root/'values.json')
    values = _write(root/'values.json', graph.to_dict(), ValueGraph.SCHEMA)
    _need(values == record.result.artifact, 'read value artifact write differs from canonical descriptor')
    doc = {'schema': SCHEMA, 'schema_version': 1, 'profile': PROFILE,
        'navigation': encode(navigation), 'storage_index': encode(storage_index),
        'protocol': encode(protocol), 'record': encode(record),
        'qualification': 'CONDITIONAL_READ_RESULT',
        'actual_memory_read_observed': False, 'content_equality_established': False,
        'readiness_established': False, 'measurements': meter.finish()}
    return _write(root/'read.json', doc, SCHEMA)


def read_native_tensor_read(artifact: ProviderArtifact, *, max_input_bytes=256_000_000, max_seconds=60):
    """Strict ordinary typed consumer; recheck original ports/state and guards.

    Returns (NativeTensorRead, ValueGraph, input_measurements). No live owner or successful-validation
    cache is accepted from serialized data or exposed for later mutable reuse.
    """
    _need(type(artifact) is ProviderArtifact and artifact.schema == SCHEMA, 'typed native read artifact required')
    meter = _Meter(max_input_bytes, max_seconds)
    doc = _read_json(artifact, meter, 1_000_000)
    _need(set(doc) == {'schema','schema_version','profile','navigation','storage_index','protocol','record',
        'qualification','actual_memory_read_observed','content_equality_established','readiness_established','measurements'}
        and doc['schema'] == SCHEMA and doc['schema_version'] == 1 and doc['profile'] == PROFILE,
        'unsupported native tensor read document')
    _need(doc['qualification'] == 'CONDITIONAL_READ_RESULT'
        and doc['actual_memory_read_observed'] is False and doc['content_equality_established'] is False
        and doc['readiness_established'] is False, 'native read document overclaims runtime/content/ready')
    record = decode(NativeTensorRead, doc['record'])
    protocol = decode(ProviderArtifact, doc['protocol'])
    _need(protocol.schema == 'scar.native-tensor-read-protocol'
          and _read_json(protocol, meter, 100_000) == _PROTOCOL, 'pinned native read protocol differs')
    _need(record.result.artifact.schema == ValueGraph.SCHEMA, 'native read result is not an original ValueGraph artifact')
    navigation = decode(ProviderArtifact, doc['navigation']);index = decode(ProviderArtifact, doc['storage_index'])
    view = query_native_input_allocation(navigation, index, native_input=record.read.basis,
        execution=record.execution, max_input_bytes=max_input_bytes-meter.stored-meter.decoded, max_seconds=max_seconds)
    meter.charge(stored=view['measurements']['stored_bytes'], decoded=view['measurements']['decoded_bytes'])
    graph, expected = _derive(view, meter, protocol, record.result.artifact.uri)
    _need(record == expected, 'read ID/port/state/actor/interval/version/conditions differ from normal original inputs')
    actual = values_from_dict(_read_json(record.result.artifact, meter, 1_000_000))
    _need(_canonical(actual.to_dict()) == _canonical(graph.to_dict()), 'read-local ValueGraph differs')
    measurements = meter.finish()
    return record, actual, measurements
