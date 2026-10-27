"""Canonical host write/read and explicit, conditional lifetime associations."""
from dataclasses import replace
from hashlib import sha256
import json

from scar.ir.execution.common import Unresolved
from scar.ir.execution.coordinates import AccessRef, OccurrencePhase, OccurrencePoint
from scar.ir.execution.ids import (
    ContributionSupportID, EstablishedProductionID, EvidenceInventoryID,
    TargetLifetimeEventID, WriteAssociationID,
)
from scar.ir.execution.inventory import build_inventory
from scar.ir.execution.production import (
    BytePrefixWrite, EvidenceInventoryBinding, HostWrite, InventorySourceRef,
    RawRecordRef, StateProduction, WriteAssociation,
)
from scar.ir.execution.resources import AllocationTarget
from scar.ir.execution.validity import (
    CompletedVisibility, ContributionSupport, EstablishedProduction, HostDomain,
    LifetimeEventKind, TargetLifetimeEvent,
)
from scar.ir.program.ids import OperationID
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from tests.fixtures.execution_content_graphs import content_connection_fixture


def host_lifetime_execution():
    """Return program/model/VG/EEG/payloads/details, with no native authority."""
    program, model, values, evidence, details = content_connection_fixture(kind='reference')
    occurrence = next(row.id for row in model.operations if row.operation == OperationID('content.mutate'))
    effect = AccessRef(occurrence, 0)
    point = OccurrencePoint(occurrence, OccurrencePhase.AFTER)
    unknown = Unresolved('native/capture applicability is not proved', model.activations[0].entry)
    profile = {'schema': 'scar.native.byte-prefix-write', 'schema_version': 1,
               'stage': 'host-write', 'requested_bytes': 16, 'written_bytes': 16}
    raw = (json.dumps({'kind': 'python_c_call', 'invocation_id': 1,
        'code_id': 'declared-host-write', 'ts_ns': 10, 'duration_ns': 1,
        'inputs': [], 'outputs': [], 'metadata': {'process_id': 10, 'thread_id': 11,
        'scar_native_result': profile}}, sort_keys=True) + '\n').encode()
    manifest, index, payloads = build_inventory({'host': raw})
    inventory = EvidenceInventoryBinding(EvidenceInventoryID('lifetime.host'), model.runs[0].id,
                                         manifest, index, model.runs[0].source)
    stage = RawRecordRef(InventorySourceRef(inventory.id, 'host'), 1, sha256(raw).hexdigest())
    artifact = ProviderArtifact('inventory:host:raw', sha256(raw).hexdigest(), len(raw), 'scar.trace.raw-jsonl')
    result = ProviderFactReference(artifact, '#L1/metadata/scar_native_result')
    write = WriteAssociation(WriteAssociationID('lifetime.host'), stage, HostWrite(occurrence),
        StateProduction(effect), model.content_reads[0].placement, (), model.runs[0].source)
    established = EstablishedProduction(EstablishedProductionID('lifetime.host'), write.id, point,
        write.placement.selector, result, BytePrefixWrite(), model.runs[0].source)
    protocol = ProviderFactReference(model.snapshot.artifact, 'declared-host-sequence')
    support = ContributionSupport(ContributionSupportID('lifetime.host'), model.content_reads[0].id,
        write.id, established.id,
        CompletedVisibility(point, effect, HostDomain(model.threads[0].id), protocol), model.runs[0].source)
    selector = write.placement.selector
    graph = values[selector.artifact.sha256]
    target = AllocationTarget(selector.artifact, graph.regions[selector.region].allocation)
    live_at = OccurrencePoint(details['producer'], OccurrencePhase.BEFORE)
    live = TargetLifetimeEvent(TargetLifetimeEventID('lifetime.live'), target, LifetimeEventKind.LIVE,
        live_at, unknown, None, protocol, model.runs[0].source)
    model = replace(model, source_inventories=(inventory,), writes=(write,),
                    established_productions=(established,), contribution_supports=(support,),
                    target_lifetime_events=(live,))
    details = {**details, 'write': write.id, 'established': established.id, 'support': support.id,
               'live': live.id, 'effect': effect, 'writer': occurrence, 'target': target}
    return program, model, values, evidence, payloads, details


__all__ = ['host_lifetime_execution']


