"""Continuation contracts consume original ports, not type-compatible claims."""
from dataclasses import replace

import pytest

from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.program.model import CompletionResult, InvokeLiteralResult, TerminatorKind
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.protocol_connections import ProtocolOperationRef, ResumeSourceBinding
from scar.ir.program.protocol_continuations import continuation_connections
from scar.ir.program.protocols import ContractResult, OutcomeAdapter, OwnedUse, ProtocolCall
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_continuation_graphs import (
    continuation_close_program, continuation_initial_loop_program,
    continuation_paired_program, continuation_parent_program, continuation_site_program,
    with_continuation_connections,
)
from tests.fixtures.program_continuation_cleanup_graphs import continuation_close_cleanup_program


def _typed(**kwargs):
    if kwargs.get("request") == "close":
        return continuation_close_program(kind=kwargs.get("kind", "delegate"))
    return with_continuation_connections(*continuation_site_program(**kwargs))


def _view(graph, *, budget=32768):
    index = ProgramIndex(graph)
    return continuation_connections(ConnectionContext(graph, index=index, budget=ValidityBudget(budget)))


def _core_valid(graph):
    """Rejecting a metadata mutation must not rely on an invalid canonical CFG."""
    require_valid(replace(graph, protocol_scopes=(), protocol_operations=(),
                          protocol_call_inputs=(), protocol_result_consumers=()))


def _codes(graph):
    _core_valid(graph)
    return {issue.code for issue in validate(graph)}


def _change_inputs(graph, predicate, change):
    return replace(graph, protocol_call_inputs=tuple(change(row) if predicate(row) else row
                                                     for row in graph.protocol_call_inputs))


@pytest.mark.parametrize("kind", ("delegate", "await", "wrapper"))
@pytest.mark.parametrize("request_kind", ("next", "send", "throw", "close"))
def test_lookup_iterator_request_and_actual_item_exhaustion_failure_are_distinct(kind, request_kind):
    graph, details = _typed(kind=kind, request=request_kind)
    require_valid(graph)
    view = _view(graph)
    assert not view["issues"]
    assert view["obligations"]
    assert not graph.body_drives and not graph.frame_context_attaches
    assert view["source_runtime_verified"] is False
    assert view["transformation_authorized"] is False
    advance = details["advance"]["operation"]
    assert tuple(edge.kind.value for edge in advance.terminator.successors) == ("NORMAL", "RAISE")
    assert details["item_exit"].terminator.kind is (TerminatorKind.RAISE if request_kind == "close" else TerminatorKind.RETURN)
    assert details["error_exit"].terminator.kind is TerminatorKind.RAISE
    if kind != "delegate":
        # __await__()'s own NORMAL result is an iterator consumed by a distinct
        # advance; the final expression is the extraction helper's result.
        assert details["iterator_row"].operation == details["await_call"]["operation"].id
        if request_kind != "close":
            assert len(details["await_adapter_rows"]) == 2
            assert details["value_exit"].uses[0].value == details["extraction"]["normal_values"][0]
            assert details["value_exit"].uses[0].value != details["await_call"]["normal_values"][0]


@pytest.mark.parametrize("arity", (1, 2, 3))
def test_delegate_throw_keeps_each_original_raw_operand_and_order(arity):
    graph, details = _typed(request="throw", throw_arity=arity)
    require_valid(graph)
    assert len(details["advance"]["operation"].invoke_arguments) == arity + 2
    assert len(details["advance_rows"][0].contract.argument_uses) == arity
    assert not _view(graph)["issues"]


def test_await_call_cannot_use_same_typed_root_instead_of_its_lookup_result():
    graph, details = _typed(kind="await")
    call = details["await_call"]["operation"].id
    from scar.ir.program.model import BlockArgument
    from scar.ir.program.ids import BlockID
    bad = _change_inputs(graph, lambda row: row.site.operation == call,
        lambda row: replace(row, cases=tuple(replace(case,
            receiver=BlockArgument(BlockID("continuation.entry"), 1)) for case in row.cases)))
    assert "protocol_input_source" in _codes(bad)


def test_await_lookup_bound_method_is_not_the_iterator_returned_by_await_call():
    graph, details = _typed(kind="await")
    lookup = details["lookup_rows"][0]
    wrong = ContractResult(lookup.scope, lookup.clause, lookup.operation, lookup.slot, lookup.contract.result)
    bad = _change_inputs(graph, lambda row: row.site.operation == details["advance"]["operation"].id,
        lambda row: replace(row, cases=tuple(replace(case, receiver=wrong) for case in row.cases)))
    assert "protocol_continuation_source" in _codes(bad)


