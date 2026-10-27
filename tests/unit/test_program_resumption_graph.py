"""C2B graph composition checks; no source/driver/runtime proof is asserted."""
from dataclasses import replace

import pytest

from scar.ir.program.binding_validation import derive_binding_facts
from scar.ir.program.bindings import BindingState
from scar.ir.program.ids import BlockID, OperationID, UseID, ValueID
from scar.ir.program.model import Operation, Behavior, Use, UseRole
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.resumption import SavedRole, SavedSlot, saved_actual_use
from scar.ir.program.resumption_validation import ContextMode
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_resumption_graphs import (
    resumption_binding_program, resumption_loop_program, resumption_program,
    resumption_two_cuts_program, resumption_invoke_program,
)


def _codes(graph):
    return {issue.code for issue in validate(graph)}


def _operation(graph, name):
    return next(op for op in graph.operations if op.id == OperationID(name))


def _mutate_operation(graph, name, change):
    return replace(graph, operations=tuple(change(op) if op.id == OperationID(name)
                                           else op for op in graph.operations))


def _change_use(graph, operation, operand, value):
    return _mutate_operation(graph, operation, lambda op: replace(op, uses=tuple(
        replace(use, value=ValueID(value)) if use.id == UseID(operand) else use
        for use in op.uses)))


def test_value_packet_and_two_current_domains_are_real_temporal_bindings():
    graph = resumption_program()
    require_valid(graph)
    index = ProgramIndex(graph)
    suspend = _operation(graph, "resume.suspend")
    value_edge, packet_edge = suspend.terminator.successors
    assert saved_actual_use(suspend, value_edge.arguments[1]) == UseID("resume.suspend.x")
    assert saved_actual_use(suspend, packet_edge.arguments[-1]) == UseID("resume.suspend.x")
    assert saved_actual_use(suspend, value_edge.arguments[0]) is None
    assert index.producer(ValueID("resume.value.world")).block == BlockID("resume.value")
    assert index.use_site(UseID("resume.return.world")).use.value == ValueID("resume.value.world.written")
    assert index.use_site(UseID("resume.raise.context")).use.value == ValueID("resume.packet.detach.after")


def test_bound_local_survives_capture_restore_with_a_new_read_result():
    graph = resumption_binding_program()
    require_valid(graph)
    facts = derive_binding_facts(graph)
    assert facts[ValueID("resume.value.binding")] == frozenset((BindingState.BOUND,))
    assert facts[ValueID("resume.packet.binding")] == frozenset((BindingState.BOUND,))
    assert graph.binding_reads[0].normal_result == ValueID("resume.read.result")
    assert _operation(graph, "resume.return").uses[0].value == ValueID("resume.read.result")


def test_attached_loop_and_ordinary_branch_preserve_the_current_caller_token():
    graph = resumption_loop_program()
    require_valid(graph)
    choose = _operation(graph, "resume.loop.choose")
    assert choose.terminator.successors[0].block == BlockID("resume.loop")
    # The loop has an exit in the graph; no claim of dynamic completion follows.
    assert choose.terminator.successors[1].block == BlockID("resume.loop.exit")
    assert {use.value for use in choose.uses if use.role is UseRole.PROTOCOL} == {
        ValueID("resume.loop.caller")}


def test_second_cut_uses_new_formals_through_an_indirect_merge():
    require_valid(resumption_two_cuts_program())


def test_logical_dominance_cannot_keep_an_unsaved_reference_after_second_cut():
    graph = resumption_two_cuts_program(save_value=False)
    assert "unavailable_value" in _codes(graph)


def test_first_cut_cannot_read_the_unrestored_entry_reference():
    graph = _change_use(resumption_program(), "resume.return", "resume.return.value", "resume.x")
    assert "unavailable_value" in _codes(graph)


@pytest.mark.parametrize("value,operand", (
    ("resume.value.world", "resume.return.world"),
    ("resume.value.context", "resume.return.context"),
))
def test_post_write_and_post_detach_state_cannot_be_replaced_by_older_versions(value, operand):
    graph = _change_use(resumption_program(), "resume.return", operand, value)
    assert "stale_state" in _codes(graph)


def test_ingress_reference_cannot_claim_a_new_object_identity():
    graph = resumption_program()
    graph = replace(graph, values=tuple(replace(value, referent_identity="fabricated")
        if value.id == ValueID("resume.value.sent") else value for value in graph.values))
    assert "resumption_reference_precision" in _codes(graph)


def test_saved_reference_cannot_gain_precision_when_restored():
    graph = resumption_program()
    graph = replace(graph, values=tuple(replace(value, referent_identity="fabricated")
        if value.id == ValueID("resume.value.x") else value for value in graph.values))
    assert "reference_identity" in _codes(graph)


def test_saved_frame_is_the_adjacent_detach_result_not_old_initial_fragment():
    graph = _change_use(resumption_program(), "resume.suspend", "resume.suspend.frame", "resume.initial.frame")
    assert "resumption_current_frame" in _codes(graph)


def test_saved_role_cannot_turn_shared_state_into_private_value():
    graph = resumption_program()
    graph = _mutate_operation(graph, "resume.suspend", lambda op: replace(op,
        uses=tuple(replace(use, value=ValueID("resume.world.0"), role=UseRole.STATE_CONTENT)
                   if use.id == UseID("resume.suspend.x") else use for use in op.uses)))
    assert "edge_type" in _codes(graph)


def test_resume_detach_cannot_restore_the_previous_drives_caller():
    graph = _change_use(resumption_program(), "resume.value.detach",
                        "resume.value.detach.operand", "resume.attach.caller")
    assert "unavailable_value" in _codes(graph)


