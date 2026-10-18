"""Original matcher/control connections, not native except/fallback proof."""
from dataclasses import replace

import pytest

from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.program.exception_matches import ExceptionHandlerOperand, FixedBuiltinHandler
from scar.ir.program.model import (
    CompletionResult, ExitKind, InvokeLiteralResult, OperationResult, TerminatorKind,
)
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.protocol_continuations import continuation_connections
from scar.ir.program.protocols import OwnedUse
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.state_addresses import ExistingAccess
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_exception_match_graphs import (
    exception_match_program, lookup_exception_match_program,
)


def _continuations(graph, *, budget=32768):
    index = ProgramIndex(graph)
    return continuation_connections(ConnectionContext(graph, index=index,
                                                       budget=ValidityBudget(budget)))


def _lookup(view, details):
    return next(row for row in view["obligations"] if row["site"] == details["consumer_site"])


def _bare_valid(graph):
    require_valid(replace(graph, exception_matches=()))


def _codes(graph):
    _bare_valid(graph)
    return {issue.code for issue in validate(graph)}


def _change_matcher(graph, **fields):
    matcher, = graph.exception_matches
    return replace(graph, exception_matches=(replace(matcher, **fields),))


def _no_authority(view):
    assert view["source_runtime_verified"] is False
    assert view["runtime_identity_verified"] is False
    assert view["native_applicability_verified"] is False
    assert view["transformation_authorized"] is False


def test_lookup_raise_has_a_real_matcher_consumer_before_category_or_fallback_proof():
    """The first red is an old connection gap, not an absent new query API."""
    graph, details = lookup_exception_match_program()
    _bare_valid(graph)
    require_valid(graph)
    view = _continuations(graph)
    obligation = _lookup(view, details)
    assert any(gap["code"] == "method_lookup_exception_category_unproved"
               and gap["path"] == str(details["consumer_site"]) for gap in view["gaps"])
    matches = obligation.get("method_exception_matches", ())
    assert matches, "the real lookup RAISE consumer is a matcher, not a proven missing-method fallback"
    connected, = matches
    assert connected["matcher"] is details["matcher"]
    assert connected["input_binding"]["match"] is True
    assert connected["report"]["normal"]["result"] == details["matcher"].normal_result
    _no_authority(connected["report"])


@pytest.mark.parametrize("input_kind", ("reference", "packet"))
@pytest.mark.parametrize("mode", ("ordinary", "invoke", "raise-only"))
def test_original_fixed_dynamic_and_only_raise_matchers_keep_every_real_port(mode, input_kind):
    graph, details = exception_match_program(mode=mode, input_kind=input_kind)
    _bare_valid(graph)
    require_valid(graph)
    row = details["matcher"]
    view = ProgramIndex(graph).exception_match(row.operation)
    assert view["matcher"] is row and not view["issues"]
    assert len(view["inputs"]) == (1 if mode == "ordinary" else 2)
    assert all(binding["match"] is True for binding in view["inputs"])
    assert view["correlation"]["match"] is True
    _no_authority(view)
    if mode == "ordinary":
        assert type(row.handler) is FixedBuiltinHandler
        assert len(details["operation"].uses) == 2  # no imaginary handler operand
        assert row.normal_result == OperationResult(row.operation, 0)
        assert row.raise_result is None and view["raised"] is None
        support, = view["state_support"]
        assert support["access"] is details["operation"].accesses[0]
        assert support["before"] == OwnedUse(row.operation, details["operation"].accesses[0].before)
        assert support["after"] is None
    else:
        assert type(row.handler) is ExceptionHandlerOperand
        assert details["handler_use"].id in details["operation"].invoke_arguments
        assert view["raised"]["result"] == row.raise_result
        assert view["raised"]["port"].values == (details["raised_packet"].id,)
        assert row.raise_result.edge.successor_index == 0 and row.raise_result.result.index == 1
        support, = view["state_support"]
        assert support["before"] == OwnedUse(row.operation, row.state_sites[0].state_use)
        assert {item["kind"] for item in support["completions"]} == (
            {ExitKind.RAISE} if mode == "raise-only" else {ExitKind.NORMAL, ExitKind.RAISE})
        assert all(item["result"].result.index == 0 for item in support["completions"])
    if mode == "raise-only":
        assert row.normal_result is None and row.branch is None
        assert view["normal"] is None and view["bool_binding"] is None
        assert view["branches"] == () and details["bool"] is None
        assert tuple(edge.kind for edge in details["operation"].terminator.successors) == (ExitKind.RAISE,)
    else:
        assert view["bool_binding"]["match"] is True
        assert view["normal"]["port"].values == (details["bool"].id,)
        assert tuple(item["truth"] for item in view["branches"]) == (True, False)
        assert tuple(item["successor"] for item in view["branches"]) == details["branch"].terminator.successors
        if mode == "invoke":
            assert row.normal_result.edge.successor_index == 1 and row.normal_result.result.index == 1
            assert details["bool"].origin.index == 2
            assert details["operation"].terminator.successors[1].arguments[0] != CompletionResult(0)


