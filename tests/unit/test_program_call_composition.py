"""A returned source stays connected when passed into another original call."""
import pytest

from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid
from tests.fixtures.program_call_composition_graphs import (
    call_composition_program, distinct_call_composition_program,
    duplicate_argument_composition_program, loop_call_composition_program,
)


def _index(graph):
    require_valid(graph)
    return ProgramIndex(graph)


def _unproved_authority(report):
    assert report["source_runtime_verified"] is False
    assert report["runtime_identity_verified"] is False
    assert report["transformation_authorized"] is False


def test_returned_source_passed_again_to_same_helper_reaches_its_internal_consumer():
    graph, details = call_composition_program()
    assert len(details["root_calls"]) == 2
    index = _index(graph)
    report = index.source_binding(details["expected"], details["actual"])
    assert report["match"] is True, report
    _unproved_authority(report)


@pytest.mark.parametrize("calls", ("single", "chain"))
def test_return_then_two_nested_helper_entries_reach_the_actual_terminal_use(calls):
    graph, details = call_composition_program(depth=2, calls=calls)
    report = _index(graph).source_binding(details["expected"], details["actual"], budget=50000)
    assert report["match"] is True, report
    assert report["routes"] and all(route["match"] is True for route in report["routes"])
    _unproved_authority(report)


def test_sibling_sources_keep_both_routes_and_a_single_good_route_is_not_success():
    graph, details = call_composition_program(calls="siblings")
    report = _index(graph).source_binding(details["expected"], details["actual"], budget=50000)
    assert report["match"] is None, report
    assert len(report["routes"]) == 2, report
    assert {route["match"] for route in report["routes"]} == {True, False}, report
    assert {route["context"][0][0] for route in report["routes"]} == set(details["root_calls"])
    _unproved_authority(report)


@pytest.mark.parametrize("wrong_actual", (False, True))
def test_return_of_one_helper_is_checked_against_the_exact_actual_of_another(wrong_actual):
    graph, details = distinct_call_composition_program(wrong_actual=wrong_actual)
    index = _index(graph)
    available = index.source_binding(details["expected"], details["available_actual"])
    assert available["match"] is True, available
    report = index.source_binding(details["expected"], details["actual"], budget=50000)
    if wrong_actual:
        # x is still available above; target actually receives b=id(y).
        assert report["match"] is not True, report
    else:
        assert report["match"] is True, report
    _unproved_authority(report)


def test_an_opaque_result_is_a_source_but_does_not_prove_copy_of_its_input():
    graph, details = distinct_call_composition_program(opaque=True)
    index = _index(graph)
    input_report = index.source_binding(details["expected"], details["actual"], budget=50000)
    result_report = index.source_binding(details["opaque_expected"], details["actual"], budget=50000)
    assert input_report["match"] is not True, input_report
    assert result_report["match"] is True, result_report
    _unproved_authority(input_report)
    _unproved_authority(result_report)


def test_duplicate_actual_uses_seed_both_formals_before_branch_merge():
    graph, details = duplicate_argument_composition_program()
    index = _index(graph)
    target = next(operation for operation in graph.operations if operation.id == details["target"])
    assert target.uses[0].id != target.uses[1].id
    assert target.uses[0].value == target.uses[1].value
    report = index.source_binding(details["expected"], details["actual"], budget=50000)
    assert report["match"] is True, report
    _unproved_authority(report)


def test_opposite_cfg_guards_share_one_budget_without_reusing_a_good_branch_proof():
    graph, details = duplicate_argument_composition_program(duplicate=False)
    index = _index(graph)
    accounting = ValidityBudget(50000)
    context = ConnectionContext(graph, index=index, budget=accounting)
    good = context.bind(details["expected"], details["actual"], guard=details["guards"][0])
    used_after_good = accounting.used
    bad = context.bind(details["expected"], details["actual"], guard=details["guards"][1])
    unguarded = context.bind(details["expected"], details["actual"])
    assert good["match"] is True, good
    assert bad["match"] is False, bad
    assert unguarded["match"] is None, unguarded
    assert accounting.used > used_after_good > 0
    assert accounting.truncated is False
    for report in (good, bad, unguarded):
        _unproved_authority(report)


@pytest.mark.parametrize("stale", (False, True))
def test_loop_source_is_not_replaced_by_a_prior_return_on_the_next_helper_entry(stale):
    graph, details = loop_call_composition_program(stale=stale)
    report = _index(graph).source_binding(details["expected"], details["actual"], budget=50000)
    if stale:
        assert report["match"] is not True, report
    else:
        assert report["match"] is True, report
    _unproved_authority(report)


def test_downward_call_composition_preserves_unknown_and_cursor_at_budget_one():
    graph, details = call_composition_program(depth=2)
    report = _index(graph).source_binding(details["expected"], details["actual"], budget=1)
    assert report["match"] is None, report
    assert report["cursor"] is not None, report
    assert report["budget"]["used"] == 1
    assert report["budget"]["truncated"] is True
    _unproved_authority(report)
