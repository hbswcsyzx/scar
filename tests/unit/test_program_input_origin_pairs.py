import importlib

from scar.ir.program.ids import OperationID, UseID
from scar.ir.program.protocols import OwnedUse
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.input_origins import paired_input_origins
from scar.ir.execution.validity_budget import ValidityBudget
from tests.fixtures.program_input_origin_graphs import input_origin_program
from scar.ir.program.validation import require_valid


def _operation(graph, identity):
    return next(row for row in graph.operations if row.id == identity)


def _use(operation, identity):
    return next(row for row in operation.uses if row.id == identity)


def _raw_operand(graph, raw_value):
    definition = next(row for row in graph.raw_driver_requests if row.value == raw_value)
    pack = next(row for row in graph.operations if row.results == (raw_value,))
    return definition, pack, _use(pack, definition.operands[0])


def test_pair_joins_only_the_exact_operand_recipe_and_keeps_caller_chain():
    graph, details = input_origin_program()
    require_valid(graph)
    index = ProgramIndex(graph)
    left_op = _operation(graph, OperationID("inputs.middle.invoke.driver"))
    left_use = _use(left_op, UseID("inputs.middle.invoke.raw"))
    definition, pack, right_use = _raw_operand(graph, details["raw_values"][0])

    result = paired_input_origins(
        index, OwnedUse(left_op.id, left_use.id), OwnedUse(pack.id, right_use.id))

    assert len(result["pairs"]) == 1
    pair, = result["pairs"]
    assert pair["raw_definition"] is definition
    assert pair["pack_operation"] is pack
    assert pair["right_operand"]["use"] is right_use
    assert pair["caller_chain_scope"] == "SUPPLIED_STATIC_PATH_FROM_PROGRAM_ROOT"
    assert pair["caller_chain_complete"] is False
    chain = pair["caller_chain"]
    assert any(step[0] == OperationID("inputs.call.none") for step in chain)
    assert all(len(step) == 6 for step in chain if step)
    assert pair["caller_chain_segments"]["operand_to_pack"] == ()
    assert pair["caller_chain_segments"]["pack_to_consumer"]
    assert result["source_runtime_verified"] is False
    assert result["runtime_identity_verified"] is False
    assert result["value_identity_verified"] is False
    assert result["transformation_authorized"] is False


def test_pair_does_not_join_an_operand_from_another_callers_raw_pack():
    graph, details = input_origin_program()
    require_valid(graph)
    index = ProgramIndex(graph)
    left_op = _operation(graph, details["caller_operations"][0])
    left_use = _use(left_op, UseID("inputs.call.none.raw"))
    wrong_definition, wrong_pack, wrong_operand = _raw_operand(
        graph, details["raw_values"][1])

    result = paired_input_origins(
        index, OwnedUse(left_op.id, left_use.id),
        OwnedUse(wrong_pack.id, wrong_operand.id))

    assert result["pairs"] == ()
    assert "raw_operand_not_paired" in {gap["code"] for gap in result["gaps"]}
    assert wrong_definition.value != details["raw_values"][0]
    assert result["caller_scope_complete"] is False
    assert result["status"] == "PARTIAL"


def test_pair_budget_cursor_keeps_unvisited_pair_dimensions():
    graph, details = input_origin_program()
    require_valid(graph)
    index = ProgramIndex(graph)
    left_op = _operation(graph, OperationID("inputs.middle.invoke.driver"))
    left_use = _use(left_op, UseID("inputs.middle.invoke.raw"))
    _, pack, right_use = _raw_operand(graph, details["raw_values"][0])
    budget = ValidityBudget(1)

    result = paired_input_origins(
        index, OwnedUse(left_op.id, left_use.id), OwnedUse(pack.id, right_use.id),
        accounting=budget)

    assert result["status"] == "TRUNCATED"
    assert result["budget"]["truncated"] is True
    assert result["cursor"] is not None
    assert (result["cursor"].get("left_cursor") is not None
            or result["cursor"].get("right_cursor") is not None)
    assert result["cursor"].get("pair_enumeration_incomplete") is True or (
        "pending_tasks" in result["cursor"])
    assert result["source_runtime_verified"] is False


