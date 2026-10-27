"""Canonical resource programs and explicit execution declarations, not runtime proof."""
from dataclasses import replace
from hashlib import sha256
import json

from scar.ir.execution.common import EvidencePoint, MissingEvidence, Unresolved
from scar.ir.execution.coordinates import (
    BlockVisit, ExecutionRun, ExecutionSegment, HostThreadInstance, InitialEntry,
    OccurrencePhase, OccurrencePoint, OperationOccurrence, ProcessInstance,
    ProgramSnapshot, RegionActivation, UseOccurrence, ValueOccurrence,
)
from scar.ir.execution.ids import (
    BlockVisitID, ExecutionSegmentID, HandleBindingID, HostThreadInstanceID,
    OperationOccurrenceID, ProcessInstanceID, RealizationID, RegionActivationID,
    NativeHandleLifetimeID, ResourceAccessID, ResourceBindingID, ResourceInstanceID, RunID, ValueOccurrenceID,
)
from scar.ir.execution.model import ExecutionModel
from scar.ir.execution.resources import (
    AllocationPlacement, AllocationTarget, CreatedAt, ExplicitHandle, HandleBinding, HandleNamespace, ImplicitBinding, ImportedAt,
    InstanceTarget, NativeHandle, ProcessRealm, RequirementBinding, ResourceAccessBinding,
    ResourceInstance, ResourceRealization, UnresolvedHandle,
)
from scar.ir.program.codec import dumps
from scar.ir.program.ids import BlockID, LocationID, OperationID, RegionID, ResourceDefinitionID, ResourceRequirementID, UseID, ValueID
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, DataValue, ExitKind, ExitPort,
    Footprint, FootprintKind, LiteralOrigin, Operation, OperationResult, ProgramGraph,
    ReferenceValue, Region, StateAccess, StateLocation, StateVersionValue,
    Terminator, TerminatorKind, Use, UseRole, ValueKind, ValueType,
)
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.program.resources import (
    CapacityConstraint, CreatedResource, ExternalResource, ResourceDefinition, ResourceKind,
    ResourceLocation, ResourceRequirement, ResourceRole, ResourceUse,
)
from scar.ir.v2.ids import StorageAllocationID
from scar.ir.v2.values import StorageAllocation, ValueGraph


