"""Canonical source/value/evidence fixtures for content-association tests.

The files and edges below are declarations used by the validator.  In
particular, an EEG operation edge never chooses one of two equal-valued core
Use occurrences.
"""
from dataclasses import replace

from scar.ir.execution.common import EvidencePoint, MissingEvidence, Unresolved
from scar.ir.execution.content import (
    ContentRead, DataIdentity, EvidenceEdgeRef, EvidenceObservationRef,
    HostConsumer, NativeInputRef, NativeOutputRef, ObjectIdentity, ObjectRef, ObservationConsumer,
    ProtocolInterval, ResourceConsumer, StorageContent, ValueDenotation,
    VersionRef, WholeWorkRead, WorkEvidenceBinding,
)
from scar.ir.execution.coordinates import (
    AccessRef, BlockVisit, ControlTransfer, ExecutionRun, ExecutionSegment,
    HostThreadInstance, InitialEntry, OccurrencePhase, OccurrencePoint,
    OperationOccurrence, OperationOccurrenceID, ProcessInstance,
    RegionActivation, UseOccurrence, UseRef, ValueOccurrence,
)
from scar.ir.execution.coverage import RegionRef
from scar.ir.execution.ids import (
    BlockVisitID, ContentReadID, DenotationID, ExecutionSegmentID,
    HostThreadInstanceID, ObservationRequirementID, ObservationRootID,
    ProcessInstanceID, RegionActivationID, RunID,
    ValueOccurrenceID, WorkEvidenceBindingID, WorkTicketID,
)
from scar.ir.execution.model import (
    ExecutionModel, LegacyOperationRef, OccurrenceEvidenceBinding,
)
from scar.ir.execution.observations import (
    ContractRef, ObservationRequirement, ObservationRoot, OutputValue,
    RequiredOutput,
)
from scar.ir.execution.snapshot import external_artifact, snapshot_for
from scar.ir.execution.work import DirectExecution, MaterializationRef, WithinOperation, WorkSubmission
from scar.ir.program.ids import (
    BlockID, LocationID, NativeBoundaryID, OperationID, RegionID, UseID, ValueID,
)
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, DataValue, ExitKind, ExitPort,
    Footprint, FootprintKind, LiteralOrigin, Operation, OperationResult,
    ProgramGraph, ReferenceValue, Region, StateAccess, StateLocation,
    StateVersionValue, Terminator, TerminatorKind, Use, UseRole, ValueKind,
    ValueType,
)
from scar.ir.program.providers import ProviderFactReference
from scar.ir.v2.common import Completeness, EvidenceClaim, EvidenceKind
from scar.ir.v2.contracts import ContractDefinition
from scar.ir.v2.evidence import (
    EvidenceEdge, EvidenceEndpoint, EvidenceGraph, EvidenceNodeKind,
    EvidenceRelation, OperationInstance, ValueObservation,
)
from scar.ir.v2.ids import (
    ContractID, LogicalValueID, MaterializationID, ObjectID,
    OperationDefinitionID, OperationInstanceID, ProvenanceID, StorageAllocationID,
    StorageRegionID, ValueSlotID, ValueVersionID,
)
from scar.ir.v2.semantic import SemanticGraph, ValueSlot
from scar.ir.v2.values import (
    LogicalValue, Materialization, StorageAllocation, StorageRegion, ValueGraph,
    ValueVersion,
)

from tests.fixtures.execution_paths import declared_path


