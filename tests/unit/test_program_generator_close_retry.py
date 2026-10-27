"""Two static close calls and original-state retry, not captured activations."""
from dataclasses import replace

from scar.ir.program.drivers import BodyResume
from scar.ir.program.model import CompletionResult, ExitKind, StateVersionValue, TerminatorKind
from scar.ir.program.protocols import OutcomeAdapter
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.resumption import ResumeSlotKind, SuspendTerminator
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_generator_close_retry_graphs import two_close_requests_program


def _operation(graph, identity):
    return next(operation for operation in graph.operations if operation.id == identity)


def _codes(graph):
    return {issue.code for issue in validate(graph)}


def _change_use(graph, operation_id, use_id, value):
    return replace(graph, operations=tuple(replace(operation, uses=tuple(
        replace(use, value=value) if use.id == use_id else use for use in operation.uses))
        if operation.id == operation_id else operation for operation in graph.operations))


def test_two_actual_calls_retry_the_new_cut_with_the_same_forwarded_instance_and_current_raise_states():
    graph, details = two_close_requests_program()
    require_valid(graph)
    index = ProgramIndex(graph)
    first_call, second_call = (_operation(graph, identity) for identity in details["calls"])
    assert first_call.callee != second_call.callee
    assert tuple(edge.kind for edge in first_call.terminator.successors) == (ExitKind.NORMAL, ExitKind.RAISE)
    caller = index.regions[graph.root]
    raised = next(block for block in caller.blocks if block.id == first_call.terminator.successors[1].block)
    assert second_call.id in raised.operations
    assert index.use_site(first_call.invoke_arguments[0]).use.value == details["caller_instance"]
    assert index.use_site(details["forward_instance"]).use.value == details["caller_instance"]
    assert first_call.invoke_arguments[0] != details["forward_instance"]
    assert first_call.terminator.successors[1].arguments[-1] == details["forward_instance"]
    assert index.use_site(second_call.invoke_arguments[0]).use.value == raised.arguments[-1] == details["retry_instance"]
    assert {index.use_site(identity).use.value for identity in second_call.invoke_arguments
            if isinstance(index.values[index.use_site(identity).use.value], StateVersionValue)} == set(
                details["first_post_states"])
    assert set(details["first_post_states"]).isdisjoint(details["initial_states"])
    assert details["raws"][0] != details["raws"][1]
    first = index.body_drive(details["first"]["drive"])
    second = index.body_drive(details["second"]["drive"])
    assert isinstance(first.target, BodyResume) and isinstance(second.target, BodyResume)
    assert first.target.suspend != second.target.suspend == details["second_cut"]
    assert second.target.successor == 1
    cut = _operation(graph, second.target.suspend)
    assert isinstance(cut.terminator, SuspendTerminator)
    ingress = cut.terminator.successors[second.target.successor]
    assert tuple(slot.kind for slot in ingress.inputs if slot.location is None) == (ResumeSlotKind.THROWN_PACKET,)
    assert len(graph.resumable_bodies) == 1
    assert {interface.body for interface in graph.driver_interfaces} == {details["shared_body"]}
    first_commit = index.body_publication(details["first"]["publication"]).commit
    second_commit = index.body_publication(details["second"]["publication"]).commit
    first_owner = index.use_site(first_commit.instance).use.value
    second_owner = index.use_site(second_commit.instance).use.value
    assert not index.lifecycle_after(first_commit.operation).terminal.is_finished(first_owner)
    assert index.lifecycle_after(second_commit.operation).terminal.is_finished(second_owner)
    release = index.terminal_release_publication(details["second"]["release"])
    assert release.point.terminal.is_finished(release.owner.use.value)
    assert _operation(graph, details["first"]["source"]).terminator.kind is TerminatorKind.SUSPEND
    assert _operation(graph, details["first"]["normal_terminal"]).terminator.kind is TerminatorKind.RETURN
    assert _operation(graph, details["second"]["source"]).terminator.kind is TerminatorKind.RAISE
    assert {row.operation for row in graph.protocol_operations if type(row.contract) is OutcomeAdapter}
    # This is supplied static control/data composition; no ExecutionModel or
    # same-runtime-activation claim is created by the test.
    assert index.protocol_obligations()["source_runtime_verified"] is False


def test_second_close_cannot_reenter_the_first_cut_while_claiming_the_retry_terminal():
    graph, details = two_close_requests_program()
    row = next(row for row in graph.body_drives if row.operation == details["second"]["drive"])
    wrong = replace(graph, body_drives=tuple(replace(current,
        target=BodyResume(details["first_cut"], 1)) if current == row else current
        for current in graph.body_drives))
    assert "driver_outcomes" in _codes(wrong)


def test_second_call_cannot_reuse_the_pre_first_call_state_after_the_actual_raise_completion():
    graph, details = two_close_requests_program()
    second = _operation(graph, details["calls"][1])
    index = ProgramIndex(graph)
    state = next(identity for identity in second.invoke_arguments
                 if isinstance(index.values[index.use_site(identity).use.value], StateVersionValue))
    wrong = _change_use(graph, second.id, state, details["initial_states"][0])
    assert "stale_state" in _codes(wrong)


def test_second_close_cannot_deliver_the_previous_host_error_in_place_of_its_fresh_normalizer_packet():
    graph, details = two_close_requests_program()
    gate = _operation(graph, details["second_gate"])
    row = next(row for row in graph.final_body_gates if row.operation == gate.id)
    actual = gate.invoke_arguments[row.delivery_arguments[0]]
    new_packet = next(use.value for use in gate.uses if use.id == actual)
    changed = replace(gate, uses=tuple(replace(use, value=details["second_old_packet"])
        if use.value == new_packet else use for use in gate.uses))
    wrong = replace(graph, operations=tuple(changed if operation.id == changed.id else operation
                                           for operation in graph.operations))
    require_valid(replace(wrong, protocol_scopes=(), protocol_operations=()))
    assert "protocol_copy" in _codes(wrong)


def test_first_yield_cannot_borrow_finished_history_from_the_second_driver_of_the_shared_body():
    graph, _ = two_close_requests_program(release_first=True)
    assert "terminal_release_unfinished" in _codes(graph)