def queue_lifetime_execution(*, terminal=False):
    """An actual six-work record/wait path, with original resource read ports."""
    from scar.ir.execution.content import ContentRead, ResourceConsumer, WholeWorkRead
    from scar.ir.execution.ids import ContentReadID, OutcomeProductionID, WorkOutcomeID, WorkTicketID
    from scar.ir.execution.production import OutcomeProduction, WorkWrite
    from scar.ir.execution.validity import OrderedVisibility
    from scar.ir.execution.work import ResourceOutcome, WorkOutcomeKind
    from scar.ir.v2.common import Completeness
    from tests.fixtures.execution_order_graphs import event_order_execution

    _, host, values, _, payloads, _ = host_lifetime_execution()
    program, model = event_order_execution()
    unknown = Unresolved('exact native work/input correspondence not captured', model.activations[0].entry)
    producer = next(row for row in model.submissions if row.id == WorkTicketID('p1'))
    consumer = next(row for row in model.submissions if row.id == WorkTicketID('c'))
    occurrence = next(row for row in model.operations if row.id == consumer.origin.operation)
    op = next(row for row in program.operations if row.id == occurrence.operation)
    before = next(row.value for row in model.uses
                  if row.operation == occurrence.id and row.use == op.accesses[0].before)
    source = model.runs[0].source
    placement = host.writes[0].placement
    read = ContentRead(ContentReadID('lifetime.queue.read'),
        ResourceConsumer(AccessRef(occurrence.id, 0), WholeWorkRead(consumer.id), unknown),
        placement, AccessRef(occurrence.id, 0),
        OccurrencePoint(occurrence.id, OccurrencePhase.BEFORE), (before,), unknown, source)
    write = replace(host.writes[0], id=WriteAssociationID('lifetime.queue.write'),
                    writer=WorkWrite(producer.id), production=StateProduction(producer.effects[0]))
    inventories = host.source_inventories
    if not terminal:
        raw = (json.dumps({'kind': 'python_c_call', 'invocation_id': 1, 'code_id': 'declared-enqueue',
            'ts_ns': 10, 'duration_ns': 1, 'inputs': [], 'outputs': [],
            'metadata': {'process_id': 10, 'thread_id': 11}}) + '\n').encode()
        manifest, index, payloads = build_inventory({'request': raw})
        inventory = EvidenceInventoryBinding(EvidenceInventoryID('lifetime.request'), model.runs[0].id,
                                             manifest, index, source)
        inventories = (inventory,)
        write = replace(write, stage=RawRecordRef(InventorySourceRef(inventory.id, 'request'),
                                               1, sha256(raw).hexdigest()))
    produced, outcomes = (), ()
    if terminal:
        outcome = ResourceOutcome(WorkOutcomeID('lifetime.queue.outcome'), producer.id,
            WorkOutcomeKind.COMPLETED,
            OccurrencePoint(producer.origin.operation, OccurrencePhase.AFTER),
            host.established_productions[0].result, (producer.effects[0],), Completeness.PARTIAL,
            unknown, source)
        produced = (OutcomeProduction(OutcomeProductionID('lifetime.queue.actual'), write.id, outcome.id,
            0, placement.selector, BytePrefixWrite(), source),)
        outcomes = (outcome,)
    support = ContributionSupport(ContributionSupportID('lifetime.queue'), read.id, write.id,
        produced[0].id if produced else None, OrderedVisibility(producer.protocol), source)
    model = replace(model, source_inventories=inventories, content_reads=(read,),
        writes=(write,), produced=produced, outcomes=outcomes, contribution_supports=(support,))
    details = {'read': read.id, 'write': write.id, 'support': support.id,
               'producer_ticket': producer.id, 'consumer_ticket': consumer.id}
    return program, model, values, {}, payloads, details


__all__.append('queue_lifetime_execution')