def test_await_iterator_cannot_replace_the_actual_extracted_expression_result():
    graph, details = _typed(kind="await")
    terminal = details["value_exit"]
    changed = replace(terminal, uses=tuple(replace(use,
        value=details["await_call"]["normal_values"][0]) if use.id == terminal.uses[0].id else use
        for use in terminal.uses))
    graph = replace(graph, operations=tuple(changed if operation.id == changed.id else operation
                                           for operation in graph.operations))
    assert "protocol_result_consumer" in _codes(graph)


def test_raw_throw_ordinals_cannot_be_reordered_even_when_all_references_have_the_same_type():
    graph, details = _typed(request="throw")
    bad = _change_inputs(graph, lambda row: row.site.operation == details["advance"]["operation"].id,
        lambda row: replace(row, cases=tuple(replace(case,
            arguments=tuple(reversed(case.arguments))) for case in row.cases)))
    assert "protocol_continuation_arguments" in _codes(bad)


@pytest.mark.parametrize("which", ("item_input", "exhaustion_input", "state_output"))
def test_item_exhaustion_packet_and_state_are_not_interchangeable_metadata(which):
    graph, details = _typed()
    row = details["item_row"] if which == "item_input" else details["extraction_rows"][0]
    if which == "state_output":
        wrong = replace(row.contract, output=InvokeLiteralResult(
            ControlEdgeReference(row.operation, 0), CompletionResult(1)))
    else:
        slot = 1 if which == "item_input" else 0
        advance = details["advance_rows"][slot]
        wrong = replace(row.contract, input=ContractResult(advance.scope, advance.clause,
            advance.operation, advance.slot, advance.contract.result))
    bad = replace(graph, protocol_operations=tuple(replace(candidate, contract=wrong)
        if candidate == row else candidate for candidate in graph.protocol_operations))
    assert {"protocol_continuation_role", "protocol_continuation_outcome", "protocol_copy"} & _codes(bad)


def test_initial_advance_names_the_current_evaluation_instead_of_a_bare_initial_flag():
    graph, details = _typed(kind="await", initial=True)
    require_valid(graph)
    assert not _view(graph)["issues"]
    assert details["iterator_row"].operation == details["await_call"]["operation"].id


def test_initial_advance_cannot_be_reused_after_a_real_advance_backedge():
    graph, _ = continuation_initial_loop_program()
    assert "protocol_initial_advance" in _codes(graph)


def test_close_normal_continues_old_injection_but_raise_overrides_with_own_packet():
    graph, details = continuation_close_program()
    require_valid(graph)
    view = _view(graph)
    assert not view["issues"]
    normal = next(item for item in view["obligations"] if item["site"].operation == details["advance"]["operation"].id
                  and item["site"].slot == 0)
    assert normal["close_routes"][0]["targets"] == (OwnedUse(details["normal_terminal"].id,
                                                            details["normal_terminal"].uses[0].id),)
    assert details["normal_terminal"].uses[0].value == details["injected_packet"].id
    assert details["raise_terminal"].uses[0].value == details["advance"]["failure_values"][0]
    assert details["raise_terminal"].uses[0].value != details["injected_packet"].id
    assert not graph.body_drives


def test_close_none_normal_result_is_not_a_new_host_item_or_parent_exception():
    graph, details = continuation_close_program()
    terminal = details["normal_terminal"]
    normal = details["advance"]["normal_values"][0]
    from scar.ir.program.model import ExitKind, ExitPort, UseRole, ValueKind, ValueType
    old = terminal.uses[0]
    changed = replace(terminal, uses=(replace(old, value=normal, role=UseRole.REFERENCE), terminal.uses[1]),
        terminator=replace(terminal.terminator, kind=TerminatorKind.RETURN, exit="normal"))
    graph = replace(graph, operations=tuple(changed if operation.id == terminal.id else operation
                                           for operation in graph.operations),
        regions=(replace(graph.regions[0], exits=(*graph.regions[0].exits,
            ExitPort("normal", ExitKind.NORMAL, (ValueType(ValueKind.REFERENCE),
                ValueType(ValueKind.STATE, location=graph.locations[0].id))))),))
    assert "protocol_close_continuation" in _codes(graph)