def test_wrong_same_typed_exception_source_is_a_known_connection_error():
    graph, details = exception_match_program(mode="invoke", input_kind="packet")
    graph = _change_matcher(graph, source=details["wrong_input"].origin)
    assert "exception_match_source" in _codes(graph)


def test_wrong_same_typed_handler_source_is_not_chosen_from_the_actual_operand():
    graph, details = exception_match_program(mode="invoke")
    handler = replace(details["matcher"].handler, source=details["wrong_handler"].origin)
    graph = _change_matcher(graph, handler=handler)
    assert "exception_match_handler" in _codes(graph)


def test_matcher_cannot_use_its_own_future_raise_result_to_justify_its_input():
    graph, details = exception_match_program(mode="invoke", input_kind="packet")
    graph = _change_matcher(graph, source=details["raised"])
    assert "exception_match_source" in _codes(graph)


def test_unrelated_bool_cannot_replace_the_real_normal_result_at_the_branch():
    graph, details = exception_match_program(mode="invoke")
    branch = details["branch"]
    changed = replace(branch, uses=tuple(replace(use, value=details["wrong_bool"].id)
        if use.id == branch.terminator.condition else use for use in branch.uses))
    graph = replace(graph, operations=tuple(changed if operation.id == changed.id else operation
                                            for operation in graph.operations))
    assert "exception_match_bool_source" in _codes(graph)


@pytest.mark.parametrize("which", ("normal", "raised"))
def test_state_completion_slot_cannot_masquerade_as_bool_or_new_packet(which):
    graph, details = exception_match_program(mode="invoke")
    original = details[which]
    wrong = InvokeLiteralResult(original.edge, CompletionResult(0))
    graph = _change_matcher(graph, **{("normal_result" if which == "normal" else "raise_result"): wrong})
    assert "exception_match_result" in _codes(graph)


@pytest.mark.parametrize("which", ("normal", "raised"))
def test_existing_completion_cannot_be_deleted_from_the_matcher_denominator(which):
    graph, _ = exception_match_program(mode="invoke")
    fields = {"raise_result": None} if which == "raised" else {"normal_result": None, "branch": None}
    graph = _change_matcher(graph, **fields)
    assert "exception_match_completions" in _codes(graph)


@pytest.mark.parametrize("wrong_site", ("missing", "another_read"))
def test_actual_matcher_state_inputs_cannot_be_omitted_or_replaced_by_another_operation(wrong_site):
    graph, details = exception_match_program()
    sites = () if wrong_site == "missing" else (ExistingAccess(details["probe"].id, 0),)
    graph = _change_matcher(graph, state_sites=sites)
    assert "exception_match_state" in _codes(graph)


