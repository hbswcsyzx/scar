"""Synchronous close connections, not native exception/phase certification."""
from dataclasses import replace

import pytest

from scar.ir.program.ids import OperationID, ValueID
from scar.ir.program.model import InvokeLiteralResult, ReferenceValue, StateVersionValue, TerminatorKind
from scar.ir.program.protocols import DriveResult, HostTerminal, OutcomeAdapter, OwnedUse
from scar.ir.program.protocol_flow import ProtocolFlow
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.resumption import ResumeSlotKind, SuspendTerminator
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_generator_close_graphs import (
    generator_close_program, state_as_close_payload_program,
)


def _operation(graph, identity):
    return next(operation for operation in graph.operations if operation.id == identity)


def _core(graph):
    return replace(graph, protocol_scopes=(), protocol_operations=())


def _codes(graph):
    return {issue.code for issue in validate(graph)}


def _change_use(graph, operation_id, use_id, value):
    return replace(graph, operations=tuple(replace(operation, uses=tuple(
        replace(use, value=value) if use.id == use_id else use for use in operation.uses))
        if operation.id == operation_id else operation for operation in graph.operations))


def test_close_metadata_cannot_call_an_unchanged_state_effect_a_yield_payload_or_runtime_error():
    graph, details = state_as_close_payload_program()
    require_valid(_core(graph))
    assert details["source_slot"] > 0
    assert "protocol_adapter_source" in _codes(graph)


@pytest.mark.parametrize("adapter", ("direct", "helper"))
def test_close_body_return_connects_the_real_value_or_selected_helper_results_to_host(adapter):
    graph, details = generator_close_program(adapter=adapter)
    require_valid(_core(graph))
    require_valid(graph)
    index = ProgramIndex(graph)
    source = _operation(graph, details["source"])
    assert source.terminator.kind is TerminatorKind.RETURN
    assert _operation(graph, details["terminals"][0]).terminator.kind is TerminatorKind.RETURN
    report = index.protocol_obligations(details["scope"])
    assert report["source_runtime_verified"] is False
    assert report["protocol_implementation_complete"] is False
    commit, = graph.body_outcome_commits
    body = next(use.value for use in _operation(graph, commit.operation).uses if use.id == commit.instance)
    assert index.lifecycle_after(commit.operation).terminal.is_finished(body)
    if adapter == "helper":
        assert _operation(graph, details["terminals"][1]).terminator.kind is TerminatorKind.RAISE
        assert {row.slot for row in graph.protocol_operations if type(row.contract) is OutcomeAdapter} == {0, 1}


def test_ignored_generator_exit_is_a_real_yield_with_two_error_constructor_routes_and_no_finished_fact():
    graph, details = generator_close_program(outcome="yield", adapter="helper")
    require_valid(_core(graph))
    require_valid(graph)
    index = ProgramIndex(graph)
    source = _operation(graph, details["source"])
    assert isinstance(source.terminator, SuspendTerminator)
    assert tuple(edge.block for edge in source.terminator.successors) == details["retry_targets"]
    assert {slot.kind for edge in source.terminator.successors for slot in edge.inputs
            if slot.location is None} == {ResumeSlotKind.SENT_VALUE, ResumeSlotKind.THROWN_PACKET}
    commit, = graph.body_outcome_commits
    body = next(use.value for use in _operation(graph, commit.operation).uses if use.id == commit.instance)
    assert not index.lifecycle_after(commit.operation).terminal.is_finished(body)
    for terminal in details["terminals"]:
        assert _operation(graph, terminal).terminator.kind is TerminatorKind.RAISE
        assert not index.lifecycle_before(terminal).terminal.is_finished(body)


@pytest.mark.parametrize("edge", (0, 1))
def test_close_error_adapter_cannot_ignore_its_actual_result_and_replay_an_old_packet(edge):
    graph, details = generator_close_program(outcome="yield", adapter="helper")
    terminal = _operation(graph, details["terminals"][edge])
    old = ValueID("driver.entry.arg.2")
    wrong = _change_use(graph, terminal.id, terminal.terminator.values[0], old)
    require_valid(_core(wrong))
    assert "protocol_copy" in _codes(wrong)


def test_host_close_error_after_yield_does_not_make_terminal_frame_release_legal():
    graph, details = generator_close_program(outcome="yield", adapter="helper", release=True)
    assert details["release"] is not None
    assert "terminal_release_unfinished" in _codes(graph)


