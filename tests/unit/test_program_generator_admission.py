"""Created/Running matrix over original ports; no dynamic/native equivalence claim."""
from dataclasses import replace
import json

import pytest

from scar.ir.program.drivers import BodyResume, BodyStart, RawRequestKind
from scar.ir.program import codec
from scar.ir.program.ids import OperationID, ValueID
from scar.ir.program.input_origins import input_origins
from scar.ir.program.model import DataValue, ExitKind, InvokeLiteralResult, LiteralOrigin, OperationResult, ReferenceValue, StateVersionValue, TerminatorKind
from scar.ir.program.protocol_flow import ProtocolFlow
from scar.ir.program.protocols import AdmissionPredicate, BodyStateCondition, BodyStatePredicateRule, OwnedUse
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_generator_admission_graphs import (
    generator_admission_program, invalid_request_binding_program,
)


def _op(graph, identity):
    return next(op for op in graph.operations if op.id == identity)


def _codes(graph):
    return {issue.code for issue in validate(graph)}


@pytest.mark.parametrize("stage", ("created", "running"))
@pytest.mark.parametrize("kind", tuple(RawRequestKind))
def test_all_eight_stage_request_cells_use_actual_predicates_callers_and_current_ports(stage, kind):
    graph, details = generator_admission_program(stage=stage, kind=kind)
    require_valid(graph)
    index = ProgramIndex(graph)
    caller = _op(graph, details["call"])
    raw = next(row for row in graph.raw_driver_requests if row.value == details["raw"])
    assert raw.kind is kind
    assert isinstance(next(value for value in graph.values if value.id == raw.value).origin, OperationResult)
    interface = next(row for row in graph.driver_interfaces if row.region == caller.callee)
    region = next(region for region in graph.regions if region.id == caller.callee)
    entry = next(block for block in region.blocks if block.id == region.entry)
    raw_position = entry.arguments.index(interface.scheduler_request)
    actual = next(use for use in caller.uses if use.id == caller.invoke_arguments[raw_position])
    assert actual.value == raw.value
    if kind is RawRequestKind.CLOSE and stage == "created":
        predicate = index.created_close_predicate(details["created_close_test"])
        assert predicate.test.operation == details["created_close_test"]
        assert graph.no_body_finishes
        true_block = next(block for block in region.blocks if block.id == predicate.true_successor.block)
        assert true_block.operations[0] == details["finish"]
        assert all(operation not in {drive.operation for drive in graph.body_drives}
                   for operation in true_block.operations)
    else:
        assert details["guards"]
        for guard in details["guards"]:
            predicate = _op(graph, guard["predicate"])
            row = next(row for row in graph.protocol_operations
                       if row.operation == predicate.id and type(row.contract) is AdmissionPredicate)
            assert all(use.value != interface.scheduler_request for use in predicate.uses)
            assert _op(graph, row.contract.branch).terminator.kind is TerminatorKind.BRANCH
            if type(row.contract.subject) is BodyStateCondition:
                assert predicate.accesses and len(predicate.uses) == 2
                assert row.contract.subject.rule is (
                    BodyStatePredicateRule.IS_CREATED if stage == "created"
                    else BodyStatePredicateRule.IS_RUNNING)
    assert index.protocol_obligations(budget=65536)["source_runtime_verified"] is False
    assert index.protocol_obligations(budget=65536)["transformation_authorized"] is False


