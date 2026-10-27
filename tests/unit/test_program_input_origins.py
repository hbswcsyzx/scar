from dataclasses import replace

from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.program.input_origins import _input_origins, input_origins
from scar.ir.program.ids import OperationID, UseID
from scar.ir.program.model import (
    LiteralEvaluation, LiteralOrigin, OperationResult, ProtocolValue,
    ReferenceValue,
)
from scar.ir.literals import PythonLiteral
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid
from tests.fixtures.program_input_origin_graphs import input_origin_program


def _entry(graph, operation_id, use_id):
    operation = next(row for row in graph.operations if row.id == operation_id)
    return next(row for row in operation.uses if row.id == use_id)


def _codes(view):
    return {row["code"] for row in view["gaps"]}


def test_two_layer_call_invoke_routes_keep_none_and_non_none_callers_separate():
    graph, details = input_origin_program()
    require_valid(graph)

    view = input_origins(graph, details["driver_consumer"],
                         details["driver_consumer_use"])

    assert view["consumer"]["operation"].id == details["driver_consumer"]
    assert view["consumer"]["use"] is _entry(
        graph, details["driver_consumer"], details["driver_consumer_use"])
    assert len(view["recipes"]) == 2
    assert view["caller_scope"] == "SUPPLIED_STATIC_CALLERS_ONLY"
    assert view["caller_scope_complete"] is False
    assert view["source_runtime_verified"] is False
    assert view["runtime_identity_verified"] is False
    assert view["value_identity_verified"] is False
    assert view["transformation_authorized"] is False

    none_pack = next(row for row in graph.raw_driver_requests
                     if row.value == details["raw_values"][0])
    value_pack = next(row for row in graph.raw_driver_requests
                      if row.value == details["raw_values"][1])
    none_recipe = next(recipe for recipe in view["recipes"]
                       if recipe["leaf"].id == none_pack.value)
    value_recipe = next(recipe for recipe in view["recipes"]
                        if recipe["leaf"].id == value_pack.value)

    assert type(none_recipe["leaf"]) is ProtocolValue
    assert type(value_recipe["leaf"]) is ProtocolValue
    assert type(none_recipe["origin"]) is OperationResult
    assert type(value_recipe["origin"]) is OperationResult
    assert [step["call_kind"] for step in none_recipe["path"]
            if step["kind"] == "CALL_ACTUAL_TO_FORMAL"] == ["CALL", "INVOKE"]
    assert [step["call_kind"] for step in value_recipe["path"]
            if step["kind"] == "CALL_ACTUAL_TO_FORMAL"] == ["CALL", "INVOKE"]
    assert [step["ordinal"] for step in none_recipe["path"]
            if step["kind"] == "CALL_ACTUAL_TO_FORMAL"] == [0, 0]
    assert [step["ordinal"] for step in value_recipe["path"]
            if step["kind"] == "CALL_ACTUAL_TO_FORMAL"] == [0, 0]
    assert none_recipe["freshness"] is True
    assert value_recipe["freshness"] is True
    assert none_recipe["raw_requests"][0]["definition"] is none_pack
    assert value_recipe["raw_requests"][0]["definition"] is value_pack

    none_operand = none_recipe["raw_requests"][0]["operands"][0]["use"]
    value_operand = value_recipe["raw_requests"][0]["operands"][0]["use"]
    values = {row.id: row for row in graph.values}
    assert type(values[none_operand.value]) is ReferenceValue
    assert type(values[none_operand.value].origin) is LiteralOrigin
    assert values[none_operand.value].origin.value is None
    assert type(values[value_operand.value]) is ReferenceValue
    assert type(values[value_operand.value].origin) is OperationResult
    assert values[value_operand.value].origin.operation == details["make_operation"]
    assert "static_call_occurrence_unlinked" in _codes(view)


def test_reference_none_literal_is_a_leaf_only_for_the_exact_owned_use():
    graph, details = input_origin_program()
    raw_row = graph.raw_driver_requests[0]
    operand = raw_row.operands[0]
    operation_id = next(operation.id for operation in graph.operations
                        if any(use.id == operand for use in operation.uses))

    view = input_origins(graph, operation_id, operand)

    assert len(view["recipes"]) == 1
    recipe, = view["recipes"]
    assert recipe["kind"] == "LITERAL_ORIGIN"
    assert recipe["origin"].value is None
    assert recipe["leaf"].id == details["none_value"]
    assert recipe["source_runtime_verified"] is False


def test_loop_backedge_keeps_prior_raw_producer_and_dynamic_visit_gap():
    graph, details = input_origin_program(loop=True)
    require_valid(graph)

    view = input_origins(graph, details["driver_consumer"],
                         details["driver_consumer_use"])

    loop_recipe = next(recipe for recipe in view["recipes"]
                       if recipe["leaf"].id == details["loop_raw"])
    assert type(loop_recipe["origin"]) is OperationResult
    assert loop_recipe["origin"].operation == OperationID("inputs.middle.rawpack.loop")
    assert any(step["kind"] == "CFG_COPY"
               and step["operation"].id == OperationID("inputs.middle.backedge")
               for step in loop_recipe["path"])
    assert "cfg_visit_unselected" in {row["code"] for row in loop_recipe["gaps"]}
    assert loop_recipe["freshness_oracle"] == "ProtocolFlow.forwards"
    assert loop_recipe["value_identity_verified"] is False


