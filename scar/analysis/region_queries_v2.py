"""Scoped value ancestry and proposed motion diagnostics, never MOVE approval.

Logical origin, physical availability and execution containment are different
facts. In particular, an output observation is not a logical-value producer.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json

from scar.ir.record_codec import decode, encode, loads
from scar.ir.provenance import EventPoint, GuardState, ProvenanceRegistry, ValueHandle
from scar.ir.v2 import (
    EvidenceClaim, EvidenceKind, EvidenceEndpoint, EvidenceNodeKind,
    EvidenceRelation, IRBundle, MaterializationID, OperationInstanceID,
    ObjectID, StorageAllocationID, StorageRegionID, ResourceID, MeasurementID,
    OptimizationRegionID,
    ProofClaim, ProofStatus, ProvenanceID, ProvenanceRelation, EquivalenceClaim,
    ValueSlotID, ValueVersionID,
)


class OriginStatus(str, Enum):
    LOCATED = "LOCATED"
    AMBIGUOUS = "AMBIGUOUS"
    UNRESOLVED = "UNRESOLVED"


class PlacementRelation(str, Enum):
    AT_TARGET = "AT_TARGET"
    ABOVE_TARGET = "ABOVE_TARGET"
    BELOW_TARGET = "BELOW_TARGET"
    UNRELATED = "UNRELATED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class OriginPlacement:
    """Explicit scoped logical producer witness; never an observation hint."""
    id: str
    version: ValueVersionID
    producer: OperationInstanceID
    scope: str
    evidence: EvidenceClaim

    def __post_init__(self):
        if not self.id or not self.scope or self.evidence.scope != self.scope:
            raise ValueError("origin placement requires an ID and matching evidence scope")
        if self.evidence.kind not in (EvidenceKind.OBSERVED, EvidenceKind.DECLARED) or not self.evidence.references:
            raise ValueError("origin placement requires an auditable observed or declared witness")


@dataclass(frozen=True)
class OriginSite:
    version: ValueVersionID
    producer: OperationInstanceID
    mechanism: str
    evidence: EvidenceClaim


@dataclass(frozen=True)
class ProvenanceStep:
    provenance: ProvenanceID
    relation: ProvenanceRelation
    inputs: tuple[ValueVersionID, ...]
    outputs: tuple[ValueVersionID, ...]
    producer: OperationInstanceID | None
    equivalence: EquivalenceClaim
    evidence: str


class _Record:
    SCHEMA = ""

    def to_dict(self):
        return {"schema": self.SCHEMA, "schema_version": 1, "record": encode(self)}

    def to_json(self):
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False, allow_nan=False)

    @classmethod
    def from_dict(cls, document):
        if (type(document) is not dict or set(document) != {"schema", "schema_version", "record"}
                or document["schema"] != cls.SCHEMA or type(document["schema_version"]) is not int
                or document["schema_version"] != 1):
            raise ValueError("unsupported query record schema")
        return decode(cls, document["record"])

    @classmethod
    def from_json(cls, payload):
        return cls.from_dict(loads(payload))


@dataclass(frozen=True)
class OriginQuery(_Record):
    SCHEMA = "scar.region.origin-query.v2"
    slot: ValueSlotID
    consumer: OperationInstanceID
    scope: str
    at: EventPoint
    handle: ValueHandle | None
    status: OriginStatus
    value_sites: tuple[OriginSite, ...]
    ancestor_sites: tuple[OriginSite, ...]
    steps: tuple[ProvenanceStep, ...]
    materializations: tuple[MaterializationID, ...]
    gaps: tuple[str, ...]

    def __post_init__(self):
        if not self.scope or self.at.scope != self.scope:
            raise ValueError("origin query event scope mismatch")
        if self.status is OriginStatus.LOCATED and (self.handle is None or not self.value_sites):
            raise ValueError("located origin requires a bound value and producer")


@dataclass(frozen=True)
class RegionOriginQuery(_Record):
    SCHEMA = "scar.region.scoped-origin-query.v2"
    region: OptimizationRegionID
    region_scope: str
    origin: OriginQuery

    def __post_init__(self):
        if not self.region_scope:
            raise ValueError("region origin requires its construction scope")


@dataclass(frozen=True)
class QueryEndpoint(EvidenceEndpoint):
    """EEG endpoint with a closed ID union for the strict record codec."""
    reference: (OperationInstanceID | ValueVersionID | MaterializationID | ObjectID |
                StorageAllocationID | StorageRegionID | ResourceID | MeasurementID | str)


@dataclass(frozen=True)
class DependencyCrossing:
    edge_id: str
    relation: EvidenceRelation
    source: QueryEndpoint
    target: QueryEndpoint
    inside_endpoint: str
    evidence: EvidenceClaim

    def __post_init__(self):
        if not self.edge_id or self.inside_endpoint not in ("source", "target"):
            raise ValueError("dependency crossing requires an edge and its inside endpoint")


@dataclass(frozen=True)
class MotionBoundaryDelta:
    container: OperationInstanceID
    removed: tuple[DependencyCrossing, ...]
    added: tuple[DependencyCrossing, ...]


@dataclass(frozen=True)
class InputAvailability:
    slot: ValueSlotID
    version: ValueVersionID | None
    materialization: MaterializationID | None
    producers: tuple[OperationInstanceID, ...]
    placement_relation: PlacementRelation
    available_at_target: ProofStatus
    reason: str


@dataclass(frozen=True)
class MotionQuery(_Record):
    SCHEMA = "scar.region.motion-query.v2"
    members: tuple[OperationInstanceID, ...]
    target: OperationInstanceID
    scope: str
    control_path: tuple[OperationInstanceID, ...]
    boundary_deltas: tuple[MotionBoundaryDelta, ...]
    inputs: tuple[InputAvailability, ...]
    origins: tuple[OriginQuery, ...]
    lifetime_extensions: tuple[MaterializationID, ...]
    obligations: tuple[ProofClaim, ...]
    gaps: tuple[str, ...]
    mode: str = "dynamic_path"
    decision: str = "REPORT_ONLY"

    def __post_init__(self):
        if not self.scope or not self.members or len(set(self.members)) != len(self.members):
            raise ValueError("motion requires a scope and unique members")
        if self.target in self.members:
            raise ValueError("motion target cannot belong to moved members")
        if self.mode != "dynamic_path" or self.decision != "REPORT_ONLY":
            raise ValueError("motion diagnostics cannot authorize MOVE or claim all-path proof")
        if any(item.available_at_target is ProofStatus.PROVEN for item in self.inputs):
            raise ValueError("scope placement does not prove availability at an insertion point")


class RegionQueries:
    """Queries validate their inputs afresh; mutable graphs have no validation cache.

    Registry bindings use the consumer's typed invocation wire as binding scope.
    Registry event ordinals are never compared to CPU/GPU timestamp clocks.
    Deserialized records require ``validate_result`` before reuse with this graph.
    """

    def __init__(self, bundle: IRBundle, registry: ProvenanceRegistry | None = None,
                 placements: tuple[OriginPlacement, ...] = ()):
        self.bundle, self.registry, self.placements = bundle, registry, tuple(placements)
        self._validate()

    def _validate(self):
        self.bundle.assert_valid()
        if self.registry is not None:
            errors = self.registry.validate_references(self.bundle.semantic, self.bundle.evidence)
            if errors:
                raise ValueError("; ".join(errors))
            # Equal ID strings in separate captures must not merge different records.
            for name in ("logical_values", "versions", "provenance", "materializations", "regions", "allocations"):
                captured, supplied = getattr(self.registry.graph, name), getattr(self.bundle.values, name)
                if any(identity not in supplied or record != supplied[identity]
                       for identity, record in captured.items()):
                    raise ValueError("registry and bundle value graphs disagree")
        ids = set()
        for placement in self.placements:
            decode(OriginPlacement, encode(placement))
            if placement.id in ids:
                raise ValueError("duplicate origin placement")
            ids.add(placement.id)
            if placement.version not in self.bundle.values.versions:
                raise ValueError("origin placement references unknown version")
            self._instance(placement.producer)
            if self.registry is not None and placement.scope != self.registry.scope:
                raise ValueError("origin placement registry scope mismatch")
            control = self.bundle.evidence.instances[placement.producer].control_scope
            if control is not None and control != placement.scope:
                raise ValueError("origin placement execution scope mismatch")
            value_scope = self.bundle.values.versions[placement.version].control_scope
            if value_scope is not None and value_scope != placement.scope:
                raise ValueError("origin placement value capture scope mismatch")
        # These indexes are rebuilt after validation for each public query,
        # never cached across mutations of the source graphs.
        self._provenance_outputs = {}
        for record in self.bundle.values.provenance.values():
            for output in record.outputs:
                self._provenance_outputs.setdefault(output, []).append(record)
        self._placements = {}
        for placement in self.placements:
            self._placements.setdefault(placement.version, []).append(placement)
        self._producer_edges = {}
        self._control_owners = {}
        self._ancestor_cache = {}
        self._producer_claims = {}
        if self.registry is not None:
            for materialization in self.registry.graph.materializations.values():
                if materialization.producer is not None:
                    # Later escape/write evidence must never retroactively
                    # certify an unwitnessed producing operation.
                    claims = self.registry.validity[materialization.id].evidence[:1]
                    self._producer_claims.setdefault((materialization.value_version, materialization.producer), []).extend(claims)
        for edge in self.bundle.evidence.edges.values():
            if edge.relation is EvidenceRelation.PRODUCES and edge.target.kind is EvidenceNodeKind.VALUE_VERSION:
                self._producer_edges.setdefault(edge.target.reference, []).append(edge)
            elif edge.relation is EvidenceRelation.OBSERVED_CONTROL:
                self._control_owners.setdefault(edge.target.reference, set()).add(edge.source.reference)

    def _instance(self, identity):
        if not isinstance(identity, OperationInstanceID) or identity not in self.bundle.evidence.instances:
            raise ValueError("unknown typed operation instance")
        return self.bundle.evidence.instances[identity]

    def _sites(self, version, scope):
        sites = []
        for placement in self._placements.get(version, ()):
            if placement.scope == scope:
                sites.append(OriginSite(version, placement.producer, "explicit_origin_placement", placement.evidence))
        primary = self.bundle.values.versions[version].provenance_id
        record = self.bundle.values.provenance.get(primary)
        if record is not None and record.producer is not None:
            producer = self._instance(record.producer)
            if producer.control_scope in (None, scope):
                claims = [item for item in self._producer_claims.get((version, record.producer), ())
                          if item.kind in (EvidenceKind.OBSERVED, EvidenceKind.DECLARED)
                          and item.references and item.scope == scope]
                witnessed = (record.evidence in (EvidenceKind.OBSERVED.value, EvidenceKind.DECLARED.value)
                             and self.bundle.values.versions[version].control_scope == scope and bool(claims))
                evidence = (claims[0] if witnessed else EvidenceClaim(EvidenceKind.UNKNOWN,
                    (record.id.wire,), scope=scope, assumptions=("producer metadata lacks a scoped source witness",)))
                sites.append(OriginSite(version, record.producer, "logical_provenance_producer", evidence))
        for edge in self._producer_edges.get(version, ()):
            producer = self._instance(edge.source.reference)
            if (producer.control_scope in (None, scope)
                    and edge.evidence.scope == scope and edge.evidence.references
                    and edge.evidence.kind in (EvidenceKind.OBSERVED, EvidenceKind.DECLARED)):
                sites.append(OriginSite(version, edge.source.reference, "explicit_logical_produces_edge", edge.evidence))
        return tuple(sorted(sites, key=lambda item: (item.producer.wire, item.mechanism, repr(item.evidence))))

    def origin(self, slot: ValueSlotID, consumer: OperationInstanceID, at: EventPoint) -> OriginQuery:
        self._validate()
        return self._origin(slot, consumer, at)

    def _origin(self, slot, consumer, at):
        instance = self._instance(consumer)
        if slot not in self.bundle.semantic.slots:
            raise ValueError("unknown typed semantic slot")
        if self.registry is None:
            raise ValueError("slot origin query requires explicit registry bindings")
        if at.scope != self.registry.scope or at.ordinal > self.registry.current_event.ordinal:
            raise ValueError("query event is outside registry capture scope")
        if instance.control_scope not in (None, self.registry.scope):
            raise ValueError("consumer execution scope does not match registry")
        bindings = [item for item in self.registry.bindings
                    if item.slot == slot and item.scope == consumer.wire
                    and item.start_event.ordinal <= at.ordinal
                    and (item.end_event is None or at.ordinal < item.end_event.ordinal)]
        if not bindings:
            return OriginQuery(slot, consumer, at.scope, at, None, OriginStatus.UNRESOLVED,
                               (), (), (), (), ("no live explicit binding for this slot/invocation/event",))
        if len(bindings) != 1:
            raise ValueError("ambiguous overlapping registry binding intervals")
        handle = bindings[0].handle
        value_scope = self.bundle.values.versions[handle.version].control_scope
        if value_scope is not None and value_scope != at.scope:
            raise ValueError("bound value belongs to another capture scope")
        binding_evidence = bindings[0].evidence
        if binding_evidence.scope not in (at.scope, consumer.wire):
            raise ValueError("binding evidence scope does not match invocation or registry")
        validity = self.registry.validity[handle.materialization]
        gaps = []
        binding_witness = (binding_evidence.kind in (EvidenceKind.OBSERVED, EvidenceKind.DECLARED)
                           and bool(binding_evidence.references))
        if not binding_witness:
            gaps.append("binding lacks an auditable observed or declared witness")
        if validity.start_event.ordinal > at.ordinal or (validity.end_event and validity.end_event.ordinal <= at.ordinal):
            gaps.append("bound materialization is outside its validity interval")
        elif at.ordinal != self.registry.current_event.ordinal:
            gaps.append("historical mutation coverage and readiness require an at-time witness")
        elif self.registry.guard(handle).state is not GuardState.VALID:
            gaps.append("bound materialization freshness or readiness requires verification")
        visited, steps, pending = set(), {}, [handle.version]
        while pending:
            version = pending.pop()
            if version in visited:
                continue
            visited.add(version)
            for record in self._provenance_outputs.get(version, ()):
                steps[record.id] = ProvenanceStep(record.id, record.relation, record.inputs,
                    record.outputs, record.producer, record.equivalence, record.evidence)
                pending.extend(parent for parent in record.inputs if parent != version)
            pending.extend(self.bundle.values.versions[version].parent_versions)
        sites = self._sites(handle.version, at.scope)
        ancestors = tuple(site for version in sorted(visited - {handle.version}, key=lambda item: item.wire)
                          for site in self._sites(version, at.scope))
        unique = {site.producer for site in sites if self._witnessed(site)}
        status = (OriginStatus.LOCATED if len(unique) == 1 else
                  OriginStatus.AMBIGUOUS if unique else OriginStatus.UNRESOLVED)
        if not binding_witness:
            status = OriginStatus.UNRESOLVED
        if not unique:
            gaps.append("logical producer is external or unwitnessed; observation order is not origin")
        elif len(unique) > 1:
            gaps.append("multiple logical producer witnesses; preserve ambiguity")
        if any(not self._witnessed(site) for site in sites):
            gaps.append("untrusted producer metadata is retained as lineage, not a witnessed origin")
        if any(step.relation in (ProvenanceRelation.COPY, ProvenanceRelation.TRANSFORM,
                                ProvenanceRelation.MUTATE, ProvenanceRelation.VIEW) and
               step.inputs != step.outputs for step in steps.values()):
            gaps.append("ancestor lineage does not prove target-version equality or availability")
        return OriginQuery(slot, consumer, at.scope, at, handle, status, sites, ancestors,
            tuple(steps[key] for key in sorted(steps, key=lambda item: item.wire)),
            tuple(sorted((mid for mid, materialization in self.bundle.values.materializations.items()
                          if materialization.value_version == handle.version), key=lambda item: item.wire)),
            tuple(sorted(set(gaps))))

    def _ancestors(self, identity):
        if identity in self._ancestor_cache:
            return self._ancestor_cache[identity]
        result = []
        parent = self._instance(identity).parent
        while parent is not None:
            result.append(parent)
            parent = self._instance(parent).parent
        self._ancestor_cache[identity] = tuple(result)
        return self._ancestor_cache[identity]

    @staticmethod
    def _witnessed(site):
        return site.evidence.kind in (EvidenceKind.OBSERVED, EvidenceKind.DECLARED) and bool(site.evidence.references)

    def _owners(self, endpoint, scope):
        if endpoint.kind is EvidenceNodeKind.OPERATION_INSTANCE:
            return {endpoint.reference}
        if endpoint.kind is EvidenceNodeKind.VALUE_OBSERVATION:
            operation = self.bundle.evidence.observations[endpoint.reference].operation
            return {operation} if operation else set()
        if endpoint.kind is EvidenceNodeKind.VALUE_VERSION:
            return {site.producer for site in self._sites(endpoint.reference, scope) if self._witnessed(site)}
        if endpoint.kind is EvidenceNodeKind.MATERIALIZATION:
            producer = self.bundle.values.materializations[endpoint.reference].producer
            return {producer} if producer else set()
        if endpoint.kind is EvidenceNodeKind.CONTROL_EVENT:
            return self._control_owners.get(endpoint.reference, set())
        return set()

    def _cut(self, members, scope):
        cut, gaps = {}, set()
        for edge in sorted(self.bundle.evidence.edges.values(), key=lambda item: item.edge_id):
            owners = [self._owners(endpoint, scope) for endpoint in (edge.source, edge.target)]
            ambiguous = any(bool(owner & members) and bool(owner - members) for owner in owners)
            if ambiguous:
                gaps.add("ambiguous endpoint ownership prevents a complete dependency cut: " + edge.edge_id)
            inside = [bool(owner & members) and not bool(owner - members) for owner in owners]
            if inside[0] != inside[1]:
                cut[edge.edge_id] = DependencyCrossing(edge.edge_id, edge.relation,
                    QueryEndpoint(edge.source.kind, edge.source.reference),
                    QueryEndpoint(edge.target.kind, edge.target.reference),
                    "source" if inside[0] else "target", edge.evidence)
        return cut, gaps

    def motion(self, members: tuple[OperationInstanceID, ...], target: OperationInstanceID,
               *, scope: str, origins: tuple[OriginQuery, ...] = ()) -> MotionQuery:
        self._validate()
        return self._motion(members, target, scope=scope, origins=origins)

    def _motion(self, members, target, *, scope, origins):
        target_instance = self._instance(target)
        if not scope or not members or len(set(members)) != len(members) or target in members:
            raise ValueError("motion requires unique members, an outside target, and scope")
        moving = set(members)
        for member in moving:
            instance = self._instance(member)
            if (instance.process_id, instance.thread_id) != (target_instance.process_id, target_instance.thread_id):
                raise ValueError("motion cannot compare different process/thread scopes")
            if instance.control_scope not in (None, scope) or target_instance.control_scope not in (None, scope):
                raise ValueError("motion execution scope mismatch")
            if target not in self._ancestors(member):
                raise ValueError("motion target must be a witnessed dynamic ancestor of every member")
        if self.registry is not None and self.registry.scope != scope:
            raise ValueError("motion registry scope mismatch")
        crossed = set()
        for member in moving:
            for ancestor in self._ancestors(member):
                if ancestor == target:
                    break
                if ancestor not in moving:
                    crossed.add(ancestor)
        ordered = tuple(sorted(crossed, key=lambda item: (-len(self._ancestors(item)), item.wire)))
        gaps = {"known EEG dependency cuts are partial; missing edges are not absent dependencies"}
        contexts = [self._instance(item) for item in moving | crossed | {target}]
        if any((item.process_id, item.thread_id) != (target_instance.process_id, target_instance.thread_id)
               for item in contexts):
            raise ValueError("crossed path spans different process/thread scopes")
        clocks = {item.metadata.get("clock_domain") for item in contexts
                  if isinstance(item.metadata.get("clock_domain"), str) and item.metadata["clock_domain"]}
        if len(clocks) > 1:
            raise ValueError("motion path spans different known clock domains")
        if any(not item.metadata.get("clock_domain") for item in contexts):
            gaps.add("runtime clock is unknown along the motion path; clocks cannot be compared")
        deltas = []
        for container in ordered:
            before = {item for item in self.bundle.evidence.instances
                      if item == container or container in self._ancestors(item)}
            old, old_gaps = self._cut(before, scope)
            new, new_gaps = self._cut(before - moving, scope)
            gaps.update(old_gaps | new_gaps)
            deltas.append(MotionBoundaryDelta(container,
                tuple(old[key] for key in sorted(old.keys() - new.keys())),
                tuple(new[key] for key in sorted(new.keys() - old.keys()))))
        descendants = {item for item in self.bundle.evidence.instances
                       if any(member in self._ancestors(item) for member in moving)}
        if descendants - moving:
            gaps.add("selected members omit dynamic descendants; composite membership needs closure")
        inputs = []
        if len({(item.slot, item.consumer) for item in origins}) != len(origins):
            raise ValueError("duplicate input origin query")
        for origin in sorted(origins, key=lambda item: (item.slot.wire, item.consumer.wire)):
            self._validate_result(origin)
            if origin.scope != scope or origin.consumer not in moving:
                raise ValueError("input origin belongs to another query scope or consumer")
            producers = tuple(sorted({site.producer for site in origin.value_sites if self._witnessed(site)}, key=lambda item: item.wire))
            relation = PlacementRelation.UNKNOWN
            if len(producers) == 1:
                producer = producers[0]
                relation = (PlacementRelation.AT_TARGET if producer == target else
                    PlacementRelation.ABOVE_TARGET if producer in self._ancestors(target) else
                    PlacementRelation.BELOW_TARGET if target in self._ancestors(producer) else
                    PlacementRelation.UNRELATED)
            inputs.append(InputAvailability(origin.slot, origin.handle.version if origin.handle else None,
                origin.handle.materialization if origin.handle else None, producers, relation, ProofStatus.UNKNOWN,
                "logical producer location does not establish readiness, dominance, or insertion-point availability"))
            gaps.update(origin.gaps)
        if not origins:
            gaps.add("input binding/provenance queries have not been supplied")
        gaps.add("lifetime extension entries are review candidates; actual live-range change requires an insertion point")
        obligations = tuple(ProofClaim(name, ProofStatus.UNKNOWN, reason=reason, required_next=reason)
            for name, reason in (
                ("input_and_state_availability", "establish every input and hidden state version at a precise target insertion point"),
                ("control_dominance_and_zero_iteration", "prove all-path branch/loop execution count and zero-iteration behavior"),
                ("effect_and_exception_order", "preserve state, RNG, external effects, synchronization and exception timing"),
                ("alias_mutation_and_lifetime", "cover alias writes, allocation lifetimes, readiness and increased live ranges"),
                ("autograd_and_hooks", "preserve autograd graph, hooks, callbacks and required state"),
                ("dependency_and_consumer_closure", "close call, control and producer-consumer boundaries beyond the observed path"),
                ("placement_and_cost", "choose a concrete insertion point and measure guard, retention and saved-work cost")))
        return MotionQuery(tuple(sorted(moving, key=lambda item: item.wire)), target, scope,
            ordered + (target,), tuple(deltas), tuple(inputs),
            tuple(sorted(origins, key=lambda item: (item.slot.wire, item.consumer.wire))),
            tuple(sorted({item.materialization for item in inputs if item.materialization} |
                         {item.id for item in self.bundle.values.materializations.values()
                          if item.producer in moving}, key=lambda item: item.wire)),
            obligations, tuple(sorted(gaps)))

    def validate_result(self, result):
        """Validate wire records against current graph/scope before reuse."""
        self._validate()
        return self._validate_result(result)

    def _validate_result(self, result):
        if isinstance(result, OriginQuery):
            decode(OriginQuery, encode(result))
            expected = self._origin(result.slot, result.consumer, result.at)
        elif isinstance(result, MotionQuery):
            decode(MotionQuery, encode(result))
            expected = self._motion(result.members, result.target, scope=result.scope, origins=result.origins)
        else:
            raise ValueError("unsupported region query result")
        if result != expected:
            raise ValueError("query result no longer matches scoped binding/provenance/dependency evidence")
        return True

    def origin_for_region(self, inventory, region: OptimizationRegionID, slot: ValueSlotID,
                          consumer: OperationInstanceID, at: EventPoint) -> RegionOriginQuery:
        """Attach a scoped origin query to an actual execution-region identity.

        The slot must have an explicit G4 binding for a consumer in the region.
        A runtime region need not contain static slot ports; the binding is the
        typed bridge, and no slot identity is invented from a legacy token.
        """
        inventory.assert_valid()
        if inventory.bundle is not self.bundle or region not in inventory.graph.regions:
            raise ValueError("region query requires the same bundle and an existing region")
        construction = inventory.constructions[region]
        if construction.view.value != "execution" or consumer not in inventory.graph.regions[region].instances:
            raise ValueError("origin consumer must belong to the selected execution region")
        return RegionOriginQuery(region, construction.scope, self.origin(slot, consumer, at))

    def validate_region_result(self, result: RegionOriginQuery, inventory):
        decode(RegionOriginQuery, encode(result))
        expected = self.origin_for_region(inventory, result.region, result.origin.slot,
                                         result.origin.consumer, result.origin.at)
        if result != expected:
            raise ValueError("region origin no longer matches region scope and provenance")
        return True


__all__ = ["OriginPlacement", "OriginSite", "ProvenanceStep", "OriginQuery", "RegionOriginQuery", "OriginStatus",
           "QueryEndpoint", "DependencyCrossing", "MotionBoundaryDelta", "InputAvailability", "PlacementRelation",
           "MotionQuery", "RegionQueries"]