@pytest.mark.parametrize("send_none,retry", ((True, False), (False, True)))
def test_created_send_none_and_real_rejected_send_retry_have_independent_original_calls(send_none, retry):
    graph, details = generator_admission_program(stage="created", kind=RawRequestKind.SEND,
                                               send_none=send_none, retry=retry)
    require_valid(graph)
    call = _op(graph, details["call"])
    assert all(type(drive.target) is BodyStart and not drive.resume_inputs for drive in graph.body_drives)
    literal = next(row for row in graph.literal_evaluations
                   if row.site == OperationResult(OperationID("matrix.calls.argument"), 0))
    assert literal.literal.to_python() == (None if send_none else 7)
    if retry:
        second = _op(graph, details["retry_call"])
        raised = next(edge for edge in call.terminator.successors if edge.kind is ExitKind.RAISE)
        block = next(block for region in graph.regions for block in region.blocks if block.id == raised.block)
        assert second.id in block.operations
        assert second.callee != call.callee
        second_uses = {use.id: use for use in second.uses}
        assert second_uses[second.invoke_arguments[0]].value == details["raise_formals"][-1]
        states = tuple(value for value in details["raise_formals"]
                       if isinstance(ProgramIndex(graph).values[value], StateVersionValue))
        assert {use.value for use in second.uses
                if isinstance(ProgramIndex(graph).values[use.value], StateVersionValue)} == set(states)
        assert not graph.no_body_finishes


@pytest.mark.parametrize("failure", (False, True))
def test_created_throw_initial_edge_finalizes_without_a_body_ingress_on_that_route(failure):
    graph, details = generator_admission_program(stage="created", kind=RawRequestKind.THROW,
                                               constructor_failure=failure)
    require_valid(graph)
    guard = details["guards"][-1]
    publications = ProgramIndex(graph).no_entry_publications(guard["helper"])
    assert len(publications) == 1
    assert publications[0].selected_edge.successor_index == int(failure)
    assert _op(graph, publications[0].terminal.operation).terminator.kind is TerminatorKind.RAISE
    helper = _op(graph, guard["helper"])
    edge = helper.terminator.successors[int(failure)]
    block = next(block for region in graph.regions for block in region.blocks if block.id == edge.block)
    assert all(identity not in {drive.operation for drive in graph.body_drives} for identity in block.operations)
    owner = guard["owner_formals"][int(failure)]
    assert ProgramIndex(graph).lifecycle_edge(helper.id, int(failure)).terminal.is_finished(owner)


def test_running_throw_preserves_normalizer_callback_failure_before_reentry_override():
    graph, details = generator_admission_program(stage="running", kind=RawRequestKind.THROW)
    require_valid(graph)
    normalizer = _op(graph, details["processing"])
    assert len(normalizer.terminator.successors) == 2
    assert normalizer.effects_complete is False
    for number, guard in enumerate(details["guards"]):
        helper = _op(graph, guard["helper"])
        phase = _op(graph, guard["predicate"])
        assert normalizer.id != helper.id != phase.id
        original = normalizer.terminator.successors[number]
        block = next(block for region in graph.regions for block in region.blocks if block.id == original.block)
        assert phase.id in block.operations
        for helper_edge in helper.terminator.successors:
            terminal_block = next(block for region in graph.regions for block in region.blocks
                                  if block.id == helper_edge.block)
            terminal = _op(graph, terminal_block.operations[-1])
            assert terminal.terminator.kind is TerminatorKind.RAISE
            assert not ProgramIndex(graph).lifecycle_before(terminal.id).terminal.is_finished(
                guard["owner_formals"][helper.terminator.successors.index(helper_edge)])
    assert _op(graph, details["outer_continuation"]).id in {
        operation for region in graph.regions for block in region.blocks for operation in block.operations}


def test_a_same_typed_other_bool_cannot_replace_the_real_running_guard_condition():
    graph, details = generator_admission_program(stage="running", kind=RawRequestKind.THROW)
    require_valid(graph)
    _, second = details["guards"]
    branch = _op(graph, second["branch"])
    # An available same-typed value isolates the protocol source check. A bool
    # from the mutually exclusive sibling block only tests core availability.
    region = next(value.region for value in graph.values
                  if value.origin == second["row"].contract.result)
    wrong = DataValue(ValueID("matrix.other.bool"), region,
                      LiteralOrigin(True), "builtins.bool")
    malformed = replace(graph, values=(*graph.values, wrong), operations=tuple(replace(op, uses=tuple(
        replace(use, value=wrong.id) if use.id == branch.terminator.condition else use
        for use in op.uses)) if op.id == branch.id else op for op in graph.operations))
    require_valid(replace(malformed, protocol_scopes=(), protocol_operations=()))
    assert "admission_bool_source" in _codes(malformed)


