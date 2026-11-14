"""Focused pass, proof, provenance and resource tests for the CPU profile."""

from dataclasses import replace
import math

import pytest

from scar.compiler.model import ArrayRegion, Expr, SourceRef
from scar.optimization import optimize_region, select_measured


SOURCE = SourceRef("/tmp/example.py", "0" * 64, "example", 1, 0, "example:v1",
                   ({"node_id": "sum", "line": 5, "column": 4},))


def region(*nodes, output=None, **kwargs):
    parameters = tuple(n.attrs["name"] for n in nodes if n.op == "input")
    return ArrayRegion("test", SOURCE, parameters, tuple(nodes),
                       output or nodes[-1].id, **kwargs)


def example():
    return region(Expr("x", "input", attrs={"name": "x"}),
                  Expr("two", "const", attrs={"value": 2.0}),
                  Expr("product", "mul", ("x", "two")),
                  Expr("sum", "add", ("product", "x")))


def test_structural_cse_handles_dict_and_list_attributes_without_reordering_operands():
    graph = region(
        Expr("x", "input", attrs={"name": "x"}),
        Expr("a", "slice", ("x",), {"bounds": [[1, -1], [None, None]]}),
        Expr("b", "slice", ("x",), {"bounds": [[1, -1], [None, None]]}),
        Expr("ab", "sub", ("a", "b")),
        Expr("ba", "sub", ("b", "a")),
        Expr("sum", "add", ("ab", "ba")),
    )
    plan = optimize_region(graph)
    # a and b merge, making these ordered operands identical after substitution.
    assert [n.id for n in plan.region.nodes] == ["x", "a", "ab", "sum"]
    assert plan.proof["source_operation_map"]["b"]["optimized_node"] == "a"
    assert plan.proof["source_operation_map"]["ba"]["optimized_node"] == "ab"
    assert plan.region.source is SOURCE
    assert plan.region.source.origins == SOURCE.origins
    assert plan.proof["effects"]["purity_basis"] == "closed_operator_semantics"

    ordered = region(Expr("x", "input", attrs={"name": "x"}),
                     Expr("y", "input", attrs={"name": "y"}),
                     Expr("xy", "sub", ("x", "y")),
                     Expr("yx", "sub", ("y", "x")),
                     Expr("sum", "add", ("xy", "yx")))
    assert len(optimize_region(ordered).region.nodes) == 5


def test_constant_folding_follows_original_float_dag_and_preserves_python_zero_types():
    graph = region(
        Expr("x", "input", attrs={"name": "x"}),
        Expr("large", "const", attrs={"value": 1e16}),
        Expr("negative", "const", attrs={"value": -1e16}),
        Expr("one", "const", attrs={"value": 1.0}),
        Expr("cancel", "add", ("large", "negative")),
        Expr("left", "add", ("cancel", "one")),
        Expr("rounded", "add", ("negative", "one")),
        Expr("right", "add", ("large", "rounded")),
        Expr("delta", "sub", ("left", "right")),
        Expr("sum", "add", ("x", "delta")),
    )
    plan = optimize_region(graph)
    constants = [n.attrs["value"] for n in plan.region.nodes if n.op == "const"]
    assert constants == [1.0]
    assert {"cancel", "left", "rounded", "right", "delta"}.issubset(
        plan.proof["folded_nodes"])

    zeros = region(Expr("x", "input", attrs={"name": "x"}),
                   Expr("i", "const", attrs={"value": 0}),
                   Expr("f", "const", attrs={"value": 0.0}),
                   Expr("ni", "neg", ("i",)),
                   Expr("nf", "neg", ("f",)),
                   Expr("ix", "mul", ("x", "ni")),
                   Expr("fx", "mul", ("x", "nf")),
                   Expr("sum", "add", ("ix", "fx")))
    plan = optimize_region(zeros)
    values = [n.attrs["value"] for n in plan.region.nodes if n.op == "const"]
    assert any(type(v) is int and v == 0 for v in values)
    assert any(type(v) is float and math.copysign(1, v) < 0 for v in values)


@pytest.mark.parametrize("op,a,b", [("div", 1.0, 0.0),
                                    ("mul", 1e308, 1e308),
                                    ("mul", 2**53, 2)])
def test_exceptional_or_out_of_profile_constant_operations_retain_original_region(op, a, b):
    graph = region(Expr("x", "input", attrs={"name": "x"}),
                   Expr("a", "const", attrs={"value": a}),
                   Expr("b", "const", attrs={"value": b}),
                   Expr("unsafe", op, ("a", "b")),
                   Expr("sum", "add", ("x", "unsafe")))
    plan = optimize_region(graph)
    assert plan.region is graph
    assert plan.cost["decision"] == "unsupported"
    assert plan.proof["retained_constant_operations"][0]["id"] == "unsafe"


def test_dce_removes_dependency_closure_but_cannot_drop_potential_numpy_warnings():
    graph = example()
    extra = (Expr("dead_const", "const", attrs={"value": 3.0}),
             Expr("dead_neg", "neg", ("dead_const",)),
             Expr("dead_view", "slice", ("x",), {"bounds": [[None, -1], [0, None]]}))
    plan = optimize_region(replace(graph, nodes=graph.nodes + extra))
    assert {n.id for n in plan.region.nodes} == {"x", "two", "product", "sum"}
    for node in extra:
        assert plan.proof["source_operation_map"][node.id]["optimized_node"] is None
        assert plan.proof["source_operation_map"][node.id]["reason"] == "dead_dependency"

    dead_div = Expr("dead_array", "div", ("x", "x"))
    guarded = optimize_region(replace(graph, nodes=graph.nodes + (dead_div,)))
    assert guarded.cost["decision"] == "unsupported"
    assert guarded.region.nodes[-1] is dead_div
    assert "dead_array_arithmetic_may_warn:dead_array" in guarded.proof["reasons"]


