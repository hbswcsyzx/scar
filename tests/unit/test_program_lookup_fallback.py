"""Lookup fallback keeps independent original packets and every real route."""
from dataclasses import replace

import pytest

from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.program.exception_matches import BuiltinExceptionCategory, ExceptionHandlerOperand
from scar.ir.program.model import ExitKind, TerminatorKind
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.protocol_connections import DelegateLookupFallback, NormalizedThrowSource
from scar.ir.program.protocol_continuations import continuation_connections
from scar.ir.program.protocol_connection_validation import common_connections
from scar.ir.program.protocol_lookup_fallbacks import fallback_binding_issues
from scar.ir.program.protocols import OwnedUse, ProtocolCall
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_lookup_fallback_graphs import (
    lookup_fallback_program, lookup_fallback_receiver_merge_program,
)


def _bare_valid(graph):
    require_valid(replace(graph, protocol_bindings=tuple(row for row in graph.protocol_bindings
                  if type(row) is not DelegateLookupFallback)))


def _view(graph, *, budget=65536):
    require_valid(graph)
    index = ProgramIndex(graph)
    return continuation_connections(ConnectionContext(graph, index=index, budget=ValidityBudget(budget)))


def _lookup(view, details):
    return next(row for row in view["obligations"] if row["site"] == details["lookup"])


def _fallback(view, details):
    rows = _lookup(view, details).get("lookup_fallbacks", ())
    return next(row for row in rows if row["binding"] == details["fallback"])


def _codes(graph):
    _bare_valid(graph)
    return {issue.code for issue in validate(graph)}


def _binding(graph, details, **fields):
    binding = replace(details["fallback"], **fields)
    return replace(graph, protocol_bindings=tuple(binding if row == details["fallback"] else row
                                                  for row in graph.protocol_bindings)), {**details, "fallback": binding}


def _gap_codes(view):
    return {gap if isinstance(gap, str) else gap["code"] for gap in view["gaps"]}


def _no_authority(view):
    assert view["source_runtime_verified"] is False
    assert view["transformation_authorized"] is False
    assert all(value is False for key, value in view.items() if key.endswith("_verified"))


def _assert_paths(view, details):
    fallback = _fallback(view, details)
    assert fallback["matcher"] is details["matcher"]
    assert fallback["binding"] is details["fallback"]
    paths = {path["kind"]: path for path in fallback["paths"]}
    expected = ({"MATCHER_RAISE"} if details["matcher_mode"] == "raise-only" else
                {"MATCH", "NO_MATCH", "MATCHER_RAISE"} if details["matcher_mode"] == "invoke" else
                {"MATCH", "NO_MATCH"})
    assert set(paths) == expected
    sources = {"MATCH": details["e0_source"], "NO_MATCH": details["el_source"],
               "MATCHER_RAISE": details["em_source"]}
    for kind, path in paths.items():
        assert path["source"] == sources[kind]
        assert path["edge"] == details["edges"][kind]
        terminal = details["terminals"][kind]
        target = OwnedUse(terminal.id, terminal.uses[0].id)
        route = path["route"]
        assert target in route["targets"]
        assert route["checks"] and all(check["binding"]["match"] is True for check in route["checks"])
        assert any(check["target"] == target and check["kind"] == "HOST_RAISE" for check in route["checks"])
        assert route["status"] == "DECLARED" and route["cursor"] is None
        assert route["frontier_only"] is True
    _no_authority(fallback)
    return fallback


def test_lookup_raise_has_three_independent_fallback_packet_routes():
    """First red uses the existing continuation API, not a missing new API."""
    graph, details = lookup_fallback_program(kind="throw", matcher="invoke")
    _bare_valid(graph)
    report = _view(graph)
    obligation = _lookup(report, details)
    assert any(gap["code"] == "method_lookup_exception_category_unproved"
               and gap["path"] == str(details["lookup"]) for gap in report["gaps"])
    fallbacks = obligation.get("lookup_fallbacks", ())
    assert fallbacks, "real lookup/matcher consumers still lack independent fallback packet routes"
    fallback, = fallbacks
    assert fallback["matcher"] is details["matcher"]
    assert {path["kind"] for path in fallback["paths"]} == {"MATCH", "NO_MATCH", "MATCHER_RAISE"}


@pytest.mark.parametrize("kind", ("close", "throw"))
@pytest.mark.parametrize("matcher", ("ordinary", "invoke", "raise-only"))
def test_original_match_and_no_match_and_new_raise_use_independent_packet_sources(kind, matcher):
    graph, details = lookup_fallback_program(kind=kind, matcher=matcher)
    _bare_valid(graph)
    report = _view(graph)
    fallback = _assert_paths(report, details)
    assert details["e0"].id != details["el"].id
    if matcher != "ordinary":
        assert details["em"].id not in (details["e0"].id, details["el"].id)
        assert details["operation"].terminator.successors[0].kind is ExitKind.RAISE
    if matcher == "invoke":
        assert details["matcher"].normal_result.result.index == 1
        assert details["matcher"].normal_result.edge.successor_index == 1
    assert "method_lookup_exception_category_unproved" in _gap_codes(report)
    if kind == "throw":
        assert type(details["request"]) is NormalizedThrowSource
        assert "normalized_packet_source_unproved" in _gap_codes(fallback)