def test_retry_cannot_reuse_the_pre_rejection_state():
    graph, details = generator_admission_program(stage="created", kind=RawRequestKind.SEND,
                                               send_none=False, retry=True)
    require_valid(graph)
    call = _op(graph, details["retry_call"])
    index = ProgramIndex(graph)
    by_location = {index.values[value].location: value for value in details["initial_states"]}
    malformed = replace(graph, operations=tuple(replace(op, uses=tuple(replace(use,
        value=by_location[index.values[use.value].location])
        if isinstance(index.values[use.value], StateVersionValue) else use for use in op.uses))
        if op.id == call.id else op for op in graph.operations))
    assert "stale_state" in _codes(malformed)


def test_running_true_to_start_is_an_exact_snapshot_gap_without_native_gate_authority():
    graph, details = generator_admission_program(stage="created", kind=RawRequestKind.NEXT)
    require_valid(graph)
    original = details["guards"][-1]["row"]
    changed = replace(original, contract=replace(original.contract,
        subject=replace(original.contract.subject, rule=BodyStatePredicateRule.IS_RUNNING)))
    graph = replace(graph, protocol_operations=tuple(changed if row == original else row
                                                    for row in graph.protocol_operations))
    # An opaque final gate can itself reject; do not declare the whole CFG
    # invalid just because its NORMAL branch is an overapproximation.
    require_valid(graph)
    report = ProgramIndex(graph).protocol_obligations(original.scope, budget=65536)
    row = next(row for scope in report["scopes"] for clause in scope["obligations"]
               for row in clause["rows"] if row["record"].operation == original.operation)
    view = row["predicate"]
    gates = [item for item in view["control_routes"]["frontiers"]
             if item["kind"] == "FINAL_GATE" and item["edge"].successor_index == 0]
    assert gates and all(item["read_snapshot_current"] for item in gates)
    assert all(item["target_compatible_at_snapshot"] is False for item in gates)
    assert "admission_phase_target_incompatible_at_snapshot" in view["gaps"]
    assert view["status"] == "PARTIAL"
    assert all(item["native_gate_verified"] is False for item in gates)
    assert view["transformation_authorized"] is False


@pytest.mark.parametrize("operands", (0, 4))
def test_invalid_arity_is_a_real_only_raise_call_before_raw_and_handler_keeps_poststate(operands):
    graph, details = invalid_request_binding_program(operand_count=operands)
    require_valid(graph)
    assert not graph.raw_driver_requests and not graph.body_drives
    assert not graph.no_body_finishes and not graph.body_outcome_commits
    call, binder, returned = (_op(graph, details[key]) for key in ("call", "binder", "return"))
    assert len(call.invoke_arguments) == operands + 2  # receiver + operands + state
    assert len(call.terminator.successors) == len(binder.terminator.successors) == 1
    assert call.terminator.successors[0].kind is ExitKind.RAISE
    assert binder.terminator.successors[0].kind is ExitKind.RAISE
    assert next(use.value for use in returned.uses if use.id == returned.terminator.values[1]) == details["handler"][1]
    assert details["handler"][1] != details["initial_state"]
    wire = codec.dumps(graph)
    assert json.loads(wire)["schema_version"] == 18
    assert codec.loads(wire) == graph


def _admission_view(index, guard):
    report = index.protocol_obligations(guard["row"].scope, budget=65536)
    return next(row["predicate"] for scope in report["scopes"] for clause in scope["obligations"]
                for row in clause["rows"] if row["record"].operation == guard["predicate"])


