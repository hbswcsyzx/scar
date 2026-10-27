"""Declared canonical work/resource paths; no native execution or ready proof."""
from dataclasses import replace

from scar.ir.execution.common import MissingEvidence, Unresolved
from scar.ir.execution.coordinates import AccessRef, OccurrencePhase, OccurrencePoint, UseRef
from scar.ir.execution.ids import (
    QueuePrefixID, ResourceAccessID, ResourceBindingID, ResourceInstanceID,
    WorkOutcomeID, WorkQuiescenceID, WorkRetentionID, WorkTicketID,
)
from scar.ir.execution.resources import (
    AllocationTarget, ImplicitBinding, ImportedAt, InstanceTarget, ProcessRealm,
    ReleaseAuthority, RequirementBinding, ResourceAccessBinding, ResourceInstance,
    Sharing,
)
from scar.ir.execution.snapshot import external_artifact, snapshot_for
from scar.ir.execution.work import (
    ActualCompletionState, BorrowRelease, DirectExecution, HandleTarget,
    InvokeBoundaryStateEffect, MaterializationRef, QueuePrefix, QueueStart,
    Queued, ResourceOutcome, WithinOperation, WorkOutcomeKind, WorkQuiescence,
    WorkRetention, WorkSubmission,
)
from scar.ir.program.ids import BlockID, OperationID, ResourceDefinitionID, ResourceRequirementID
from scar.ir.program.model import CompletionResult, StateVersionValue
from scar.ir.program.providers import ProviderFactReference
from scar.ir.program.resources import (
    ExternalResource, ResourceDefinition, ResourceKind, ResourceRequirement,
    ResourceRole, ResourceUse,
)
from scar.ir.v2.common import Completeness
from scar.ir.v2.ids import LogicalValueID, MaterializationID, StorageAllocationID, StorageRegionID, ValueVersionID
from scar.ir.v2.values import LogicalValue, Materialization, StorageAllocation, StorageRegion, ValueGraph, ValueVersion
from tests.fixtures.execution_paths import declared_path
from tests.fixtures.execution_resource_graphs import resource_execution_program
from tests.fixtures.program_resumption_invoke_graphs import partial_state_invoke_program


def _support(program, model, occurrence):
    """Actual state operands at this original operation, once per location."""
    op = next(row for row in program.operations if row.id == occurrence.operation)
    values = {row.id: row for row in program.values}
    uses = {(row.operation, row.use): row for row in model.uses}
    result = {}
    for use in op.uses:
        value = values[use.value]
        if isinstance(value, StateVersionValue):
            result.setdefault(value.location, uses[occurrence.id, use.id].value)
    return tuple(result.values())


def _with_compute_resources(program, model, operations):
    """Join CPU/queue accesses to real canonical operation/Use/state ports."""
    source = MissingEvidence("declared work fixture; no runtime/source adapter")
    point = model.activations[0].entry
    resources, requirements, accesses = list(model.resources), list(model.requirements), list(model.accesses)
    definitions, static_requirements, static_uses = list(program.resources), list(program.resource_requirements), list(program.resource_uses)
    for label, kind, role in (("executor", ResourceKind.CPU, ResourceRole.EXECUTOR),
                              ("queue", ResourceKind.STREAM, ResourceRole.QUEUE)):
        definition = ResourceDefinition(ResourceDefinitionID("work." + label), kind, role,
            ExternalResource(program.root, "work." + label))
        requirement = ResourceRequirement(ResourceRequirementID("work." + label), program.root, kind, role)
        resource = ResourceInstance(ResourceInstanceID("work." + label), kind, role,
            ProcessRealm(model.processes[0].id), ImportedAt(point), source)
        definitions.append(definition)
        static_requirements.append(requirement)
        static_uses.extend(ResourceUse(op, requirement.id, definition.id) for op in operations)
        resources.append(resource)
        for activation in model.activations:
            binding = RequirementBinding(ResourceBindingID(activation.id.value + ".work." + label),
                requirement.id, activation.id, InstanceTarget(resource.id), source)
            requirements.append(binding)
            for occurrence in model.operations:
                visit = next(row for row in model.visits if row.id == occurrence.visit)
                segment = next(row for row in model.segments if row.id == visit.segment)
                if segment.activation != activation.id or occurrence.operation not in operations:
                    continue
                support = _support(program, model, occurrence)
                accesses.append(ResourceAccessBinding(ResourceAccessID("work." + label + "." + occurrence.id.value),
                    occurrence.id, binding.id,
                    ImplicitBinding(ProviderFactReference(model.snapshot.artifact, "declared-current-" + label), support),
                    support, (), source))
    # External definitions are intentionally unresolved realizations, not new
    # physical creation claims. Exact owner/access/state links are still present.
    program = replace(program, resources=tuple(definitions), resource_requirements=tuple(static_requirements),
                      resource_uses=tuple(static_uses))
    return program, replace(model, snapshot=snapshot_for(program), resources=tuple(resources),
        requirements=tuple(requirements), accesses=tuple(accesses))