def resource_worker_program(*, external=False, implicit=False, capacity=False, fixed_descriptor=None):
    """One acquire, two stateful uses and Return, with a region-owned requirement."""
    region, block, world = RegionID("resource.worker"), BlockID("resource.entry"), LocationID("resource.world")
    entry = StateVersionValue(ValueID("resource.initial"), region, BlockArgument(block, 0), world)
    create = OperationID("resource.acquire")
    handle = ReferenceValue(ValueID("resource.handle"), region, OperationResult(create, 0))
    descriptor = DataValue(ValueID("resource.fd"), region, OperationResult(create, 1), "builtins.int")
    after = StateVersionValue(ValueID("resource.created"), region, OperationResult(create, 2), world)
    before = Use(UseID("resource.acquire.before"), entry.id, UseRole.STATE_CONTENT)
    acquire = Operation(create, "acquire resource handle", (Behavior.CONTROL, Behavior.READ, Behavior.WRITE),
        (before,), (handle.id, descriptor.id, after.id),
        (StateAccess(world, before.id, AccessMode.READ_WRITE, after.id, Footprint(FootprintKind.WHOLE)),))
    if fixed_descriptor is not None:
        descriptor = replace(descriptor, origin=LiteralOrigin(fixed_descriptor))
        after = replace(after, origin=OperationResult(create, 1))
        acquire = replace(acquire, results=(handle.id, after.id))
    operations, values, resource_uses = [acquire], [entry, handle, descriptor, after], []
    definition = ResourceDefinition(ResourceDefinitionID("resource.ofd"), ResourceKind.FILE,
        ResourceRole.OPEN_FILE_DESCRIPTION,
        ExternalResource(region, "external.ofd") if external else CreatedResource(create))
    requirement = ResourceRequirement(ResourceRequirementID("resource.required"), region,
                                     definition.kind, definition.role,
                                     (CapacityConstraint("bytes", "B", 16),) if capacity else ())
    for number in range(2):
        identity = OperationID(f"resource.use.{number}")
        reference = Use(UseID(f"resource.use.{number}.handle"), handle.id, UseRole.REFERENCE)
        fd = Use(UseID(f"resource.use.{number}.fd"), descriptor.id, UseRole.DATA)
        before = Use(UseID(f"resource.use.{number}.before"), after.id, UseRole.STATE_CONTENT)
        after = StateVersionValue(ValueID(f"resource.used.{number}"), region, OperationResult(identity, 0), world)
        values.append(after)
        operations.append(Operation(identity, "stateful resource access", (Behavior.READ, Behavior.WRITE),
            (reference, fd, before), (after.id,),
            (StateAccess(world, before.id, AccessMode.READ_WRITE, after.id, Footprint(FootprintKind.WHOLE)),)))
        resource_uses.append(ResourceUse(identity, requirement.id, definition.id,
                                         None if implicit else reference.id))
    returned = (Use(UseID("resource.return.handle"), handle.id, UseRole.REFERENCE),
                Use(UseID("resource.return.world"), after.id, UseRole.STATE_CONTENT))
    operations.append(Operation(OperationID("resource.return"), "return resource", (Behavior.CONTROL,),
        returned, terminator=Terminator(TerminatorKind.RETURN, exit="normal", values=tuple(row.id for row in returned))))
    body = Region(region, "generic resource worker", block,
        (Block(block, (entry.id,), tuple(row.id for row in operations)),),
        (ExitPort("normal", ExitKind.NORMAL, (ValueType(ValueKind.REFERENCE), ValueType(ValueKind.STATE, location=world))),))
    return ProgramGraph(region, (body,), tuple(operations), tuple(values), (StateLocation(world, "resource state"),),
        resources=(definition,), resource_requirements=(requirement,), resource_uses=tuple(resource_uses),
        resource_locations=(ResourceLocation(world, definition.id),))


def _with_native_descriptor_operations(program):
    """Real Data ports for a dup and an independent open, with current state."""
    region, world = program.root, program.locations[0].id
    added_ops, added_values = [], []
    previous = ValueID("resource.created")
    for name in ("resource.dup", "resource.open"):
        identity = OperationID(name)
        fd = DataValue(ValueID(name + ".fd"), region, OperationResult(identity, 0), "builtins.int")
        after = StateVersionValue(ValueID(name + ".after"), region, OperationResult(identity, 1), world)
        before = Use(UseID(name + ".before"), previous, UseRole.STATE_CONTENT)
        uses = ((Use(UseID(name + ".fd-in"), ValueID("resource.fd"), UseRole.DATA),)
                if name == "resource.dup" else ())
        added_ops.append(Operation(identity, name, (Behavior.CONTROL, Behavior.READ, Behavior.WRITE),
            (*uses, before), (fd.id, after.id),
            (StateAccess(world, before.id, AccessMode.READ_WRITE, after.id, Footprint(FootprintKind.WHOLE)),)))
        added_values.extend((fd, after))
        previous = after.id
    first = program.operations[1]
    first = replace(first, uses=tuple(replace(row, value=previous) if row.id == first.accesses[0].before else row
                                     for row in first.uses))
    operations = (program.operations[0], *added_ops, first, *program.operations[2:])
    body = program.regions[0]
    return replace(program, operations=operations, values=(*program.values, *added_values),
        regions=(replace(body, blocks=(replace(body.blocks[0], operations=tuple(row.id for row in operations)),)),),
        resources=(*program.resources, ResourceDefinition(ResourceDefinitionID("resource.other-ofd"),
            ResourceKind.FILE, ResourceRole.OPEN_FILE_DESCRIPTION, CreatedResource(OperationID("resource.open")))))


