"""Counterexamples for replacement-boundary and cross-graph integrity."""
import pytest

from scar.ir.v2 import (
    OptimizationGraph, OptimizationContext, OptimizationRegion,
    OptimizationRegionID, OperationDefinitionID, PlanAlternative,
    PlanAlternativeID, RegionGranularity, TransformKind, TransformDelta,
    PlanInstruction, InstructionKind, PlanSelection, PlanDisposition, PlanID,
    LiteralValue, IRBundle, ValueVersion, ValueVersionID,
)
from test_ir_v2_optimization import _foundation


def _graph():
    a, b = OperationDefinitionID("a"), OperationDefinitionID("b")
    graph = OptimizationGraph(OptimizationContext(definitions=frozenset((a, b))))
    for definition in (a, b):
        region = OptimizationRegionID(definition.value)
        graph.add_region(OptimizationRegion(region, RegionGranularity.FUNCTION,
                                           definition.value, definitions=(definition,)))
        graph.add_alternative(PlanAlternative(
            PlanAlternativeID(definition.value + ":original"), region,
            "original", TransformKind.NO_OP, original=True))
    return graph, a, b


def test_delta_cannot_delete_another_regions_operations():
    graph, _, other = _graph()
    with pytest.raises(ValueError, match="outside target region"):
        graph.add_alternative(PlanAlternative(
            PlanAlternativeID("bad"), OptimizationRegionID("a"), "bad",
            TransformKind.DELETE, TransformDelta(removed_definitions=(other,)),
            fallback=PlanAlternativeID("a:original")))


def test_mutation_and_decode_cannot_bypass_selected_region_check():
    graph, _, _ = _graph()
    # The decoder populates records before graph validation, so exercise that
    # entry point explicitly instead of only testing add_plan().
    graph.plans[PlanID("bad")] = PlanSelection(
        PlanID("bad"), OptimizationRegionID("a"), PlanDisposition.KEEP,
        PlanAlternativeID("b:original"), "wrong region")
    assert any("another region" in error for error in graph.validate()["errors"])


def test_instruction_dependency_cycle_is_rejected():
    graph, a, _ = _graph()
    graph.add_alternative(PlanAlternative(
        PlanAlternativeID("cycle"), OptimizationRegionID("a"), "cycle",
        TransformKind.DELETE, TransformDelta(removed_definitions=(a,)),
        instructions=(
            PlanInstruction("i1", InstructionKind.DELETE_SOURCE, a.wire, depends_on=("i2",)),
            PlanInstruction("i2", InstructionKind.DELETE_SOURCE, a.wire, depends_on=("i1",)),
        ), fallback=PlanAlternativeID("a:original")))
    assert any("cyclic instruction" in error for error in graph.validate()["errors"])


def test_materialization_cannot_observe_another_version():
    sg, eeg, values, *_ = _foundation()
    observation = next(iter(eeg.observations.values()))
    other = ValueVersionID(observation.version.logical_value, 1)
    values.add_version(ValueVersion(other))
    observation.version = other
    assert any("materialization version mismatch" in error
               for error in IRBundle(sg, eeg, values).validate()["errors"])


@pytest.mark.parametrize("value", [(1, 2), {1: "x"}, float("inf"), b"x"])
def test_literals_that_json_would_change_are_rejected(value):
    with pytest.raises(ValueError, match="JSON value"):
        LiteralValue(value)


def test_original_alternative_cannot_be_mutated_into_a_rewrite():
    graph, a, _ = _graph()
    graph.alternatives[PlanAlternativeID("a:original")].delta = TransformDelta(
        removed_definitions=(a,))
    assert not graph.validate()["valid"]


def test_region_cycle_is_rejected():
    graph, _, _ = _graph()
    graph.regions[OptimizationRegionID("a")].parent = OptimizationRegionID("b")
    graph.regions[OptimizationRegionID("b")].parent = OptimizationRegionID("a")
    assert any("cyclic" in error for error in graph.validate()["errors"])