@pytest.mark.parametrize("arity", (1, 2, 3))
def test_throw_fallback_preserves_all_original_normal_method_arguments_and_independent_e0(arity):
    graph, details = lookup_fallback_program(kind="throw", matcher="invoke", throw_arity=arity)
    require_valid(graph)
    prior = details["prior"]
    assert len(prior["advance_rows"][0].contract.argument_uses) == arity
    assert len(prior["advance"]["operation"].invoke_arguments) == arity + 2
    raw, = graph.raw_driver_requests
    assert len(raw.operands) == arity
    marker = details["raw_marker"]
    assert details["raw"] == OwnedUse(marker.id, marker.uses[0].id)
    assert marker.uses[0].value == raw.value
    entry = next(block for block in graph.regions[0].blocks if block.id == graph.regions[0].entry)
    assert entry.operations.index(marker.id) < entry.operations.index(prior["lookup"]["operation"].id)
    _assert_paths(_view(graph), details)


@pytest.mark.parametrize("leg", ("MATCH", "NO_MATCH", "MATCHER_RAISE"))
def test_same_typed_original_lookup_and_matcher_packets_cannot_be_swapped_between_routes(leg):
    graph, details = lookup_fallback_program(kind="throw", matcher="invoke")
    if leg == "MATCHER_RAISE":
        target = details["terminals"][leg]
        changed = replace(target, uses=tuple(replace(use, value=details["el"].id)
            if use.id == target.uses[0].id else use for use in target.uses))
    else:
        target = details["branch"]
        edge = target.terminator.successors[0 if leg == "MATCH" else 1]
        wrong = details["el"] if leg == "MATCH" else details["e0"]
        changed = replace(target, uses=tuple(replace(use, value=wrong.id)
            if use.id == edge.arguments[0] else use for use in target.uses))
    graph = replace(graph, operations=tuple(changed if operation.id == changed.id else operation
                                            for operation in graph.operations))
    assert "protocol_lookup_fallback_packet" in _codes(graph)


def test_independent_e0_cannot_be_reselected_from_the_true_branch_actual():
    graph, details = lookup_fallback_program(kind="close", matcher="invoke")
    request = replace(details["request"], packet=details["wrong_e0_source"])
    graph, _ = _binding(graph, details, request=request)
    assert "protocol_lookup_fallback_packet" in _codes(graph)


def test_future_matcher_error_packet_cannot_be_the_original_injection_before_lookup():
    graph, details = lookup_fallback_program(kind="throw", matcher="invoke")
    request = replace(details["request"], packet=details["em_source"])
    graph, _ = _binding(graph, details, request=request)
    assert "protocol_lookup_fallback_source" in _codes(graph)


def test_known_reference_operand_cannot_stand_for_a_missing_external_raw_request():
    graph, details = lookup_fallback_program(kind="throw", matcher="invoke")
    lookup = details["lookup_row"]
    wrong = OwnedUse(lookup.operation, lookup.contract.receiver_use)
    request = replace(details["request"], raw=wrong)
    graph, _ = _binding(graph, details, request=request)
    assert "protocol_lookup_fallback_source" in _codes(graph)


def test_matching_a_declared_broader_category_does_not_authorize_attribute_missing_fallback():
    graph, details = lookup_fallback_program(kind="close", matcher="invoke")
    matcher = details["matcher"]
    assert type(matcher.handler) is ExceptionHandlerOperand
    interpretation = replace(matcher.handler.interpretation, category=BuiltinExceptionCategory.BASE_EXCEPTION)
    changed = replace(matcher, handler=replace(matcher.handler, interpretation=interpretation))
    graph = replace(graph, exception_matches=tuple(changed if row == matcher else row
                                                   for row in graph.exception_matches))
    assert "protocol_lookup_fallback_category" in _codes(graph)


def test_lookup_normal_bound_method_result_is_not_the_exception_source_for_fallback():
    graph, details = lookup_fallback_program(kind="throw", matcher="invoke")
    normal = details["prior"]["method_rows"][0]
    site = replace(details["lookup"], slot=normal.slot)
    graph, _ = _binding(graph, details, lookup=site)
    assert "protocol_lookup_fallback_site" in _codes(graph)


def test_same_kind_sibling_lookup_cannot_supply_another_lookups_matcher():
    graph, details = lookup_fallback_program(kind="throw", matcher="invoke", two_lookups=True)
    own = details["lookup_row"]
    sibling = next(row for row in graph.protocol_operations
        if type(row.contract) is ProtocolCall and row.contract.rule is own.contract.rule
        and row.operation != own.operation and row.slot == own.slot)
    site = replace(details["lookup"], operation=sibling.operation)
    graph, _ = _binding(graph, details, lookup=site)
    assert "protocol_lookup_fallback_site" in _codes(graph)


