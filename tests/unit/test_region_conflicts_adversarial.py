"""Independent dependency queries over real, explicitly scoped inventories."""
from dataclasses import replace

import pytest

import scar.analysis.region_conflicts_v2 as conflicts
from scar.analysis.effects_v2 import (
    EffectClosureEngine, EffectCoverage, EffectDimension, EffectOccurrence,
    ObservationScope, OperationEffects, ScopeMode,
)
from scar.analysis.region_conflicts_v2 import ConflictStatus, compare_regions
from scar.analysis.regions_v2 import build_regions
import scar.ir.v2 as ir


def _fixture(*, targets=((), ()), closed=True, values=None, dataflow=False):
    semantic = ir.SemanticGraph()
    members = (ir.OperationDefinitionID("producer"), ir.OperationDefinitionID("consumer"))
    slot = ir.ValueSlotID("result")
    semantic.add_definition(ir.OperationDefinition(members[0], ir.OperationKind.FUNCTION, "producer",
                                                   output_slots=(slot,) if dataflow else ()))
    semantic.add_definition(ir.OperationDefinition(members[1], ir.OperationKind.FUNCTION, "consumer"))
    claim = ir.EvidenceClaim(ir.EvidenceKind.DECLARED, ("fixture:closed-effect-contract",), scope="scope")
    if dataflow:
        semantic.slots[slot] = ir.ValueSlot(slot, "result", "output", owner=members[0])
        semantic.add_edge(ir.SemanticEdge("read-producer-output", ir.SemanticRelation.READS_SLOT,
            ir.SemanticEndpoint(ir.SemanticNodeKind.OPERATION, members[1]),
            ir.SemanticEndpoint(ir.SemanticNodeKind.VALUE_SLOT, slot), claim))
    engine = EffectClosureEngine(semantic)
    engine.add_scope(ObservationScope("scope", "entry", "exit" if closed else None, "fixture-run",
        ScopeMode.ALL_PATHS, "declared-order", closed=closed, evidence=(claim,) if closed else ()))
    coverage = tuple(EffectCoverage("scope", dimension, ir.Completeness.COMPLETE,
        branches=ir.Completeness.COMPLETE, calls=ir.Completeness.COMPLETE,
        aliases=ir.Completeness.COMPLETE, evidence=(claim,)) for dimension in EffectDimension)
    for index, (definition, specs) in enumerate(zip(members, targets)):
        occurrences = []
        for number, (dimension, target) in enumerate(specs):
            occurrence = EffectOccurrence(f"effect:{index}:{number}", definition, dimension,
                target, "scope", number, claim, dependency_coverage=ir.Completeness.COMPLETE,
                order_coverage=ir.Completeness.COMPLETE)
            engine.add_occurrence(occurrence)
            occurrences.append(occurrence.id)
        engine.add_operation_effects(OperationEffects(definition, "scope", tuple(occurrences), coverage))
    bundle = ir.IRBundle(semantic, ir.EvidenceGraph(), values or ir.ValueGraph())
    inventory = build_regions(bundle, view="semantic", roots=members, max_depth=0,
                              effects=engine, scope="scope")
    regions = tuple(next(key for key, region in inventory.graph.regions.items()
                         if region.definitions == (member,)) for member in members)
    return inventory, regions


def test_declared_closed_effects_do_not_erase_producer_to_reader_dataflow():
    inventory, (left, right) = _fixture(dataflow=True)
    result = compare_regions(inventory, left, right)
    assert result.semantic_status is not ConflictStatus.NONE_IN_SCOPE
    assert any("output-to-input" in fact.reason for fact in result.facts)
    assert any(fact.left_target.reference == "slot:result" for fact in result.facts)
    assert result.report_only


def test_unknown_storage_descriptor_is_not_a_certified_physical_identity():
    target = ir.EffectTarget(ir.EffectTargetKind.STORAGE, "region:not-captured")
    inventory, (left, right) = _fixture(targets=(
        ((EffectDimension.WRITES, target),), ((EffectDimension.READS, target),)))
    result = compare_regions(inventory, left, right)
    assert result.semantic_status is ConflictStatus.POSSIBLE
    assert all(fact.status is not ConflictStatus.DEPENDENCY for fact in result.facts)