def test_packet_source_and_exception_reference_roles_cannot_be_silently_interchanged():
    graph, details = exception_match_program(mode="invoke", input_kind="packet")
    graph = _change_matcher(graph, source=details["handler"].origin)
    assert "exception_match_source" in _codes(graph)


def test_edge_forward_use_is_not_a_dynamic_handler_invocation_argument():
    graph, details = exception_match_program(mode="invoke")
    forwarded = details["operation"].terminator.successors[1].arguments[0]
    assert forwarded not in details["operation"].invoke_arguments
    handler = replace(details["matcher"].handler, use=forwarded, source=details["input"].origin)
    graph = _change_matcher(graph, handler=handler)
    assert "exception_match_handler" in _codes(graph)


def test_only_raise_uses_new_packet_and_current_raise_state_not_the_original_input():
    graph, details = exception_match_program(mode="raise-only", input_kind="packet")
    require_valid(graph)
    terminal = next(operation for operation in graph.operations
                    if operation.terminator is not None and operation.terminator.kind is TerminatorKind.RAISE)
    assert terminal.uses[0].value == details["raised_packet"].id != details["input"].id
    assert terminal.uses[1].value == details["raised_state"].id != details["initial_state"].id
    report = ProgramIndex(graph).exception_match(details["matcher"].operation)
    assert report["raised"]["consumers"] is not None and not report["issues"]
    _no_authority(report)


def test_known_callee_invoke_matcher_preserves_its_real_normal_and_raise_ports():
    graph, details = exception_match_program(mode="invoke", input_kind="packet", known_callee=True)
    _bare_valid(graph)
    # A legitimate original known-callee INVOKE is not an ordinary CALL and
    # must not be excluded by the attachment's primitive-only ordinary rule.
    require_valid(graph)
    operation = details["operation"]
    assert operation.callee == details["callee"].id
    assert tuple(edge.kind for edge in operation.terminator.successors) == (ExitKind.RAISE, ExitKind.NORMAL)
    report = ProgramIndex(graph).exception_match(operation.id)
    assert not report["issues"] and report["bool_binding"]["match"] is True
    assert report["normal"]["port"].values == (details["bool"].id,)
    assert report["raised"]["port"].values == (details["raised_packet"].id,)
    assert details["callee_normal"].terminator.kind is TerminatorKind.RETURN
    assert details["callee_raised"].terminator.kind is TerminatorKind.RAISE
    assert details["callee_raised"].uses[0].value == details["callee_after"].id
    _no_authority(report)


def test_complete_matcher_retains_forwarded_current_state_ports_on_each_original_edge():
    graph, details = exception_match_program(mode="invoke", input_kind="packet", forward_state=True)
    _bare_valid(graph)
    require_valid(graph)
    operation = details["operation"]
    assert operation.effects_complete is True
    assert all(len(signature.types) == 1 for signature in operation.completions)
    blocks = {block.id: block for region in graph.regions for block in region.blocks}
    values = {value.id: value for value in graph.values}
    expected = []
    for index, edge in enumerate(operation.terminator.successors):
        # These state carriers are original forwarded Uses, not logical
        # produced completion slots.  The bool/packet slot has another role.
        actual, formal = next((actual, formal) for actual, formal in
            zip(edge.arguments, blocks[edge.block].arguments)
            if getattr(values[formal], "location", None) == graph.locations[0].id)
        assert actual not in operation.invoke_arguments
        expected.append((ControlEdgeReference(operation.id, index), edge.kind, actual, formal))
    assert expected[0][2] != expected[1][2]
    report = ProgramIndex(graph).exception_match(operation.id)
    support, = report["state_support"]
    completions = support["completions"]
    assert len(completions) == 2, "forwarded current state ports are still part of the N/R denominator"
    for observed, (edge, kind, argument, formal) in zip(completions, expected):
        assert observed["edge"] == edge and observed["kind"] is kind
        assert observed["formal"] == formal and observed["argument"] == argument
        assert observed["result"] is None
        assert observed["source"] == OwnedUse(operation.id, argument)
    assert report["bool_binding"]["match"] is True and not report["issues"]
    _no_authority(report)


