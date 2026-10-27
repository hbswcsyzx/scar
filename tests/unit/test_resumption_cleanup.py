"""C2B suspension retains C1 activation, original anchors and fresh values."""
from dataclasses import replace

import pytest

from scar.ir.program.ids import ControlScopeID, OperationID, UseID, ValueID
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_resumption_graphs import (
    resumption_cleanup_program, resumption_cleanup_invoke_program,
)


def _codes(graph):
    return {issue.code for issue in validate(graph)}


def _change_use(graph, operation, operand, value):
    return replace(graph, operations=tuple(replace(op, uses=tuple(
        replace(use, value=ValueID(value)) if use.id == UseID(operand) else use
        for use in op.uses)) if op.id == OperationID(operation) else op
        for op in graph.operations))


@pytest.mark.parametrize("replace_pending", (False, True))
def test_finally_suspension_keeps_original_pending_and_saved_context(replace_pending):
    graph = resumption_cleanup_program(replace_pending=replace_pending)
    require_valid(graph)
    index = ProgramIndex(graph)
    scope = ControlScopeID("finally.cleanup.scope")
    assert ValueID("finally.landing.pending") in index.cleanup_pending_copies(scope)
    assert ValueID("finally.finish-cleanup.saved-context") in index.cleanup_context_copies(scope)
    assert len(graph.cleanup_enters) == 1
    assert index.cleanup_stack(graph.cleanup_interfaces[0].entry) == ()


def test_replacement_created_before_yield_is_still_fresh_after_resume():
    graph = resumption_cleanup_program(replace_pending=True)
    require_valid(graph)
    assert graph.cleanup_replacements[0].replacement == UseID("finally.replace.replacement")
    # The same pending constructor is not rerun after the temporal edge.
    assert sum(op.id == OperationID("finally.fresh") for op in graph.operations) == 1


def test_old_entry_pending_cannot_masquerade_as_fresh_after_resume():
    graph = _change_use(resumption_cleanup_program(replace_pending=True),
                        "finally.replace", "finally.replace.replacement",
                        "finally.finish-cleanup.pending")
    graph = _change_use(graph, "finally.finish.jump", "finally.finish.jump.0",
                        "finally.finish-cleanup.pending")
    assert "cleanup_replacement_fresh" in _codes(graph)


def test_saved_context_cannot_be_repacked_or_replaced_by_a_pre_cut_value():
    graph = _change_use(resumption_cleanup_program(), "finally.resume", "finally.resume.context",
                        "finally.saved-context")
    assert "unavailable_value" in _codes(graph)


def test_resume_does_not_regain_the_old_cleanup_world():
    graph = _change_use(resumption_cleanup_program(), "finally.resume", "finally.resume.world",
                        "finally.enter.world")
    assert "stale_state" in _codes(graph)


def test_resumed_cleanup_invoke_normal_resumes_and_new_raise_replaces_pending():
    graph = resumption_cleanup_invoke_program()
    require_valid(graph)
    index = ProgramIndex(graph)
    scope = ControlScopeID("finally.cleanup.scope")
    assert ValueID("finally.replace-raise.pending") in index.cleanup_pending_copies(scope)
    assert ValueID("finally.replace-raise.saved-context") in index.cleanup_context_copies(scope)
    assert len(graph.cleanup_enters) == 1
    assert len(graph.cleanup_resumes) == len(graph.cleanup_replacements) == 1
    assert index.use_site(UseID("finally.new-raise.packet")).use.value == ValueID("finally.failed.packet")
    assert index.use_site(UseID("finally.raise-exit.context.out")).use.value == ValueID("finally.raise-exit.detach.after")


@pytest.mark.parametrize("operation,operand,value", (
    ("finally.invoke", "finally.invoke.context", "finally.landing.context"),
    ("finally.raise-replace", "finally.raise-replace.world", "finally.enter.world"),
    ("finally.raise-replace", "finally.raise-replace.context", "finally.landing.attach.after"),
))
def test_resumed_cleanup_invoke_rejects_old_pre_attach_or_pre_failure_states(operation, operand, value):
    graph = _change_use(resumption_cleanup_invoke_program(), operation, operand, value)
    assert "stale_state" in _codes(graph)


def test_resumed_cleanup_invoke_cannot_claim_original_return_as_selected_new_raise():
    graph = _change_use(resumption_cleanup_invoke_program(), "finally.raise-replace",
                        "finally.raise-replace.replacement", "finally.replace-raise.pending")
    # Preserve the actual jump: it selects the fresh Raise token. An action
    # claiming the old Return as its replacement must be refused at this boundary.
    assert "cleanup_corridor_pending" in _codes(graph)
