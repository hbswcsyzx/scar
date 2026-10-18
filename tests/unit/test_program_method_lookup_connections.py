"""Expanded method contracts must consume this lookup's original result."""
from dataclasses import replace

import pytest

from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.program.model import CompletionResult, InvokeLiteralResult, TerminatorKind
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.protocol_connection_validation import common_connections
from scar.ir.program.protocol_continuations import continuation_connections
from scar.ir.program.protocols import ContractResult, OwnedUse, ProtocolCallRule as CR
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_method_lookup_graphs import (
    method_lookup_loop_program, method_lookup_paired_program, method_lookup_program,
    prior_advance_case_program,
)


def _core_valid(graph):
    require_valid(replace(graph, protocol_scopes=(), protocol_operations=(),
                          protocol_call_inputs=(), protocol_result_consumers=()))


def _codes(graph):
    _core_valid(graph)
    return {issue.code for issue in validate(graph)}


def _context(graph, *, budget=131072):
    return ConnectionContext(graph, index=ProgramIndex(graph), budget=ValidityBudget(budget))


def _inputs(graph, operation, change):
    return replace(graph, protocol_call_inputs=tuple(change(row)
        if row.site.operation == operation else row for row in graph.protocol_call_inputs))


@pytest.mark.parametrize("request_kind", ("next", "send", "throw", "close"))
@pytest.mark.parametrize("formal", (False, True))
def test_method_own_normal_result_is_the_real_callable_receiver(request_kind, formal):
    graph, details = method_lookup_program(request=request_kind, receiver_formal=formal)
    require_valid(graph)
    context = _context(graph)
    report = continuation_connections(context)
    assert not report["issues"]
    call = details["advance"]["operation"]
    actual = next(use for use in call.uses if use.id == details["advance"]["receiver"])
    assert actual.value == details["method"]["normal_values"][0]
    assert actual.value != details["lookup"]["normal_values"][0]
    method = details["method"]["operation"]
    assert len(method.invoke_arguments) == 2  # iterator and original state, no fake raw argument
    assert tuple(edge.kind.value for edge in method.terminator.successors) == ("NORMAL", "RAISE")
    normal = next(row for row in report["obligations"]
        if row["site"].operation == method.id and row["site"].slot == 0)
    assert normal["method_call_consumers"]
    assert all(case["match"] is True for consumer in normal["method_call_consumers"]
               for case in consumer["cases"])
    failure = details["method_failure"]
    assert failure.terminator.kind is TerminatorKind.RAISE
    assert failure.uses[0].value == details["method"]["failure_values"][0]
    assert {gap["code"] for gap in report["gaps"]} >= {"method_lookup_exception_category_unproved"}
    assert report["source_runtime_verified"] is False
    assert report["transformation_authorized"] is False
    assert not graph.body_drives and not graph.frame_context_attaches


@pytest.mark.parametrize("arity", (1, 2, 3))
def test_bound_throw_call_still_uses_every_original_raw_ordinal(arity):
    graph, details = method_lookup_program(request="throw", throw_arity=arity)
    require_valid(graph)
    call = details["advance"]["operation"]
    assert len(call.invoke_arguments) == arity + 2
    assert len(details["method"]["operation"].invoke_arguments) == 2
    declaration = next(row for row in graph.protocol_call_inputs if row.site.operation == call.id)
    assert tuple(source.ordinal for source in declaration.cases[0].arguments) == tuple(range(arity))


@pytest.mark.parametrize("wrong", ("iterator", "raise", "other_lookup", "wrong_kind"))
def test_same_type_or_completion_substitutions_do_not_choose_the_expected_lookup_from_actual(wrong):
    graph, details = method_lookup_program(request="send", two_lookups=wrong == "other_lookup")
    if wrong == "wrong_kind":
        selected = {row.operation for row in details["method_rows"]}
        graph = replace(graph, protocol_operations=tuple(replace(row,
            contract=replace(row.contract, rule=CR.DELEGATE_NEXT_LOOKUP))
            if row.operation in selected else row for row in graph.protocol_operations))
    else:
        row = details["method_rows"][1] if wrong == "raise" else None
        source = (details["iterator_source"] if wrong == "iterator" else
                  ContractResult(row.scope, row.clause, row.operation, row.slot, row.contract.result)
                  if wrong == "raise" else next(row.cases[0].receiver for row in graph.protocol_call_inputs
                    if row.site.operation == details["all_methods"][0]["operation"].id))
        if wrong == "other_lookup":
            first = next(row for row in graph.protocol_operations
                if row.operation == details["all_methods"][0]["operation"].id and row.slot == 0)
            source = ContractResult(first.scope, first.clause, first.operation, first.slot, first.contract.result)
        graph = _inputs(graph, details["advance"]["operation"].id,
            lambda row: replace(row, cases=tuple(replace(case, receiver=source) for case in row.cases)))
    assert {"protocol_input_source", "protocol_continuation_source",
            "protocol_method_lookup_kind", "protocol_method_lookup_consumer"} & _codes(graph)