def test_deleting_match_attachment_preserves_lookup_raise_and_original_consumer_obligation():
    graph, details = lookup_exception_match_program(attach=False)
    require_valid(graph)
    view = _continuations(graph)
    obligation = _lookup(view, details)
    assert obligation["site"] == details["consumer_site"]
    assert not obligation.get("method_exception_matches", ())
    assert any(gap["code"] == "method_lookup_exception_category_unproved"
               and gap["path"] == str(details["consumer_site"]) for gap in view["gaps"])
    matcher_use = OwnedUse(details["operation"].id, details["input_use"].id)
    consumer, = (row for row in graph.protocol_result_consumers if row.site == details["consumer_site"])
    assert consumer.targets == (matcher_use,)  # the unclassified real consumer was not erased


def test_budget_one_cannot_turn_an_unchecked_dynamic_input_or_bool_route_into_success():
    graph, details = exception_match_program(mode="invoke", input_kind="packet")
    require_valid(graph)
    report = ProgramIndex(graph).exception_match(details["matcher"].operation, budget=1)
    assert report["matcher"] is details["matcher"]
    assert report["budget"]["limit"] == 1 and report["budget"]["used"] <= 1
    assert report["budget"]["truncated"] is True and report["cursor"]
    assert report["gaps"]
    assert report["status"] not in ("DECLARED", "MATCHED")
    assert all(item["match"] is not True for item in report["inputs"])
    assert report["bool_binding"] is None or report["bool_binding"]["match"] is not True
    assert report["normal"]["result"] == details["normal"]
    assert report["raised"]["result"] == details["raised"]
    _no_authority(report)


@pytest.mark.parametrize("budget,error", ((True, TypeError), (0, ValueError)))
def test_invalid_match_budget_is_not_an_authority_switch(budget, error):
    graph, details = exception_match_program()
    index = ProgramIndex(graph)
    with pytest.raises(error):
        index.exception_match(details["matcher"].operation, budget=budget)


@pytest.mark.parametrize('declaration', ('gap', 'fact'))
def test_unverified_builtin_applicability_stays_an_explicit_query_gap(declaration):
    from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
    graph, details = exception_match_program()
    handler = details['matcher'].handler
    if declaration == 'fact':
        fact = ProviderFactReference(ProviderArtifact('memory://handler-declaration',
            '0' * 64, 0, 'unverified-handler-declaration'), 'handler')
        handler = replace(handler, applicability=fact)
        graph = _change_matcher(graph, handler=handler)
    require_valid(graph)
    report = ProgramIndex(graph).exception_match(details['operation'].id)
    assert all(item['match'] is True for item in report['inputs'])
    assert report['bool_binding']['match'] is True
    assert report['status'] == 'PARTIAL'
    assert 'exception_match_builtin_applicability_unproved' in report['gaps']
    assert report['handler_interpretation'].applicability == handler.applicability
    _no_authority(report)


def test_whole_query_budget_keeps_the_matcher_inventory_and_partial_completion_ports():
    graph, details = exception_match_program(mode='invoke', input_kind='packet')
    report = ProgramIndex(graph).protocol_obligations(budget=1)
    matchers = report['connections']['families']['exception_matches']
    assert report['budget']['used'] <= 1 and report['budget']['truncated']
    assert matchers['supplied_matcher_count'] == 1
    assert matchers['known_inventory_complete'] is False and matchers['cursor']
    assert matchers['unexamined_matcher_count'] + len(matchers['obligations']) == 1
    assert matchers['gaps'] and matchers['transformation_authorized'] is False
    for partial in matchers['obligations']:
        assert partial['matcher'] is details['matcher']
        assert partial['normal']['result'] == details['normal']
        assert partial['raised']['result'] == details['raised']
        assert partial['status'] != 'DECLARED'
