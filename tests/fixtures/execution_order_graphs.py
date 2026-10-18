"""Canonical pending record/wait paths; declarations, not native order proof."""
from dataclasses import replace

from scar.ir.execution.common import MissingEvidence, Unresolved
from scar.ir.execution.coordinates import AccessRef, OccurrencePhase, OccurrencePoint, UseRef
from scar.ir.execution.ids import (
    EventRecordID, HandleBindingID, QueueOrderProfileID, QueuePrefixID, QueueWaitID,
    RealizationID, ResourceAccessID, ResourceBindingID, ResourceInstanceID,
    WorkTicketID,
)
from scar.ir.execution.order import EventRecord, QueueOrderProfile, QueueWait, RecordedPrefix
from scar.ir.execution.resources import (
    ExplicitHandle, HandleBinding, ImplicitBinding, ImportedAt, InstanceTarget,
    ProcessRealm, RequirementBinding, ResourceAccessBinding, ResourceInstance,
    ResourceRealization, UnresolvedHandle,
)
from scar.ir.execution.work import QueuePrefix, QueueStart, Queued, WithinOperation, WorkSubmission
from scar.ir.program.ids import BlockID, LocationID, OperationID, RegionID, ResourceDefinitionID, ResourceRequirementID, UseID, ValueID
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, ExitKind, ExitPort, Footprint,
    FootprintKind, Operation, OperationResult, ProgramGraph, ReferenceValue,
    Region, StateAccess, StateLocation, StateVersionValue, Terminator,
    TerminatorKind, Use, UseRole, ValueKind, ValueType,
)
from scar.ir.program.providers import ProviderFactReference
from scar.ir.program.resources import (
    ExternalResource, ResourceDefinition, ResourceKind, ResourceLocation,
    ResourceRequirement, ResourceRole, ResourceUse,
)
from scar.ir.v2.common import Completeness
from tests.fixtures.execution_paths import declared_path