@pytest.mark.parametrize("stage", ("suspended", "closed"))
@pytest.mark.parametrize("kind", tuple(RawRequestKind))
def test_suspended_closed_cells_have_real_phase_branch_known_raw_and_current_host_route(stage, kind):
    graph, details = generator_admission_program(stage=stage, kind=kind, send_none=False)
    require_valid(graph)
    index, guard = ProgramIndex(graph), details["guards"][0]
    view = _admission_view(index, guard)
    assert view["predicate"] == guard["row"]
    assert guard["row"].contract.subject.rule is (
        BodyStatePredicateRule.IS_SUSPENDED if stage == "suspended" else BodyStatePredicateRule.IS_CLOSED)
    assert view["bool_must_copy"] is True and view["state_support"]
    assert all(item["current"] is True for item in view["state_support"])
    caller = _op(graph, details["call"])
    raw = next(row for row in graph.raw_driver_requests if row.value == details["raw"])
    assert raw.kind is kind
    assert len(raw.operands) == (1 if kind in (RawRequestKind.SEND, RawRequestKind.THROW) else 0)
    assert next(use.value for use in caller.uses if use.id == caller.invoke_arguments[1]) == raw.value
    assert view["native_phase_verified"] is False
    assert view["source_runtime_verified"] is False and view["transformation_authorized"] is False
    if stage == "closed":
        assert not graph.body_drives and not graph.final_body_gates
        assert not graph.body_outcome_commits and not graph.no_body_finishes
        helper = _op(graph, details["processing"])
        flow = ProtocolFlow(graph)
        for number, terminal_id in enumerate(details["terminals"]):
            terminal = _op(graph, terminal_id)
            original = next(row.contract.result for row in graph.protocol_operations
                if row.operation == helper.id and row.slot == number)
            assert flow.forwards(original, OwnedUse(terminal.id, terminal.terminator.values[0])) is True
            assert not index.lifecycle_before(terminal.id).terminal.is_finished(details["owner_formals"][number])
        if kind is RawRequestKind.CLOSE:
            assert any(type(row.site) is InvokeLiteralResult and row.site.edge.operation == helper.id
                       and row.literal.to_python() is None for row in graph.literal_evaluations)
        if kind in (RawRequestKind.SEND, RawRequestKind.THROW):
            joint = index.request_input_binding(OwnedUse(helper.id, details["row"].contract.effective_request_use),
                OwnedUse(helper.id, details["operand_use"]), ordinal=0, budget=65536)
            assert joint["bindings"]
            assert all(item["definition"].kind is kind and item["ordinal"] == 0
                       for item in joint["bindings"])
            assert joint["runtime_identity_verified"] is False
    else:
        drive, = graph.body_drives
        assert type(drive.target) is BodyResume
        assert drive.resume_inputs and not graph.created_close_tests
        gates = [item for item in view["control_routes"]["frontiers"]
                 if item["kind"] == "FINAL_GATE" and item["edge"].successor_index == 0]
        assert gates
        if kind in (RawRequestKind.NEXT, RawRequestKind.SEND):
            assert all(item["target_compatible_at_snapshot"] is True for item in gates)
        else:
            assert all(item["target_compatible_at_snapshot"] is None for item in gates)
            assert "admission_gate_support_changed_or_unresolved" in view["gaps"]


def test_suspended_next_delivers_this_none_and_send_delivers_the_same_caller_ordinal_zero():
    for kind in (RawRequestKind.NEXT, RawRequestKind.SEND):
        graph, details = generator_admission_program(stage="suspended", kind=kind, send_none=False)
        require_valid(graph)
        index, drive = ProgramIndex(graph), graph.body_drives[0]
        source = OwnedUse(drive.operation, drive.resume_inputs[0].source)
        if kind is RawRequestKind.NEXT:
            assert ProtocolFlow(graph).forwards(OperationResult(OperationID("matrix.suspended.next.none"), 0), source) is True
            assert next(row.literal.to_python() for row in graph.literal_evaluations
                        if row.site == OperationResult(OperationID("matrix.suspended.next.none"), 0)) is None
            assert not next(row for row in graph.raw_driver_requests if row.value == details["raw"]).operands
        else:
            joint = index.request_input_binding(OwnedUse(drive.operation, drive.scheduler_request), source,
                                                ordinal=0, budget=65536)
            assert joint["bindings"]
            assert all(binding["definition"].kind is kind and binding["ordinal"] == 0
                       and binding["declared_operand_is_none"] is False for binding in joint["bindings"])
            assert joint["transformation_authorized"] is False


