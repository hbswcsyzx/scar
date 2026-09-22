"""Construct scoped, report-only regions without inventing execution semantics.

The source view is a lexical decomposition. The execution view follows actual
invocation identity. Neither graph's missing edges constitute closure evidence.
Expanded membership costs are proportional to the explicit output membership;
no subsets, backend choices, or transformation legality are enumerated here.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import json

from scar.ir.record_codec import decode, encode, loads
from scar.ir.v2 import (
    Completeness, ControlRegionID, EffectTarget, EffectTargetKind, EvidenceClaim,
    EvidenceKind, IRBundle, OperationDefinitionID, OperationInstanceID,
    OptimizationGraph, OptimizationRegion, OptimizationRegionID, PlanAlternative,
    PlanAlternativeID, RegionGranularity, RegionPort, RegionPortKind,
    TransformKind, ValuePattern,
)
from scar.ir.v2._validation import record_errors
from scar.ir.v2.schemas import optimization_context
from scar.ir.v2.semantic import SemanticEndpoint, SemanticNodeKind, SemanticRelation
from scar.ir.v2.evidence import EvidenceEndpoint, EvidenceNodeKind, EvidenceRelation
from .effects_v2 import (
    EffectClosureEngine, EffectCoverage, EffectDimension, EffectOccurrence,
    ObservationScope, ScopeMode,
)


class RegionView(str, Enum):
    SEMANTIC = "semantic"
    EXECUTION = "execution"


class BoundaryFacet(str, Enum):
    DATA = "data"
    STATE = "state"
    CONTROL = "control"
    RESOURCE = "resource"
    EFFECTS = "effects"
    CONSUMERS = "consumers"
    ALIASES = "aliases"
    CORRESPONDENCE = "correspondence"


class BoundaryDirection(str, Enum):
    INPUT = "input"
    OUTPUT = "output"
    STATE = "state"
    CONTROL = "control"
    RESOURCE = "resource"
    EFFECT = "effect"
    ORDERING = "ordering"
    ESCAPE = "escape"


MemberID = OperationDefinitionID | OperationInstanceID
Endpoint = SemanticEndpoint | EvidenceEndpoint


@dataclass(frozen=True)
class BoundaryCoverage:
    facet: BoundaryFacet
    completeness: Completeness
    evidence: tuple[EvidenceClaim, ...] = ()


@dataclass(frozen=True)
class RegionGap:
    facet: BoundaryFacet
    reason: str
    definition: OperationDefinitionID | None = None
    instance: OperationInstanceID | None = None
    reference: str | None = None

    def __post_init__(self):
        if not self.reason:
            raise ValueError("region gap requires a reason")


@dataclass(frozen=True)
class CrossingDependency:
    id: str
    graph: RegionView
    relation: str
    source: Endpoint
    target: Endpoint
    direction: BoundaryDirection
    evidence: EvidenceClaim
    port_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class RegionEffectLink:
    port_id: str
    occurrence_id: str
    scope: str
    instance: OperationInstanceID | None
    evidence: EvidenceClaim


@dataclass(frozen=True)
class RegionConstruction:
    region: OptimizationRegionID
    view: RegionView
    scope: str
    mode: ScopeMode
    roots: tuple[MemberID, ...]
    direct_members: tuple[MemberID, ...]
    children: tuple[OptimizationRegionID, ...] = ()
    dependencies: tuple[CrossingDependency, ...] = ()
    coverage: tuple[BoundaryCoverage, ...] = ()
    gaps: tuple[RegionGap, ...] = ()
    effect_occurrences: tuple[EffectOccurrence, ...] = ()
    effect_links: tuple[RegionEffectLink, ...] = ()
    effect_coverage: tuple[EffectCoverage, ...] = ()
    unexpanded_children: tuple[MemberID, ...] = ()

    @property
    def effects_closed(self):
        dimensions = {item.dimension for item in self.effect_coverage if item.closed and "*" in item.target_domain}
        return (dimensions == set(EffectDimension)
                and not any(item.facet is BoundaryFacet.EFFECTS for item in self.gaps))


def _digest(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:32]


def _ordered(items):
    return tuple(sorted(set(items), key=lambda item: item.wire))


def _member(endpoint):
    if isinstance(endpoint, SemanticEndpoint) and endpoint.kind is SemanticNodeKind.OPERATION:
        return endpoint.id
    if isinstance(endpoint, EvidenceEndpoint) and endpoint.kind is EvidenceNodeKind.OPERATION_INSTANCE:
        return endpoint.reference
    return None


def _endpoint_key(endpoint):
    return (endpoint.kind.value, endpoint.id.wire if isinstance(endpoint, SemanticEndpoint) else endpoint.wire)


def _direction(relation):
    text = relation.value
    if text in {"reads_slot", "consumes", "observed_read"}:
        return BoundaryDirection.INPUT
    if text in {"writes_slot", "produces", "observed_write", "overwrites", "materializes"}:
        return BoundaryDirection.OUTPUT
    if text == "escapes":
        return BoundaryDirection.ESCAPE
    if text in {"happens_before"}:
        return BoundaryDirection.ORDERING
    if text in {"requires_resource", "uses_resource", "uses_storage"}:
        return BoundaryDirection.RESOURCE
    if text in {"has_effect", "may_raise"}:
        return BoundaryDirection.EFFECT
    if text == "aliases":
        return BoundaryDirection.STATE
    return BoundaryDirection.CONTROL


class RegionInventory:
    SCHEMA = "scar.regions.construction"
    SCHEMA_VERSION = 1

    def __init__(self, bundle: IRBundle, *, view=RegionView.SEMANTIC,
                 effects: EffectClosureEngine | None = None, scope: str | None = None):
        bundle.assert_valid()
        self.bundle, self.view, self.effects = bundle, RegionView(view), effects
        if effects is not None:
            effects.assert_valid()
            if effects.semantic is not bundle.semantic or (effects.evidence is not None and effects.evidence is not bundle.evidence):
                raise ValueError("effect engine must refer to the inventory graph objects")
            if scope is None:
                if len(effects.scopes) != 1:
                    raise ValueError("multiple effect scopes require an explicit scope")
                scope = next(iter(effects.scopes))
            if scope not in effects.scopes:
                raise ValueError("unknown effect observation scope")
            observation_scope = effects.scopes[scope]
        else:
            token = _digest(self.view.value, sorted(item.wire for item in bundle.semantic.definitions),
                            sorted(item.wire for item in bundle.evidence.instances))
            scope = scope or "region-scope:" + token
            observation_scope = ObservationScope(
                scope, "selected graph records", None, "snapshot:" + token,
                ScopeMode.ALL_PATHS if self.view is RegionView.SEMANTIC else ScopeMode.DYNAMIC_PATH,
                "source-structural" if self.view is RegionView.SEMANTIC else "unclosed-runtime-snapshot")
        if self.view is RegionView.EXECUTION and observation_scope.mode is not ScopeMode.DYNAMIC_PATH:
            raise ValueError("execution region cannot claim an ALL_PATHS scope")
        self.scope = scope
        self.scopes = {scope: observation_scope}
        self.graph = OptimizationGraph(optimization_context(bundle.semantic, bundle.evidence, bundle.values))
        self.constructions: dict[OptimizationRegionID, RegionConstruction] = {}
        self._nodes = bundle.semantic.definitions if self.view is RegionView.SEMANTIC else bundle.evidence.instances
        self._children = defaultdict(list)
        self._edges = defaultdict(list)
        self._observations = defaultdict(list)
        self._occurrences = defaultdict(list)
        self._batching = False
        self._batch_members = {}
        self._batch_children = defaultdict(list)
        for key, node in self._nodes.items():
            parent = node.parent_id if self.view is RegionView.SEMANTIC else node.parent
            self._children[parent].append(key)
        for children in self._children.values():
            children.sort(key=lambda item: item.wire)
        edge_graph = bundle.semantic if self.view is RegionView.SEMANTIC else bundle.evidence
        for edge in edge_graph.edges.values():
            for member in {_member(edge.source), _member(edge.target)} - {None}:
                self._edges[member].append(edge)
        if self.view is RegionView.EXECUTION:
            for observation in bundle.evidence.observations.values():
                if observation.operation is not None:
                    self._observations[observation.operation].append(observation)
        if effects is not None:
            for occurrence in effects.occurrences.values():
                if occurrence.scope == scope:
                    owner = occurrence.definition if self.view is RegionView.SEMANTIC else occurrence.instance
                    if owner is not None:
                        self._occurrences[owner].append(occurrence)

    @property
    def available_roots(self):
        return tuple(self._children.get(None, ()))

    def _scope_error(self, member):
        if self.view is RegionView.SEMANTIC or self.effects is None:
            return None
        node, scope = self._nodes[member], self.scopes[self.scope]
        if scope.process_id is not None and scope.process_id != str(node.process_id):
            return "instance belongs to another process scope"
        if scope.thread_id is not None and scope.thread_id != str(node.thread_id):
            return "instance belongs to another thread scope"
        clock = node.metadata.get("clock_domain")
        if isinstance(clock, str) and clock and clock != scope.clock_domain:
            return "instance belongs to another clock domain"
        if scope.clock_domain.startswith("unresolved:") and scope.clock_domain != "unresolved:" + member.wire:
            return "instance belongs to another unresolved clock domain"
        return None

    def descendants(self, member):
        """Yield known structural descendants; this is not call completeness."""
        if member not in self._nodes:
            raise ValueError("unknown region member")
        stack = [member]
        while stack:
            current = stack.pop()
            yield current
            stack.extend(reversed(self._children.get(current, ())))

    def region(self, members, *, granularity=RegionGranularity.DATAFLOW_SUBGRAPH,
               parent=None, label=None, roots=None, direct_members=None):
        """Construct exactly the supplied membership; never silently add descendants."""
        members = _ordered(members)
        expected = OperationDefinitionID if self.view is RegionView.SEMANTIC else OperationInstanceID
        if not members or any(type(item) is not expected or item not in self._nodes for item in members):
            raise ValueError("region requires nonempty, correctly typed known membership")
        for member in members:
            error = self._scope_error(member)
            if error:
                raise ValueError(error)
        granularity = RegionGranularity(granularity)
        roots = _ordered(members if roots is None else roots)
        direct = _ordered(members if direct_members is None else direct_members)
        member_set = set(members)
        direct_set = set(direct)
        if not roots or not set(roots).issubset(member_set) or not direct_set.issubset(member_set):
            raise ValueError("region roots/direct members must belong to membership")
        if parent is not None:
            if parent not in self.constructions:
                raise ValueError("unknown region parent")
            outer = self.graph.regions[parent]
            if self._batching:
                outer_members = self._batch_members[parent]
            else:
                outer_members = set(outer.definitions if self.view is RegionView.SEMANTIC else outer.instances)
            if not member_set.issubset(outer_members):
                raise ValueError("child membership must be a subset of its parent")
        rid = OptimizationRegionID(_digest(self.view.value, self.scope, granularity.value,
                                           [item.wire for item in members], [item.wire for item in roots],
                                           parent.wire if parent else None))
        if rid in self.constructions:
            return rid
        definitions = members if self.view is RegionView.SEMANTIC else _ordered(
            self.bundle.evidence.instances[item].definition for item in members)
        ports, dependencies, links = {}, [], []
        gaps = [RegionGap(BoundaryFacet.CONSUMERS, "Known consumers are not a closed consumer/escape lifetime."),
                RegionGap(BoundaryFacet.DATA, "Data ports conservatively include known reads/writes; internal slot elimination and read-before-write closure are unproven."),
                RegionGap(BoundaryFacet.ALIASES, "Alias and foreign-write completeness is not established."),
                RegionGap(BoundaryFacet.CONTROL, "Structural membership does not prove all-path execution or dominance.")]
        if self.view is RegionView.SEMANTIC:
            gaps.append(RegionGap(BoundaryFacet.CONTROL,
                                  "Lexical descendants are structural members, not evidence of executed callees."))
        else:
            gaps.append(RegionGap(BoundaryFacet.CORRESPONDENCE,
                                  "Definition identity does not bind source slots to invocation-specific values."))
        def port(kind, *, value=None, slot=None, control=None, resource=None, effect=None, operation=None):
            payload = encode((value, slot, control, resource, effect, operation))
            pid = "region-port:" + _digest(rid.wire, kind.value, payload)
            ports[pid] = RegionPort(pid, kind, kind.value, value=value, slot=slot,
                                    control=control, resource=resource, effect=effect, operation=operation)
            return pid
        def endpoint_port(endpoint, direction):
            kind = RegionPortKind(direction.value)
            member = _member(endpoint)
            if member is not None:
                return port(RegionPortKind.ORDERING if direction is BoundaryDirection.ORDERING
                            else RegionPortKind.CONTROL, operation=member)
            if isinstance(endpoint, SemanticEndpoint):
                if endpoint.kind is SemanticNodeKind.VALUE_SLOT:
                    if kind not in {RegionPortKind.INPUT, RegionPortKind.OUTPUT, RegionPortKind.STATE, RegionPortKind.ESCAPE}:
                        kind = RegionPortKind.STATE
                    return port(kind, slot=endpoint.id)
                if endpoint.kind is SemanticNodeKind.CONTROL:
                    return port(RegionPortKind.CONTROL, control=endpoint.id)
                if endpoint.kind is SemanticNodeKind.RESOURCE:
                    return port(RegionPortKind.RESOURCE, resource=endpoint.id)
                if endpoint.kind is SemanticNodeKind.EFFECT:
                    return port(RegionPortKind.EFFECT, effect=EffectTarget(EffectTargetKind.OPAQUE, endpoint.id.wire))
                return None
            reference = endpoint.reference
            if endpoint.kind is EvidenceNodeKind.VALUE_OBSERVATION:
                observation = self.bundle.evidence.observations[reference]
                value = ValuePattern(versions=(observation.version,),
                                     materializations=(observation.materialization,) if observation.materialization else ())
            elif endpoint.kind is EvidenceNodeKind.VALUE_VERSION:
                value = ValuePattern(versions=(reference,))
            elif endpoint.kind is EvidenceNodeKind.MATERIALIZATION:
                materialization = self.bundle.values.materializations[reference]
                value = ValuePattern(versions=(materialization.value_version,), materializations=(reference,))
            else:
                value = None
            if value is not None:
                if kind not in {RegionPortKind.INPUT, RegionPortKind.OUTPUT, RegionPortKind.STATE, RegionPortKind.ESCAPE}:
                    kind = RegionPortKind.STATE
                return port(kind, value=value)
            if endpoint.kind is EvidenceNodeKind.RESOURCE:
                return port(RegionPortKind.RESOURCE, resource=reference)
            if endpoint.kind in {EvidenceNodeKind.OBJECT, EvidenceNodeKind.ALLOCATION, EvidenceNodeKind.STORAGE_REGION}:
                target_kind = EffectTargetKind.OBJECT if endpoint.kind is EvidenceNodeKind.OBJECT else EffectTargetKind.STORAGE
                return port(RegionPortKind.ESCAPE if kind is RegionPortKind.ESCAPE else RegionPortKind.STATE,
                            effect=EffectTarget(target_kind, endpoint.wire))
            if endpoint.kind is EvidenceNodeKind.CONTROL_EVENT:
                return port(RegionPortKind.ORDERING, effect=EffectTarget(EffectTargetKind.ORDERING, endpoint.wire))
            return None
        seen_edges = set()
        for member in members:
            for edge in self._edges.get(member, ()):
                if edge.edge_id in seen_edges:
                    continue
                seen_edges.add(edge.edge_id)
                source_in, target_in = _member(edge.source) in member_set, _member(edge.target) in member_set
                if source_in == target_in:
                    continue
                if edge.relation.value in {"has_source", "has_contract"}:
                    continue
                direction = _direction(edge.relation)
                other = edge.target if source_in else edge.source
                pid = endpoint_port(other, direction)
                dependencies.append(CrossingDependency(edge.edge_id, self.view, edge.relation.value,
                                                       edge.source, edge.target, direction, edge.evidence,
                                                       (pid,) if pid else ()))
        # Definition fields are authoritative even when a producer emitted no
        # redundant READS_SLOT / CONTROL / RESOURCE edges.
        for definition_id in definitions:
            definition = self.bundle.semantic.definitions[definition_id]
            if self.view is RegionView.SEMANTIC:
                for kind, slots in ((RegionPortKind.INPUT, definition.input_slots),
                                    (RegionPortKind.OUTPUT, definition.output_slots),
                                    (RegionPortKind.STATE, definition.state_slots)):
                    for slot in slots:
                        port(kind, slot=slot)
            if definition.control_region is not None:
                port(RegionPortKind.CONTROL, control=definition.control_region)
            for resource in definition.resource_requirements:
                port(RegionPortKind.RESOURCE, resource=resource)
            if definition.effect_summary is not None:
                summary = self.bundle.semantic.effects[definition.effect_summary]
                for dimension in EffectDimension:
                    field = getattr(summary, dimension.value)
                    for target in getattr(field, "members", ()):
                        kind = (RegionPortKind.ESCAPE if dimension is EffectDimension.ESCAPES else
                                RegionPortKind.ORDERING if dimension is EffectDimension.ORDERING else RegionPortKind.EFFECT)
                        port(kind, effect=target)
                        if dimension in {EffectDimension.READS, EffectDimension.WRITES, EffectDimension.ALIASES}:
                            port(RegionPortKind.STATE, effect=target)
                    if getattr(field, "value", None) == "PRESENT":
                        port(RegionPortKind.EFFECT, effect=EffectTarget(
                            EffectTargetKind.OPAQUE, summary.id.wire + ":" + dimension.value))
        for member in members:
            for observation in self._observations.get(member, ()):
                direction = (BoundaryDirection.INPUT if observation.role in {"input", "argument", "arg"} else
                             BoundaryDirection.OUTPUT if observation.role in {"output", "return", "result"} else BoundaryDirection.STATE)
                endpoint_port(EvidenceEndpoint(EvidenceNodeKind.VALUE_OBSERVATION, observation.observation_id), direction)
        occurrences = tuple(sorted({item.id: item for member in members
                                    for item in self._occurrences.get(member, ())}.values(), key=lambda item: item.id))
        for occurrence in occurrences:
            kind = (RegionPortKind.ESCAPE if occurrence.dimension is EffectDimension.ESCAPES else
                    RegionPortKind.ORDERING if occurrence.dimension is EffectDimension.ORDERING else RegionPortKind.EFFECT)
            pid = port(kind, effect=occurrence.target)
            links.append(RegionEffectLink(pid, occurrence.id, self.scope, occurrence.instance, occurrence.evidence))
            if occurrence.dimension in {EffectDimension.READS, EffectDimension.WRITES, EffectDimension.ALIASES, EffectDimension.RNG}:
                state_pid = port(RegionPortKind.STATE, effect=occurrence.target)
                links.append(RegionEffectLink(state_pid, occurrence.id, self.scope, occurrence.instance, occurrence.evidence))
        # Definition summaries aggregate separate invocations. They are never
        # promoted to per-instance effect coverage by this builder.
        gaps.append(RegionGap(BoundaryFacet.EFFECTS,
                              "Occurrence membership is known; per-region effect/branch/call closure is not certified."))
        evidence_claims = tuple(sorted({item.evidence for item in dependencies}, key=lambda item: json.dumps(encode(item), sort_keys=True)))
        coverage = tuple(BoundaryCoverage(facet,
            Completeness.PARTIAL if facet in {BoundaryFacet.DATA, BoundaryFacet.CONTROL, BoundaryFacet.RESOURCE}
            and (ports or dependencies) else Completeness.UNKNOWN,
            evidence_claims if facet is BoundaryFacet.DATA else ()) for facet in BoundaryFacet)
        for value in ports.values():
            self.graph.add_port(value)
        atoms = _ordered(atom for definition in definitions for atom in self.bundle.semantic.definitions[definition].source_atoms)
        region = OptimizationRegion(rid, granularity, label or "region " + roots[0].wire,
                                    definitions=definitions,
                                    instances=members if self.view is RegionView.EXECUTION else (),
                                    parent=parent, ports=tuple(sorted(ports)), source_atoms=atoms)
        self.graph.add_region(region)
        self.graph.add_alternative(PlanAlternative(PlanAlternativeID("original:" + rid.value), rid,
                                                   "Original execution", TransformKind.NO_OP, original=True))
        self.constructions[rid] = RegionConstruction(
            rid, self.view, self.scope, self.scopes[self.scope].mode, roots, direct,
            dependencies=tuple(sorted(dependencies, key=lambda item: item.id)), coverage=coverage,
            gaps=tuple(gaps), effect_occurrences=occurrences, effect_links=tuple(links))
        pending = _ordered(child for member in direct for child in self._children.get(member, ())
                           if child in member_set and child not in direct_set)
        self.constructions[rid] = replace(self.constructions[rid], unexpanded_children=pending)
        if self._batching:
            self._batch_members[rid] = member_set
        if parent is not None:
            if self._batching:
                self._batch_children[parent].append(rid)
            else:
                outer = self.constructions[parent]
                self.constructions[parent] = replace(outer, children=_ordered(outer.children + (rid,)),
                                                      unexpanded_children=tuple(item for item in outer.unexpanded_children if item not in roots))
        if not self._batching:
            self._attach_effect_closure((rid,))
        return rid

    def _finish_batch(self):
        """Finalize sibling lists once instead of copying them for every child."""
        for parent, additions in self._batch_children.items():
            outer = self.constructions[parent]
            expanded = {root for child in additions for root in self.constructions[child].roots}
            self.constructions[parent] = replace(
                outer, children=_ordered(outer.children + tuple(additions)),
                unexpanded_children=tuple(item for item in outer.unexpanded_children if item not in expanded))
        self._batch_children.clear()
        self._batch_members.clear()
        self._batching = False

    def _attach_effect_closure(self, identities):
        if self.effects is None or self.view is not RegionView.SEMANTIC:
            return
        identities = tuple(identities)
        summaries = self.effects.boundaries((self.graph.regions[key].definitions, self.scope) for key in identities)
        for key, summary in zip(identities, summaries):
            record = self.constructions[key]
            # Explicit effect children may extend the semantic member set.
            # Such a closure cannot certify the smaller region's boundary.
            if set(summary.members) != set(self.graph.regions[key].definitions):
                continue
            changes = {"effect_coverage": summary.coverage}
            if summary.ready_for_region_construction and summary.mode is record.mode:
                changes["gaps"] = tuple(item for item in record.gaps if item.facet is not BoundaryFacet.EFFECTS)
                changes["coverage"] = tuple(replace(item, completeness=Completeness.COMPLETE,
                    evidence=tuple(claim for coverage in summary.coverage for claim in coverage.evidence))
                    if item.facet is BoundaryFacet.EFFECTS else item for item in record.coverage)
            self.constructions[key] = replace(record, **changes)

    def validate(self):
        errors = list(self.graph.validate()["errors"])
        if errors:
            return {"valid": False, "errors": errors}
        errors.extend(record_errors(self.scope, str, "inventory.scope"))
        errors.extend(record_errors(self.scopes, dict[str, ObservationScope], "inventory.scopes"))
        if errors:
            return {"valid": False, "errors": errors}
        if self.scope not in self.scopes:
            errors.append("selected inventory scope is missing")
        if any(key != scope.id for key, scope in self.scopes.items()):
            errors.append("inventory scope key/identity mismatch")
        if errors:
            return {"valid": False, "errors": errors}
        if self.graph.context != optimization_context(self.bundle.semantic, self.bundle.evidence, self.bundle.values):
            errors.append("inventory context no longer matches its source graphs")
        if set(self.graph.regions) != set(self.constructions):
            errors.append("construction/optimization region identity mismatch")
        typed_errors = {key: record_errors(item, RegionConstruction, "construction")
                        for key, item in self.constructions.items()}
        # These indexes belong to this validation call only. The source graphs
        # and inventories are mutable and are rechecked on the next call.
        member_index = {key: set(region.definitions if self.view is RegionView.SEMANTIC else region.instances)
                        for key, region in self.graph.regions.items()}
        port_index = {key: set(region.ports) for key, region in self.graph.regions.items()}
        child_index = {key: set(item.children) for key, item in self.constructions.items() if not typed_errors[key]}
        certified = {}
        candidates = [key for key, item in self.constructions.items()
                      if not typed_errors[key] and item.effects_closed]
        if candidates and self.effects is not None and self.view is RegionView.SEMANTIC:
            summaries = self.effects.boundaries((self.graph.regions[key].definitions, self.scope)
                                               for key in candidates if key in self.graph.regions)
            certified = dict(zip((key for key in candidates if key in self.graph.regions), summaries))
        for key, construction in self.constructions.items():
            typed = typed_errors[key]
            errors.extend(typed)
            if typed:
                continue
            region = self.graph.regions.get(key)
            if key != construction.region or region is None:
                errors.append("construction key/region identity mismatch")
                continue
            scope = self.scopes.get(construction.scope)
            if scope is None or construction.mode != scope.mode:
                errors.append("construction scope/mode mismatch")
            if construction.view is not self.view:
                errors.append("mixed source/execution region views")
            if construction.view is RegionView.EXECUTION and construction.mode is not ScopeMode.DYNAMIC_PATH:
                errors.append("execution region cannot prove ALL_PATHS")
            members = member_index[key]
            region_ports = port_index[key]
            if not construction.roots or not set(construction.roots).issubset(members) or not set(construction.direct_members).issubset(members):
                errors.append("construction roots/direct members outside region")
            if not set(construction.unexpanded_children).issubset(members) or set(construction.unexpanded_children) & set(construction.direct_members):
                errors.append("unexpanded child identities outside region or overlapping direct members")
            for member in members:
                if self._scope_error(member):
                    errors.append("construction instance outside selected observation scope")
            for child in construction.children:
                nested = self.graph.regions.get(child)
                if nested is None or nested.parent != key:
                    errors.append("construction child/parent mismatch")
                elif not member_index[child].issubset(members):
                    errors.append("construction child members outside parent")
            if region.parent is not None and key not in child_index.get(region.parent, set()):
                errors.append("construction parent missing child")
            graph = self.bundle.semantic if construction.view is RegionView.SEMANTIC else self.bundle.evidence
            for dependency in construction.dependencies:
                edge = graph.edges.get(dependency.id)
                if (dependency.graph is not construction.view or edge is None or
                    edge.relation.value != dependency.relation or edge.source != dependency.source or
                    edge.target != dependency.target or edge.evidence != dependency.evidence):
                    errors.append("dependency lacks matching original edge evidence")
                if (_member(dependency.source) in members) == (_member(dependency.target) in members):
                    errors.append("dependency does not cross membership boundary")
                if not set(dependency.port_ids).issubset(region_ports):
                    errors.append("dependency references unknown region port")
            occurrences = {item.id: item for item in construction.effect_occurrences}
            if len(occurrences) != len(construction.effect_occurrences):
                errors.append("duplicate effect occurrence")
            for occurrence in occurrences.values():
                owner = occurrence.definition if construction.view is RegionView.SEMANTIC else occurrence.instance
                if owner not in members or occurrence.scope != construction.scope:
                    errors.append("effect occurrence outside region member/scope")
                if self.effects is None or self.effects.occurrences.get(occurrence.id) != occurrence:
                    errors.append("effect occurrence lacks matching ledger evidence")
            for link in construction.effect_links:
                occurrence, port = occurrences.get(link.occurrence_id), self.graph.ports.get(link.port_id)
                if (occurrence is None or port is None or link.port_id not in region_ports or
                    port.effect != occurrence.target or link.scope != occurrence.scope or
                    link.instance != occurrence.instance or link.evidence != occurrence.evidence):
                    errors.append("invalid scoped port/effect occurrence link")
            if {item.facet for item in construction.coverage} != set(BoundaryFacet) or len(construction.coverage) != len(BoundaryFacet):
                errors.append("region coverage must describe each boundary facet exactly once")
            summary = certified.get(key)
            backed = (summary is not None and summary.ready_for_region_construction and
                      set(summary.members) == members and summary.scope == construction.scope and
                      summary.mode is construction.mode and summary.coverage == construction.effect_coverage)
            if construction.effects_closed and not backed:
                errors.append("region effect closure lacks exact scoped semantic coverage")
            if any(item.completeness is Completeness.COMPLETE and not
                   (item.facet is BoundaryFacet.EFFECTS and construction.effects_closed and backed)
                   for item in construction.coverage):
                errors.append("region construction has unsupported completeness certification")
        if self.graph.plans or any(not item.original or item.transform is not TransformKind.NO_OP for item in self.graph.alternatives.values()):
            errors.append("region builder inventory must not select transformations")
        if not errors:
            errors.extend(self._projection_errors())
        return {"valid": not errors, "errors": errors}

    def _projection_errors(self):
        """Rebuild the known interface once, including omissions and input edits.

        The input graphs remain mutable. A fresh transient index is required;
        trusting only the records which survived deserialization is insufficient.
        Reconstruction never recursively validates another inventory.
        """
        try:
            expected = RegionInventory(self.bundle, view=self.view, effects=self.effects, scope=self.scope)
            if expected.scopes != self.scopes:
                return ["inventory scope differs from its source/evidence snapshot"]
            expected._batching = True
            children = defaultdict(list)
            for key, region in self.graph.regions.items():
                children[region.parent].append(key)
            pending = sorted(children[None], key=lambda item: item.wire, reverse=True)
            while pending:
                key = pending.pop()
                region, construction = self.graph.regions[key], self.constructions[key]
                members = region.definitions if self.view is RegionView.SEMANTIC else region.instances
                rebuilt = expected.region(members, granularity=region.granularity, parent=region.parent,
                    label=region.label, roots=construction.roots, direct_members=construction.direct_members)
                if rebuilt != key:
                    return ["region identity does not match scoped membership/roots"]
                pending.extend(sorted(children[key], key=lambda item: item.wire, reverse=True))
            expected._finish_batch()
            expected._attach_effect_closure(expected.constructions)
            errors = []
            if expected.constructions != self.constructions:
                errors.append("known boundary projection differs: omitted/changed dependency, occurrence, link, coverage or expansion")
            if expected.graph.ports != self.graph.ports:
                errors.append("known boundary ports omitted, changed or fabricated")
            if expected.graph.regions != self.graph.regions:
                errors.append("region membership/interface differs from source projection")
            if expected.graph.alternatives != self.graph.alternatives:
                errors.append("original alternatives differ from region construction")
            return errors
        except (ValueError, TypeError, KeyError) as error:
            return ["cannot reproduce known boundary projection: " + str(error)]

    def assert_valid(self):
        report = self.validate()
        if not report["valid"]:
            raise ValueError("invalid region inventory: " + "; ".join(report["errors"]))
        return report

    def to_dict(self):
        self.assert_valid()
        return {"schema": self.SCHEMA, "schema_version": self.SCHEMA_VERSION,
                "view": self.view.value, "scope": self.scope,
                "scopes": [encode(item) for _, item in sorted(self.scopes.items())],
                "graph": self.graph.to_dict(),
                "constructions": [encode(self.constructions[key]) for key in sorted(self.constructions, key=lambda item: item.wire)]}

    @classmethod
    def from_dict(cls, document, *, bundle, effects=None):
        required = {"schema", "schema_version", "view", "scope", "scopes", "graph", "constructions"}
        if type(document) is not dict or set(document) != required or document["schema"] != cls.SCHEMA or type(document["schema_version"]) is not int or document["schema_version"] != cls.SCHEMA_VERSION:
            raise ValueError("invalid region inventory document/schema")
        scope = decode(str, document["scope"])
        result = cls(bundle, view=decode(RegionView, document["view"]), effects=effects, scope=scope)
        scopes = decode(tuple[ObservationScope, ...], document["scopes"])
        if len({item.id for item in scopes}) != len(scopes) or {item.id for item in scopes} != {scope}:
            raise ValueError("invalid/duplicate inventory scopes")
        if effects is not None and scopes != (effects.scopes[scope],):
            raise ValueError("scope does not match supplied effect ledger")
        result.scopes = {item.id: item for item in scopes}
        from scar.ir.v2.codec import optimization_from_dict
        result.graph = optimization_from_dict(document["graph"], optimization_context(bundle.semantic, bundle.evidence, bundle.values))
        if type(document["constructions"]) is not list:
            raise ValueError("constructions must be an array")
        for payload in document["constructions"]:
            if type(payload) is not dict or type(payload.get("dependencies")) is not list:
                raise ValueError("invalid construction record")
            rest = dict(payload)
            dependencies = []
            for item in rest["dependencies"]:
                dependencies.append(_decode_dependency(item))
            rest["dependencies"] = []
            construction = replace(decode(RegionConstruction, rest), dependencies=tuple(dependencies))
            if construction.region in result.constructions:
                raise ValueError("duplicate region construction")
            result.constructions[construction.region] = construction
        result.assert_valid()
        return result

    @classmethod
    def from_json(cls, payload, *, bundle, effects=None):
        return cls.from_dict(loads(payload), bundle=bundle, effects=effects)


def _decode_endpoint(payload, view):
    # Generic record_codec cannot infer a concrete Identifier from an abstract
    # Identifier annotation. Resolve the endpoint's typed namespace explicitly.
    if view is RegionView.SEMANTIC:
        if type(payload) is not dict or set(payload) != {"kind", "id"}:
            raise ValueError("invalid semantic dependency endpoint")
        kind = decode(SemanticNodeKind, payload["kind"])
        from scar.ir.v2.semantic import _ENDPOINT_TYPES
        return SemanticEndpoint(kind, decode(_ENDPOINT_TYPES[kind], payload["id"]))
    if type(payload) is not dict or set(payload) != {"kind", "reference"}:
        raise ValueError("invalid execution dependency endpoint")
    kind = decode(EvidenceNodeKind, payload["kind"])
    from scar.ir.v2.evidence import _TYPED_EVIDENCE_ENDPOINTS
    return EvidenceEndpoint(kind, decode(_TYPED_EVIDENCE_ENDPOINTS.get(kind, str), payload["reference"]))


def _decode_dependency(payload):
    if type(payload) is not dict or set(payload) != {"id", "graph", "relation", "source", "target", "direction", "evidence", "port_ids"}:
        raise ValueError("invalid crossing dependency fields")
    view = decode(RegionView, payload["graph"])
    return CrossingDependency(decode(str, payload["id"]), view, decode(str, payload["relation"]),
                              _decode_endpoint(payload["source"], view), _decode_endpoint(payload["target"], view),
                              decode(BoundaryDirection, payload["direction"]), decode(EvidenceClaim, payload["evidence"]),
                              decode(tuple[str, ...], payload["port_ids"]))


def _granularity(node, view):
    kind = node.kind.value
    if view is RegionView.EXECUTION and kind == "module":
        return RegionGranularity.FUNCTION
    # A repeated runtime action is not a loop-body witness. Its enclosing
    # control region must be supplied explicitly when constructing that view.
    if view is RegionView.EXECUTION and kind == "loop":
        return RegionGranularity.INSTRUCTION
    return {"function": RegionGranularity.FUNCTION, "method": RegionGranularity.FUNCTION,
            "module": RegionGranularity.PIPELINE_STAGE, "stage": RegionGranularity.PIPELINE_STAGE,
            "loop": RegionGranularity.LOOP_BODY, "operator": RegionGranularity.OPERATOR,
            "kernel": RegionGranularity.OPERATOR}.get(kind, RegionGranularity.INSTRUCTION)


def build_regions(bundle: IRBundle, *, view="semantic", roots=None, max_depth=None,
                  effects: EffectClosureEngine | None = None, scope=None):
    """Build parent-before-child regions; ``max_depth=0`` retains root membership.

    A selected root always contains its known descendants. max_depth limits
    materialized child regions, not the root's membership or coverage scope.
    """
    if max_depth is not None and (type(max_depth) is not int or max_depth < 0):
        raise ValueError("max_depth must be a non-negative integer or None")
    inventory = RegionInventory(bundle, view=view, effects=effects, scope=scope)
    selected = _ordered(inventory._children.get(None, ()) if roots is None else roots)
    if not selected or any(item not in inventory._nodes for item in selected):
        raise ValueError("selected roots must be nonempty known operation identities")
    # Redundant nested roots are a caller error: silently duplicating hierarchy
    # would give one operation two apparent execution contexts.
    selected_set = set(selected)
    # This set belongs only to this preflight. Once an ancestor path has been
    # checked against the fixed selection, sibling roots can reuse that check.
    checked_ancestors = set()
    for root in selected:
        node = inventory._nodes[root]
        parent = node.parent_id if inventory.view is RegionView.SEMANTIC else node.parent
        while parent is not None:
            if parent in selected_set:
                raise ValueError("selected roots must not contain ancestor/descendant duplicates")
            if parent in checked_ancestors:
                break
            checked_ancestors.add(parent)
            node = inventory._nodes[parent]
            parent = node.parent_id if inventory.view is RegionView.SEMANTIC else node.parent
    stack = [(root, None, 0) for root in reversed(selected)]
    inventory._batching = True
    while stack:
        root, parent, depth = stack.pop()
        rid = inventory.region(tuple(inventory.descendants(root)),
                               granularity=_granularity(inventory._nodes[root] if inventory.view is RegionView.SEMANTIC else
                                   inventory.bundle.semantic.definitions[inventory._nodes[root].definition], inventory.view),
                               parent=parent, roots=(root,), direct_members=(root,),
                               label=inventory.bundle.semantic.definitions[root].label if inventory.view is RegionView.SEMANTIC
                               else "invocation " + root.wire)
        if max_depth is None or depth < max_depth:
            stack.extend((child, rid, depth + 1) for child in reversed(inventory._children.get(root, ())))
    inventory._finish_batch()
    inventory._attach_effect_closure(inventory.constructions)
    inventory.assert_valid()
    return inventory


__all__ = ["RegionView", "BoundaryFacet", "BoundaryDirection", "BoundaryCoverage", "RegionGap",
           "CrossingDependency", "RegionEffectLink", "RegionConstruction", "RegionInventory", "build_regions"]
