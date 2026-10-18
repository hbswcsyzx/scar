"""Returned state enters the next helper only through its exact current actual."""
import pytest

from scar.ir.program.model import ExitKind
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid
from tests.fixtures.program_call_composition_state_graphs import call_composition_state_program


def _program(**options):
    graph, details = call_composition_state_program(**options)
    require_valid(graph)
    return details, ProgramIndex(graph)


def _binding(index, source, actual):
    report = index.source_binding(source, actual)
    assert report["source_runtime_verified"] is False
    assert report["runtime_identity_verified"] is False
    assert report["transformation_authorized"] is False
    return report


def test_internal_written_raise_state_exports_then_enters_the_second_helper():
    details, index = _program()
    assert tuple(edge.kind for edge in details["h1"]["operation"].terminator.successors) == (
        ExitKind.RAISE, ExitKind.NORMAL)
    assert details["h1"]["raise_world"].result.index == 2
    report = _binding(index, details["new_raise_world"], details["targets"]["world"])
    assert report["match"] is True, report
    assert report["routes"]


def test_old_world_availability_cannot_substitute_for_the_second_helpers_written_actual():
    details, index = _program()
    assert details["calls"]["raise"]["arguments"][0].operation != details["old_world"].operation
    report = _binding(index, details["old_world"], details["targets"]["world"])
    assert report["match"] is not True


def test_both_first_completion_routes_preserve_the_independent_domain_on_entry_to_h2():
    details, index = _program(branches=("normal", "raise"))
    assert len(details["calls"]) == 2
    report = _binding(index, details["internal_context"], details["targets"]["context"])
    assert report["match"] is True, report
    assert report["routes"]


def test_mixed_preserved_and_written_world_routes_do_not_collapse_to_one_positive_input():
    details, index = _program(branches=("normal", "raise"))
    report = _binding(index, details["old_world"], details["targets"]["world"])
    assert report["match"] is not True


def test_preserved_normal_world_can_be_copied_to_the_next_helpers_actual_and_formal():
    details, index = _program(branches=("normal",))
    report = _binding(index, details["old_world"], details["targets"]["world"])
    assert report["match"] is True, report


@pytest.mark.parametrize("invoke", (False, True), ids=("CALL", "INVOKE"))
@pytest.mark.parametrize("ordinal,domain", ((0, "world"), (1, "context")))
def test_second_helpers_future_result_cannot_supply_its_own_entry(invoke, ordinal, domain):
    details, index = _program(invoke=invoke)
    future = details["calls"]["raise"]["sources"][ordinal]
    report = _binding(index, future, details["targets"][domain])
    assert report["match"] is not True
