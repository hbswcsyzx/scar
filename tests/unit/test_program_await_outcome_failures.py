"""Original invoke failure routes remain distinct and keep all result slots."""

from dataclasses import replace

from scar.ir.program.model import CompletionResult, InvokeLiteralResult
from scar.ir.program.protocols import HostTerminal, OwnedUse
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_await_outcome_failure_graphs import (
    await_outcome_failure_program, await_wrapper_outcome_failure_program,
)


def _report(graph, scope, *, budget=65536):
    return ProgramIndex(graph).protocol_obligations(
        scope, budget=budget)["connections"]["families"]["await"]


def _stage(path):
    value = path["stage"]
    return getattr(value, "value", value)


def _raise_path(report, details, stage):
    matches = tuple(path for path in report["failure_paths"]
        if path["scope"] == details["acquisition_scope"]
        and path["source_operation"] == details["get"].id
        and _stage(path) == stage)
    assert len(matches) == 1
    return matches[0]


def test_lookup_call_and_bool_rejection_failures_keep_distinct_prefixes_and_slots():
    graph, details = await_outcome_failure_program("qualification_reject")
    require_valid(graph)
    report = _report(graph, details["acquisition_scope"])

    lookup = _raise_path(report, details, "LOOKUP")
    call = _raise_path(report, details, "METHOD_CALL")
    rejected = _raise_path(report, details, "QUALIFICATION_REJECT")
    lookup_edge = ControlEdgeReference(details["helper_lookup"].id, 0)
    call_edge = ControlEdgeReference(details["helper_call"].id, 0)
    assert lookup["stage_operation"] == details["helper_lookup"].id
    assert lookup["edge"] == ControlEdgeReference(details["helper_lookup"].id, 1)
    assert lookup["choices"] == ()
    assert call["stage_operation"] == details["helper_call"].id
    assert call["edge"] == ControlEdgeReference(details["helper_call"].id, 1)
    assert lookup_edge in call["choices"]
    assert rejected["stage_operation"] == details["qualification_branch"].id
    assert rejected["edge"] == details["rejected_edge"]
    assert lookup_edge in rejected["choices"]
    assert call_edge in rejected["choices"]

    terminal, = tuple(item for item in rejected["terminals"]
                      if item["terminal"] == HostTerminal(details["helper_type_error"].id))
    raise_op = details["helper_type_error"]
    assert terminal["packet"] == OwnedUse(raise_op.id, raise_op.uses[0].id)
    assert terminal["binding"]["match"] is True

    parent_edge = ControlEdgeReference(details["get"].id, 1)
    signature = next(item for item in details["get"].completions
                     if item.kind.value == "RAISE")
    assert tuple(state["slot"] for state in terminal["states"]) == tuple(
        range(1, len(signature.types)))
    for state in terminal["states"]:
        slot = state["slot"]
        assert state["source"] == OwnedUse(raise_op.id, raise_op.uses[slot].id)
        assert state["target"] == InvokeLiteralResult(parent_edge, CompletionResult(slot))
        assert state["binding"]["match"] is True

    host = HostTerminal(details["get_failure"].id)
    assert any(item["actual"] == host for item in terminal["consumers"])
    assert report["source_runtime_verified"] is False
    assert report["transformation_authorized"] is False


def test_removing_parent_raise_consumer_keeps_the_consumer_obligation():
    graph, details = await_outcome_failure_program(
        "qualification_reject", omit_parent_raise_consumer=True)
    require_valid(graph)
    report = _report(graph, details["acquisition_scope"])
    rejected = _raise_path(report, details, "QUALIFICATION_REJECT")
    terminal, = tuple(item for item in rejected["terminals"]
                      if item["terminal"] == HostTerminal(details["helper_type_error"].id))

    host = HostTerminal(details["get_failure"].id)
    consumer, = tuple(item for item in terminal["consumers"] if item["actual"] == host)
    assert terminal["status"] != "DECLARED" or terminal["gaps"]


def test_get_own_raise_inventory_survives_missing_row_and_advance_metadata():
    graph, details = await_outcome_failure_program(
        "qualification_reject", omit_acquisition_raise_row=True,
        remove_success_metadata=True)
    require_valid(graph)
    report = _report(graph, details["acquisition_scope"])
    own_raise = tuple(path for path in report["failure_paths"]
        if path["scope"] == details["acquisition_scope"]
        and path["source_operation"] == details["get"].id
        and _stage(path) == "ACQUISITION_RAISE"
        and path["edge"] == ControlEdgeReference(details["get"].id, 1))
    assert len(own_raise) == 1
    assert own_raise[0]["stage_operation"] == details["get"].id
    assert own_raise[0]["acquisition"] is None
    assert own_raise[0]["status"] != "MISSING"
    inventory = report["failure_path_inventory"]
    assert inventory["enumerated_count"] >= 1
    assert inventory["checked_count"] >= 1


def test_wrapper_constructor_own_raise_is_inventoried_without_a_drive_link():
    graph, details = await_wrapper_outcome_failure_program(attach_link=False)
    require_valid(graph)
    report = _report(graph, details["construction_scope"])
    paths = tuple(path for path in report["failure_paths"]
        if path["scope"] == details["construction_scope"]
        and path["source_operation"] == details["constructor"].id
        and _stage(path) == "WRAPPER_CONSTRUCTION_RAISE")
    path, = paths
    assert path["acquisition"] is None
    assert path["edge"] == ControlEdgeReference(details["constructor"].id, 1)
    terminal, = tuple(item for item in path["terminals"]
                      if item["terminal"] == HostTerminal(details["get_failure"].id))
    assert terminal["packet"] == OwnedUse(details["get_failure"].id,
                                          details["get_failure"].uses[0].id)


def test_parent_raise_packet_cannot_be_declared_from_a_state_completion_slot():
    graph, details = await_outcome_failure_program(
        "qualification_reject", wrong_parent_packet_slot=True)
    # The original execution CFG and all state SSA remain valid; the bad
    # connection exists only in the await declaration.
    core_graph = replace(graph, protocol_scopes=(), protocol_operations=(),
        protocol_call_inputs=(), protocol_result_consumers=(), protocol_bindings=())
    require_valid(core_graph)
    assert "protocol_await_reference" in {issue.code for issue in validate(graph)}