def _storage():
    values = ValueGraph()
    logical = LogicalValueID("work.output")
    version = ValueVersionID(logical, 1)
    allocation = StorageAllocationID("work.output")
    region = StorageRegionID("work.output")
    materialization = MaterializationID("work.output")
    values.add_logical_value(LogicalValue(logical, "bytes"))
    values.add_version(ValueVersion(version))
    values.add_allocation(StorageAllocation(allocation, "cpu", 16))
    values.add_region(StorageRegion(region, allocation, 0, (16,), (1,), "uint8", "cpu"))
    values.add_materialization(Materialization(materialization, version, "bytes", "cpu", region))
    artifact = external_artifact(values, uri="memory:declared-work-values")
    return values, MaterializationRef(artifact, materialization), AllocationTarget(artifact, allocation)


def _work_rows(program, model, occurrences, effects, *, queued, kind, quiescent, retained):
    source = MissingEvidence("declared work relationships; physical applicability is unverified")
    unresolved = Unresolved("not captured by this declared fixture", model.activations[0].entry)
    protocol = ProviderFactReference(model.snapshot.artifact, "declared-work-protocol")
    submissions, outcomes, quiescences, retentions, prefixes = [], [], [], [], []
    catalogs = {}
    materializations = ()
    if retained in ("allocation", "materialization"):
        values, materialization, allocation = _storage()
        catalogs[materialization.artifact.sha256] = values
        materializations = (materialization,)
    previous = QueueStart(source)
    for number, (occurrence, effect) in enumerate(zip(occurrences, effects, strict=True)):
        visits = {row.id: row for row in model.visits}
        segments = {row.id: row for row in model.segments}
        activation = segments[visits[occurrence.visit].segment].activation
        last = next(row for row in reversed(model.operations)
                    if segments[visits[row.visit].segment].activation == activation)
        final = OccurrencePoint(last.id, OccurrencePhase.BEFORE)
        released = OccurrencePoint(last.id, OccurrencePhase.AFTER)
        ticket = WorkTicketID("work." + str(number))
        retention_id = WorkRetentionID(ticket.value)
        quiescence_id = WorkQuiescenceID(ticket.value)
        executor = ResourceAccessID("work.executor." + occurrence.id.value)
        origin = WithinOperation(occurrence.id, source)
        if queued:
            prefix_id = QueuePrefixID(ticket.value)
            observed = (OccurrencePoint(occurrence.id, OccurrencePhase.EDGE, effect.post.successor_index)
                        if isinstance(effect, InvokeBoundaryStateEffect)
                        else OccurrencePoint(occurrence.id, OccurrencePhase.AFTER))
            prefixes.append(QueuePrefix(prefix_id, ResourceInstanceID("work.queue"), previous,
                ticket, observed, protocol, source))
            scheduling = Queued(ResourceAccessID("work.queue." + occurrence.id.value), prefix_id)
            previous = prefix_id
        else:
            scheduling = DirectExecution(model.threads[0].id, source)
        original_access = next((row for row in model.accesses
                                if row.operation == occurrence.id
                                and not row.id.value.startswith("work.")), None)
        original_target = (next(row.target for row in model.requirements
                                if row.id == original_access.requirement)
                           if original_access is not None else None)
        if retained == "handle":
            op = next(row for row in program.operations if row.id == occurrence.operation)
            handle_use = next(row.handle for row in program.resource_uses
                              if row.operation == op.id and row.handle is not None)
            basis = UseRef(occurrence.id, handle_use)
            handle_value = next(row.value for row in model.uses
                                if row.operation == occurrence.id and row.use == handle_use)
            handle = next(row for row in model.handles
                          if row.target == original_target and row.handle.value == handle_value)
            target = HandleTarget(handle.id)
        elif retained == "allocation":
            target, basis = allocation, materialization
        elif retained == "materialization":
            target = basis = materialization
        elif isinstance(effect, AccessRef):
            target, basis = original_target, effect
        else:
            target, basis = InstanceTarget(ResourceInstanceID("work.executor")), executor
        release = BorrowRelease(released, quiescence_id, source) if quiescent else unresolved
        retentions.append(WorkRetention(retention_id, ticket, target, basis, origin,
            _support(program, model, occurrence), ReleaseAuthority.BORROWED, Sharing.SHARED, release, source))
        submissions.append(WorkSubmission(ticket, origin, executor, scheduling, (), Completeness.UNKNOWN,
            (effect,), Completeness.PARTIAL, materializations, Completeness.UNKNOWN,
            (retention_id,), protocol, source))
        if quiescent:
            quiescences.append(WorkQuiescence(quiescence_id, ticket, final, source))
        outcomes.append(ResourceOutcome(WorkOutcomeID(ticket.value), ticket, kind, final,
            protocol, (effect,), Completeness.PARTIAL,
            quiescence_id if quiescent else unresolved, source))
    return replace(model, submissions=tuple(submissions), outcomes=tuple(outcomes),
        quiescences=tuple(quiescences), retentions=tuple(retentions), queue_prefixes=tuple(prefixes)), catalogs