def _program(*, duplicate_use=False):
    region = RegionID("content.body")
    entry = BlockID("content.entry")
    world = LocationID("content.world")

    reference = ReferenceValue(ValueID("content.buffer"), region, BlockArgument(entry, 0))
    initial = StateVersionValue(ValueID("content.world.initial"), region,
                                BlockArgument(entry, 1), world)
    data = DataValue(ValueID("content.output"), region,
                     OperationResult(OperationID("content.produce"), 0), "builtins.bytes")
    mutated = StateVersionValue(ValueID("content.world.mutated"), region,
                                OperationResult(OperationID("content.mutate"), 0), world)

    produce = Operation(OperationID("content.produce"), "produce declared data",
                        (Behavior.COMPUTE,), (), (data.id,))
    mutate_before = Use(UseID("content.mutate.before"), initial.id, UseRole.STATE_CONTENT)
    mutate = Operation(OperationID("content.mutate"), "update declared host state",
                       (Behavior.READ, Behavior.WRITE), (mutate_before,), (mutated.id,),
                       (StateAccess(world, mutate_before.id, AccessMode.READ_WRITE, mutated.id,
                                    Footprint(FootprintKind.WHOLE)),))

    ref_use = Use(UseID("content.read.reference"), reference.id, UseRole.REFERENCE)
    data_uses = [Use(UseID("content.read.data.0"), data.id, UseRole.DATA)]
    if duplicate_use:
        data_uses.append(Use(UseID("content.read.data.1"), data.id, UseRole.DATA))
    read_before = Use(UseID("content.read.before"), mutated.id, UseRole.STATE_CONTENT)
    read = Operation(OperationID("content.read"), "read declared content",
                     (Behavior.READ,), (ref_use, *data_uses, read_before), (),
                     (StateAccess(world, read_before.id, AccessMode.READ, None,
                                  Footprint(FootprintKind.WHOLE), reference=ref_use.id),))

    ret_ref = Use(UseID("content.return.reference"), reference.id, UseRole.REFERENCE)
    ret_world = Use(UseID("content.return.world"), mutated.id, UseRole.STATE_CONTENT)
    returned = Operation(OperationID("content.return"), "return declared values",
                         (Behavior.CONTROL,), (ret_ref, ret_world),
                         terminator=Terminator(TerminatorKind.RETURN, exit="normal",
                                               values=(ret_ref.id, ret_world.id)))
    operations = (produce, mutate, read, returned)
    graph = ProgramGraph(
        region,
        (Region(region, "content connection fixture", entry,
                (Block(entry, (reference.id, initial.id), tuple(row.id for row in operations)),),
                (ExitPort("normal", ExitKind.NORMAL,
                          (ValueType(ValueKind.REFERENCE),
                           ValueType(ValueKind.STATE, location=world))),)),),
        operations,
        (reference, initial, data, mutated),
        (StateLocation(world, "fixture world"),),
    )
    return graph, data, reference, read, tuple(data_uses), read_before


