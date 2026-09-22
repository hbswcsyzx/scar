from dataclasses import replace
import json

import pytest

from scar.analysis.effects_v2 import (
    EffectClosureEngine, EffectCoverage, EffectDimension, EffectOccurrence,
    ObservationScope, OperationEffects, ScopeMode,
)
from scar.analysis.region_conflicts_v2 import (
    ConflictStatus, MembershipRelation, RegionComparison, compare_regions,
)
from scar.analysis.regions_v2 import build_regions
from scar.ir.v2 import (
    Completeness, EffectTarget, EffectTargetKind, EvidenceClaim, EvidenceGraph,
    EvidenceKind, IRBundle, OperationDefinition, OperationDefinitionID,
    OperationKind, RegionGranularity, SemanticGraph, ValueGraph,
    StorageAllocation, StorageAllocationID, StorageRegion, StorageRegionID,
)


def fixture(*, closed=True, complete=True, targets=(), values=None):
    graph = SemanticGraph()
    definitions = tuple(OperationDefinitionID(f"op:{index}") for index in range(3))
    for identity in definitions:
        graph.add_definition(OperationDefinition(identity, OperationKind.FUNCTION, identity.value))
    engine = EffectClosureEngine(graph)
    claim = EvidenceClaim(EvidenceKind.DECLARED, ("fixture:effect-contract",), scope="scope")
    engine.add_scope(ObservationScope("scope", "entry", "exit" if closed else None, "run",
        ScopeMode.ALL_PATHS, "semantic", closed=closed, evidence=(claim,) if closed else ()))
    for index, identity in enumerate(definitions):
        ids = []
        for n, (dimension, target, kind) in enumerate(targets[index] if index < len(targets) else ()):
            effect = EffectOccurrence(f"effect:{index}:{n}", identity, dimension, target, "scope", n,
                replace(claim, kind=kind), dependency_coverage=Completeness.COMPLETE,
                order_coverage=Completeness.COMPLETE)
            engine.add_occurrence(effect)
            ids.append(effect.id)
        coverage = tuple(EffectCoverage("scope", dimension,
            Completeness.COMPLETE if complete else Completeness.UNKNOWN,
            branches=Completeness.COMPLETE, calls=Completeness.COMPLETE, aliases=Completeness.COMPLETE,
            evidence=(claim,)) for dimension in EffectDimension)
        engine.add_operation_effects(OperationEffects(identity, "scope", tuple(ids), coverage))
    bundle = IRBundle(graph, EvidenceGraph(), values or ValueGraph())
    inventory = build_regions(bundle, view="semantic", roots=definitions, max_depth=0,
                              effects=engine, scope="scope")
    regions = tuple(next(key for key, region in inventory.graph.regions.items()
                         if region.definitions == (identity,)) for identity in definitions)
    return inventory, regions, definitions


def test_disjoint_members_can_have_known_state_dependency():
    target = EffectTarget(EffectTargetKind.OBJECT, "module-buffer")
    inventory, (left, right, _), _ = fixture(targets=(
        ((EffectDimension.WRITES, target, EvidenceKind.DECLARED),),
        ((EffectDimension.READS, target, EvidenceKind.OBSERVED),)))
    result = compare_regions(inventory, left, right)
    assert result.membership is MembershipRelation.DISJOINT
    assert result.semantic_status is ConflictStatus.DEPENDENCY
    assert result.facts[0].left_effects == ("effect:0:0",)
    assert result.facts[0].right_effects == ("effect:1:0",)


def test_inferred_write_cannot_become_known_dependency():
    target = EffectTarget(EffectTargetKind.OBJECT, "buffer")
    inventory, (left, right, _), _ = fixture(targets=(
        ((EffectDimension.WRITES, target, EvidenceKind.INFERRED),),
        ((EffectDimension.READS, target, EvidenceKind.DECLARED),)))
    assert compare_regions(inventory, left, right).semantic_status is ConflictStatus.POSSIBLE