def ordinary_work_execution(*, queued=False, two_tickets=False, kind=WorkOutcomeKind.COMPLETED,
                            quiescent=True, retained="resource", activations=1):
    """Ordinary StateAccess submissions; distinct work may share an operation."""
    program, model = resource_execution_program(activations=activations)
    names = (OperationID("resource.use.0"), OperationID("resource.use.1"))
    program, model = _with_compute_resources(program, model, names)
    selected = names if two_tickets else names[:1]
    occurrences = [row for row in model.operations if row.operation in selected]
    effects = [AccessRef(row.id, 0) for row in occurrences]
    model, catalogs = _work_rows(program, model, occurrences, effects, queued=queued, kind=kind,
        quiescent=quiescent, retained=retained)
    return program, model, catalogs


def invoke_work_execution(*, raised=False, queued=False, quiescent=True):
    """Use actual differently ordered NORMAL/RAISE state-result/formal ports."""
    program = partial_state_invoke_program()
    edge, block = (1, "invoke.failure") if raised else (0, "invoke.normal")
    model = declared_path(program, ((BlockID("invoke.entry"), edge), (BlockID(block), None)))
    operation = OperationID("invoke.call")
    program, model = _with_compute_resources(program, model, (operation,))
    occurrence = next(row for row in model.operations if row.operation == operation)
    invoke = next(row for row in program.operations if row.id == operation)
    successor = invoke.terminator.successors[edge]
    state_input = next(use for use in invoke.invoke_arguments)
    target_block = next(row for region in program.regions for row in region.blocks if row.id == successor.block)
    # Both signatures put world at result 0, but its destination formal is at
    # index 0 on NORMAL and index 1 on RAISE. Result 1 is ref vs packet.
    formal = next(value for value, argument in zip(target_block.arguments, successor.arguments, strict=True)
                  if argument == CompletionResult(0))
    formal_occurrence = next(row.id for row in model.values if row.value == formal)
    effect = InvokeBoundaryStateEffect(occurrence.id, UseRef(occurrence.id, state_input),
                                      ActualCompletionState(edge, 0, formal_occurrence))
    model, catalogs = _work_rows(program, model, (occurrence,), (effect,), queued=queued,
        kind=WorkOutcomeKind.FAILED if raised else WorkOutcomeKind.COMPLETED,
        quiescent=quiescent, retained="resource")
    return program, model, catalogs