def test_static_recursion_is_finite_and_keeps_an_explicit_cycle_gap():
    graph, details = input_origin_program(recursive=True, second_caller=False)
    require_valid(graph)

    view = input_origins(graph, details["driver_consumer"],
                         details["driver_consumer_use"])

    assert view["status"] == "PARTIAL"
    assert "static_route_cycle" in _codes(view)
    assert view["caller_scope_complete"] is False
    assert any(recipe["kind"] == "STATIC_CYCLE" for recipe in view["recipes"])


def test_direct_call_layer_and_budget_cursor_preserve_pending_work():
    graph, details = input_origin_program(invoke_middle=False)
    require_valid(graph)

    direct = input_origins(graph, details["driver_consumer"],
                           details["driver_consumer_use"])
    assert len(direct["recipes"]) == 2
    assert all([step["call_kind"] for step in recipe["path"]
                if step["kind"] == "CALL_ACTUAL_TO_FORMAL"] == ["CALL", "CALL"]
               for recipe in direct["recipes"])

    truncated = input_origins(graph, details["driver_consumer"],
                              details["driver_consumer_use"], budget=1)
    assert truncated["status"] == "TRUNCATED"
    assert truncated["cursor"] is not None
    assert truncated["budget"]["limit"] == 1
    assert truncated["budget"]["truncated"] is True
    assert truncated["cursor"]["pending_tasks"] >= 1


def test_unknown_consumer_use_is_not_repaired_from_equal_values():
    graph, details = input_origin_program()
    try:
        input_origins(graph, details["driver_consumer"], UseID("inputs.not-owned"))
    except KeyError:
        pass
    else:
        raise AssertionError("unknown UseID must not be inferred by ValueID equality")


def test_raw_operand_candidate_is_charged_before_it_is_added_to_a_recipe():
    graph, details = input_origin_program()
    caller = next(row for row in graph.operations
                  if row.id == details["caller_operations"][0])
    use_id = UseID("inputs.call.none.raw")

    complete = input_origins(graph, caller.id, use_id)
    raw_operand_cost = complete["budget"]["costs"]["raw_operands"]
    assert raw_operand_cost == 1
    budget_limit = complete["budget"]["used"] - raw_operand_cost
    assert budget_limit > 0

    truncated = input_origins(graph, caller.id, use_id, budget=budget_limit)

    assert truncated["status"] == "TRUNCATED"
    assert truncated["cursor"]["phase"] == "raw_request_operands"
    assert truncated["cursor"]["pending_raw_operands"] == 1
    recipe, = truncated["recipes"]
    assert recipe["raw_requests"][0]["operands"] == ()
    assert truncated["budget"]["costs"]["raw_operands"] == 0


def test_literal_evaluation_candidate_is_charged_before_it_is_added():
    graph, details = input_origin_program()
    evaluation = LiteralEvaluation(
        OperationResult(details["make_operation"], 0),
        PythonLiteral.from_python(None, exact=True))
    graph = replace(graph, literal_evaluations=(evaluation,))
    require_valid(graph)
    caller = next(row for row in graph.operations
                  if row.id == details["caller_operations"][1])
    use_id = UseID("inputs.call.value.payload")

    complete = input_origins(graph, caller.id, use_id)
    assert complete["budget"]["costs"]["literal_evaluations"] == 1
    budget_limit = complete["budget"]["used"] - 1
    truncated = input_origins(graph, caller.id, use_id, budget=budget_limit)

    assert truncated["status"] == "TRUNCATED"
    assert truncated["cursor"]["phase"] == "literal_evaluations"
    assert truncated["cursor"]["pending_literal_evaluations"] == 1
    recipe, = truncated["recipes"]
    assert recipe["literal_evaluations"] == ()


def test_prevalidated_private_entry_reuses_program_index_and_shared_accounting(monkeypatch):
    graph, details = input_origin_program()
    require_valid(graph)
    index = ProgramIndex(graph)
    caller = next(row for row in graph.operations
                  if row.id == details["caller_operations"][0])
    accounting = ValidityBudget(256)

    def forbidden_init(*args, **kwargs):
        raise AssertionError("private source query must not rebuild ProgramIndex")

    monkeypatch.setattr(ProgramIndex, "__init__", forbidden_init)
    view = _input_origins(index, caller.id, UseID("inputs.call.none.raw"),
                          accounting=accounting)

    assert view["consumer"]["operation"] is caller
    assert view["budget"]["used"] == accounting.used
    assert accounting.used > 0


def test_public_entry_builds_one_program_index(monkeypatch):
    graph, details = input_origin_program()
    require_valid(graph)
    original_init = ProgramIndex.__init__
    calls = []

    def counted_init(self, selected_graph):
        calls.append(selected_graph)
        original_init(self, selected_graph)

    monkeypatch.setattr(ProgramIndex, "__init__", counted_init)
    view = input_origins(graph, details["driver_consumer"],
                         details["driver_consumer_use"])

    assert calls == [graph]
    assert view["consumer"]["operation"].id == details["driver_consumer"]