def _external_graphs():
    value_graph = ValueGraph()
    logical = LogicalValueID("content.logical")
    version0, version1 = ValueVersionID(logical, 0), ValueVersionID(logical, 1)
    value_graph.add_logical_value(LogicalValue(logical, "builtins.bytes"))
    value_graph.add_version(ValueVersion(version0, semantic_type="builtins.bytes"))
    value_graph.add_version(ValueVersion(version1, semantic_type="builtins.bytes"))
    allocation = StorageAllocationID("content.alloc")
    other_allocation = StorageAllocationID("content.unrelated.alloc")
    value_graph.add_allocation(StorageAllocation(allocation, "cpu", 64))
    value_graph.add_allocation(StorageAllocation(other_allocation, "cpu", 64))
    region = StorageRegionID("content.region")
    other_region = StorageRegionID("content.unrelated.region")
    value_graph.add_region(StorageRegion(region, allocation, 0, (16,), (1,), "uint8", "cpu"))
    value_graph.add_region(StorageRegion(other_region, other_allocation, 0, (16,), (1,), "uint8", "cpu"))
    materialization = MaterializationID("content.mat")
    value_graph.add_materialization(Materialization(materialization, version0, "dense", "cpu", region))
    value_artifact = external_artifact(value_graph, "memory:content-values")

    evidence = EvidenceGraph()
    producer = OperationInstanceID("content.eeg.producer")
    reader = OperationInstanceID("content.eeg.reader")
    reader_second = OperationInstanceID("content.eeg.reader.second")
    producer_wrong = OperationInstanceID("content.eeg.producer.wrong")
    for identity, name in ((producer, "producer"), (reader, "reader"),
                           (reader_second, "reader.second"), (producer_wrong, "producer.wrong")):
        evidence.add_instance(OperationInstance(identity, OperationDefinitionID("content." + name),
                                                process_id=10, thread_id=11))
    evidence.add_observation(ValueObservation("content.produced", version0, producer,
                                               materialization, role="output"))
    evidence.add_observation(ValueObservation("content.read.data", version0, reader,
                                               materialization, role="read"))
    evidence.add_observation(ValueObservation("content.read.data.second", version0, reader_second,
                                               materialization, role="read"))
    evidence.add_observation(ValueObservation("content.produced.wrong", version0, producer_wrong,
                                               materialization, role="output"))
    object_id = ObjectID("content.object")
    object_endpoint = EvidenceEndpoint(EvidenceNodeKind.OBJECT, object_id)
    evidence.register_external(object_endpoint)
    claim = EvidenceClaim(EvidenceKind.OBSERVED, references=("fixture-only",))

    def endpoint(kind, identity):
        return EvidenceEndpoint(kind, identity)

    edges = (
        EvidenceEdge("content.edge.produce", EvidenceRelation.PRODUCES,
                     endpoint(EvidenceNodeKind.OPERATION_INSTANCE, producer),
                     endpoint(EvidenceNodeKind.VALUE_OBSERVATION, "content.produced"), claim),
        EvidenceEdge("content.edge.produce.wrong", EvidenceRelation.PRODUCES,
                     endpoint(EvidenceNodeKind.OPERATION_INSTANCE, producer_wrong),
                     endpoint(EvidenceNodeKind.VALUE_OBSERVATION, "content.produced.wrong"), claim),
        EvidenceEdge("content.edge.read", EvidenceRelation.OBSERVED_READ,
                     endpoint(EvidenceNodeKind.OPERATION_INSTANCE, reader),
                     endpoint(EvidenceNodeKind.VALUE_OBSERVATION, "content.read.data"), claim),
        EvidenceEdge("content.edge.read.second", EvidenceRelation.OBSERVED_READ,
                     endpoint(EvidenceNodeKind.OPERATION_INSTANCE, reader_second),
                     endpoint(EvidenceNodeKind.VALUE_OBSERVATION, "content.read.data.second"), claim),
        EvidenceEdge("content.edge.read.object", EvidenceRelation.OBSERVED_READ,
                     endpoint(EvidenceNodeKind.OPERATION_INSTANCE, reader), object_endpoint, claim),
    )
    for edge in edges:
        evidence.add_edge(edge)
    evidence_artifact = external_artifact(evidence, "memory:content-evidence")
    return (value_graph, value_artifact, version0, version1, region, other_region,
            materialization, evidence, evidence_artifact, object_id,
            producer, reader, reader_second, producer_wrong)