def test_a_different_static_body_terminal_cannot_supply_finished_history_for_this_yield():
    graph, details = generator_close_program(outcome="yield", adapter="helper")
    require_valid(_core(graph))
    commit, = graph.body_outcome_commits
    # resume.return exists on a different ingress.  It is not the current
    # Drive's first outcome, even though it belongs to the same body region.
    wrong = replace(graph, body_outcome_commits=(replace(commit,
        outcome=replace(commit.outcome, source=OperationID("resume.return"))),))
    assert "publication_outcome" in _codes(wrong)


def test_close_release_cannot_reuse_the_pre_drive_state_instead_of_the_actual_current_post():
    graph, details = generator_close_program(release=True)
    release = _operation(graph, details["release"])
    access = release.accesses[0]
    values = {value.id: value for value in graph.values}
    drive = _operation(graph, details["drive"])
    previous = next(use.value for use in drive.uses if isinstance(values[use.value], StateVersionValue)
                    and values[use.value].location == access.location)
    wrong = _change_use(graph, release.id, access.before, previous)
    assert "stale_state" in _codes(wrong)


def test_close_return_helper_cannot_replay_an_available_owner_instead_of_its_own_result():
    graph, details = generator_close_program(adapter="helper")
    terminal = _operation(graph, details["terminals"][0])
    wrong = _change_use(graph, terminal.id, terminal.terminator.values[0],
                        graph.driver_interfaces[0].receiver)
    require_valid(_core(wrong))
    assert "protocol_copy" in _codes(wrong)


def test_close_suppression_reads_the_body_raise_and_returns_its_own_normal_none_result():
    graph, details = generator_close_program(outcome="raise", adapter="helper")
    require_valid(_core(graph))
    require_valid(graph)
    index = ProgramIndex(graph)
    assert _operation(graph, details["source"]).terminator.kind is TerminatorKind.RAISE
    evaluation, = graph.literal_evaluations
    assert isinstance(evaluation.site, InvokeLiteralResult)
    assert evaluation.literal.to_python() is None
    original = index.literal_evaluation(evaluation.site)
    assert original["row"] is evaluation
    assert isinstance(original["result"], ReferenceValue)
    normal = _operation(graph, details["terminals"][0])
    assert normal.terminator.kind is TerminatorKind.RETURN
    assert index.use_site(normal.terminator.values[0]).use.value == original["result"].id
    failure = _operation(graph, details["terminals"][1])
    assert failure.terminator.kind is TerminatorKind.RAISE
    row = next(row for row in graph.protocol_operations if type(row.contract) is OutcomeAdapter and row.slot == 1)
    assert ProtocolFlow(graph).forwards(row.contract.output,
        OwnedUse(failure.id, failure.terminator.values[0])) is True


def test_close_suppression_cannot_return_an_unrelated_same_typed_reference_in_place_of_none():
    graph, details = generator_close_program(outcome="raise", adapter="helper")
    terminal = _operation(graph, details["terminals"][0])
    wrong = _change_use(graph, terminal.id, terminal.terminator.values[0],
                        graph.driver_interfaces[0].receiver)
    require_valid(_core(wrong))
    assert "protocol_copy" in _codes(wrong)


def test_other_body_helper_exception_packets_propagate_without_close_none_suppression():
    graph, details = generator_close_program(outcome="propagate")
    require_valid(_core(graph))
    require_valid(graph)
    flow = ProtocolFlow(graph)
    for source, terminal_id in zip(details["sources"], details["terminals"], strict=True):
        terminal = _operation(graph, terminal_id)
        assert _operation(graph, source).terminator.kind is TerminatorKind.RAISE
        assert terminal.terminator.kind is TerminatorKind.RAISE
        assert flow.forwards(DriveResult(graph.body_outcome_commits[details["sources"].index(source)].outcome, 0),
            OwnedUse(terminal.id, terminal.terminator.values[0])) is True
    assert not graph.literal_evaluations


@pytest.mark.parametrize("edge", (0, 1))
def test_other_exception_propagation_cannot_replay_the_preexisting_input_packet(edge):
    graph, details = generator_close_program(outcome="propagate")
    terminal = _operation(graph, details["terminals"][edge])
    wrong = _change_use(graph, terminal.id, terminal.terminator.values[0], ValueID("driver.entry.arg.2"))
    require_valid(_core(wrong))
    assert "protocol_copy" in _codes(wrong)