def _order_program(*, same_queue):
    region, block = RegionID("order.body"), BlockID("order.entry")
    locations = {name: LocationID("order." + name) for name in ("content", "qa", "qb", "event")}
    values, operations, requirements, definitions, resource_uses = [], [], [], [], []
    current = {}
    for index, (name, location) in enumerate(locations.items()):
        value = StateVersionValue(ValueID("order.initial." + name), region, BlockArgument(block, index), location)
        current[name] = value.id
        values.append(value)
    buffer = ReferenceValue(ValueID("order.buffer"), region, BlockArgument(block, 4))
    event = ReferenceValue(ValueID("order.event"), region, BlockArgument(block, 5))
    values.extend((buffer, event))
    entry = tuple(row.id for row in values)
    resource_shapes = {
        "content": (ResourceKind.OTHER, ResourceRole.OPAQUE_RESOURCE),
        "event": (ResourceKind.OTHER, ResourceRole.OPAQUE_RESOURCE),
        "qa": (ResourceKind.STREAM, ResourceRole.QUEUE),
        "qb": (ResourceKind.STREAM, ResourceRole.QUEUE),
        "executor": (ResourceKind.CPU, ResourceRole.EXECUTOR),
    }
    for name, (kind, role) in resource_shapes.items():
        definitions.append(ResourceDefinition(ResourceDefinitionID("order." + name), kind, role,
            ExternalResource(region, "declared-" + name)))
        requirements.append(ResourceRequirement(ResourceRequirementID("order." + name), region, kind, role))

    def add(name, queue, modes):
        identity = OperationID("order." + name)
        uses, results, accesses, touched = [], [], [], set()
        for domain, mode in modes:
            before = Use(UseID(identity.value + "." + domain), current[domain], UseRole.STATE_CONTENT)
            uses.append(before)
            after = None
            if mode is not AccessMode.READ:
                value = StateVersionValue(ValueID(identity.value + "." + domain + ".after"), region,
                    OperationResult(identity, len(results)), locations[domain])
                values.append(value)
                current[domain] = after = value.id
                results.append(after)
            accesses.append(StateAccess(locations[domain], before.id, mode, after,
                                        Footprint(FootprintKind.WHOLE)))
            touched.add(domain)
        references = {}
        for domain, reference in (("content", buffer), ("event", event)):
            if domain in touched:
                use = Use(UseID(identity.value + "." + domain + ".reference"), reference.id, UseRole.REFERENCE)
                uses.append(use)
                references[domain] = use.id
        if queue is not None:
            touched.update((queue, "executor"))
        for resource in sorted(touched):
            resource_uses.append(ResourceUse(identity, ResourceRequirementID("order." + resource),
                ResourceDefinitionID("order." + resource), references.get(resource)))
        behaviors = [Behavior.READ]
        if any(mode is not AccessMode.READ for _, mode in modes):
            behaviors.append(Behavior.WRITE)
        if queue is not None:
            behaviors.append(Behavior.ORDER)
        operations.append(Operation(identity, "declared " + name, tuple(behaviors), tuple(uses), tuple(results),
                                    tuple(accesses), effects_complete=True))

    add("p1", "qa", (("content", AccessMode.READ_WRITE), ("qa", AccessMode.READ_WRITE)))
    add("r1", "qa", (("event", AccessMode.READ_WRITE), ("qa", AccessMode.READ_WRITE)))
    add("w", "qb", (("event", AccessMode.READ), ("qb", AccessMode.READ_WRITE)))
    consumer_queue = "qa" if same_queue else "qb"
    add("c", consumer_queue, (("content", AccessMode.READ), (consumer_queue, AccessMode.READ_WRITE)))
    add("p2", "qa", (("content", AccessMode.READ_WRITE), ("qa", AccessMode.READ_WRITE)))
    add("r2", "qa", (("event", AccessMode.READ_WRITE), ("qa", AccessMode.READ_WRITE)))
    add("host_read", None, (("content", AccessMode.READ),))
    returned = (Use(UseID("order.return.buffer"), buffer.id, UseRole.REFERENCE), *(
        Use(UseID("order.return." + name), current[name], UseRole.STATE_CONTENT) for name in locations))
    operations.append(Operation(OperationID("order.return"), "return declared path", (Behavior.CONTROL,), returned,
        terminator=Terminator(TerminatorKind.RETURN, exit="normal", values=tuple(use.id for use in returned))))
    body = Region(region, "pending event order", block,
        (Block(block, entry, tuple(op.id for op in operations)),),
        (ExitPort("normal", ExitKind.NORMAL, (ValueType(ValueKind.REFERENCE), *(
            ValueType(ValueKind.STATE, location=location) for location in locations.values()))),))
    return ProgramGraph(region, (body,), tuple(operations), tuple(values),
        tuple(StateLocation(location, "declared " + name) for name, location in locations.items()),
        resources=tuple(definitions), resource_requirements=tuple(requirements),
        resource_uses=tuple(resource_uses),
        resource_locations=tuple(ResourceLocation(location, ResourceDefinitionID("order." + name))
                                 for name, location in locations.items()))