def test_caller_token_cannot_be_consumed_by_an_ordinary_user_operation():
    graph = resumption_program()
    leak = Operation(OperationID("resume.leak"), "unrelated operation",
        (Behavior.COMPUTE,), (Use(UseID("resume.leak.caller"),
            ValueID("resume.value.attach.caller"), UseRole.PROTOCOL),), effects_complete=True)
    graph = replace(graph, operations=(*graph.operations, leak),
        regions=tuple(replace(region, blocks=tuple(replace(block,
            operations=(block.operations[0], leak.id, *block.operations[1:]))
            if block.id == BlockID("resume.value") else block for block in region.blocks))
            for region in graph.regions))
    assert "resumption_private_escape" in _codes(graph)


def test_ordinary_loop_edge_cannot_drop_or_replace_the_current_caller():
    graph = _change_use(resumption_loop_program(), "resume.loop.choose", "resume.loop.again.0",
                        "resume.value.attach.caller")
    assert "resumption_caller_forward" in _codes(graph)


def test_handoff_cannot_repeat_world_instead_of_current_context():
    graph = _change_use(resumption_program(), "resume.suspend", "resume.suspend.context", "resume.world.0")
    assert "resumption_handoff" in _codes(graph)


def test_local_binding_saved_role_must_match_the_restored_tokens_slot():
    graph = resumption_binding_program()
    op = _operation(graph, "resume.suspend")
    slots = (*op.terminator.saved[:-1], SavedSlot(SavedRole.VALUE, op.terminator.saved[-1].use))
    graph = _mutate_operation(graph, op.id.value,
                             lambda op: replace(op, terminator=replace(op.terminator, saved=slots)))
    # Binding analysis runs before the C2 switch validator and must refuse
    # this value as a same-slot LOCAL_BINDING copy, rather than deriving BOUND.
    assert "binding_edge_slot" in _codes(graph)


def test_a_reference_cannot_be_declared_as_a_saved_local_binding():
    graph = resumption_program()
    graph = _mutate_operation(graph, "resume.suspend", lambda op: replace(op,
        terminator=replace(op.terminator, saved=(op.terminator.saved[0],
            SavedSlot(SavedRole.LOCAL_BINDING, op.terminator.saved[1].use)))))
    assert "resumption_saved_role" in _codes(graph)


def test_query_views_derive_original_endpoints_without_new_producers():
    graph = resumption_program()
    index = ProgramIndex(graph)
    assert index.resumable_body(graph.root) == graph.resumable_bodies[0]
    assert index.frame_context_action(OperationID("resume.initial")) == graph.frame_context_initials[0]
    assert index.frame_context_action(OperationID("resume.suspend")) is None
    assert index.drive_context(BlockID("resume.entry")).mode is ContextMode.DETACHED
    assert index.drive_context(BlockID("resume.value")).caller is None
    assert set(index.availability_roots(graph.root)) == {
        BlockID("resume.entry"), BlockID("resume.value"), BlockID("resume.packet")}
    bindings = index.resumption_bindings(OperationID("resume.suspend"), 0)
    assert bindings[0].formal == ValueID("resume.value.world")
    assert bindings[0].saved is None
    assert bindings[0].supplied.location == graph.locations[0].id
    assert bindings[1].saved.use.id == UseID("resume.suspend.x")
    assert bindings[1].supplied is None
    assert bindings[3].formal == ValueID("resume.value.sent")
    handoff = index.suspension_handoff(OperationID("resume.suspend"))
    assert handoff.exported.use.id == UseID("resume.suspend.export")
    assert tuple(site.use.value for site in handoff.states) == (
        ValueID("resume.world.0"), ValueID("resume.detach.after"))
    assert index.suspension_handoff(OperationID("resume.return")) is None
    loop = ProgramIndex(resumption_loop_program())
    assert loop.drive_context(BlockID("resume.loop")).mode is ContextMode.ATTACHED
    assert loop.drive_context(BlockID("resume.loop")).caller == ValueID("resume.loop.caller")


@pytest.mark.parametrize("method,argument", (
    ("resumable_body", "resume"), ("frame_context_action", "resume.initial"),
    ("drive_context", "resume.value"), ("availability_roots", "resume"),
    ("suspension_handoff", "resume.suspend"),
))
def test_query_endpoints_require_exact_typed_ids(method, argument):
    index = ProgramIndex(resumption_program())
    with pytest.raises(TypeError):
        getattr(index, method)(argument)


def test_query_rejects_missing_or_non_suspension_endpoints_and_bad_case_indices():
    index = ProgramIndex(resumption_program())
    with pytest.raises(KeyError):
        index.drive_context(BlockID("absent"))
    with pytest.raises(ValueError):
        index.resumption_bindings(OperationID("resume.return"), 0)
    with pytest.raises(TypeError):
        index.resumption_bindings(OperationID("resume.suspend"), True)
    with pytest.raises(IndexError):
        index.resumption_bindings(OperationID("resume.suspend"), 2)


def test_unknown_invoke_keeps_caller_local_and_threads_both_partial_state_outcomes():
    graph = resumption_invoke_program()
    require_valid(graph)
    index = ProgramIndex(graph)
    assert index.drive_context(BlockID("invoke.normal")).caller == ValueID("invoke.normal.caller")
    assert index.drive_context(BlockID("invoke.failure")).caller == ValueID("invoke.failure.caller")


def test_invoke_cannot_share_a_caller_use_between_user_argument_and_local_forward():
    assert "control_binding" in _codes(resumption_invoke_program(leak_caller=True, reuse_use=True))


def test_an_independent_opaque_invoke_argument_cannot_escape_the_private_caller():
    assert "resumption_private_escape" in _codes(resumption_invoke_program(leak_caller=True))
