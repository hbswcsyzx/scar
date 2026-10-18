"""Content queries preserve original ports and never upgrade source gaps."""
from dataclasses import replace

import pytest

from scar.ir.execution.common import Unresolved
from scar.ir.execution.content import (
    ContentRead, EndpointContent, NativeWorkRead, ObservationConsumer, ProtocolSelector,
)
from scar.ir.execution.ids import ContentReadID
from scar.ir.execution.observations import ExternalEndpoint
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.resources import AllocationTarget
from scar.ir.execution.snapshot import external_artifact
from scar.ir.execution.work import MaterializationRef
from scar.ir.v2.ids import LogicalValueID, MaterializationID, StorageAllocationID, ValueVersionID
from scar.ir.v2.values import LogicalValue, Materialization, StorageAllocation, ValueGraph, ValueVersion
from tests.fixtures.execution_content_graphs import content_connection_fixture
from tests.fixtures.execution_observation_graphs import observation_execution


def _index(**options):
    program, model, values, evidence, details = content_connection_fixture(**options)
    return ExecutionIndex(model, program, value_graphs=values, evidence_graphs=evidence), details, values, evidence


@pytest.mark.parametrize('kind', ('data', 'reference'))
def test_query_returns_original_occurrence_subject_and_separate_denotation(kind):
    index, details, _, _ = _index(kind=kind)
    value = index.denotation(details['value'])
    read = index.content_read(details['read'])
    assert value['kind'] == kind
    assert value['occurrence'].id == details['value']
    assert read['subject']['subject'] == details['subject']
    assert read['actual'].id == details['value']
    assert read['placement'][0].id == details['materialization'].materialization
    assert not read['source_runtime_verified'] and not read['transformation_authorized']
    assert 'ready' not in read and 'free' not in read
    assert any(gap.code == 'content_exact_port_unresolved' for gap in read['gaps'])


def test_whole_work_query_uses_start_to_end_and_keeps_exact_ticket():
    from scar.ir.execution.order import WorkStart, WorkEnd
    index, details, _, _ = _index(consumer='work')
    result = index.content_read(details['read'])
    ticket = result['read'].consumer.read.ticket
    assert result['interval'] == (WorkStart(ticket), WorkEnd(ticket))
    assert result['conservative_work_interval'] == result['interval']
    assert result['consumer_input']['instance'] == result['basis']['instance']
    assert any(gap.code == 'content_exact_port_unresolved' for gap in result['gaps'])


def test_missing_exact_work_pair_remains_a_gap_and_never_borrows_same_host_pair():
    program, model, values, evidence, details = content_connection_fixture(consumer='work', duplicate_use=True)
    first, second = model.content_reads
    changed = replace(first, consumer=replace(first.consumer, read=second.consumer.read))
    model = replace(model, content_reads=(changed, second))
    index = ExecutionIndex(model, program, value_graphs=values, evidence_graphs=evidence)
    missing = index.content_read(changed.id)
    matched = index.content_read(second.id)
    assert missing['basis']['correspondence'] == ()
    assert missing['consumer_input']['correspondence'] == ()
    assert any(gap.code == 'content_work_source_unresolved' for gap in missing['gaps'])
    assert matched['basis']['correspondence']
    assert all(row.ticket == second.consumer.read.ticket for row in matched['basis']['correspondence'])
    assert missing['basis']['instance'] != matched['basis']['instance']
    assert not missing['transformation_authorized']


def test_unparsed_narrow_native_interval_does_not_shorten_conservative_read_obligation():
    from scar.ir.execution.coordinates import OccurrencePhase, OccurrencePoint
    from scar.ir.execution.content import ProtocolInterval
    from scar.ir.execution.order import WorkStart, WorkEnd
    program, model, values, evidence, details = content_connection_fixture(consumer='work')
    row = model.content_reads[0]
    before = OccurrencePoint(row.consumer.subject.operation, OccurrencePhase.BEFORE)
    interval = ProtocolInterval(before, replace(before, phase=OccurrencePhase.AFTER),
                                model.submissions[0].protocol, row.source)
    row = replace(row, consumer=replace(row.consumer, read=NativeWorkRead(row.consumer.read.ticket, interval)))
    model = replace(model, content_reads=(row,))
    result = ExecutionIndex(model, program, value_graphs=values, evidence_graphs=evidence).content_read(row.id)
    ticket = row.consumer.read.ticket
    assert result['interval'] == (WorkStart(ticket), WorkEnd(ticket))
    assert result['declared_native_interval'] == interval
    assert any(gap.code == 'content_native_read_interval_unverified' for gap in result['gaps'])


