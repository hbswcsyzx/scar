"""Canonical split writers and a queued read; declarations, not native capture."""
from dataclasses import replace
import json

from scar.ir.execution.common import Unresolved
from scar.ir.execution.content import ContentRead, ResourceConsumer, StorageContent, WholeWorkRead
from scar.ir.execution.coordinates import AccessRef, OccurrencePhase, OccurrencePoint
from scar.ir.execution.coverage import RegionRef
from scar.ir.execution.ids import (
    ContentReadID, ContributionSupportID, EvidenceInventoryID, OutcomeProductionID,
    ResourceAccessID, WorkOutcomeID, WorkTicketID, WriteAssociationID,
)
from scar.ir.execution.inventory import InventoryResolver, build_inventory
from scar.ir.execution.order import WorkEnd
from scar.ir.execution.production import (
    BytePrefixWrite, EvidenceInventoryBinding, InventorySourceRef, OutcomeProduction,
    RawRecordRef, StateProduction, WorkWrite, WriteAssociation,
)
from scar.ir.execution.resources import ImplicitBinding, ResourceAccessBinding
from scar.ir.execution.snapshot import ExternalSnapshots, external_artifact
from scar.ir.execution.validity import CompletedVisibility, ContributionSupport, OrderedVisibility, QueueDomain
from scar.ir.execution.work import MaterializationRef, ResourceOutcome, WorkOutcomeKind
from scar.ir.program.ids import OperationID, ResourceDefinitionID, ResourceRequirementID, UseID, ValueID
from scar.ir.program.model import AccessMode, Footprint, FootprintKind, OperationResult, StateAccess, StateVersionValue, Use, UseRole
from scar.ir.program.providers import ProviderFactReference
from scar.ir.program.resources import ResourceUse
from scar.ir.v2.common import Completeness
from scar.ir.v2.ids import LogicalValueID, MaterializationID, StorageAllocationID, StorageRegionID, ValueVersionID
from scar.ir.v2.values import LogicalValue, Materialization, StorageAllocation, StorageRegion, ValueGraph, ValueVersion
from tests.fixtures.execution_order_graphs import event_order_execution
from tests.fixtures.execution_paths import declared_path


def _second_writer(program, model):
    """Add a real content StateAccess to r1, then rebuild actual state SSA."""
    operation = next(row for row in program.operations if row.id == OperationID('order.r1'))
    old = next(row for row in program.values if row.id == ValueID('order.p1.content.after'))
    new = StateVersionValue(ValueID('visibility.r1.content.after'), program.root,
        OperationResult(operation.id, len(operation.results)), old.location)
    before = Use(UseID('visibility.r1.content.before'), old.id, UseRole.STATE_CONTENT)
    reference = Use(UseID('visibility.r1.content.reference'), ValueID('order.buffer'), UseRole.REFERENCE)
    access = StateAccess(old.location, before.id, AccessMode.READ_WRITE, new.id,
                         Footprint(FootprintKind.WHOLE), reference=reference.id)
    operations, seen = [], False
    for row in program.operations:
        if row.id == operation.id:
            row = replace(row, uses=(*row.uses, before, reference), results=(*row.results, new.id),
                          accesses=(*row.accesses, access))
            seen = True
        elif seen:
            row = replace(row, uses=tuple(replace(use, value=new.id) if use.value == old.id else use for use in row.uses))
        operations.append(row)
    values = tuple(replace(row, targets=(old.location,), selector=Footprint(FootprintKind.WHOLE))
                   if row.id == ValueID('order.buffer') else row for row in program.values)
    program = replace(program, operations=tuple(operations), values=(*values, new),
        resource_uses=(*program.resource_uses, ResourceUse(operation.id, ResourceRequirementID('order.content'),
            ResourceDefinitionID('order.content'), reference.id)))
    fresh = declared_path(program, ((program.regions[0].entry, None),))
    model = replace(model, snapshot=fresh.snapshot, runs=fresh.runs, processes=fresh.processes,
        threads=fresh.threads, activations=fresh.activations, segments=fresh.segments, visits=fresh.visits,
        operations=fresh.operations, values=fresh.values, uses=fresh.uses, transfers=fresh.transfers)
    definitions = {row.id: row for row in program.values}
    originals = {row.id: row for row in program.operations}
    occurrences = {row.id: row for row in model.operations}
    uses = {(row.operation, row.use): row for row in model.uses}

    def support(identity):
        original = originals[occurrences[identity].operation]
        return tuple(uses[identity, use.id].value for use in original.uses
                     if isinstance(definitions[use.value], StateVersionValue))

    accesses = tuple(replace(row, support=support(row.operation),
        handle=replace(row.handle, support=support(row.operation))
            if type(row.handle) is ImplicitBinding else row.handle) for row in model.accesses)
    r1 = next(row.id for row in model.operations if row.operation == operation.id)
    handle = next(row for row in model.accesses if row.id == ResourceAccessID('order.p1.content'))
    accesses = (*accesses, ResourceAccessBinding(ResourceAccessID('visibility.r1.content'), r1,
        handle.requirement, handle.handle, support(r1), (), handle.source))
    effect = AccessRef(r1, len(operation.accesses))
    submissions = tuple(replace(row, effects=(*row.effects, effect)) if row.id == WorkTicketID('r1') else row
                        for row in model.submissions)
    return program, replace(model, accesses=accesses, submissions=submissions), effect