def content_connection_fixture(*, consumer="host", kind="data", duplicate_use=False,
                               wrong_source=None, observation=False):
    """Return ``(program, model, value_graphs, evidence_graphs, details)``.

    ``consumer`` is ``host`` or ``work``.  The work form deliberately gives
    two tickets the same canonical host operation while binding each ticket
    to a different EEG operation instance. ``kind`` is ``data`` or
    ``reference``. ``wrong_source`` may be ``producer`` or ``read`` to select
    an otherwise well-formed but contradictory EEG association.
    """
    if consumer not in ("host", "work"):
        raise ValueError("consumer must be 'host' or 'work'")
    if kind not in ("data", "reference"):
        raise ValueError("kind must be 'data' or 'reference'")
    if wrong_source not in (None, "producer", "read"):
        raise ValueError("wrong_source must be None, 'producer', or 'read'")
    program, data, reference, static_read, data_uses, read_before = _program(
        duplicate_use=duplicate_use)
    (value_graph, value_artifact, version0, version1, region, other_region,
     materialization, evidence, evidence_artifact, object_id,
     producer_instance, reader_instance, reader_second_instance,
     producer_wrong_instance) = _external_graphs()
    model = declared_path(program, ((program.regions[0].entry, None),))
    occurrences = {row.operation: row.id for row in model.operations}
    producer_occ = occurrences[OperationID("content.produce")]
    read_occ = occurrences[OperationID("content.read")]
    actual_values = {(row.origin, row.value): row.id for row in model.values}
    values_for_static = {row.value: row.id for row in model.values}
    state_before = next(row.value for row in model.uses
                        if row.operation == read_occ and row.use == read_before.id)
    fact = ProviderFactReference(model.snapshot.artifact, "content-fixture/protocol")
    missing = MissingEvidence("hand-authored fixture; no source/runtime authority")
    version_ref = VersionRef(value_artifact, version0)
    mat_ref = MaterializationRef(value_artifact, materialization)
    basis_producer = EvidenceEdgeRef(evidence_artifact,
        "content.edge.produce.wrong" if wrong_source == "producer" else "content.edge.produce")
    data_occ = actual_values[(producer_occ, data.id)]
    ref_occ = values_for_static[reference.id]
    if kind == "data":
        denotation = ValueDenotation(DenotationID("content.denotation.data"), data_occ,
            DataIdentity(version_ref), basis_producer, missing)
        subject_uses = tuple(use for use in data_uses)
        subjects = tuple(UseRef(read_occ, use.id) for use in subject_uses)
        content_value = data_occ
        content_effect = None
        read_basis_edge = ("content.edge.read.second" if wrong_source == "read"
                           else "content.edge.read")
        denotations = (denotation,)
    else:
        object_basis = EvidenceEdgeRef(evidence_artifact, "content.edge.read.object")
        denotation = ValueDenotation(DenotationID("content.denotation.object"), ref_occ,
            ObjectIdentity(ObjectRef(evidence_artifact, object_id)), object_basis, missing)
        subjects = (UseRef(read_occ, UseID("content.read.reference")),)
        content_value = ref_occ
        content_effect = AccessRef(read_occ, 0)
        read_basis_edge = "content.edge.read"
        denotations = (denotation,)

    bindings = (
        OccurrenceEvidenceBinding(producer_occ,
            LegacyOperationRef(evidence_artifact, producer_instance), missing),
        OccurrenceEvidenceBinding(read_occ,
            LegacyOperationRef(evidence_artifact, reader_instance), missing),
    )
    work_rows, work_bindings = [], []
    work_sources = (reader_instance, reader_second_instance)
    work_tickets = ()
    if consumer == "work":
        thread = model.threads[0].id
        tickets = (WorkTicketID("content.ticket.0"), WorkTicketID("content.ticket.1"))
        work_tickets = tickets
        for index, ticket in enumerate(tickets):
            work_rows.append(WorkSubmission(ticket,
                WithinOperation(read_occ, missing),
                Unresolved("executor not captured", model.activations[0].entry),
                DirectExecution(thread, missing), (), Completeness.UNKNOWN, (), Completeness.UNKNOWN,
                (), Completeness.UNKNOWN, Unresolved("retention not captured", model.activations[0].entry),
                fact, missing))
            work_bindings.append(WorkEvidenceBinding(WorkEvidenceBindingID("content.work.binding." + str(index)),
                ticket, evidence_artifact, work_sources[index], missing))
    model = replace(model, evidence_bindings=bindings, submissions=tuple(work_rows),
                    denotations=denotations, work_evidence_bindings=tuple(work_bindings))

    content_reads = []
    for index, subject in enumerate(subjects):
        if consumer == "work":
            ticket = work_tickets[index]
            selected_edge = ("content.edge.read.second" if wrong_source == "read" and index == 0
                             else "content.edge.read" if index == 0
                             else "content.edge.read.second")
            source = ResourceConsumer(subject, WholeWorkRead(ticket),
                                      EvidenceEdgeRef(evidence_artifact, selected_edge))
            basis = EvidenceEdgeRef(evidence_artifact, selected_edge)
        else:
            start = OccurrencePoint(read_occ, OccurrencePhase.BEFORE)
            end = OccurrencePoint(read_occ, OccurrencePhase.AFTER)
            source = HostConsumer(subject, ProtocolInterval(start, end, fact, missing))
            selected_edge = read_basis_edge if index == 0 else "content.edge.read"
            basis = EvidenceEdgeRef(evidence_artifact, selected_edge)
        content_reads.append(ContentRead(ContentReadID("content.read." + str(index)), source,
            StorageContent(mat_ref, RegionRef(value_artifact, region)), content_effect,
            OccurrencePoint(read_occ, OccurrencePhase.BEFORE), (state_before,), basis, missing))
    model = replace(model, content_reads=tuple(content_reads))

    semantic_graphs = {}
    if observation:
        semantic = SemanticGraph()
        slot, contract_id = ValueSlotID("content.output.slot"), ContractID("content.output.contract")
        semantic.add_slot(ValueSlot(slot, "output", "output"))
        semantic.add_contract(ContractDefinition(contract_id, "content fixture output", (slot,)))
        semantic_artifact = external_artifact(semantic, "memory:content-semantic")
        protocol = ProviderFactReference(semantic_artifact, "contract/output")
        requirement = ObservationRequirement(ObservationRequirementID("content.output.requirement"),
            ContractRef(semantic_artifact, contract_id), RequiredOutput(slot), protocol, missing)
        anchor = OccurrencePoint(read_occ, OccurrencePhase.BEFORE)
        interval = ProtocolInterval(anchor, replace(anchor, phase=OccurrencePhase.AFTER), protocol, missing)
        root = ObservationRoot(ObservationRootID("content.output.root"), requirement.id,
            OutputValue(data_occ), interval, anchor, (state_before,), missing)
        model = replace(model, observation_requirements=(requirement,), observation_roots=(root,),
            content_reads=(ContentRead(ContentReadID("content.observation.read"),
                ObservationConsumer(root.id),
                StorageContent(mat_ref, RegionRef(value_artifact, region)), None, anchor, (state_before,),
                EvidenceObservationRef(evidence_artifact, "content.read.data"), missing),))
        semantic_graphs = {semantic_artifact.sha256: semantic}

    selected_reads = model.content_reads
    details = {
        "value": content_value,
        "data_value": data_occ,
        "reference_value": ref_occ,
        "read": selected_reads[0].id,
        "reads": tuple(row.id for row in selected_reads),
        "materialization": mat_ref,
        "version": version_ref,
        "subject": None if observation else subjects[0],
        "subjects": () if observation else subjects,
        "before": state_before,
        "producer": producer_occ,
        "operation": read_occ,
        "ticket": work_tickets[0] if work_tickets else None,
        "tickets": work_tickets,
        "value_graph_artifact": value_artifact,
        "evidence_artifact": evidence_artifact,
        "other_region": other_region,
        "other_version": VersionRef(value_artifact, version1),
        "semantic_graphs": semantic_graphs,
    }
    return program, model, {value_artifact.sha256: value_graph}, {evidence_artifact.sha256: evidence}, details