@pytest.mark.parametrize("propagates", (False, True))
def test_suspended_throw_current_normalized_packet_reaches_caught_yield_or_propagated_raise(propagates):
    graph, details = generator_admission_program(stage="suspended", kind=RawRequestKind.THROW,
                                               throw_propagates=propagates)
    require_valid(graph)
    drive, = graph.body_drives
    flow, index = ProtocolFlow(graph), ProgramIndex(graph)
    assert flow.forwards(details["normal_result"], OwnedUse(drive.operation, drive.resume_inputs[0].source)) is True
    raw = OwnedUse(details["processing"], details["raw_use"])
    operand = OwnedUse(details["processing"], next(row.contract.operand_bindings[0].operation_use
        for row in graph.protocol_operations if row.operation == details["processing"]))
    assert index.request_input_binding(raw, operand, budget=65536)["bindings"]
    sources = tuple(_op(graph, edge.source) for edge in _op(graph, drive.operation).terminator.successors)
    assert any(op.terminator.kind is (TerminatorKind.RAISE if propagates else TerminatorKind.SUSPEND)
               for op in sources)


@pytest.mark.parametrize("stage", ("suspended", "closed"))
@pytest.mark.parametrize("kind", tuple(RawRequestKind))
def test_each_later_cell_rejects_an_available_same_typed_other_bool(stage, kind):
    graph, details = generator_admission_program(stage=stage, kind=kind)
    require_valid(graph)
    guard = details["guards"][0]
    predicate = _op(graph, guard["predicate"])
    original = next(value for value in graph.values if value.id == predicate.results[0])
    wrong = DataValue(ValueID("matrix.other.phase.bool"), original.region, LiteralOrigin(True), "builtins.bool")
    graph = replace(graph, values=(*graph.values, wrong), operations=tuple(replace(op, uses=tuple(
        replace(use, value=wrong.id) if use.id == guard["condition_use"] else use for use in op.uses))
        if op.id == guard["branch"] else op for op in graph.operations))
    require_valid(replace(graph, protocol_scopes=(), protocol_operations=()))
    assert "admission_bool_source" in _codes(graph)


@pytest.mark.parametrize("stage", ("suspended", "closed"))
@pytest.mark.parametrize("kind", tuple(RawRequestKind))
def test_each_later_cell_cannot_reuse_prehelper_state_at_host(stage, kind):
    graph, details = generator_admission_program(stage=stage, kind=kind)
    require_valid(graph)
    index = ProgramIndex(graph)
    region = next(region for region in graph.regions if region.id == graph.driver_interfaces[0].region)
    entry = next(block for block in region.blocks if block.id == region.entry)
    old = {index.values[value].location: value for value in entry.arguments
           if isinstance(index.values[value], StateVersionValue)}
    if stage == "closed":
        terminal = _op(graph, details["terminals"][0])
    elif kind is RawRequestKind.CLOSE:
        terminal = _op(graph, details["normal_terminal"])
    else:
        edge = _op(graph, graph.body_drives[0].operation).terminator.successors[0]
        landing = next(block for region in graph.regions for block in region.blocks if block.id == edge.block)
        terminal = _op(graph, landing.operations[-1])
    changed = replace(terminal, uses=tuple(replace(use, value=old[index.values[use.value].location])
        if isinstance(index.values[use.value], StateVersionValue) else use for use in terminal.uses))
    graph = replace(graph, operations=tuple(changed if op.id == terminal.id else op for op in graph.operations))
    assert "stale_state" in _codes(graph)


@pytest.mark.parametrize("kind", tuple(RawRequestKind))
def test_closed_cannot_replay_the_old_same_typed_packet_or_return(kind):
    graph, details = generator_admission_program(stage="closed", kind=kind, send_none=False)
    require_valid(graph)
    guard = details["guards"][0]
    old = guard["admitted_map"][details["old_return"] if kind is RawRequestKind.CLOSE else details["old_packet"]]
    terminal = _op(graph, details["terminals"][0])
    graph = replace(graph, operations=tuple(replace(op, uses=tuple(replace(use, value=old)
        if use.id == terminal.terminator.values[0] else use for use in op.uses))
        if op.id == terminal.id else op for op in graph.operations))
    require_valid(replace(graph, protocol_scopes=(), protocol_operations=()))
    assert "protocol_copy" in _codes(graph)