def test_close_normal_cannot_replay_a_different_same_typed_entry_packet():
    from scar.ir.program.control import ProtocolValueKind as P
    from scar.ir.program.ids import ValueID
    from scar.ir.program.model import BlockArgument, ProtocolValue
    graph, details = continuation_close_program()
    region = graph.regions[0]
    entry = next(block for block in region.blocks if block.id == region.entry)
    old_packet = ProtocolValue(ValueID("continuation.unrelated.packet"), graph.root,
        BlockArgument(entry.id, len(entry.arguments)), P.EXCEPTION_PACKET)
    terminal = details["normal_terminal"]
    changed = replace(terminal, uses=tuple(replace(use, value=old_packet.id)
        if use.id == terminal.uses[0].id else use for use in terminal.uses))
    graph = replace(graph, values=(*graph.values, old_packet),
        operations=tuple(changed if operation.id == changed.id else operation for operation in graph.operations),
        regions=(replace(region, blocks=tuple(replace(block, arguments=(*block.arguments, old_packet.id))
            if block.id == entry.id else block for block in region.blocks)),))
    assert "protocol_close_continuation" in _codes(graph)


@pytest.mark.parametrize("flavor", ("AWAIT", "DELEGATION"))
@pytest.mark.parametrize("slot", ("SENT_VALUE", "THROWN_PACKET", "DELEGATE_VALUE", "DELEGATE_PACKET"))
def test_parent_resume_binds_the_actual_non_state_slot_without_guessing_from_flavor(flavor, slot):
    graph, details = continuation_parent_program(slot=slot, flavor=flavor)
    require_valid(graph)
    view = _view(graph)
    rows = [row for row in view["obligations"] if row["site"].operation == details["drive"].operation]
    assert len(rows) == 1 and rows[0]["kind"].value == slot
    assert rows[0]["binding"]["match"] is True
    assert rows[0]["status"] == "DECLARED"


def test_parent_slot_relation_deletion_preserves_the_original_required_slot():
    graph, details = continuation_parent_program()
    graph = replace(graph, protocol_operations=tuple(row for row in graph.protocol_operations
                                                   if row != details["row"]))
    require_valid(graph)
    rows = [row for row in _view(graph)["obligations"]
            if row["site"].operation == details["drive"].operation]
    assert len(rows) == 1 and rows[0]["status"] == "MISSING"


def test_parent_slot_cannot_borrow_another_same_typed_current_reference():
    graph, details = continuation_parent_program()
    row = details["row"]
    gate = graph.final_body_gates[0]
    operation = next(operation for operation in graph.operations if operation.id == gate.operation)
    wrong = OwnedUse(operation.id, operation.invoke_arguments[gate.body_argument])
    bad = replace(graph, protocol_operations=tuple(replace(candidate, contract=ResumeSourceBinding(wrong))
        if candidate == row else candidate for candidate in graph.protocol_operations))
    assert "protocol_resume_source" in _codes(bad)


@pytest.mark.parametrize("wrong_site", ("start", "non_drive", "missing", "state_slot"))
def test_supplied_resume_rows_outside_the_canonical_slot_inventory_are_rejected(wrong_site):
    from scar.ir.program.ids import OperationID, ProtocolScopeID
    from scar.ir.program.protocols import DriverSubject, ProtocolClause, ProtocolOperation, ProtocolProfile, ProtocolScope
    from scar.ir.program.resumption import ResumeSlotKind
    from scar.ir.program.driver_flow import body_drive_target
    from tests.fixtures.program_driver_graphs import driver_program
    from tests.fixtures.program_protocol_graphs import _source_gap
    if wrong_site == "start":
        graph = driver_program()
        drive, = graph.body_drives
        scope = ProtocolScope(ProtocolScopeID("not.a.resume"), ProtocolProfile.GENERATOR_BODY_V1,
                              DriverSubject(graph.driver_interfaces[0].region), _source_gap())
        row = ProtocolOperation(scope.id, ProtocolClause.BODY_INGRESS, drive.operation, 0,
                                ResumeSourceBinding(OwnedUse(drive.operation, drive.instance)), _source_gap())
        graph = replace(graph, protocol_scopes=(scope,), protocol_operations=(row,))
    else:
        graph, details = continuation_parent_program()
        row = details["row"]
        if wrong_site == "non_drive":
            changed = replace(row, operation=details["processing"]["processing"])
        elif wrong_site == "missing":
            changed = replace(row, operation=OperationID("missing.resume.operation"))
        else:
            _, _, successor = body_drive_target(graph, details["drive"])
            state_slot = next(index for index, slot in enumerate(successor.inputs) if slot.kind is ResumeSlotKind.STATE)
            changed = replace(row, slot=state_slot)
        graph = replace(graph, protocol_operations=tuple(changed if candidate == row else candidate
                                                       for candidate in graph.protocol_operations))
    assert {"protocol_resume_site", "protocol_operation"} & _codes(graph)