def test_zero_stride_view_aliases_the_actual_written_element():
    values = ir.ValueGraph()
    allocation = ir.StorageAllocationID("shared-allocation")
    values.add_allocation(ir.StorageAllocation(allocation, "cpu", nbytes=32))
    broadcast = ir.StorageRegion(ir.StorageRegionID("broadcast"), allocation, 0, (8,), (0,), "float32", "cpu")
    dense = ir.StorageRegion(ir.StorageRegionID("dense"), allocation, 0, (8,), (1,), "float32", "cpu")
    for region in (broadcast, dense):
        values.add_region(region)
    inventory, (left, right) = _fixture(values=values, targets=(
        ((EffectDimension.WRITES, ir.EffectTarget(ir.EffectTargetKind.STORAGE, broadcast.id.wire)),),
        ((EffectDimension.READS, ir.EffectTarget(ir.EffectTargetKind.STORAGE, dense.id.wire)),)))
    result = compare_regions(inventory, left, right)
    assert result.semantic_status is ConflictStatus.DEPENDENCY
    assert any("overlap" in fact.reason for fact in result.facts)


def test_identical_opaque_target_never_becomes_an_alias_proof():
    target = ir.EffectTarget(ir.EffectTargetKind.OPAQUE, "unknown-callback-state")
    inventory, (left, right) = _fixture(targets=(
        ((EffectDimension.WRITES, target),), ((EffectDimension.READS, target),)))
    result = compare_regions(inventory, left, right)
    assert result.semantic_status is ConflictStatus.POSSIBLE
    assert any("opaque" in fact.reason for fact in result.facts)


def test_nonclosed_endpoint_retains_future_consumer_gap_even_for_disjoint_effects():
    inventory, (left, right) = _fixture(closed=False, targets=(
        ((EffectDimension.WRITES, ir.EffectTarget(ir.EffectTargetKind.ENVIRONMENT, "LEFT")),),
        ((EffectDimension.READS, ir.EffectTarget(ir.EffectTargetKind.ENVIRONMENT, "RIGHT")),)))
    result = compare_regions(inventory, left, right)
    assert result.semantic_status is ConflictStatus.POSSIBLE
    assert any("future" in gap for gap in result.gaps)


def test_scope_and_view_mutations_cannot_compare_incomparable_regions():
    inventory, (left, right) = _fixture()
    original = inventory.constructions[right]
    inventory.scopes["other"] = replace(inventory.scopes["scope"], id="other")
    inventory.constructions[right] = replace(original, scope="other")
    with pytest.raises(ValueError):
        compare_regions(inventory, left, right)
    inventory.constructions[right] = replace(original, mode=ScopeMode.DYNAMIC_PATH)
    with pytest.raises(ValueError):
        compare_regions(inventory, left, right)
    with pytest.raises(ValueError):
        compare_regions(inventory, left, ir.OptimizationRegionID("missing"))


def test_exactly_consumed_pair_budget_does_not_fabricate_unexamined_pairs():
    target = ir.EffectTarget(ir.EffectTargetKind.ENVIRONMENT, "SHARED")
    inventory, (left, right) = _fixture(targets=(
        ((EffectDimension.WRITES, target),), ((EffectDimension.READS, target),)))
    result = compare_regions(inventory, left, right, target_pair_budget=1)
    assert result.compared_target_pairs == 1
    assert result.semantic_status is ConflictStatus.DEPENDENCY
    assert not any("budget" in gap for gap in result.gaps)


def test_read_only_groups_do_not_bypass_pair_budget_with_quadratic_scans(monkeypatch):
    count = 24
    targets = tuple(tuple((EffectDimension.READS,
        ir.EffectTarget(ir.EffectTargetKind.ENVIRONMENT, f"side:{side}:{index}"))
        for index in range(count)) for side in range(2))
    inventory, (left, right) = _fixture(targets=targets)

    class SideEffectChecks(set):
        visits = 0

        def __rand__(self, other):
            self.visits += 1
            return set(other).intersection(self)

    checks = SideEffectChecks(conflicts._SIDE_EFFECTS)
    monkeypatch.setattr(conflicts, "_SIDE_EFFECTS", checks)
    result = compare_regions(inventory, left, right, target_pair_budget=1)
    assert result.compared_target_pairs == 0
    assert not any("budget" in gap for gap in result.gaps)
    # Compare classification work, not a noisy timing threshold. A read-only
    # group may be classified once; enumerating every read/read pair is waste.
    assert checks.visits <= 2 * count + 2