def test_pair_loop_path_keeps_selected_original_backedge_and_does_not_merge_iterations():
    graph, details = input_origin_program(loop=True)
    require_valid(graph)
    index = ProgramIndex(graph)
    left_op = _operation(graph, OperationID("inputs.middle.invoke.driver"))
    left_use = _use(left_op, UseID("inputs.middle.invoke.raw"))
    loop_definition, loop_pack, loop_operand = _raw_operand(graph, details["loop_raw"])

    result = paired_input_origins(
        index, OwnedUse(left_op.id, left_use.id),
        OwnedUse(loop_pack.id, loop_operand.id))

    assert len(result["pairs"]) == 2
    assert all(pair["raw_definition"] is loop_definition for pair in result["pairs"])
    assert all(any(edge[0] == OperationID("inputs.middle.backedge")
                   for edge in pair["cfg_edges"]["pack_to_consumer"])
               for pair in result["pairs"])
    assert all(any(gap["code"] == "cfg_visit_unselected"
                   for gap in pair["gaps"])
               for pair in result["pairs"])
    assert len({pair["caller_chain_segments"]["operand_to_pack"][0][0]
                for pair in result["pairs"]}) == 2
    assert all(pair["value_identity_verified"] is False
               for pair in result["pairs"])


def test_pair_local_shared_callee_keeps_recursive_outer_context_as_gap():
    graph, details = input_origin_program(loop=True, recursive=True)
    require_valid(graph)
    index = ProgramIndex(graph)
    left_op = _operation(graph, OperationID("inputs.middle.invoke.driver"))
    left_use = _use(left_op, UseID("inputs.middle.invoke.raw"))
    _, loop_pack, loop_operand = _raw_operand(graph, details["loop_raw"])

    result = paired_input_origins(
        index, OwnedUse(left_op.id, left_use.id),
        OwnedUse(loop_pack.id, loop_operand.id))

    assert result["pairs"]
    unresolved = [gap for gap in result["gaps"]
                  if gap["code"] == "raw_pack_caller_context_unresolved"]
    assert unresolved
    assert any(any(step[0] == OperationID("inputs.middle.recursive.call")
                   for step in gap.get("right_calls", ()))
               for gap in unresolved)
    assert result["caller_scope_complete"] is False


def test_origin_route_indexes_are_built_once_and_reused_across_source_and_joint_queries(
        monkeypatch):
    graph, details = input_origin_program()
    require_valid(graph)
    index = ProgramIndex(graph)
    module = importlib.import_module("scar.ir.program.input_origins")
    original_builder = module._build_origin_route_indexes
    builds = []

    def counted_builder(candidate_index):
        builds.append(candidate_index)
        return original_builder(candidate_index)

    monkeypatch.setattr(module, "_build_origin_route_indexes", counted_builder)

    source_view = index.input_origins(
        details["driver_consumer"], details["driver_consumer_use"])
    assert source_view["preparation"]["origin_route_index_cache"] == "BUILT"
    source_counts = source_view["preparation"]["origin_route_index_rows"]
    assert source_counts["operations"] == len(graph.operations)
    assert source_counts["raw_driver_requests"] == len(graph.raw_driver_requests)

    left_op = _operation(graph, OperationID("inputs.middle.invoke.driver"))
    left_use = _use(left_op, UseID("inputs.middle.invoke.raw"))
    _, pack, right_use = _raw_operand(graph, details["raw_values"][0])
    paired = paired_input_origins(
        index, OwnedUse(left_op.id, left_use.id), OwnedUse(pack.id, right_use.id))

    assert paired["preparation"]["origin_route_index_cache"] == "REUSED"
    assert paired["left"]["preparation"]["origin_route_index_cache"] == "REUSED"
    assert paired["right"]["preparation"]["origin_route_index_cache"] == "REUSED"
    assert paired["preparation"]["origin_route_index_rows"] == source_counts
    assert len(builds) == 1
    assert builds[0] is index
