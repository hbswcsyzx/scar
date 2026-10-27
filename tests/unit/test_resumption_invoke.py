from scar.ir.program.control import ProtocolValueKind as P
from scar.ir.program.ids import BlockID, OperationID, UseID, ValueID
from scar.ir.program.model import CompletionResult, ProtocolValue, StateVersionValue
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.resumption import SavedRole, SuspendTerminator
from scar.ir.program.validation import require_valid

from tests.fixtures.program_resumption_invoke_graphs import (
    direct_call_to_resumable_body_program, direct_invoke_to_resumable_body_program,
    issue_codes, old_context_at_invoke_program, old_world_after_invoke_program,
    partial_state_invoke_program, precut_context_after_suspension_program,
    precut_world_after_suspension_program, suspended_partial_state_invoke_program,
)


def _operation(graph, name):
    return next(operation for operation in graph.operations
                if operation.id == OperationID(name))


def _value(graph, name):
    return next(value for value in graph.values if value.id == ValueID(name))


def test_invoke_partial_poststate_forwards_current_context_and_caller_per_edge():
    graph = partial_state_invoke_program()
    require_valid(graph)

    operation = _operation(graph, "invoke.call")
    assert operation.effects_complete is True
    assert operation.invoke_arguments == (UseID("invoke.call.world"),)
    assert tuple(signature.kind.value for signature in operation.completions) == ("NORMAL", "RAISE")
    assert tuple(len(signature.types) for signature in operation.completions) == (2, 2)

    normal, failure = operation.terminator.successors
    assert normal.arguments[0] == CompletionResult(0)
    assert normal.arguments[3] == CompletionResult(1)
    assert failure.arguments[1] == CompletionResult(0)
    assert failure.arguments[2] == CompletionResult(1)
    assert normal.arguments[2] == UseID("invoke.call.normal.context")
    assert failure.arguments[3] == UseID("invoke.call.failure.context")
    assert normal.arguments[1] == UseID("invoke.call.normal.caller")
    assert failure.arguments[0] == UseID("invoke.call.failure.caller")
    forwarded = (normal.arguments[1], normal.arguments[2], failure.arguments[0], failure.arguments[3])
    assert len(forwarded) == len(set(forwarded))

    normal_world = _value(graph, "invoke.normal.world")
    failure_world = _value(graph, "invoke.failure.world")
    assert isinstance(normal_world, StateVersionValue)
    assert isinstance(failure_world, StateVersionValue)
    assert normal_world.location == failure_world.location
    assert normal_world.origin.block == BlockID("invoke.normal")
    assert failure_world.origin.block == BlockID("invoke.failure")
    assert isinstance(_value(graph, "invoke.normal.x"), type(_value(graph, "invoke.x")))
    assert isinstance(_value(graph, "invoke.failure.packet"), ProtocolValue)
    assert _value(graph, "invoke.failure.packet").protocol is P.EXCEPTION_PACKET

    index = ProgramIndex(graph)
    assert index.drive_context(BlockID("invoke.normal")).caller == ValueID("invoke.normal.caller")
    assert index.drive_context(BlockID("invoke.failure")).caller == ValueID("invoke.failure.caller")


def test_invoke_normal_exit_cannot_use_preinvoke_world():
    codes = issue_codes(old_world_after_invoke_program())
    assert "stale_state" in codes or "unavailable_value" in codes


def test_invoke_cannot_forward_pre_attach_context_as_current_context():
    codes = issue_codes(old_context_at_invoke_program())
    assert "stale_state" in codes or "unavailable_value" in codes


def test_resumable_body_is_not_an_ordinary_call_callee():
    assert "resumption_direct_call" in issue_codes(direct_call_to_resumable_body_program())


def test_resumable_body_is_not_an_invoke_callee():
    assert "resumption_direct_call" in issue_codes(direct_invoke_to_resumable_body_program())


def test_suspension_restores_state_before_partial_invoke_completions():
    graph = suspended_partial_state_invoke_program()
    require_valid(graph)
    region = graph.regions[0]
    assert region.entry == BlockID("invoke.start")
    suspend = _operation(graph, "invoke.start.suspend")
    assert isinstance(suspend.terminator, SuspendTerminator)
    assert tuple(slot.role for slot in suspend.terminator.saved) == (
        SavedRole.FRAME_CONTEXT, SavedRole.VALUE)
    assert suspend.terminator.successors[0].block == BlockID("invoke.entry")
    landing = next(block for block in region.blocks if block.id == BlockID("invoke.entry"))
    assert landing.operations[0] == OperationID("invoke.resume.attach")

    invoke = _operation(graph, "invoke.call")
    uses = {use.id: use for use in invoke.uses}
    assert tuple(uses[use_id].value for use_id in invoke.invoke_arguments) == (
        ValueID("invoke.resume.world"), ValueID("invoke.resume.x"),
        ValueID("invoke.resume.sent"))
    index = ProgramIndex(graph)
    assert index.drive_context(BlockID("invoke.normal")).caller == ValueID("invoke.normal.caller")
    assert index.drive_context(BlockID("invoke.failure")).caller == ValueID("invoke.failure.caller")


def test_pre_cut_world_or_context_is_unavailable_after_suspension():
    for graph in (precut_world_after_suspension_program(),
                  precut_context_after_suspension_program()):
        assert "unavailable_value" in issue_codes(graph)