def test_lookup_receiver_is_its_independent_iterator_not_an_unrelated_same_typed_root():
    from scar.ir.program.ids import BlockID
    from scar.ir.program.model import BlockArgument
    graph, details = method_lookup_program(request="send")
    graph = _inputs(graph, details["method"]["operation"].id, lambda row: replace(row,
        cases=tuple(replace(case, receiver=BlockArgument(BlockID("continuation.entry"), 1))
                    for case in row.cases)))
    assert "protocol_input_source" in _codes(graph)


def test_lookup_cannot_export_a_state_result_as_the_bound_method():
    graph, details = method_lookup_program()
    normal = details["method_rows"][0]
    bad = replace(normal, contract=replace(normal.contract, result=InvokeLiteralResult(
        ControlEdgeReference(normal.operation, 0), CompletionResult(1))))
    graph = replace(graph, protocol_operations=tuple(bad if row == normal else row
                                                   for row in graph.protocol_operations))
    assert {"protocol_result_owner", "protocol_continuation_role", "protocol_continuation_port"} & _codes(graph)


def test_deleting_method_inputs_or_consumer_targets_keeps_the_known_lookup_obligations():
    graph, details = method_lookup_program(request="send")
    method_id = details["method"]["operation"].id
    graph = replace(graph, protocol_call_inputs=tuple(row for row in graph.protocol_call_inputs
        if row.site.operation != method_id), protocol_result_consumers=tuple(replace(row, targets=())
        if row.site.operation == method_id else row for row in graph.protocol_result_consumers))
    require_valid(graph)
    context = _context(graph)
    common = common_connections(context)
    assert len([row for row in common["inputs"]
        if row["site"].operation == method_id and row["status"] == "MISSING"]) == 2
    outputs = [row for row in common["consumers"] if row["site"].operation == method_id]
    assert len(outputs) == 2 and all(row["targets"] and row["missing"] for row in outputs)
    report = continuation_connections(context)
    assert len([row for row in report["obligations"] if row["site"].operation == method_id]) == 2


def test_independent_lookups_on_real_branches_keep_method_receiver_and_raw_operand_paired():
    graph, details = method_lookup_paired_program()
    require_valid(graph)
    context = _context(graph, budget=524288)
    report = common_connections(context)
    calls = [row for row in report["inputs"] if row["site"].operation == details["call"]["operation"].id]
    assert len(calls) == 2 and all(len(row["cases"]) == 2 for row in calls)
    assert all(case["joint"] for row in calls for case in row["cases"])
    view = continuation_connections(context)
    assert not view["issues"]
    normal = [row for row in view["obligations"]
        if row["site"].operation in {method["operation"].id for method in details["methods"]}
        and row["site"].slot == 0]
    assert len(normal) == 2 and all(row["method_call_consumers"] for row in normal)


def test_crossed_same_kind_method_sources_from_opposite_branch_are_rejected():
    graph, _ = method_lookup_paired_program(crossed=True)
    assert {"protocol_input_source", "protocol_method_lookup_consumer"} & _codes(graph)


@pytest.mark.parametrize("stale", (False, True))
def test_reexecuted_lookup_cannot_use_last_iteration_bound_method(stale):
    graph, _ = method_lookup_loop_program(stale=stale)
    if stale:
        assert "protocol_input_source" in _codes(graph)
    else:
        require_valid(graph)
        assert not continuation_connections(_context(graph))["issues"]


def test_expanded_initial_next_uses_lookup_iterator_not_bound_method_as_marker():
    graph, details = method_lookup_program(initial=True)
    require_valid(graph)
    report = continuation_connections(_context(graph))
    assert not report["issues"]
    initial = next(row for row in graph.protocol_call_inputs
        if row.site.operation == details["advance"]["operation"].id).cases[0]
    assert initial.trigger.iterator != initial.receiver
    # Lookup is an opaque callback boundary, so the first-step applicability
    # remains partial even though the independent iterator ports are correct.
    assert any(gap["code"] == "continuation_source_unresolved" for gap in report["gaps"])


def test_budget_does_not_drop_method_sites_or_grant_an_empty_complete_inventory():
    graph, details = method_lookup_program(request="throw")
    context = _context(graph, budget=1)
    report = continuation_connections(context)
    assert report["cursor"] is not None
    methods = [row for row in report["obligations"]
               if row["site"].operation == details["method"]["operation"].id]
    assert len(methods) == 2 and all(row["status"] == "NOT_CHECKED" for row in methods)
    assert context.budget.truncated is True


def test_conditional_prior_advance_must_false_is_not_proof_that_no_case_advanced_this_iterator():
    graph, details = prior_advance_case_program()
    _core_valid(graph)
    require_valid(graph)
    context = _context(graph)
    receiver = OwnedUse(details["send"]["operation"].id, details["send"]["receiver"])
    source = details["sources"][0]
    assert context.bind(source, receiver)["match"] is False
    assert context.bind(source, receiver, guard=details["guards"][0])["match"] is True
    assert context.bind(source, receiver, guard=details["guards"][1])["match"] is False
    report = continuation_connections(_context(graph))
    following = [row for row in report["obligations"]
                 if row["site"].operation == details["following"]["operation"].id]
    assert len(following) == 2
    assert all(row["status"] != "DECLARED" for row in following)
    assert any(gap["code"] == "continuation_source_unresolved" for gap in report["gaps"])