def _native_declared_path(program, region, path):
    """Small finite path builder for one declared native Region."""
    missing = MissingEvidence("hand-authored native path; no collected runtime")
    run, process, thread = RunID("native.content.run"), ProcessInstanceID("native.content.process"), HostThreadInstanceID("native.content.thread")
    point = EvidencePoint(run, process, missing)
    activation, segment = RegionActivationID("native.content.activation"), ExecutionSegmentID("native.content.segment")
    blocks = {block.id: block for block in region.blocks}
    operations_by_id = {row.id: row for row in program.operations}
    visits, occurrences, values, uses, transfers = [], [], [], [], []
    env = {}
    previous = None
    selected_occurrence = None
    first_visit = None
    for index, (block_id, edge) in enumerate(path):
        visit_id = BlockVisitID(f"native.content.visit.{index}")
        if first_visit is None:
            first_visit = visit_id
        if previous is not None:
            previous_op, previous_occurrence, previous_edge = previous
            transfers.append(ControlTransfer(previous_occurrence, previous_edge, visit_id))
        visits.append(BlockVisit(visit_id, segment, block_id))
        block = blocks[block_id]
        env = {}
        for formal in block.arguments:
            value_occurrence = ValueOccurrence(
                ValueOccurrenceID(f"native.content.{index}.{formal.value}"), formal, visit_id)
            values.append(value_occurrence)
            env[formal] = value_occurrence.id
        block_ops = []
        for op_id in block.operations:
            op = operations_by_id[op_id]
            occurrence_id = OperationOccurrenceID(f"native.content.{index}.{op_id.value}")
            occurrences.append(OperationOccurrence(occurrence_id, visit_id, op_id))
            uses.extend(UseOccurrence(occurrence_id, use.id, env[use.value]) for use in op.uses)
            block_ops.append((op, occurrence_id))
        if edge is not None:
            if not block_ops:
                raise ValueError("native path edge requires a block terminator")
            previous = (*block_ops[-1], edge)
        else:
            previous = None
        if index == len(path) - 1:
            if not block_ops:
                raise ValueError("native terminal block must contain its Return/Raise")
            selected_occurrence = block_ops[-1][1]
    model = ExecutionModel(
        snapshot_for(program),
        runs=(ExecutionRun(run, missing),),
        processes=(ProcessInstance(process, run, 10, missing),),
        threads=(HostThreadInstance(thread, process, 11, missing),),
        activations=(RegionActivation(activation, region.id, process, point),),
        segments=(ExecutionSegment(segment, activation, thread, InitialEntry(point)),),
        visits=tuple(visits), operations=tuple(occurrences), values=tuple(values),
        uses=tuple(uses), transfers=tuple(transfers),
    )
    return model, first_visit, selected_occurrence