@pytest.mark.parametrize("kind", tuple(RawRequestKind))
def test_suspended_host_cannot_replace_current_body_item_or_close_return_with_old_owner(kind):
    graph, details = generator_admission_program(stage="suspended", kind=kind)
    require_valid(graph)
    guard = details["guards"][0]
    old = guard["admitted_map"][graph.driver_interfaces[0].receiver]
    if kind is RawRequestKind.CLOSE:
        terminal = _op(graph, details["normal_terminal"])
    else:
        edge = _op(graph, graph.body_drives[0].operation).terminator.successors[0]
        landing = next(block for region in graph.regions for block in region.blocks if block.id == edge.block)
        terminal = _op(graph, landing.operations[-1])
    assert terminal.terminator.kind is TerminatorKind.RETURN
    graph = replace(graph, operations=tuple(replace(op, uses=tuple(replace(use, value=old)
        if use.id == terminal.terminator.values[0] else use for use in op.uses))
        if op.id == terminal.id else op for op in graph.operations))
    require_valid(replace(graph, protocol_scopes=(), protocol_operations=()))
    assert "protocol_copy" in _codes(graph)


@pytest.mark.parametrize("stage", ("suspended", "closed"))
@pytest.mark.parametrize("kind", (RawRequestKind.SEND, RawRequestKind.THROW))
def test_request_binding_cannot_join_an_independent_same_typed_caller_input(stage, kind):
    graph, details = generator_admission_program(stage=stage, kind=kind, send_none=False)
    require_valid(graph)
    index, call = ProgramIndex(graph), _op(graph, details["call"])
    region = next(region for region in graph.regions if region.id == call.callee)
    entry = next(block for block in region.blocks if block.id == region.entry)
    input_formal = (details["old_return"] if stage == "closed" else entry.arguments[2])
    position = entry.arguments.index(input_formal)
    use_id = call.invoke_arguments[position]
    independent_id = OperationID("matrix.calls.independent")
    independent = ReferenceValue(ValueID("matrix.calls.independent.value"), graph.root,
                                 OperationResult(independent_id, 0))
    producer = replace(_op(graph, OperationID("matrix.calls.argument")), id=independent_id,
                       results=(independent.id,))
    graph = replace(graph, values=(*graph.values, independent), operations=tuple(replace(op, uses=tuple(
        replace(use, value=independent.id) if use.id == use_id else use for use in op.uses))
        if op.id == call.id else op for op in graph.operations) + (producer,),
        regions=tuple(replace(item, blocks=tuple(replace(block,
            operations=(independent_id, *block.operations)) if call.id in block.operations else block
            for block in item.blocks)) if item.id == graph.root else item for item in graph.regions))
    require_valid(graph)
    index = ProgramIndex(graph)
    if stage == "suspended" and kind is RawRequestKind.SEND:
        drive, = graph.body_drives
        raw, supplied = OwnedUse(drive.operation, drive.scheduler_request), OwnedUse(drive.operation, drive.resume_inputs[0].source)
    else:
        helper = _op(graph, details["processing"])
        raw_id = (details["raw_use"] if stage == "suspended" else details["row"].contract.effective_request_use)
        operand_id = (next(row.contract.operand_bindings[0].operation_use
            for row in graph.protocol_operations if row.operation == helper.id)
            if stage == "suspended" else details["operand_use"])
        raw, supplied = OwnedUse(helper.id, raw_id), OwnedUse(helper.id, operand_id)
    result = index.request_input_binding(raw, supplied, budget=65536)
    assert not result["bindings"]
    assert "request_input_binding_unresolved" in {gap["code"] for gap in result["gaps"]}
    assert result["source_runtime_verified"] is False and result["transformation_authorized"] is False