def endpoint_lifetime_execution():
    """Exact Q endpoint observation; unsupported native selector stays a gap."""
    from scar.ir.execution.content import ContentRead, EndpointContent, ObservationConsumer, ProtocolSelector
    from scar.ir.execution.ids import ContentReadID
    from scar.ir.execution.snapshot import external_artifact
    from scar.ir.execution.validity import EndpointDomain
    from scar.ir.execution.work import MaterializationRef
    from scar.ir.v2.ids import LogicalValueID, MaterializationID, ValueVersionID
    from scar.ir.v2.values import LogicalValue, Materialization, ValueGraph, ValueVersion
    from tests.fixtures.execution_observation_graphs import observation_execution

    program, model, semantics = observation_execution()
    root = model.observation_roots[0]
    protocol = model.observation_requirements[0].protocol
    target = model.requirements[0].target
    writer = next(row for row in model.operations if row.operation == OperationID('resource.use.1'))
    effect = AccessRef(writer.id, 0)
    point = OccurrencePoint(writer.id, OccurrencePhase.AFTER)
    unknown = Unresolved('endpoint native selector/result is not interpreted', model.activations[0].entry)
    graph = ValueGraph()
    logical = LogicalValueID('lifetime.endpoint')
    version, mat = ValueVersionID(logical, 0), MaterializationID('lifetime.endpoint')
    graph.add_logical_value(LogicalValue(logical, 'file-content'))
    graph.add_version(ValueVersion(version))
    graph.add_materialization(Materialization(mat, version, 'endpoint', 'file'))
    artifact = external_artifact(graph)
    placement = EndpointContent(MaterializationRef(artifact, mat), target, ProtocolSelector(protocol))
    read = ContentRead(ContentReadID('lifetime.endpoint'), ObservationConsumer(root.id), placement,
                       None, root.anchor, root.support, unknown, model.runs[0].source)
    write = WriteAssociation(WriteAssociationID('lifetime.endpoint'), unknown, HostWrite(writer.id),
        StateProduction(effect), placement, (), model.runs[0].source)
    established = EstablishedProduction(EstablishedProductionID('lifetime.endpoint'), write.id, point,
        ProtocolSelector(protocol), unknown, unknown, model.runs[0].source)
    support = ContributionSupport(ContributionSupportID('lifetime.endpoint'), read.id, write.id,
        established.id, CompletedVisibility(point, effect, EndpointDomain(target), protocol), model.runs[0].source)
    model = replace(model, content_reads=(read,), writes=(write,), established_productions=(established,),
                    contribution_supports=(support,))
    return program, model, {artifact.sha256: graph}, {}, {}, {'read': read.id, 'write': write.id,
        'support': support.id, 'established': established.id, 'semantic_graphs': semantics}


__all__.append('endpoint_lifetime_execution')


def intervening_host_execution():
    """Two distinct canonical overwrites remain despite a restored version label."""
    from scar.ir.program.ids import UseID, ValueID
    from scar.ir.program.model import (
        AccessMode, Behavior, Footprint, FootprintKind, Operation, OperationResult,
        StateAccess, StateVersionValue, Use, UseRole,
    )
    from tests.fixtures.execution_paths import declared_path

    program, model, values, evidence, payloads, details = host_lifetime_execution()
    read = next(row for row in program.operations if row.id == OperationID('content.read'))
    before_use = next(use for use in read.uses if use.id == read.accesses[0].before)
    current, location = before_use.value, read.accesses[0].location
    new_operations, new_values = [], []
    for number in range(2):
        identity = OperationID(f'validity.overwrite.{number}')
        value = StateVersionValue(ValueID(f'validity.overwrite.{number}.after'), program.root,
                                  OperationResult(identity, 0), location)
        use = Use(UseID(f'validity.overwrite.{number}.before'), current, UseRole.STATE_CONTENT)
        new_operations.append(Operation(identity, 'write then restore declared content',
            (Behavior.READ, Behavior.WRITE), (use,), (value.id,),
            (StateAccess(location, use.id, AccessMode.READ_WRITE, value.id,
                         Footprint(FootprintKind.WHOLE)),), effects_complete=True))
        new_values.append(value)
        current = value.id
    operations = []
    for row in program.operations:
        if row.id == read.id:
            operations.extend(new_operations)
        if row.id in (read.id, OperationID('content.return')):
            row = replace(row, uses=tuple(replace(use, value=current)
                if use.role is UseRole.STATE_CONTENT and use.value == before_use.value else use for use in row.uses))
        operations.append(row)
    region = program.regions[0]
    block = replace(region.blocks[0], operations=tuple(row.id for row in operations))
    program = replace(program, operations=tuple(operations), values=(*program.values, *new_values),
                      regions=(replace(region, blocks=(block,)),))
    actual = declared_path(program, ((block.id, None),))
    new_before = next(row.value for row in actual.uses
                     if row.operation == details['operation'] and row.use == before_use.id)
    writes, established, effects = list(model.writes), list(model.established_productions), []
    for number, operation in enumerate(new_operations):
        occurrence = next(row.id for row in actual.operations if row.operation == operation.id)
        effect = AccessRef(occurrence, 0)
        effects.append(effect)
        write = replace(model.writes[0], id=WriteAssociationID(f'validity.overwrite.{number}'),
                        writer=HostWrite(occurrence), production=StateProduction(effect))
        writes.append(write)
        established.append(replace(model.established_productions[0],
            id=EstablishedProductionID(f'validity.overwrite.{number}'), write=write.id,
            established=OccurrencePoint(occurrence, OccurrencePhase.AFTER)))
    model = replace(model, snapshot=actual.snapshot, operations=actual.operations, values=actual.values,
                    uses=actual.uses, writes=tuple(writes), established_productions=tuple(established),
                    content_reads=(replace(model.content_reads[0], support=(new_before,)),))
    return program, model, values, evidence, payloads, {**details, 'middle_effects': tuple(effects)}


__all__.append('intervening_host_execution')
