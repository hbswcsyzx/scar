"""Separate region membership overlap from scoped effect dependencies.

This query never authorizes a transformation or promises that two rewrites can
compose. Unknown aliases and a bounded comparison budget remain explicit.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from scar.ir.provenance import Overlap, region_overlap
from scar.ir.record_codec import encode, decode, loads
from scar.ir.v2 import EffectTarget, EffectTargetKind, EvidenceKind, OptimizationRegionID, RegionPortKind
from .effects_v2 import EffectDimension


class MembershipRelation(str, Enum):
    EQUAL = "equal"
    LEFT_CONTAINS = "left_contains"
    RIGHT_CONTAINS = "right_contains"
    PARTIAL = "partial_overlap"
    DISJOINT = "disjoint"


class ConflictStatus(str, Enum):
    DEPENDENCY = "known_dependency"
    POSSIBLE = "possible_dependency"
    NONE_IN_SCOPE = "no_dependency_in_closed_scope"


@dataclass(frozen=True)
class ConflictFact:
    left_effects: tuple[str, ...]
    right_effects: tuple[str, ...]
    left_target: EffectTarget
    right_target: EffectTarget
    status: ConflictStatus
    reason: str


@dataclass(frozen=True)
class RegionComparison:
    left: OptimizationRegionID
    right: OptimizationRegionID
    scope: str
    membership: MembershipRelation
    shared_members: tuple[str, ...]
    semantic_status: ConflictStatus
    facts: tuple[ConflictFact, ...]
    gaps: tuple[str, ...]
    compared_target_pairs: int
    report_only: bool = True

    def __post_init__(self):
        if not self.scope or not self.report_only:
            raise ValueError("region comparison is scoped and report-only")
        if type(self.compared_target_pairs) is not int or self.compared_target_pairs < 0:
            raise ValueError("comparison count must be a nonnegative integer")
        if self.semantic_status is ConflictStatus.NONE_IN_SCOPE and (self.gaps or self.facts):
            raise ValueError("unresolved or conflicting comparison cannot claim no dependency")
        if self.semantic_status is ConflictStatus.DEPENDENCY and not any(
                fact.status is ConflictStatus.DEPENDENCY for fact in self.facts):
            raise ValueError("known dependency needs an explicit fact")
        if bool(self.shared_members) != (self.membership is not MembershipRelation.DISJOINT):
            raise ValueError("membership relation and shared members disagree")

    def to_dict(self):
        return {"schema": "scar.region-comparison", "schema_version": 1,
                "comparison": encode(self)}

    @classmethod
    def from_dict(cls, document):
        if (type(document) is not dict
                or set(document) != {"schema", "schema_version", "comparison"}
                or document["schema"] != "scar.region-comparison"
                or type(document["schema_version"]) is not int
                or document["schema_version"] != 1):
            raise ValueError("unsupported region-comparison document")
        return decode(cls, document["comparison"])

    @classmethod
    def from_json(cls, payload):
        return cls.from_dict(loads(payload))


_SIDE_EFFECTS = set(EffectDimension) - {EffectDimension.READS}
_GLOBAL_ORDER = {EffectDimension.MAY_RAISE, EffectDimension.ORDERING}


def _auditable(group):
    return all(item.evidence.kind in {EvidenceKind.OBSERVED, EvidenceKind.DECLARED}
               and item.evidence.references for item in group)


def _target_relation(left, right, regions):
    if left == right:
        if left.kind is EffectTargetKind.OPAQUE:
            return ConflictStatus.POSSIBLE, "opaque target identity is not an alias proof"
        if left.kind is EffectTargetKind.STORAGE and left.reference not in regions:
            return ConflictStatus.POSSIBLE, "storage descriptor lacks a region/lifetime identity witness"
        return ConflictStatus.DEPENDENCY, "same scoped effect target"
    if left.kind is EffectTargetKind.STORAGE and right.kind is EffectTargetKind.STORAGE:
        a, b = regions.get(left.reference), regions.get(right.reference)
        if a is not None and b is not None:
            overlap = region_overlap(a, b)
            if overlap is Overlap.DISJOINT:
                return None, "disjoint storage regions"
            if overlap is Overlap.POSSIBLE:
                return ConflictStatus.POSSIBLE, "storage-region overlap is unresolved"
            return ConflictStatus.DEPENDENCY, "physical storage regions overlap"
    # Scoped environment keys and slot bindings are distinct identities. This
    # does not assert that the objects stored in distinct slots cannot alias.
    if left.kind == right.kind and left.kind in {
            EffectTargetKind.ENVIRONMENT, EffectTargetKind.VALUE_SLOT}:
        return None, "different scoped bindings"
    return ConflictStatus.POSSIBLE, "different target descriptors do not prove disjoint effects"


def _port_targets(inventory, region, kinds):
    result = set()
    for identity in region.ports:
        port = inventory.graph.ports[identity]
        if port.kind not in kinds:
            continue
        if port.slot is not None:
            result.add(EffectTarget(EffectTargetKind.VALUE_SLOT, port.slot.wire))
        if port.value:
            result.update(EffectTarget(EffectTargetKind.VALUE_VERSION, item.wire)
                          for item in port.value.versions)
    return result


def compare_regions(inventory, left: OptimizationRegionID, right: OptimizationRegionID,
                    *, target_pair_budget: int = 4096) -> RegionComparison:
    """Query known/possible dependencies; source and invocation views stay distinct."""
    if type(target_pair_budget) is not int or target_pair_budget <= 0:
        raise ValueError("target-pair budget must be positive")
    inventory.assert_valid()
    if left not in inventory.constructions or right not in inventory.constructions:
        raise ValueError("unknown region")
    a, b = inventory.constructions[left], inventory.constructions[right]
    if a.view != b.view or a.scope != b.scope or a.mode != b.mode:
        raise ValueError("region comparison requires the same view, scope and mode")
    ra, rb = inventory.graph.regions[left], inventory.graph.regions[right]
    ma = {item.wire for item in (ra.instances if ra.instances else ra.definitions)}
    mb = {item.wire for item in (rb.instances if rb.instances else rb.definitions)}
    shared = tuple(sorted(ma & mb))
    membership = (MembershipRelation.EQUAL if ma == mb else
                  MembershipRelation.LEFT_CONTAINS if mb < ma else
                  MembershipRelation.RIGHT_CONTAINS if ma < mb else
                  MembershipRelation.PARTIAL if shared else MembershipRelation.DISJOINT)
    gaps = set()
    scope = inventory.scopes[a.scope]
    if not scope.closed:
        gaps.add("observation scope is open; future consumers/order effects may be missing")
    if not a.effects_closed or not b.effects_closed:
        gaps.add("effect/call/branch/alias coverage is incomplete")
    groups = []
    for construction in (a, b):
        grouped = {}
        for occurrence in construction.effect_occurrences:
            grouped.setdefault(occurrence.target, []).append(occurrence)
        groups.append(grouped)
    facts, compared, exhausted = [], 0, False
    for producer, consumer in ((ra, rb), (rb, ra)):
        targets = (_port_targets(inventory, producer, {RegionPortKind.OUTPUT}) &
                   _port_targets(inventory, consumer, {RegionPortKind.INPUT, RegionPortKind.STATE}))
        for target in sorted(targets, key=lambda item: (item.kind.value, item.reference)):
            facts.append(ConflictFact((), (), target, target, ConflictStatus.POSSIBLE,
                f"possible output-to-input dependency from {producer.id.wire} to {consumer.id.wire}; "
                "interface overlap alone does not prove actual consumption"))
    storage_regions = {item.id.wire: item for item in inventory.bundle.values.regions.values()}
    ordered_b = sorted(groups[1].items(), key=lambda item: (item[0].kind.value, item[0].reference))
    b_dimensions = {target: {item.dimension for item in group} for target, group in ordered_b}
    side_effect_b = [(target, group) for target, group in ordered_b if b_dimensions[target] & _SIDE_EFFECTS]
    for target_a, group_a in sorted(groups[0].items(), key=lambda item: (item[0].kind.value, item[0].reference)):
        dims_a = {item.dimension for item in group_a}
        for target_b, group_b in ordered_b if dims_a & _SIDE_EFFECTS else side_effect_b:
            dims_b = b_dimensions[target_b]
            if compared >= target_pair_budget:
                exhausted = True
                break
            compared += 1
            status, reason = _target_relation(target_a, target_b, storage_regions)
            if (dims_a | dims_b) & _GLOBAL_ORDER:
                # Different data does not remove exception timing or ordering obligations.
                status = status or ConflictStatus.POSSIBLE
                reason = "exception/ordering effect requires relative-order evidence; " + reason
            if status is None:
                continue
            if status is ConflictStatus.DEPENDENCY and not _auditable((*group_a, *group_b)):
                status, reason = ConflictStatus.POSSIBLE, "inferred effect membership; " + reason
            facts.append(ConflictFact(tuple(sorted(item.id for item in group_a)),
                tuple(sorted(item.id for item in group_b)), target_a, target_b, status, reason))
        if exhausted:
            gaps.add("target-pair budget exhausted; unexamined target pairs may conflict")
            break
    status = (ConflictStatus.DEPENDENCY if any(item.status is ConflictStatus.DEPENDENCY for item in facts)
              else ConflictStatus.POSSIBLE if facts or gaps else ConflictStatus.NONE_IN_SCOPE)
    return RegionComparison(left, right, a.scope, membership, shared, status, tuple(facts),
                            tuple(sorted(gaps)), compared)


__all__ = ["MembershipRelation", "ConflictStatus", "ConflictFact", "RegionComparison", "compare_regions"]