def test_setup_is_descriptor_only_and_plan_is_shared_scalar_dag_with_fresh_output():
    plan = optimize_region(example())
    assert plan.proof["setup_nodes"] == ["x", "two"]
    assert plan.proof["body_nodes"] == ["product", "sum"]
    assert plan.proof["body_load_nodes"] == ["x"]
    assert "x" in plan.proof["variant_array_nodes"]
    assert "array contents are loaded again" in plan.proof["setup_semantics"]
    assert [axis.variable for axis in plan.schedule] == ["row", "col"]
    assert plan.buffer_policy == "fresh_output"
    assert plan.cpu_threads == 1
    assert plan.proof["resource_allocation"]["cpu_threads"] == 1
    assert plan.proof["effects"]["output_cache"] is False
    assert "FLOAT_STATUS_CLEAR_OR_FALLBACK_TO_ORIGINAL" in plan.proof["runtime_guards"]
    assert plan.proof["legality"]["status"] == "CONDITIONAL"
    assert "NO_FOREIGN_CONCURRENT_INPUT_WRITERS" in plan.proof["legality"]["external_assumptions"]


def test_resource_estimates_propose_coalescing_and_distinguish_budget_and_noop():
    plan = optimize_region(example(), memory_budget_bytes=1024)
    assert plan.cost["status"] == "ESTIMATED"
    assert plan.cost["decision"] == "proposed"
    assert plan.proof["selected"] is False
    assert plan.proof["lowering_eligible"] is True
    assert plan.cost["baseline_array_allocations"] == 2
    assert plan.cost["proposed_array_allocations"] == 1
    assert plan.cost["baseline_traffic_bytes_per_output_element"] == 40
    assert plan.cost["proposed_traffic_bytes_per_output_element"] == 16
    assert plan.cost["memory_guard_required"] is True
    assert plan.cost["memory_budget_bytes"] == 1024
    assert plan.cost["cpu_threads"] == 1
    assert "OUTPUT_NBYTES_WITHIN_MEMORY_BUDGET" in plan.proof["runtime_guards"]
    assert optimize_region(example(), memory_budget_bytes=0).cost["decision"] == "not_profitable"

    single = replace(example(), nodes=example().nodes[:3], output="product")
    no_op = optimize_region(single)
    assert no_op.proof["legal"] is True
    assert no_op.proof["selected"] is False
    assert no_op.cost["decision"] == "not_profitable"
    with pytest.raises(ValueError, match="nonnegative integer"):
        optimize_region(example(), memory_budget_bytes=-1)
    with pytest.raises(ValueError, match="nonnegative integer"):
        optimize_region(example(), memory_budget_bytes=True)
    with pytest.raises(ValueError, match="positive integer"):
        optimize_region(example(), cpu_threads=0)


@pytest.mark.parametrize("change", ["frontier", "operator", "assumptions", "attributes"])
def test_unknown_semantics_block_transformation_even_if_names_look_pure(change):
    graph = example()
    if change == "frontier":
        graph = replace(graph, frontiers=("unknown effect",))
    elif change == "operator":
        graph = replace(graph, nodes=graph.nodes + (Expr("pure", "pure_by_name"),))
    elif change == "assumptions":
        graph = replace(graph, assumptions=("PURE",))
    else:
        graph = replace(graph, nodes=(replace(graph.nodes[0], attrs={"name": "x", "pure": True}),)
                        + graph.nodes[1:])
    plan = optimize_region(graph)
    assert plan.region is graph
    assert not plan.proof["legal"]
    assert plan.cost["decision"] == "unsupported"
    assert plan.passes == ()


@pytest.mark.parametrize("nodes,output,message", [
    ((Expr("a", "neg", ("b",)), Expr("b", "neg", ("a",))), "a", "cycle"),
    ((Expr("a", "neg", ("missing",)),), "a", "dangling"),
    ((Expr("a", "const", attrs={"value": 1}),) * 2, "a", "duplicate"),
])
def test_invalid_graphs_fail_before_optimization(nodes, output, message):
    with pytest.raises(ValueError, match=message):
        optimize_region(region(*nodes, output=output))


def test_unsorted_input_dag_is_stably_sorted_before_dependency_passes():
    graph = example()
    plan = optimize_region(replace(graph, nodes=tuple(reversed(graph.nodes))))
    assert [n.id for n in plan.region.nodes] == ["two", "x", "product", "sum"]
    assert set(plan.proof["source_operation_map"]) == {n.id for n in graph.nodes}


def test_measured_selection_accepts_gain_and_accepts_slower_native_as_noop():
    plan = optimize_region(example())
    faster = select_measured(plan, [1.0, 1.1, 0.9], [0.8, 0.9, 0.7], validated=True)
    assert faster["decision"] == "TRANSFORM_UNDER_CONTRACT"
    assert faster["status"] == "MEASURED" and faster["selected"]
    assert faster["baseline"]["median"] == 1.0
    assert faster["native"]["min"] == 0.7
    assert faster["baseline"]["stdev"] == pytest.approx(0.1)
    assert faster["speedup"] == pytest.approx(1.25)
    assert faster["external_assumptions"] == plan.proof["legality"]["external_assumptions"]
    slower = select_measured(plan, [0.547], [1.0], validated=True)
    assert slower["decision"] == "NO_OP" and not slower["selected"]
    assert slower["speedup"] == pytest.approx(0.547)
    assert "measured_gain_below_required_threshold" in slower["reasons"]
    assert plan.proof["selected"] is False