def event_order_execution(*, same_queue=False, with_wait=True):
    """Return (ProgramGraph, ExecutionModel), all six work tickets pending.

    Host CFG: P1, record r1, wait W, consumer C, P2, record r2, host read,
    Return. Both records use the same event instance, and W reads r1 state.
    same_queue puts C on QA; with_wait=False removes only the typed wait
    association, preserving the real ORDER operation and its work occurrence.
    """
    program = _order_program(same_queue=same_queue)
    model = declared_path(program, ((BlockID("order.entry"), None),))
    source = MissingEvidence("declared queue/event fixture; no native protocol adapter")
    point = model.activations[0].entry
    unknown = Unresolved("physical correspondence/coverage not established", point)
    protocol = ProviderFactReference(model.snapshot.artifact, "declared-queue-event-protocol")
    resources, realizations, bindings, handles, accesses = [], [], [], [], []
    values = {row.id: row for row in program.values}
    dynamic_uses = {(row.operation, row.use): row for row in model.uses}
    for definition in program.resources:
        name = definition.id.value.removeprefix("order.")
        instance = ResourceInstance(ResourceInstanceID("order." + name), definition.kind, definition.role,
            ProcessRealm(model.processes[0].id), ImportedAt(point), source)
        resources.append(instance)
        target = InstanceTarget(instance.id)
        realizations.append(ResourceRealization(RealizationID(name), definition.id, model.activations[0].id, target, source))
        bindings.append(RequirementBinding(ResourceBindingID(name), ResourceRequirementID("order." + name),
                                           model.activations[0].id, target, source))
        if name in ("content", "event"):
            formal = ValueID("order.buffer" if name == "content" else "order.event")
            occurrence = next(row.id for row in model.values if row.value == formal)
            handles.append(HandleBinding(HandleBindingID(name), UnresolvedHandle(occurrence, unknown), target,
                point, unknown, (), unknown, unknown, source))
    for occurrence in model.operations:
        op = next(row for row in program.operations if row.id == occurrence.operation)
        support = tuple(dynamic_uses[occurrence.id, use.id].value for use in op.uses
                        if isinstance(values[use.value], StateVersionValue))
        for static in program.resource_uses:
            if static.operation != op.id:
                continue
            name = static.requirement.value.removeprefix("order.")
            handle = (ExplicitHandle(HandleBindingID(name)) if static.handle is not None
                      else ImplicitBinding(protocol, support))
            accesses.append(ResourceAccessBinding(ResourceAccessID(op.id.value + "." + name), occurrence.id,
                ResourceBindingID(name), handle, support, (), source))
    model = replace(model, resources=tuple(resources), realizations=tuple(realizations),
                    requirements=tuple(bindings), handles=tuple(handles), accesses=tuple(accesses))
    submissions, prefixes, records = [], [], []
    previous = {queue: QueueStart(source) for queue in ("qa", "qb")}
    for name in ("p1", "r1", "w", "c", "p2", "r2"):
        queue = "qb" if name == "w" or (name == "c" and not same_queue) else "qa"
        occurrence = next(row for row in model.operations if row.operation == OperationID("order." + name))
        op = next(row for row in program.operations if row.id == occurrence.operation)
        ticket, prefix = WorkTicketID(name), QueuePrefixID(name)
        observed = OccurrencePoint(occurrence.id, OccurrencePhase.AFTER)
        captured = previous[queue]
        prefixes.append(QueuePrefix(prefix, ResourceInstanceID("order." + queue), captured,
                                    ticket, observed, protocol, source))
        previous[queue] = prefix
        effects = tuple(AccessRef(occurrence.id, index) for index in range(len(op.accesses)))
        submissions.append(WorkSubmission(ticket, WithinOperation(occurrence.id, source),
            ResourceAccessID(op.id.value + ".executor"),
            Queued(ResourceAccessID(op.id.value + "." + queue), prefix), (), Completeness.UNKNOWN,
            effects, Completeness.PARTIAL, (), Completeness.UNKNOWN, unknown, protocol, source))
        if name in ("r1", "r2"):
            records.append(EventRecord(EventRecordID(name), ResourceInstanceID("order.event"),
                ResourceAccessID(op.id.value + ".event"), ticket,
                RecordedPrefix(ResourceInstanceID("order." + queue), captured),
                effects[0], observed, protocol, source))
    wait_occurrence = next(row for row in model.operations if row.operation == OperationID("order.w"))
    waits = (QueueWait(QueueWaitID("w"), WorkTicketID("w"), EventRecordID("r1"),
        ResourceAccessID("order.w.event"), UseRef(wait_occurrence.id, UseID("order.w.event")),
        OccurrencePoint(wait_occurrence.id, OccurrencePhase.AFTER), protocol, source),) if with_wait else ()
    profiles = tuple(QueueOrderProfile(QueueOrderProfileID(queue), ResourceInstanceID("order." + queue),
        previous[queue], protocol, source) for queue in previous)
    return program, replace(model, submissions=tuple(submissions), queue_prefixes=tuple(prefixes),
        queue_order_profiles=profiles, event_records=tuple(records), queue_waits=waits)