def visibility_execution(*, right_terminal=False, right_written=4,
                         right_kind=WorkOutcomeKind.COMPLETED, with_wait=True,
                         old_version=False, missing_right_support=False, right_alias=False):
    """Return (program, model, values, artifact_bytes, details).

    P1 establishes [0,4), r1 independently establishes [4,8), C reads [0,8).
    P1 has an actual result and CompletedVisibility, r1 uses OrderedVisibility.
    r1's event record and wait provide the existing exact path to C's Start.
    """
    program, model = event_order_execution(same_queue=False, with_wait=with_wait)
    program, model, right_effect = _second_writer(program, model)
    source, point = model.runs[0].source, model.activations[0].entry
    unknown = Unresolved('fixture protocol/native applicability is not established', point)
    tickets = {row.id.value: row for row in model.submissions}
    effects = {'left': tickets['p1'].effects[0], 'right': right_effect,
               'old': tickets['p2'].effects[0]}
    names = ('left', 'right', 'old') if old_version else ('left', 'right')
    counts = {'left': 4, 'right': right_written, 'old': 4}
    rows = []
    for name in names:
        metadata = {'process_id': 10, 'thread_id': 11}
        if name != 'right' or right_terminal:
            metadata['scar_native_result'] = {'schema': 'scar.native.byte-prefix-write', 'schema_version': 1,
                'stage': name, 'requested_bytes': 4, 'written_bytes': counts[name]}
        else:
            # This is a request/enqueue observation, not an observed native
            # result. Removing an Outcome cannot convert a result into this.
            metadata['request_stage'] = name
        rows.append({'kind': 'python_c_call', 'invocation_id': len(rows) + 1,
            'code_id': 'declared-stage-' + name, 'ts_ns': 10 * (len(rows) + 1), 'duration_ns': 1,
            'inputs': [], 'outputs': [], 'metadata': metadata})
    raw = ''.join(json.dumps(row, sort_keys=True) + '\n' for row in rows).encode()
    manifest, index, payloads = build_inventory({'visibility': raw})
    resolved, = InventoryResolver(ExternalSnapshots(artifact_bytes=payloads)).resolve(manifest, index).sources
    inventory = EvidenceInventoryBinding(EvidenceInventoryID('visibility'), model.runs[0].id,
                                         manifest, index, source)
    reference = InventorySourceRef(inventory.id, resolved.key)
    stages = {name: RawRecordRef(reference, item.line, item.sha256)
              for name, item in zip(names, resolved.raw_records)}
    graph = ValueGraph()
    logical = LogicalValueID('visibility.content')
    wanted, previous = ValueVersionID(logical, 1), ValueVersionID(logical, 0)
    graph.add_logical_value(LogicalValue(logical, 'bytes'))
    graph.add_version(ValueVersion(wanted))
    graph.add_version(ValueVersion(previous))
    allocation = StorageAllocationID('visibility.content')
    graph.add_allocation(StorageAllocation(allocation, 'cpu', 8))
    specifications = (('whole', 0, 8), ('left', 0, 4), ('right', 4, 4), ('right.actual', 4, right_written))
    for name, offset, length in specifications:
        graph.add_region(StorageRegion(StorageRegionID(name), allocation, offset, (length,), (1,), 'uint8', 'cpu'))
    mat, old_mat = MaterializationID('visibility.content'), MaterializationID('visibility.old')
    graph.add_materialization(Materialization(mat, wanted, 'bytes', 'cpu', StorageRegionID('whole')))
    graph.add_materialization(Materialization(old_mat, previous, 'bytes', 'cpu', StorageRegionID('whole')))
    artifact = external_artifact(graph)
    region = lambda name: RegionRef(artifact, StorageRegionID(name))
    materialization = MaterializationRef(artifact, mat)
    original_tickets = {'left': 'p1', 'right': 'r1', 'old': 'p2'}
    writes, outcomes, produced, supports = [], [], [], []
    consumer = tickets['c']
    queue_access = next(row for row in model.accesses if row.id == consumer.scheduling.queue_access)
    binding = next(row for row in model.requirements if row.id == queue_access.requirement)
    domain = QueueDomain(binding.target.instance)
    read_id = ContentReadID('visibility.read')
    for name in names:
        ticket = tickets[original_tickets[name]]
        alias = name == 'old' or name == 'right' and right_alias
        requested = region('right' if name == 'right' and not right_alias else 'left')
        placement = StorageContent(MaterializationRef(artifact, old_mat) if alias else materialization, requested)
        write = WriteAssociation(WriteAssociationID(name), stages[name], WorkWrite(ticket.id),
            StateProduction(effects[name]), placement, (), source)
        writes.append(write)
        actual = None
        terminal = name != 'right' or right_terminal
        if terminal:
            occurrence = ticket.origin.operation
            result = ProviderFactReference(resolved.raw_artifact,
                                           f'#L{stages[name].line}/metadata/scar_native_result')
            outcome = ResourceOutcome(WorkOutcomeID(name), ticket.id,
                right_kind if name == 'right' else WorkOutcomeKind.COMPLETED,
                OccurrencePoint(occurrence, OccurrencePhase.AFTER), result,
                (effects[name],), Completeness.PARTIAL, unknown, source)
            outcomes.append(outcome)
            actual = OutcomeProduction(OutcomeProductionID(name), write.id, outcome.id, 0,
                region('right.actual' if name == 'right' and not right_alias else 'left'), BytePrefixWrite(), source)
            produced.append(actual)
        visibility = (CompletedVisibility(WorkEnd(ticket.id), effects[name], domain, ticket.protocol)
                      if name == 'left' else OrderedVisibility(ticket.protocol))
        if not (name == 'right' and missing_right_support):
            supports.append(ContributionSupport(ContributionSupportID(name), read_id, write.id,
                None if actual is None else actual.id, visibility, source))
    read_effect = consumer.effects[0]
    occurrence = next(row for row in model.operations if row.id == read_effect.operation)
    operation = next(row for row in program.operations if row.id == occurrence.operation)
    use = operation.accesses[read_effect.index].before
    before = next(row.value for row in model.uses if row.operation == occurrence.id and row.use == use)
    read = ContentRead(read_id, ResourceConsumer(read_effect, WholeWorkRead(consumer.id), unknown),
        StorageContent(materialization, region('left' if right_alias else 'whole')), read_effect,
        OccurrencePoint(occurrence.id, OccurrencePhase.BEFORE), (before,), unknown, source)
    model = replace(model, source_inventories=(inventory,), writes=tuple(writes), outcomes=tuple(outcomes),
        produced=tuple(produced), content_reads=(read,), contribution_supports=tuple(supports))
    details = {'read': read_id, 'whole': region('whole'), 'left': region('left'), 'right': region('right'),
               'artifact': artifact, 'consumer': consumer.id, 'domain': domain,
               'stages': stages, 'source': resolved}
    return program, model, {artifact.sha256: graph}, payloads, details


__all__ = ['visibility_execution']
