"""Created/Running matrix over original ports; no dynamic/native equivalence claim."""
from dataclasses import replace

import pytest

from scar.ir.program.drivers import BodyStart, RawRequestKind
from scar.ir.program.ids import OperationID, UseID
from scar.ir.program.input_origins import input_origins
from scar.ir.program.model import ExitKind, OperationResult, StateVersionValue, TerminatorKind
from scar.ir.program.protocol_flow import ProtocolFlow
from scar.ir.program.protocols import AdmissionPredicate, BodyStateCondition, BodyStatePredicateRule, OwnedUse
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_generator_admission_graphs import generator_admission_program


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
    first, second = details["guards"]
    wrong_value = next(value for value in graph.values
                       if value.origin == first["row"].contract.result).id
    branch = _op(graph, second["branch"])
    malformed = replace(graph, operations=tuple(replace(op, uses=tuple(
        replace(use, value=wrong_value) if use.id == branch.terminator.condition else use
        for use in op.uses)) if op.id == branch.id else op for op in graph.operations))
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