def native_content_fixture(*, completion="return"):
    """Exercise exact P1 input/output slots on actual Return and Raise paths.

    Return uses native output slot 0. Raise uses slot 2. Both paths start from
    the true initial visit for ``native.rep`` and retain original core uses.
    """
    if completion not in ("return", "raise"):
        raise ValueError("completion must be 'return' or 'raise'")
    from tests.fixtures.program_native_graphs import native_boundary_graph

    program = native_boundary_graph()
    region = next(row for row in program.regions if row.id == RegionID("native.rep"))
    if completion == "return":
        path = ((BlockID("native.entry"), 0), (BlockID("native.return.a"), None))
        output_position = 0
        input_static = ValueID("native.flag")
        boundary_position = 0
    else:
        path = ((BlockID("native.entry"), 1), (BlockID("native.choose.more"), 1),
                (BlockID("native.raise"), None))
        output_position = 2
        input_static = ValueID("native.flag")
        boundary_position = 0
    model, entry_visit, output_operation = _native_declared_path(program, region, path)
    values = {(row.origin, row.value): row.id for row in model.values}
    entry_value = values[(entry_visit, input_static)]
    output_term = next(row.terminator for row in program.operations
                       if row.id == next(row.operation for row in model.operations
                                        if row.id == output_operation))
    output_use = output_term.values[output_position if completion == "return" else 0]
    output_occurrence = next(row.value for row in model.uses
                             if row.operation == output_operation and row.use == output_use)
    value_graph, value_artifact, version0, _version1, _region, _other_region, _mat, \
        evidence, evidence_artifact, object_id, *_ = _external_graphs()
    evidence.register_external(EvidenceEndpoint(EvidenceNodeKind.OBJECT, object_id))
    evidence_artifact = external_artifact(evidence, "memory:native-content-evidence")
    source = MissingEvidence("native port is declarative; physical correspondence is unverified")
    data_denotation = ValueDenotation(DenotationID("native.content.input"), entry_value,
        DataIdentity(VersionRef(value_artifact, version0)),
        NativeInputRef(NativeBoundaryID("native.rep.boundary"), entry_visit, boundary_position), source)
    output_denotation = ValueDenotation(DenotationID("native.content.output"), output_occurrence,
        ObjectIdentity(ObjectRef(evidence_artifact, object_id)),
        NativeOutputRef(NativeBoundaryID("native.rep.boundary"), output_operation, output_position), source)
    model = replace(model, denotations=(data_denotation, output_denotation))
    details = {
        "value": output_occurrence,
        "input_value": entry_value,
        "output_value": output_occurrence,
        "read": None,
        "materialization": None,
        "version": VersionRef(value_artifact, version0),
        "subject": None,
        "before": None,
        "entry": entry_visit,
        "operation": output_operation,
        "native_input_position": boundary_position,
        "native_output_position": output_position,
    }
    return program, model, {value_artifact.sha256: value_graph}, {evidence_artifact.sha256: evidence}, details


__all__ = ["content_connection_fixture", "native_content_fixture"]