def test_reference_and_current_state_do_not_permanently_bind_object_to_content_version():
    index, details, _, _ = _index(kind='reference')
    reference = index.denotation(details['value'])
    state = index.denotation(details['before'])
    assert reference['kind'] == 'reference' and state['kind'] == 'state'
    assert state['association'] is None
    result = index.content_read(details['read'])
    assert any(gap.code == 'content_state_version_unverified' for gap in result['gaps'])


def test_unobserved_reference_operand_cannot_turn_unknown_content_effect_into_none():
    program, model, values, evidence, details = content_connection_fixture(kind='reference')
    subject = details['subject']
    uses = tuple(replace(row, value=Unresolved('actual operand not captured', model.activations[0].entry))
                 if (row.operation, row.use) == (subject.operation, subject.use) else row for row in model.uses)
    model = replace(model, uses=uses, content_reads=(replace(model.content_reads[0], effect=None),))
    with pytest.raises(ValueError, match='content_reference_effect'):
        ExecutionIndex(model, program, value_graphs=values, evidence_graphs=evidence)


@pytest.mark.parametrize('role', ('producer', 'reader'))
def test_exact_host_occurrence_pair_rejects_conflicting_known_source_process(role):
    program, model, values, evidence, details = content_connection_fixture()
    graph = next(iter(evidence.values()))
    owner = details['producer'] if role == 'producer' else details['operation']
    pair = next(row for row in model.evidence_bindings if row.operation == owner)
    graph.instances[pair.legacy.instance].process_id = 999
    artifact = external_artifact(graph, pair.legacy.artifact.uri)
    bindings = tuple(replace(row, legacy=replace(row.legacy, artifact=artifact)) for row in model.evidence_bindings)
    denotations = tuple(replace(row, basis=replace(row.basis, artifact=artifact)) for row in model.denotations)
    reads = tuple(replace(row, basis=replace(row.basis, artifact=artifact)) for row in model.content_reads)
    model = replace(model, evidence_bindings=bindings, denotations=denotations, content_reads=reads)
    with pytest.raises(ValueError, match='content_operation_process'):
        ExecutionIndex(model, program, value_graphs=values, evidence_graphs={artifact.sha256: graph})


@pytest.mark.parametrize('known_queue_process', (False, True))
def test_work_source_process_uses_actual_queue_realm_and_never_guesses_from_host(known_queue_process):
    from scar.ir.execution.content import WorkEvidenceBinding
    from scar.ir.execution.ids import WorkEvidenceBindingID
    from scar.ir.execution.resources import RunRealm
    from scar.ir.v2.evidence import EvidenceGraph, OperationInstance
    from scar.ir.v2.ids import OperationDefinitionID, OperationInstanceID
    from tests.fixtures.execution_order_graphs import event_order_execution
    program, model = event_order_execution()
    graph = EvidenceGraph()
    instance = OperationInstanceID('queued.source')
    graph.add_instance(OperationInstance(instance, OperationDefinitionID('queued.source'), 999, 999))
    artifact = external_artifact(graph)
    work = model.submissions[0]
    queue = next(row.queue for row in model.queue_prefixes if row.id == work.scheduling.prefix)
    if not known_queue_process:
        model = replace(model, resources=tuple(replace(row, realm=RunRealm(model.runs[0].id))
                                              if row.id == queue else row for row in model.resources))
    pair = WorkEvidenceBinding(WorkEvidenceBindingID('queued.source'), work.id, artifact, instance, model.runs[0].source)
    model = replace(model, work_evidence_bindings=(pair,))
    if known_queue_process:
        with pytest.raises(ValueError, match='content_work_process'):
            ExecutionIndex(model, program, evidence_graphs={artifact.sha256: graph})
    else:
        index = ExecutionIndex(model, program, evidence_graphs={artifact.sha256: graph})
        assert any(gap.code == 'content_work_process_unresolved' for gap in index.report.gaps)


@pytest.mark.parametrize('family', ('values', 'evidence'))
def test_every_content_query_revalidates_caller_graph_after_index_construction(family):
    index, details, values, evidence = _index()
    index.content_read(details['read'])
    if family == 'values':
        graph = next(iter(values.values()))
        next(iter(graph.logical_values.values())).description = 'changed after index construction'
    else:
        graph = next(iter(evidence.values()))
        next(iter(graph.instances.values())).metadata['changed'] = True
    with pytest.raises(ValueError, match='external_snapshot'):
        index.denotation(details['value'])
    with pytest.raises(ValueError, match='external_snapshot'):
        index.content_read(details['read'])


