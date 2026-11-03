"""Describe boundaries of selected original operations, without transforming.

Declared interfaces, an outside consumer, an implementation transfer and an
observable escape are distinct facts. Missing effect/alias/observer contracts
remain field-specific obligations. No callee body or SSA definition is copied.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from scar.analysis.program_dependencies import DependencyCut
from scar.ir.program.dependencies import (
    DependencyCondition, DependencyEdge, DependencyEvidence, DependencyFrontier,
    DependencyKind as K, DependencyMeaning as M, DependencyPoint as Point,
)
from scar.ir.program.ids import LocationID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    AccessMode, Behavior, CompletionResult, Footprint, ReferenceValue, StateVersionValue,
    TerminatorKind, UseRole,
)
from scar.ir.program.resources import CreatedResource, ResourceDefinition, ResourceLocation, ResourceRequirement, ResourceUse
from scar.ir.program.control import PendingPayload
from scar.ir.program.drivers import BodyDriveResult
from scar.ir.program.resumption import ResumeInput, SavedInput
from scar.ir.program.stored_values import StoredValueWrite
from scar.ir.program.state_addresses import (
    ExistingAccess, InvokeStateOperand, ReferenceOwner, StateAddressRefinement,
    UnknownOwner, UnknownSelection, address_effect_uses,
)


class BoundaryKnowledge(str, Enum):
    KNOWN = "KNOWN"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True, slots=True)
class BoundaryFieldStatus:
    field: str
    knowledge: BoundaryKnowledge
    scope: str
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BoundaryPayload:
    position: int
    original_kind: str
    original_index: int | None
    use: Point | None
    value: Point | None
    landing: Point | None
    original: UseID | CompletionResult | PendingPayload | ResumeInput | SavedInput | BodyDriveResult


@dataclass(frozen=True, slots=True)
class BoundaryControlFlow:
    source: Point
    target: Point | None
    kind: str
    successor: int | None
    exit_name: str | None
    payload: tuple[BoundaryPayload, ...]
    source_selected: bool
    target_selected: bool
    structural: bool


@dataclass(frozen=True, slots=True)
class BoundaryStateOutcome:
    kind: str
    successor: int | None
    value: Point


@dataclass(frozen=True, slots=True)
class BoundaryStateAccess:
    operation: Point
    location: Point
    before: Point
    before_value: Point
    before_role: UseRole
    before_is_member: bool
    mode: AccessMode | None
    footprint: Footprint | None
    full_overwrite: bool | None
    reference: Point | None
    outcomes: tuple[BoundaryStateOutcome, ...]
    refinements: tuple[StateAddressRefinement, ...]
    address_operands: tuple[Point, ...]
    kind: str = "ACCESS"

    @property
    def mode_knowledge(self):
        if self.kind == "CONTROL_TRANSFER":
            return BoundaryKnowledge.NOT_APPLICABLE
        return (BoundaryKnowledge.KNOWN if self.mode is not None else
                BoundaryKnowledge.PARTIAL if self.refinements else BoundaryKnowledge.UNKNOWN)

    @property
    def range_knowledge(self):
        if self.kind == "CONTROL_TRANSFER":
            return BoundaryKnowledge.NOT_APPLICABLE
        if self.footprint is not None and self.footprint.kind.value != "UNKNOWN":
            return BoundaryKnowledge.KNOWN
        return BoundaryKnowledge.PARTIAL if self.refinements else BoundaryKnowledge.UNKNOWN


@dataclass(frozen=True, slots=True)
class BoundaryReference:
    value: Point
    referent_identity: str | None
    targets: tuple[Point, ...] | None
    selector: Footprint


@dataclass(frozen=True, slots=True)
class BoundaryResource:
    point: Point
    requirement: ResourceRequirement
    uses: tuple[ResourceUse, ...]
    definitions: tuple[ResourceDefinition, ...]
    locations: tuple[ResourceLocation, ...]


@dataclass(frozen=True, slots=True)
class BoundaryEscape:
    kind: str
    source: Point
    value: Point | None
    sink: Point | None
    observable: bool | None
    interface_only: bool
    witness: StoredValueWrite | DependencyEdge | None = None


@dataclass(frozen=True, slots=True)
class BoundaryEffect:
    operation: Point
    declared_behaviors: tuple[Behavior, ...]
    effects_complete: bool
    declared_may_raise: bool | None
    open_facets: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BoundaryAnalysis:
    cut: DependencyCut
    inputs: tuple[DependencyEdge, ...]
    consumers: tuple[DependencyEdge, ...]
    implementation_interfaces: tuple[DependencyEdge, ...]
    control: tuple[BoundaryControlFlow, ...]
    state: tuple[BoundaryStateAccess, ...]
    references: tuple[BoundaryReference, ...]
    alias_relations: tuple[DependencyEdge, ...]
    escapes: tuple[BoundaryEscape, ...]
    effects: tuple[BoundaryEffect, ...]
    resources: tuple[BoundaryResource, ...]
    created_resources: tuple[Point, ...]
    ordering: tuple[DependencyEdge, ...]
    fields: tuple[BoundaryFieldStatus, ...]
    frontiers: tuple[DependencyFrontier, ...]
    transformation_authorized: bool = False

    def field(self, name):
        return next(row for row in self.fields if row.field == name)

    @property
    def control_dependencies(self):
        return tuple(e for e in (*self.cut.inputs, *self.cut.outputs, *self.cut.interfaces)
                     if e.kind in (K.CONTROL, K.CONTROL_CONDITION))

    @property
    def reads(self):
        return tuple(row for row in self.state if row.mode in (AccessMode.READ, AccessMode.READ_WRITE)
            or any(effect.mode in (AccessMode.READ, AccessMode.READ_WRITE)
                   for refinement in row.refinements for effect in refinement.effects))

    @property
    def writes(self):
        return tuple(row for row in self.state if row.mode in (AccessMode.WRITE, AccessMode.READ_WRITE)
            or any(effect.mode in (AccessMode.WRITE, AccessMode.READ_WRITE)
                   for refinement in row.refinements for effect in refinement.effects))


def analyze_boundary(view, operations, *, internal_values=(), max_members=16384):
    """Mechanically describe an operation set in its original graph contexts.

    Knowledge scopes distinguish enumeration of the declared graph from
    closure of program behavior. In particular KNOWN declared ports do not
    establish pure effects, observer closure, single-entry structure or legal
    replacement. Optional internal_values select original block-argument ports
    only when their entire original block is selected. Phi/loop state ports
    retain their original Value identities.
    """
    operations = tuple(dict.fromkeys(operations))
    if not operations or any(type(point) is not Point or type(point.node) is not OperationID
                             for point in operations):
        raise TypeError('dependency cut needs qualified original Operation endpoints')
    if type(max_members) is not int or max_members < 1:
        raise ValueError('dependency cut needs a positive membership bound')
    if len(operations) > max_members:
        raise OverflowError('dependency cut membership budget exhausted')
    # Pin original inputs before a bounded cross-body query can run out of
    # time. Its known edges/frontiers must still produce a partial boundary,
    # rather than being discarded by a second, post-cut graph read.
    indexes = {namespace: view.load_index(namespace)
               for namespace in dict.fromkeys(point.namespace for point in operations)}
    cut = view.cut(operations, internal_values=internal_values, max_members=max_members)
    selected, members = set(cut.operations), set(cut.members)
    stored_writes = {}
    for namespace, index in indexes.items():
        by_operation = {}
        for write in index.graph.stored_value_writes:
            by_operation.setdefault(write.site.operation, []).append(write)
        stored_writes[namespace] = by_operation
    control, states, references, resources, effects, escapes, created, ordering = [], [], {}, [], [], [], [], []
    frontiers = list(cut.frontiers)
    groups = {}
    for p in cut.operations:
        groups.setdefault((p.namespace, p.context), set()).add(p.node)

    def point(original, node):
        return Point(original.namespace, node, original.context)

    def payload(original, arguments, landing=()):
        index = indexes[original.namespace]
        rows = []
        for position, argument in enumerate(arguments):
            use = point(original, argument) if type(argument) is UseID else None
            value = point(original, index.use_site(argument).use.value) if use is not None else None
            rows.append(BoundaryPayload(position, type(argument).__name__,
                argument.index if type(argument) is CompletionResult else None, use, value,
                point(original, landing[position]) if position < len(landing) else None, argument))
        return tuple(rows)

    for original in cut.operations:
        index = indexes[original.namespace]
        operation = index.operations[original.node]
        for use in operation.uses:
            value = index.values[use.value]
            if type(value) is ReferenceValue:
                key = point(original, value.id)
                references[key] = BoundaryReference(key, value.referent_identity,
                    None if value.targets is None else tuple(point(original, t) for t in value.targets), value.selector)
        for produced in operation.results:
            value = index.values[produced]
            if type(value) is ReferenceValue:
                key = point(original, value.id)
                references[key] = BoundaryReference(key, value.referent_identity,
                    None if value.targets is None else tuple(point(original, t) for t in value.targets), value.selector)

        state_start = len(states)

        def state_row(before, location, mode, footprint, overwrite, reference, outcomes, site, kind="ACCESS"):
            use = index.use_site(before).use
            refinement = index._state_addresses.get(site)
            refinements = (refinement,) if refinement is not None else ()
            operands = []
            for refinement in refinements:
                for effect in refinement.effects:
                    if type(effect.owner) is ReferenceOwner:
                        operands.append(point(original, effect.owner.use))
                    operands.extend(point(original, u) for u in address_effect_uses(effect))
            states.append(BoundaryStateAccess(original, point(original, location), point(original, before),
                point(original, use.value), use.role, point(original, use.value) in members,
                mode, footprint, overwrite, point(original, reference) if reference is not None else None,
                outcomes, refinements, tuple(dict.fromkeys(operands)), kind))

        for ordinal, access in enumerate(operation.accesses):
            outcomes = (() if access.after is None else
                        (BoundaryStateOutcome("AFTER_OPERATION", None, point(original, access.after)),))
            state_row(access.before, access.location, access.mode, access.footprint, access.full_overwrite,
                      access.reference, outcomes, ExistingAccess(operation.id, ordinal))
        term = operation.terminator
        if term is not None and term.kind is TerminatorKind.INVOKE:
            for use in operation.uses:
                before = index.values[use.value]
                if type(before) is not StateVersionValue or use.id not in operation.invoke_arguments:
                    continue
                outcomes = []
                for ordinal, successor in enumerate(term.successors):
                    block = index._block_records[successor.block]
                    for actual, formal in zip(successor.arguments, block.arguments):
                        value = index.values[formal]
                        if type(value) is not StateVersionValue or value.location != before.location:
                            continue
                        produced = type(actual) is CompletionResult
                        passed = (type(actual) is UseID and index.use_site(actual).use.value == before.id)
                        if produced or passed:
                            outcomes.append(BoundaryStateOutcome(successor.kind.value, ordinal, point(original, formal)))
                state_row(use.id, before.location, None, None, None, None, tuple(outcomes),
                          InvokeStateOperand(operation.id, use.id), "INVOKE")

        represented = {s.before.node for s in states[state_start:]}
        for use in operation.uses:
            before = index.values[use.value]
            if use.id in represented or type(before) is not StateVersionValue:
                continue
            outcomes = []
            if term is not None:
                for ordinal, successor in enumerate(term.successors):
                    block = index._block_records[successor.block]
                    for argument, formal in zip(successor.arguments, block.arguments):
                        if argument == use.id and type(index.values[formal]) is StateVersionValue:
                            kind = getattr(getattr(successor, "kind", None), "value", term.kind.value)
                            outcomes.append(BoundaryStateOutcome(kind, ordinal, point(original, formal)))
                if term.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE) and use.id in term.values:
                    outcomes.append(BoundaryStateOutcome(term.kind.value, None, point(original, use.value)))
            if operation.callee is not None:
                outcomes.extend(BoundaryStateOutcome("CALL_RESULT", None, point(original, value.id))
                    for value in (index.values[v] for v in operation.results)
                    if type(value) is StateVersionValue and value.location == before.location)
            transfer = (term is not None and term.kind in (TerminatorKind.JUMP, TerminatorKind.BRANCH,
                TerminatorKind.RETURN, TerminatorKind.RAISE) and operation.callee is None)
            state_row(use.id, before.location, None, None, None, None, tuple(outcomes), None,
                      "CONTROL_TRANSFER" if transfer else "STATE_INTERFACE")

        if term is not None:
            if term.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE):
                control.append(BoundaryControlFlow(original, None, term.kind.value, None, term.exit,
                    payload(original, term.values), True, False, False))
                for use_id in term.values:
                    value = index.use_site(use_id).use.value
                    if type(index.values[value]) is ReferenceValue:
                        escapes.append(BoundaryEscape("OWNER_REGION_COMPLETION", point(original, use_id),
                            point(original, value), None, None, True))
            for ordinal, successor in enumerate(term.successors):
                block = index._block_records[successor.block]
                target = point(original, block.operations[0])
                if target not in selected:
                    kind = getattr(getattr(successor, "kind", None), "value", term.kind.value)
                    control.append(BoundaryControlFlow(original, target, kind, ordinal, None,
                        payload(original, successor.arguments, block.arguments), True, False, False))

        may_raise = (True if term is not None and (term.kind is TerminatorKind.RAISE or any(
            getattr(getattr(s, "kind", None), "value", None) == "RAISE"
            for s in getattr(term, "successors", ()))) else None)
        open_facets = ("allocation", "release", "alias", "observable_escape", "rng", "external", "termination")
        if not operation.effects_complete:
            open_facets += ("read_coverage", "write_coverage", "ordering_coverage")
        if may_raise is None:
            open_facets += ("exception_coverage",)
        effects.append(BoundaryEffect(original, operation.behaviors, operation.effects_complete, may_raise, open_facets))
        for stored in stored_writes[original.namespace].get(operation.id, ()):
            use = index.use_site(stored.payload).use
            escapes.append(BoundaryEscape("DECLARED_STATE_SLOT_STORE", point(original, stored.payload),
                point(original, use.value), original, None, False, stored))

    # INVOKE completion values are original block arguments, not ordinary
    # operation.results. Keep their reference declarations as well.
    for member in cut.members:
        if type(member.node) is ValueID:
            value = indexes[member.namespace].values[member.node]
            if type(value) is ReferenceValue:
                references[member] = BoundaryReference(member, value.referent_identity,
                    None if value.targets is None else tuple(point(member, t) for t in value.targets), value.selector)

    for (namespace, context), identities in groups.items():
        index = indexes[namespace]
        representative = next(p for p in cut.operations if p.namespace == namespace and p.context == context)
        for region in index.graph.regions:
            for block in region.blocks:
                for left, right in zip(block.operations, block.operations[1:]):
                    if (left in identities) != (right in identities):
                        control.append(BoundaryControlFlow(point(representative, left), point(representative, right),
                            "SEQUENCE", None, None, (), left in identities, right in identities, True))
                source_id = block.operations[-1]
                source = index.operations[source_id]
                if source_id in identities or source.terminator is None:
                    continue
                for ordinal, successor in enumerate(source.terminator.successors):
                    target_block = index._block_records[successor.block]
                    if target_block.operations[0] in identities:
                        kind = getattr(getattr(successor, "kind", None), "value", source.terminator.kind.value)
                        origin = point(representative, source_id)
                        control.append(BoundaryControlFlow(origin, point(representative, target_block.operations[0]),
                            kind, ordinal, None, payload(origin, successor.arguments, target_block.arguments), False, True, False))
        owners = {index._blocks[index._operation_blocks[identity]] for identity in identities}
        selected_requirements = {u.requirement for u in index.graph.resource_uses if u.operation in identities}
        selected_requirements.update(r.id for r in index.graph.resource_requirements if r.owner in identities or r.owner in owners)
        for requirement in index.graph.resource_requirements:
            if requirement.id not in selected_requirements:
                continue
            uses = tuple(u for u in index.graph.resource_uses if u.operation in identities and u.requirement == requirement.id)
            definitions = tuple(d for d in index.graph.resources if any(u.definition == d.id for u in uses))
            locations = tuple(l for l in index.graph.resource_locations if any(d.id == l.resource for d in definitions))
            resources.append(BoundaryResource(point(representative, requirement.id), requirement, uses, definitions, locations))
        created.extend(point(representative, d.id) for d in index.graph.resources
            if type(d.origin) is CreatedResource and d.origin.operation in identities)
        for ordered in index.graph.ordering:
            if ordered.before in identities or ordered.after in identities:
                ordering.append(DependencyEdge(point(representative, ordered.before), point(representative, ordered.after),
                    K.ORDER, M.ORDER, (DependencyEvidence("BOUNDARY_ORIGINAL_ORDER_V1", (namespace.graph,)),)))

    # A downstream use is a boundary consumer, not evidence that it observes
    # identity/content or escapes the program. Implementation transfers stay
    # separate even when their actual is an object reference.
    data_kinds = frozenset((K.VALUE_USE, K.OPERAND, K.RESULT, K.BLOCK_ARGUMENT,
        K.BINDING_PAYLOAD, K.BINDING_READ, K.STATE_INPUT, K.STATE_OUTPUT, K.STATE_VALUE, K.PROJECTION))
    inputs = tuple(e for e in cut.inputs if e.kind in data_kinds)
    consumers = tuple(e for e in cut.outputs if e.kind in data_kinds)
    aliases = tuple(e for e in (*cut.inputs, *cut.outputs, *cut.interfaces) if e.kind is K.ALIAS)
    ordering.extend(e for e in (*cut.inputs, *cut.outputs) if e.kind is K.ORDER)
    for edge in consumers:
        value = edge.source if type(edge.source.node) is ValueID else None
        escapes.append(BoundaryEscape("OUTSIDE_CONSUMER", edge.source, value, edge.target, None, False, edge))
    for edge in cut.interfaces:
        escapes.append(BoundaryEscape("IMPLEMENTATION_INTERFACE", edge.source,
            edge.source if type(edge.source.node) is ValueID else None, edge.target, None, True, edge))

    known, partial, unknown = BoundaryKnowledge.KNOWN, BoundaryKnowledge.PARTIAL, BoundaryKnowledge.UNKNOWN
    interrupted = any(f.kind == "DEPENDENCY_BOUNDARY_ENUMERATION_OPEN"
        or "BUDGET" in f.kind or "UNENUMERATED" in f.kind for f in frontiers)
    access_closed = all(e.effects_complete for e in effects) and all(
        row.mode is not None or row.kind == "CONTROL_TRANSFER" for row in states)
    statuses = [
        BoundaryFieldStatus("inputs", partial if interrupted else known, "CURRENT_REGISTERED_RELATIONS"),
        BoundaryFieldStatus("consumers", partial if interrupted else known, "CURRENT_REGISTERED_RELATIONS"),
        BoundaryFieldStatus("implementation_interfaces", partial, "DECLARED_INTERFACES",
            ("Interface edges do not establish implementation/effect closure or observable escape.",)),
        BoundaryFieldStatus("control", known, "CANONICAL_CFG_AND_COMPLETION_PORTS",
            ("Sequence is structural; this does not prove a single-entry replaceable Region.",)),
        BoundaryFieldStatus("control_dependencies", partial if frontiers else known, "CURRENT_REGISTERED_CONTROL_RELATIONS",
            ("Control conditions and MAY strengths remain on their original dependency edges.",)),
        BoundaryFieldStatus("state", known, "CANONICAL_STATE_PORTS",
            ("Phi/loop versions and contexts remain original SSA ports; INVOKE mode may be unknown.",)),
        BoundaryFieldStatus("reads", known if access_closed else partial if states else unknown, "DECLARED_ACCESS_MODES_AND_REFINEMENTS",
            ("Known modes/paths do not close unknown operation effects or alias targets.",)),
        BoundaryFieldStatus("writes", known if access_closed else partial if states else unknown, "DECLARED_ACCESS_MODES_AND_REFINEMENTS",
            ("Normal and raise post-states are separate; failure is not assumed to preserve input state.",)),
        BoundaryFieldStatus("aliases", partial if references or aliases else unknown, "REFERENCE_DECLARATIONS",
            ("Targets are may-targets; reference identity is not content or storage identity.",)),
        BoundaryFieldStatus("escapes", unknown, "OBSERVABLE_BEHAVIOR",
            ("Outside consumers, stores and completion/interface transfers are not observer-closure proofs.",)),
        BoundaryFieldStatus("resources", partial if resources or created else unknown, "DECLARED_REQUIREMENTS",
            ("Requirements/created resources do not establish physical allocation, placement or completion.",)),
        BoundaryFieldStatus("ordering", partial, "EXPLICIT_ORDER_AND_STATE_RELATIONS",
            ("Sequence/CFG edges are not promoted to necessary ordering; additional effect constraints may remain.",)),
    ]
    for name in ("allocates", "frees", "rng", "external_effects"):
        statuses.append(BoundaryFieldStatus(name, unknown, "PROGRAM_EFFECTS",
            ("No unified per-operation contract for this facet is supplied by the canonical records.",)))
    statuses.append(BoundaryFieldStatus("may_raise", partial if any(e.declared_may_raise for e in effects) else unknown,
        "DECLARED_COMPLETIONS", ("A declared raise route is preserved; absent routes are not silently declared impossible.",)))
    return BoundaryAnalysis(cut, inputs, consumers, cut.interfaces, tuple(control), tuple(states),
        tuple(references.values()), aliases, tuple(escapes), tuple(effects), tuple(resources), tuple(created),
        tuple(dict.fromkeys(ordering)), tuple(statuses), tuple(dict.fromkeys(frontiers)))
