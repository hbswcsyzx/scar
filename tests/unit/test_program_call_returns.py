"""Known-call copy relations retain original producers and use ports."""
import pytest

from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid
from tests.fixtures.program_call_return_graphs import (
    call_return_program, multi_return_program, recursive_return_program,
    repeated_return_program,
)


def _index(graph):
    # Every positive/negative relation below starts from a usable canonical
    # graph. False means no must-copy relation, not unequal Python objects.
    require_valid(graph)
    return ProgramIndex(graph)


def _unproved_authority(report):
    assert report["source_runtime_verified"] is False
    assert report["runtime_identity_verified"] is False
    assert report["transformation_authorized"] is False


def test_known_identity_call_returns_the_original_entry_reference():
    graph, details = call_return_program()
    index = _index(graph)
    report = ConnectionContext(graph, index=index).bind(details["expected"], details["actual"])
    assert report["match"] is True, report
    _unproved_authority(report)


def test_identity_call_preserves_the_original_unchanged_state_port():
    graph, details = call_return_program()
    report = _index(graph).source_binding(details["state_expected"], details["state_actual"])
    assert report["match"] is True, report
    _unproved_authority(report)


@pytest.mark.parametrize("calls,depth", (("chain", 1), ("single", 2), ("chain", 2)))
def test_serial_and_nested_calls_keep_their_exact_return_composition(calls, depth):
    graph, details = call_return_program(calls=calls, depth=depth)
    index = _index(graph)
    assert len(details["calls"]) == (2 if calls == "chain" else 1) + depth - 1
    report = index.source_binding(details["expected"], details["actual"], budget=50000)
    assert report["match"] is True, report
    _unproved_authority(report)


def test_two_sibling_calls_do_not_exchange_their_helper_entry_sources():
    graph, details = call_return_program(calls="siblings")
    index = _index(graph)
    assert len(details["root_calls"]) == 2
    wrong = index.source_binding(details["expected"], details["actual"], budget=50000)
    correct = index.source_binding(details["other_expected"], details["actual"], budget=50000)
    assert wrong["match"] is False, wrong
    assert correct["match"] is True, correct
    _unproved_authority(wrong)


def test_a_returned_value_can_be_the_source_of_the_next_sibling_call():
    graph, details = call_return_program(calls="chain")
    report = _index(graph).source_binding(details["result_sources"][0], details["actual"], budget=50000)
    assert report["match"] is True, report


def test_mutation_keeps_the_reference_copy_but_does_not_copy_state_content():
    graph, details = call_return_program(mutate=True)
    index = _index(graph)
    reference = index.source_binding(details["expected"], details["actual"], budget=50000)
    state = index.source_binding(details["state_expected"], details["state_actual"], budget=50000)
    assert reference["match"] is True, reference
    assert state["match"] is False, state
    _unproved_authority(reference)


def test_all_original_return_sites_must_copy_the_same_input():
    graph, details = multi_return_program()
    index = _index(graph)
    assert len(details["terminals"]) == 2
    report = index.source_binding(details["expected"], details["actual"], budget=50000)
    assert report["match"] is True, report


def test_one_different_original_return_cannot_be_selected_away_as_a_good_copy():
    graph, details = multi_return_program(mixed=True)
    index = _index(graph)
    assert len(details["terminals"]) == 2
    report = index.source_binding(details["expected"], details["actual"], budget=50000)
    assert report["match"] is None, report
    assert report["gaps"], report


@pytest.mark.parametrize("stale", (False, True))
def test_source_reexecution_distinguishes_fresh_from_prior_returned_incarnation(stale):
    graph, details = repeated_return_program(stale=stale)
    report = _index(graph).source_binding(details["expected"], details["actual"], budget=50000)
    assert report["match"] is (not stale), report
    _unproved_authority(report)


@pytest.mark.parametrize("depth", (1, 2))
def test_exact_internal_source_is_exported_through_a_unique_caller_chain(depth):
    graph, details = call_return_program(depth=depth, internal=True)
    index = _index(graph)
    source, = details["helper_sources"]
    report = index.source_binding(source, details["actual"], budget=50000)
    assert report["match"] is True, report
    _unproved_authority(report)


def test_internal_source_with_two_possible_callers_needs_an_invocation_context():
    graph, details = call_return_program(calls="siblings", internal=True)
    source, = details["helper_sources"]
    report = _index(graph).source_binding(source, details["actual"], budget=50000)
    assert report["match"] is None, report
    assert report["gaps"], report


def test_recursive_return_path_stays_explicitly_unresolved():
    graph, details = recursive_return_program()
    index = _index(graph)
    assert len(details["terminals"]) == 2
    report = index.source_binding(details["expected"], details["actual"], budget=50000)
    assert report["match"] is None, report
    assert report["gaps"], report


def test_no_actual_return_frontier_is_not_an_empty_all_true_proof():
    graph, details = multi_return_program(no_terminal=True)
    index = _index(graph)
    assert details["terminals"] == ()
    report = index.source_binding(details["expected"], details["actual"], budget=50000)
    assert report["match"] is None, report
    assert report["gaps"], report


def test_shared_small_budget_returns_unknown_and_an_unfinished_cursor():
    graph, details = call_return_program(depth=2, calls="chain")
    report = _index(graph).source_binding(details["expected"], details["actual"], budget=1)
    assert report["match"] is None, report
    assert report["cursor"] is not None, report
    assert report["budget"]["used"] == 1
    assert report["budget"]["truncated"] is True
    _unproved_authority(report)