@pytest.mark.parametrize("flavor", ("AWAIT", "DELEGATION"))
def test_resume_source_connection_composes_with_active_cleanup_saved_pending_and_fresh_raise(flavor):
    from scar.ir.program.control import ProtocolValueKind as P
    from scar.ir.program.resumption import SavedRole, SuspendTerminator
    graph, details = continuation_parent_program(flavor=flavor, cleanup=True)
    require_valid(graph)
    index = ProgramIndex(graph)
    assert not _view(graph)["issues"]
    cut, = (operation for operation in graph.operations if type(operation.terminator) is SuspendTerminator)
    assert {SavedRole.PENDING_COMPLETION, SavedRole.CLEANUP_CONTEXT, SavedRole.FRAME_CONTEXT} <= {
        slot.role for slot in cut.terminator.saved}
    helper = next(operation for operation in graph.operations if operation.id.value == "finally.invoke")
    values = {value.id: value for value in graph.values}
    actuals = {use.id for use in helper.uses if getattr(values[use.value], "protocol", None) in (
        P.PENDING_COMPLETION, P.SAVED_HANDLED_CONTEXT, P.DRIVE_CALLER_CONTEXT)}
    assert actuals and actuals.isdisjoint(helper.invoke_arguments)
    failed = next(row for row in graph.pending_completions if row.value.value == "finally.new-raise.pending")
    assert index.use_site(failed.payload).use.value.value == "finally.failed.packet"
    replacement = next(row for row in graph.cleanup_replacements if row.operation.value == "finally.raise-replace")
    assert index.use_site(replacement.replacement).use.value.value == "finally.replace-raise.replacement"
    assert graph.cleanup_resumes and graph.cleanup_replacements


def test_continuation_metadata_cannot_let_an_active_cleanup_private_token_escape_through_the_helper():
    from scar.ir.program.ids import UseID
    from scar.ir.program.model import Use, UseRole
    graph, _ = continuation_parent_program(cleanup=True)
    helper = next(operation for operation in graph.operations if operation.id.value == "finally.invoke")
    pending = next(use for use in helper.uses if use.id.value == "finally.invoke.normal.pending")
    escaped = Use(UseID("continuation.illegal.pending"), pending.value, UseRole.PROTOCOL)
    changed = replace(helper, uses=(*helper.uses, escaped), invoke_arguments=(*helper.invoke_arguments, escaped.id))
    graph = replace(graph, operations=tuple(changed if operation.id == changed.id else operation
                                           for operation in graph.operations))
    assert "pending_escape" in {issue.code for issue in validate(graph)}


def test_two_lookup_request_tuples_merge_upstream_of_the_real_send_call():
    from scar.ir.program.protocol_connection_validation import common_connections
    graph, details = continuation_paired_program()
    require_valid(graph)
    index = ProgramIndex(graph)
    context = ConnectionContext(graph, index=index, budget=ValidityBudget(131072))
    report = common_connections(context)
    assert not report["issues"]
    calls = [item for item in report["inputs"] if item["site"].operation == details["call"]["operation"].id]
    assert len(calls) == 2
    assert all(len(item["cases"]) == 2 for item in calls)
    for item in calls:
        assert all(case["joint"] for case in item["cases"])
    expected_target = OwnedUse(details["call"]["operation"].id, details["call"]["receiver"])
    source_sites = {row.site for row in details["consumers"]}
    consumers = [item for item in report["consumers"] if item["site"] in source_sites]
    assert len(consumers) == 2
    assert all(expected_target in item["targets"] and not item["missing"] for item in consumers)


def test_receiver_and_send_operand_cannot_come_from_opposite_merge_predecessors():
    graph, _ = continuation_paired_program(crossed=True)
    assert {"protocol_input_source", "protocol_continuation_arguments"} & _codes(graph)