def _with_close_operation(program):
    """An explicit state-changing close phase before the second access."""
    identity, world = OperationID("resource.close"), program.locations[0].id
    before = Use(UseID("resource.close.before"), ValueID("resource.used.0"), UseRole.STATE_CONTENT)
    handle = Use(UseID("resource.close.handle"), ValueID("resource.handle"), UseRole.REFERENCE)
    after = StateVersionValue(ValueID("resource.closed"), program.root, OperationResult(identity, 0), world)
    closed = Operation(identity, "completed close phase", (Behavior.CONTROL, Behavior.READ, Behavior.WRITE),
        (handle, before), (after.id,),
        (StateAccess(world, before.id, AccessMode.READ_WRITE, after.id, Footprint(FootprintKind.WHOLE)),))
    operations = []
    for operation in program.operations:
        if operation.id == OperationID("resource.use.1"):
            operations.append(closed)
            operation = replace(operation, uses=tuple(replace(row, value=after.id)
                if row.id == operation.accesses[0].before else row for row in operation.uses))
        operations.append(operation)
    body = program.regions[0]
    return replace(program, operations=tuple(operations), values=(*program.values, after),
        regions=(replace(body, blocks=(replace(body.blocks[0], operations=tuple(row.id for row in operations)),)),))


def resource_execution_program(*, activations=2, external=False, implicit=False, native_handles=False,
                               close=False, capacity=False, fixed_descriptor=None):
    """Separate occurrences and resources for repeated execution of one static Create."""
    program = resource_worker_program(external=external, implicit=implicit, capacity=capacity,
                                      fixed_descriptor=fixed_descriptor)
    if native_handles:
        program = _with_native_descriptor_operations(program)
    if close:
        program = _with_close_operation(program)
    payload = dumps(program).encode("utf-8")
    artifact = ProviderArtifact("memory:canonical-resource-program", sha256(payload).hexdigest(),
                                len(payload), "scar.program-graph")
    snapshot = ProgramSnapshot(artifact, json.loads(payload)["schema_version"])
    missing = MissingEvidence("hand-authored declaration; no runtime/source correspondence")
    run, process, thread = RunID("resource.run"), ProcessInstanceID("resource.process"), HostThreadInstanceID("resource.thread")
    point = EvidencePoint(run, process, missing)
    rows = {key: [] for key in ("activations", "segments", "visits", "operations", "values", "uses",
                                "resources", "realizations", "requirements", "handles", "accesses")}
    for number in range(activations):
        prefix = f"activation.{number}"
        activation, segment, visit = RegionActivationID(prefix), ExecutionSegmentID(prefix), BlockVisitID(prefix)
        rows["activations"].append(RegionActivation(activation, program.root, process, point))
        rows["segments"].append(ExecutionSegment(segment, activation, thread, InitialEntry(point)))
        rows["visits"].append(BlockVisit(visit, segment, program.regions[0].entry))
        occurrences = {op.id: OperationOccurrenceID(prefix + "." + op.id.value) for op in program.operations}
        values = {}
        for value in program.values:
            identity = ValueOccurrenceID(prefix + "." + value.id.value)
            origin = (visit if isinstance(value.origin, BlockArgument) else activation
                      if isinstance(value.origin, LiteralOrigin) else occurrences[value.origin.operation])
            rows["values"].append(ValueOccurrence(identity, value.id, origin))
            values[value.id] = identity
        for op in program.operations:
            rows["operations"].append(OperationOccurrence(occurrences[op.id], visit, op.id))
            rows["uses"].extend(UseOccurrence(occurrences[op.id], use.id, values[use.value]) for use in op.uses)
        resource = ResourceInstanceID(prefix + ".ofd")
        target = InstanceTarget(resource)
        acquire = occurrences[OperationID("resource.acquire")]
        rows["resources"].append(ResourceInstance(resource, ResourceKind.FILE, ResourceRole.OPEN_FILE_DESCRIPTION,
            ProcessRealm(process), ImportedAt(point) if external else CreatedAt(acquire), missing))
        rows["realizations"].append(ResourceRealization(RealizationID(prefix), program.resources[0].id,
            activation if external else acquire, target, missing))
        binding = ResourceBindingID(prefix)
        rows["requirements"].append(RequirementBinding(binding, program.resource_requirements[0].id,
                                                     activation, target, missing))
        handle = HandleBindingID(prefix)
        support = (values[ValueID("resource.created")],)
        rows["handles"].append(HandleBinding(handle,
            UnresolvedHandle(values[ValueID("resource.handle")], Unresolved("object denotation not captured", point)),
            target, OccurrencePoint(acquire, OccurrencePhase.AFTER), Unresolved("handle end not captured", point),
            support, Unresolved("rights unknown", point), Unresolved("ownership unknown", point), missing))
        if native_handles:
            other = ResourceInstanceID(prefix + ".other-ofd")
            rows["resources"].append(ResourceInstance(other, ResourceKind.FILE, ResourceRole.OPEN_FILE_DESCRIPTION,
                ProcessRealm(process), CreatedAt(occurrences[OperationID("resource.open")]), missing))
            rows["realizations"].append(ResourceRealization(RealizationID(prefix + ".other"),
                ResourceDefinitionID("resource.other-ofd"), occurrences[OperationID("resource.open")],
                InstanceTarget(other), missing))
            namespace = HandleNamespace(ProcessRealm(process), ProviderFactReference(artifact, "declared-native-descriptor-namespace"))
            for label, static_fd, producer, static_state, selected_target in (
                ("first", "resource.fd", "resource.acquire", "resource.created", target),
                ("dup", "resource.dup.fd", "resource.dup", "resource.dup.after", target),
                ("open", "resource.open.fd", "resource.open", "resource.open.after", InstanceTarget(other)),
            ):
                endpoint = NativeHandle(values[ValueID(static_fd)], namespace,
                                        NativeHandleLifetimeID(prefix + "." + label), missing)
                rows["handles"].append(HandleBinding(HandleBindingID(prefix + "." + label), endpoint, selected_target,
                    OccurrencePoint(occurrences[OperationID(producer)], OccurrencePhase.AFTER),
                    Unresolved("native handle end unknown", point), (values[ValueID(static_state)],),
                    Unresolved("rights unknown", point), Unresolved("ownership unknown", point), missing))
        for index in range(2):
            identity = occurrences[OperationID(f"resource.use.{index}")]
            static_op = next(row for row in program.operations if row.id == OperationID(f"resource.use.{index}"))
            state = values[next(row.value for row in static_op.uses if row.id == static_op.accesses[0].before)]
            selected = (ImplicitBinding(ProviderFactReference(artifact, "declared-current-resource-selection"), (state,))
                        if implicit else ExplicitHandle(handle))
            rows["accesses"].append(ResourceAccessBinding(ResourceAccessID(prefix + f".access.{index}"),
                identity, binding, selected, (state,), (), missing))
    model = ExecutionModel(snapshot, runs=(ExecutionRun(run, missing),),
        processes=(ProcessInstance(process, run, None, missing),),
        threads=(HostThreadInstance(thread, process, None, missing),),
        **{name: tuple(items) for name, items in rows.items()})
    return program, model


def resource_execution_with_allocation():
    """A real ValueGraph allocation placed in a distinct external memory pool."""
    from scar.ir.execution.snapshot import external_artifact

    program, model = resource_execution_program(activations=1)
    values = ValueGraph()
    allocation = StorageAllocationID("resource.storage")
    values.add_allocation(StorageAllocation(allocation, "cpu", 64))
    artifact = external_artifact(values, "memory:resource-allocation")
    target = AllocationTarget(artifact, allocation)
    point = model.activations[0].entry
    missing = MissingEvidence("declared allocation placement; runtime identity unverified")
    pool = ResourceInstance(ResourceInstanceID("resource.pool"), ResourceKind.MEMORY, ResourceRole.MEMORY_POOL,
        ProcessRealm(model.processes[0].id), ImportedAt(point), missing)
    model = replace(model, resources=(*model.resources, pool),
        placements=(AllocationPlacement(target, InstanceTarget(pool.id), missing),))
    return program, model, {artifact.sha256: values}