@pytest.mark.parametrize("closed,complete", [(False, True), (True, False)])
def test_empty_observations_do_not_prove_independence(closed, complete):
    inventory, (left, right, _), _ = fixture(closed=closed, complete=complete)
    result = compare_regions(inventory, left, right)
    assert result.semantic_status is ConflictStatus.POSSIBLE and result.gaps


def test_closed_complete_effectless_regions_have_only_scoped_result():
    inventory, (left, right, _), _ = fixture()
    result = compare_regions(inventory, left, right)
    assert result.semantic_status is ConflictStatus.NONE_IN_SCOPE
    assert result.report_only and result.scope == "scope"
    assert all(item.original for item in inventory.graph.alternatives.values())


def test_nested_partial_and_equal_membership_are_separate_from_semantic_conflict():
    inventory, (left, _, _), (a, b, c) = fixture()
    ab = inventory.region((a, b), granularity=RegionGranularity.DATAFLOW_SUBGRAPH)
    bc = inventory.region((b, c), granularity=RegionGranularity.DATAFLOW_SUBGRAPH)
    # Builders may return a region ID or the region record. Normalize the public result.
    ab = getattr(ab, "id", ab)
    bc = getattr(bc, "id", bc)
    assert compare_regions(inventory, ab, left).membership is MembershipRelation.LEFT_CONTAINS
    assert compare_regions(inventory, left, ab).membership is MembershipRelation.RIGHT_CONTAINS
    assert compare_regions(inventory, ab, bc).membership is MembershipRelation.PARTIAL
    assert compare_regions(inventory, left, left).membership is MembershipRelation.EQUAL


def test_budget_exhaustion_cannot_claim_no_conflict():
    def effects(prefix):
        return tuple((EffectDimension.WRITES, EffectTarget(EffectTargetKind.ENVIRONMENT, f"{prefix}{i}"),
                      EvidenceKind.DECLARED) for i in range(3))
    inventory, (left, right, _), _ = fixture(targets=(effects("left"), effects("right")))
    result = compare_regions(inventory, left, right, target_pair_budget=2)
    assert result.semantic_status is ConflictStatus.POSSIBLE
    assert result.compared_target_pairs == 2
    assert any("budget" in gap for gap in result.gaps)
    assert compare_regions(inventory, left, right).semantic_status is ConflictStatus.NONE_IN_SCOPE


def test_same_input_comparison_is_deterministic_and_strict():
    inventory, (left, right, _), _ = fixture()
    result = compare_regions(inventory, left, right)
    document = result.to_dict()
    assert compare_regions(inventory, left, right).to_dict() == document
    assert RegionComparison.from_json(json.dumps(document)) == result
    document["comparison"]["report_only"] = False
    with pytest.raises(ValueError):
        RegionComparison.from_dict(document)
    with pytest.raises(ValueError):
        compare_regions(inventory, left, right, target_pair_budget=True)


@pytest.mark.parametrize("offset,size,expected", [
    (2, 4, ConflictStatus.DEPENDENCY),
    (8, 4, ConflictStatus.NONE_IN_SCOPE),
    (1, 5000, ConflictStatus.POSSIBLE),
])
def test_storage_alias_geometry_not_descriptor_string(offset, size, expected):
    values = ValueGraph()
    allocation = StorageAllocationID("allocation")
    values.add_allocation(StorageAllocation(allocation, "cpu", 100000))
    regions = [StorageRegion(StorageRegionID("left"), allocation, 0, (size,), (2,), "float32", "cpu"),
               StorageRegion(StorageRegionID("right"), allocation, offset, (size,), (2,), "float32", "cpu")]
    for region in regions:
        values.add_region(region)
    inventory, (left, right, _), _ = fixture(values=values, targets=(
        ((EffectDimension.WRITES, EffectTarget(EffectTargetKind.STORAGE, regions[0].id.wire), EvidenceKind.DECLARED),),
        ((EffectDimension.READS, EffectTarget(EffectTargetKind.STORAGE, regions[1].id.wire), EvidenceKind.DECLARED),)))
    result = compare_regions(inventory, left, right)
    assert result.semantic_status is expected