def test_deleting_the_paired_call_attachment_keeps_both_selected_call_rows_required():
    from scar.ir.program.protocol_connection_validation import common_connections
    graph, details = continuation_paired_program()
    graph = replace(graph, protocol_call_inputs=tuple(row for row in graph.protocol_call_inputs
        if row.site.operation != details["call"]["operation"].id))
    require_valid(graph)
    report = common_connections(ConnectionContext(graph, index=ProgramIndex(graph), budget=ValidityBudget(131072)))
    missing = [item for item in report["inputs"] if item["site"].operation == details["call"]["operation"].id]
    assert len(missing) == 2 and all(item["status"] == "MISSING" for item in missing)


def test_partial_single_guard_does_not_claim_the_other_merge_predecessor_was_checked():
    from scar.ir.program.protocol_connection_validation import common_connections
    graph, details = continuation_paired_program(omitted=True)
    require_valid(graph)
    report = common_connections(ConnectionContext(graph, index=ProgramIndex(graph), budget=ValidityBudget(131072)))
    calls = [item for item in report["inputs"] if item["site"].operation == details["call"]["operation"].id]
    assert len(calls) == 2
    for call in calls:
        assert call["missing_incoming"] == ((details["guards"][1].operation, details["guards"][1].successor_index),)
        assert call["status"] == "PARTIAL"


def test_close_normal_and_raise_merge_into_one_real_fresh_pending_and_current_cleanup_replace():
    from scar.ir.program.resumption import SavedRole, SuspendTerminator
    graph, details = continuation_close_cleanup_program()
    _core_valid(graph)
    require_valid(graph)
    view = _view(graph, budget=262144)
    assert not view["issues"]
    routes = [item["close_routes"][0] for item in view["obligations"]
              if item["site"].operation == details["helper"]]
    assert len(routes) == 2
    assert all(route["status"] == "DECLARED" for route in routes)
    actions = [target for route in routes for target in route["targets"]
               if isinstance(target, dict) and "action" in target]
    assert len(actions) == 2 and all(target["action"].operation == details["replacement"] for target in actions)
    assert all(target["sources"] and all(source["packet_match"] is True for source in target["sources"])
               for target in actions)
    cut, = (operation for operation in graph.operations if type(operation.terminator) is SuspendTerminator)
    assert {SavedRole.DELEGATE_REFERENCE, SavedRole.PENDING_COMPLETION,
            SavedRole.CLEANUP_CONTEXT, SavedRole.FRAME_CONTEXT} <= {slot.role for slot in cut.terminator.saved}
    helper = next(operation for operation in graph.operations if operation.id == details["helper"])
    # The injected packet and all C1 private resources are copied on original
    # completion edges; none becomes a fake close method argument.
    assert len(helper.invoke_arguments) == 3
    assert all(use.id not in helper.invoke_arguments for use in helper.uses
               if use.role.value == "PROTOCOL")
    assert not graph.body_drives and not graph.terminal_frame_releases


@pytest.mark.parametrize("wrong", ("normal_none", "raise_old_packet"))
def test_shared_cleanup_pending_cannot_use_close_none_or_lose_the_new_close_exception(wrong):
    graph, details = continuation_close_cleanup_program()
    operation_id = details["normal_jump"] if wrong == "normal_none" else details["failure_jump"]
    original = next(operation for operation in graph.operations if operation.id == operation_id)
    if wrong == "normal_none":
        # Metadata-only wrong source stays core-valid: choose the close NORMAL
        # Reference result as the packet trigger, without changing any edge.
        from scar.ir.program.protocol_connections import InjectedPacketTrigger
        graph = replace(graph, protocol_call_inputs=tuple(replace(row, cases=tuple(
            replace(case, trigger=InjectedPacketTrigger(details["none_result"])) for case in row.cases))
            for row in graph.protocol_call_inputs))
        assert "protocol_continuation_trigger" in _codes(graph)
    else:
        changed = replace(original, uses=tuple(replace(use, value=details["injected"])
            if index == 0 else use for index, use in enumerate(original.uses)))
        graph = replace(graph, operations=tuple(changed if operation.id == changed.id else operation
                                               for operation in graph.operations))
        assert "protocol_close_continuation" in _codes(graph)


def test_tiny_shared_budget_retains_unchecked_sites_and_resume_slot_denominators():
    graph, _ = _typed()
    view = _view(graph, budget=1)
    assert view["cursor"] is not None
    assert len(view["obligations"]) == len(graph.protocol_operations)
    assert any(row["status"] == "NOT_CHECKED" for row in view["obligations"])
