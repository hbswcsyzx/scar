"""Known-call copying does not collapse completion kinds or current state."""
import pytest

from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.program.model import CompletionResult, ExitKind
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid
from tests.fixtures.program_call_return_state_graphs import call_return_state_program


def _fixture(**options):
    graph, details = call_return_state_program(**options)
    require_valid(graph)
    return graph, details, ProgramIndex(graph)


def _binding(index, source, target, **options):
    report = index.source_binding(source, target, **options)
    assert report["source_runtime_verified"] is False
    assert report["runtime_identity_verified"] is False
    assert report["transformation_authorized"] is False
    return report


def test_original_invoke_reverses_completion_kinds_and_keeps_slot_formal_positions_distinct():
    graph, details, _ = _fixture()
    call = details["callers"]["a"]
    failure, normal = call["operation"].terminator.successors
    assert (failure.kind, normal.kind) == (ExitKind.RAISE, ExitKind.NORMAL)
    assert failure.arguments[0] in {use.id for use in call["operation"].uses}
    assert normal.arguments[0] in {use.id for use in call["operation"].uses}
    assert failure.arguments[1:] == normal.arguments[1:] == (
        CompletionResult(2), CompletionResult(0), CompletionResult(1))
    assert call["raise_formals"][1].location == details["world"]
    assert call["normal_formals"][3].location == details["world"]
    assert not graph.protocol_operations  # Source relations do not require a family label.


@pytest.mark.parametrize("ordinal,role", ((0, "payload"), (3, "world"), (4, "context")))
def test_normal_completion_copies_only_its_exact_original_input_slot(ordinal, role):
    _, details, index = _fixture()
    call = details["callers"]["a"]
    report = _binding(index, call["arguments"][ordinal], call["consumers"][ExitKind.NORMAL][role])
    assert report["match"] is True
    assert report["routes"]


def test_raise_world_write_cannot_be_matched_as_the_old_input_version():
    _, details, index = _fixture()
    call = details["callers"]["a"]
    report = _binding(index, call["arguments"][3], call["consumers"][ExitKind.RAISE]["world"])
    assert report["match"] is not True


def test_raise_preserves_the_other_domain_at_its_reordered_completion_slot():
    _, details, index = _fixture()
    call = details["callers"]["a"]
    report = _binding(index, call["arguments"][4], call["consumers"][ExitKind.RAISE]["context"])
    assert report["match"] is True
    assert call["raise_context"].result.index == 0


def test_internal_written_state_lifts_through_the_single_exact_raise_caller():
    _, details, index = _fixture()
    call = details["callers"]["a"]
    report = _binding(index, details["raise_world"], call["consumers"][ExitKind.RAISE]["world"])
    assert report["match"] is True
    assert report["routes"]


def test_internal_raise_state_is_not_relabelled_as_the_normal_state():
    _, details, index = _fixture()
    call = details["callers"]["a"]
    report = _binding(index, details["raise_world"], call["consumers"][ExitKind.NORMAL]["world"])
    assert report["match"] is not True


def test_exact_caller_raise_world_port_uses_completion_slot_not_landing_ordinal():
    _, details, index = _fixture()
    call = details["callers"]["a"]
    report = _binding(index, call["raise_world"], call["consumers"][ExitKind.RAISE]["world"])
    assert report["match"] is True
    assert call["raise_world"].result.index == 2
    assert call["raise_formals"][1].origin.index == 1


def test_returning_the_same_reference_does_not_preserve_a_prewrite_state_snapshot():
    graph, details, index = _fixture(normal_write=True)
    call = details["callers"]["a"]
    normal = call["consumers"][ExitKind.NORMAL]
    assert _binding(index, call["arguments"][0], normal["payload"])["match"] is True
    assert _binding(index, call["arguments"][3], normal["world"])["match"] is not True
    context = ConnectionContext(graph, index=index, budget=ValidityBudget(4096))
    current = context.current(call["world_site"], normal["payload"])
    assert current["match"] is not True
    assert current["source_runtime_verified"] is False


def test_different_caller_inputs_are_not_unioned_into_one_callee_seed_set():
    _, details, index = _fixture(two_callers=True)
    a, b = (details["callers"][label] for label in ("a", "b"))
    target = b["consumers"][ExitKind.NORMAL]["payload"]
    assert _binding(index, a["arguments"][0], target)["match"] is False
    assert _binding(index, b["arguments"][0], target)["match"] is True


def test_internal_source_with_multiple_callers_keeps_the_missing_frame_context():
    _, details, index = _fixture(two_callers=True)
    call = details["callers"]["a"]
    report = _binding(index, details["raise_world"], call["consumers"][ExitKind.RAISE]["world"])
    assert report["match"] is None
    assert report["gaps"]


def test_tiny_shared_budget_cannot_certify_a_partially_scanned_callee():
    _, details, index = _fixture()
    call = details["callers"]["a"]
    report = _binding(index, details["raise_world"], call["consumers"][ExitKind.RAISE]["world"], budget=1)
    assert report["match"] is None
    assert report["gaps"] and report["cursor"]