def test_an_accurate_preceding_iterator_normal_guard_keeps_all_three_source_routes():
    graph, details = lookup_fallback_program(kind="throw", matcher="invoke")
    guard = ControlEdgeReference(details["prior"]["lookup"]["operation"].id, 0)
    graph, details = _binding(graph, details, guard=guard)
    _bare_valid(graph)
    _assert_paths(_view(graph), details)


def test_lookup_cannot_claim_a_guard_whose_selected_raise_terminates_before_method_lookup():
    graph, details = lookup_fallback_program(kind="throw", matcher="invoke")
    guard = ControlEdgeReference(details["prior"]["lookup"]["operation"].id, 1)
    graph, _ = _binding(graph, details, guard=guard)
    assert "protocol_lookup_fallback_guard" in _codes(graph)


def test_deleting_optional_fallback_keeps_lookup_matcher_and_missing_binding_obligation():
    graph, details = lookup_fallback_program(kind="close", matcher="invoke", attach=False)
    report = _view(graph)
    obligation = _lookup(report, details)
    rows = obligation.get("lookup_fallbacks", ())
    assert rows and any(row["matcher"] is details["matcher"] and row["binding"] is None for row in rows)
    assert "lookup_fallback_binding_missing" in _gap_codes(report)


def test_deleting_matcher_attachment_keeps_the_real_operation_and_lookup_obligation():
    graph, details = lookup_fallback_program(kind="close", matcher="invoke")
    graph = replace(graph, exception_matches=())
    report = _view(graph)
    obligation = _lookup(report, details)
    assert obligation["site"] == details["lookup"]
    assert "lookup_fallback_matcher_missing" in _gap_codes(report)
    assert details["operation"] in graph.operations


def test_deleting_consumer_targets_does_not_erase_the_real_matcher_input_inventory():
    graph, details = lookup_fallback_program(kind="close", matcher="invoke")
    graph = replace(graph, protocol_result_consumers=tuple(replace(row, targets=())
        if row.site == details["lookup"] else row for row in graph.protocol_result_consumers))
    require_valid(graph)
    ctx = ConnectionContext(graph, index=ProgramIndex(graph), budget=ValidityBudget(65536))
    common = common_connections(ctx)
    consumer = next(row for row in common["consumers"] if row["site"] == details["lookup"])
    original = OwnedUse(details["matcher"].operation, details["matcher"].input_use)
    assert original in consumer["missing"] and original in consumer["targets"]
    assert _lookup(continuation_connections(ctx), details)["site"] == details["lookup"]


def test_tiny_budget_keeps_unchecked_lookup_slots_and_a_concrete_cursor():
    graph, details = lookup_fallback_program(kind="close", matcher="invoke")
    report = _view(graph, budget=1)
    assert report["cursor"]
    lookup = _lookup(report, details)
    assert lookup["site"] == details["lookup"] and lookup["status"] == "NOT_CHECKED"
    assert details["fallback"] in graph.protocol_bindings
    _no_authority(report)


def test_binding_port_resolution_budget_exhaustion_is_not_a_false_site_contradiction():
    graph, _ = lookup_fallback_program(kind='close', matcher='invoke')
    index = ProgramIndex(graph)
    ctx = ConnectionContext(graph, index=index, budget=ValidityBudget(1))
    assert fallback_binding_issues(ctx) == ()
    assert ctx.budget.truncated
    assert ctx.preparation['lookup_fallback_binding_rows'] == 1
    assert ctx.preparation['lookup_fallback_binding_sites'] == 1


def test_mutually_exclusive_receiver_cases_are_complete_tuples_not_one_impossible_and():
    graph, details = lookup_fallback_receiver_merge_program()
    _bare_valid(graph)
    index = ProgramIndex(replace(graph, protocol_bindings=()))
    ctx = ConnectionContext(index.graph, index=index, budget=ValidityBudget(65536))
    common = common_connections(ctx)
    actual = next(row for row in common["inputs"] if row["site"] == details["lookup"])
    assert len(actual["cases"]) == 2
    assert tuple(case["case"].guard for case in actual["cases"]) == details["receiver_guards"]
    assert all(case["correlation"]["match"] is True for case in actual["cases"])
    assert all(all(binding["match"] is True for binding in case["inputs"]) for case in actual["cases"])
    # Both canonical input cases are independently sound.  The fallback must
    # preserve their alternative coverage rather than require both guards.
    require_valid(graph)
    fallback = _assert_paths(_view(graph), details)
    assert len(fallback['input_cases']) == 2
    assert tuple(case['case'].guard for case in fallback['input_cases']) == details['receiver_guards']
    assert all(case['correlation']['match'] is True for case in fallback['input_cases'])
    assert all(all(report['match'] is True for report in case['inputs'])
               for case in fallback['input_cases'])