def test_returned_materialization_and_source_records_are_detached():
    index, details, values, evidence = _index()
    before = index.content_read(details['read'])
    before['placement'][0].representation = 'caller forgery'
    before['basis']['observation'].role = 'caller forgery'
    after = index.content_read(details['read'])
    assert after['placement'][0].representation != 'caller forgery'
    assert after['basis']['observation'].role != 'caller forgery'
    assert all(row.representation != 'caller forgery' for graph in values.values() for row in graph.materializations.values())
    assert all(row.role != 'caller forgery' for graph in evidence.values() for row in graph.observations.values())


@pytest.mark.parametrize('output', (False, True))
def test_observation_query_resolves_contract_and_original_actual_without_work(output):
    program, model, semantic = observation_execution(output=output)
    index = ExecutionIndex(model, program, semantic_graphs=semantic)
    result = index.observation_root(model.observation_roots[0].id)
    assert result['contract'].id == result['requirement'].contract.contract
    assert result['root'] == model.observation_roots[0]
    assert not model.submissions and not result['transformation_authorized']
    assert any(gap.code == 'observation_source_protocol_unverified' for gap in result['gaps'])


def test_observation_query_rechecks_semantic_graph_and_detaches_contract():
    program, model, semantic = observation_execution()
    index = ExecutionIndex(model, program, semantic_graphs=semantic)
    identity = model.observation_roots[0].id
    result = index.observation_root(identity)
    result['contract'].name = 'caller forgery'
    assert index.observation_root(identity)['contract'].name != 'caller forgery'
    graph = next(iter(semantic.values()))
    next(iter(graph.contracts.values())).name = 'external source changed'
    with pytest.raises(ValueError, match='external_snapshot'):
        index.observation_root(identity)


def _endpoint_read(*, wrong_target=False):
    program, model, semantic = observation_execution(external=True)
    graph = ValueGraph()
    logical = LogicalValueID('endpoint.content')
    version = ValueVersionID(logical, 0)
    graph.add_logical_value(LogicalValue(logical, 'bytes'))
    graph.add_version(ValueVersion(version))
    allocation = StorageAllocationID('endpoint.content')
    other = StorageAllocationID('endpoint.other')
    graph.add_allocation(StorageAllocation(allocation, 'cpu', 8))
    graph.add_allocation(StorageAllocation(other, 'cpu', 8))
    mat = MaterializationID('endpoint.content')
    graph.add_materialization(Materialization(mat, version, 'endpoint-protocol', 'cpu', None))
    artifact = external_artifact(graph, 'memory:original-allocation-catalog')
    target = AllocationTarget(artifact, allocation)
    root = replace(model.observation_roots[0], actual=ExternalEndpoint(target))
    alias = replace(artifact, uri='unavailable:equivalent-uri-never-opened')
    placement_target = AllocationTarget(alias, other if wrong_target else allocation)
    unknown = Unresolved('declared content; no native content mapping', model.activations[0].entry)
    read = ContentRead(ContentReadID('endpoint.read'), ObservationConsumer(root.id),
        EndpointContent(MaterializationRef(artifact, mat), placement_target,
                        ProtocolSelector(root.interval.protocol)),
        unknown, root.anchor, root.support, unknown, model.runs[0].source)
    model = replace(model, observation_roots=(root,), content_reads=(read,))
    return program, model, {artifact.sha256: graph}, semantic, read.id


def test_endpoint_observation_content_has_no_fake_storage_and_uri_is_not_identity():
    program, model, values, semantic, identity = _endpoint_read()
    result = ExecutionIndex(model, program, value_graphs=values,
                            semantic_graphs=semantic).content_read(identity)
    assert result['subject'] is None and result['actual'] is None
    assert result['placement'][0].region is None
    assert result['interval'] == model.observation_roots[0].interval
    assert not model.submissions and not result['transformation_authorized']
    assert any(gap.code == 'content_selector_protocol_unverified' for gap in result['gaps'])


def test_endpoint_content_cannot_substitute_another_known_allocation():
    program, model, values, semantic, _ = _endpoint_read(wrong_target=True)
    with pytest.raises(ValueError, match='content_observation_target'):
        ExecutionIndex(model, program, value_graphs=values, semantic_graphs=semantic)
