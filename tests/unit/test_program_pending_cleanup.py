"""Two real temporal cuts retain C1 pending and reach PendingPayload."""
from dataclasses import replace

from scar.ir.program.control import PendingDispatchTerminator, PendingPayload
from scar.ir.program.ids import BlockID, OperationID, UseID, ValueID
from scar.ir.program.model import TerminatorKind
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.resumption import SavedRole, SuspendTerminator, SuspensionFlavor
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_pending_cleanup_graphs import (
    normal_pending_two_cuts_program, pending_cleanup_two_cuts_program,
)


def _codes(graph):
    return {issue.code for issue in validate(graph)}


def _change_use(graph, operation_id, use_id, value_id):
    return replace(graph, operations=tuple(
        replace(operation, uses=tuple(
            replace(use, value=ValueID(value_id)) if use.id == UseID(use_id) else use
            for use in operation.uses)) if operation.id == OperationID(operation_id) else operation
        for operation in graph.operations))


def test_active_c1_pending_payload_crosses_two_cuts_to_the_original_host_raise():
    graph, details = pending_cleanup_two_cuts_program()
    require_valid(graph)

    suspends = [operation.terminator for operation in graph.operations
                if isinstance(operation.terminator, SuspendTerminator)]
    assert len(suspends) == 2
    assert [item.flavor for item in suspends] == [
        SuspensionFlavor.DELEGATION, SuspensionFlavor.YIELD]
    assert len(graph.cleanup_enters) == len(graph.cleanup_replacements) == 1
    second_cut = next(operation.terminator for operation in graph.operations
                      if operation.id == details["second_suspend"])
    assert [slot.role for slot in second_cut.saved] == [
        SavedRole.FRAME_CONTEXT, SavedRole.PENDING_COMPLETION,
        SavedRole.PENDING_COMPLETION, SavedRole.CLEANUP_CONTEXT,
        SavedRole.DELEGATE_REFERENCE]
    assert all(slot.use != UseID("finally.new-raise.packet") for slot in second_cut.saved)
    dispatch = next(operation for operation in graph.operations
                    if operation.terminator is not None
                    and operation.terminator.kind is TerminatorKind.PENDING_DISPATCH)
    assert isinstance(dispatch.terminator, PendingDispatchTerminator)
    raise_edge = next(edge for edge in dispatch.terminator.successors
                      if edge.block == BlockID("finally.raise-exit"))
    assert type(raise_edge.arguments[0]) is PendingPayload
    assert details["helper_raise"].edge.operation == OperationID("finally.invoke")
    assert details["host_packet"].operation == OperationID("finally.raise-exit.op")
    host = next(operation for operation in graph.operations
                 if operation.id == details["host_packet"].operation)
    assert host.terminator.kind is TerminatorKind.RAISE

    index = ProgramIndex(graph)
    unguarded = index.source_binding(details["helper_raise"], details["host_packet"])
    assert unguarded["match"] is not True
    report = index.source_binding(details["helper_raise"], details["host_packet"],
                                  guard=details["helper_raise_guard"])
    assert report["match"] is True
    assert report["native_applicability_verified"] is False
    assert report["runtime_identity_verified"] is False
    assert report["transformation_authorized"] is False


def test_original_return_payload_not_created_after_the_first_cut_crosses_both_cuts():
    graph, details = normal_pending_two_cuts_program()
    require_valid(graph)
    suspends = [operation.terminator for operation in graph.operations
                if isinstance(operation.terminator, SuspendTerminator)]
    assert len(suspends) == 2
    assert all(item.flavor is SuspensionFlavor.YIELD for item in suspends)

    report = ProgramIndex(graph).source_binding(details["expected"], details["actual"])
    assert report["match"] is True
    assert report["native_applicability_verified"] is False
    assert report["runtime_identity_verified"] is False


def test_second_cut_cannot_handoff_the_pre_detach_cleanup_context():
    graph, _ = pending_cleanup_two_cuts_program()
    graph = _change_use(graph, "finally.second.suspend",
                        "finally.second.suspend.context", "finally.second.input.context")
    assert "stale_state" in _codes(graph)


def test_second_cut_cannot_reuse_context_from_before_the_first_cut():
    graph, _ = pending_cleanup_two_cuts_program()
    graph = _change_use(graph, "finally.second.suspend",
                        "finally.second.suspend.saved-context", "finally.saved-context")
    assert "unavailable_value" in _codes(graph)


def test_second_cut_cannot_replace_raise_with_the_old_return_pending_token():
    graph, _ = pending_cleanup_two_cuts_program()
    graph = _change_use(graph, "finally.second.suspend",
                        "finally.second.suspend.replacement", "finally.second.input.pending")
    # The old token selects RETURN while the actual replacement selects RAISE;
    # the canonical pending dispatch rejects the mismatched case set first.
    assert "pending_dispatch_cases" in _codes(graph)


def test_same_typed_injected_packet_cannot_replace_the_helper_raise_source():
    graph, details = pending_cleanup_two_cuts_program()
    graph = _change_use(graph, "finally.new-raise", "finally.new-raise.packet",
                        "finally.landing.sent")
    # The continuation-specific declaration has its own (older) raw→pack
    # check.  Remove only those query declarations here to isolate the generic
    # original-port source_binding result over the unchanged core/C1 graph.
    graph = replace(graph, protocol_scopes=(), protocol_operations=(),
                    protocol_call_inputs=(), protocol_result_consumers=())
    require_valid(graph)
    report = ProgramIndex(graph).source_binding(
        details["helper_raise"], details["host_packet"],
        guard=details["helper_raise_guard"])
    assert report["match"] is not True
