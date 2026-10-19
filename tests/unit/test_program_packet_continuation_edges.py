"""Bounded regressions for complete packet routes at existing protocol edges.

These checks consume the original lookup, matcher, pending, and host ports.  A
DECLARED continuation is a static supplied-CFG relation only; it is not native
applicability or evidence that the route executed.
"""
from dataclasses import replace

import pytest

from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.program.model import Operation, Behavior
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.protocol_continuations import continuation_connections
from scar.ir.program.protocol_packet_routes import packet_continuations
from scar.ir.program.protocols import OwnedUse
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid
from tests.fixtures.program_lookup_fallback_graphs import lookup_fallback_program
from tests.fixtures.program_packet_continuation_graphs import packet_continuation_program


def _context(graph, *, budget=65536):
    require_valid(graph)
    return ConnectionContext(graph, index=ProgramIndex(graph), budget=ValidityBudget(budget))


def _fallback_entry(report, details):
    obligation = next(row for row in report["obligations"]
                      if row["site"] == details["lookup"])
    return next(row for row in obligation["lookup_fallbacks"]
                if row["binding"] == details["fallback"])


def _assert_unproved(route):
    assert route["frontier_only"] is False
    assert route["source_runtime_verified"] is False
    assert route["runtime_identity_verified"] is False
    assert route["transformation_authorized"] is False


@pytest.mark.parametrize("kind", ("close", "throw"))
def test_fallback_e0_el_em_each_continue_to_its_selected_original_terminal(kind):
    graph, details = lookup_fallback_program(kind=kind, matcher="invoke")
    report = continuation_connections(_context(graph))
    entry = _fallback_entry(report, details)
    paths = {path["kind"]: path for path in entry["paths"]}
    assert set(paths) == {"MATCH", "NO_MATCH", "MATCHER_RAISE"}

    packet_targets = {
        name: OwnedUse(terminal.id, terminal.uses[0].id)
        for name, terminal in details["terminals"].items()
    }
    all_packet_targets = set(packet_targets.values())
    for name, target in packet_targets.items():
        route = paths[name]["continuation"]
        assert route["status"] == "DECLARED", route
        assert route["source"] == paths[name]["source"]
        assert target in route["targets"]
        assert all(other == target for other in route["targets"] if other in all_packet_targets)
        assert any(check["target"] == target and check["binding"]["match"] is True
                   for check in route["checks"]), route
        _assert_unproved(route)

    # E0 cannot borrow EL's good NO_MATCH route merely because both packets
    # have the same protocol type. Keep the exact lookup/matcher/branch guards.
    context = _context(graph)
    no_match = details["edges"]["NO_MATCH"]
    branch = context.operations[no_match.operation]
    choices = (
        ControlEdgeReference(details["lookup"].operation, details["lookup"].slot),
        details["matcher"].normal_result.edge,
        no_match,
    )
    wrong_source = packet_continuations(context, details["e0_source"],
        start=(branch.terminator.successors[no_match.successor_index].block, 0),
        choices=choices)
    no_match_target = packet_targets["NO_MATCH"]
    assert wrong_source["status"] == "CONTRADICTED", wrong_source
    assert any(check["target"] == no_match_target and check["binding"]["match"] is False
               for check in wrong_source["checks"]), wrong_source
    _assert_unproved(wrong_source)


def test_known_packet_helper_copy_does_not_hide_an_opaque_operation_inside_the_callee():
    graph, details = packet_continuation_program(two_cuts=True,
        complete_transitions=True, packet_helper="known")
    helper = details["packet_helper"]
    terminal = details["packet_helper_terminal"]
    opaque = Operation(
        id=type(helper.id)("packet.continuation.known-helper.opaque"),
        label="unknown helper effect before returning the packet",
        behaviors=(Behavior.COMPUTE,), effects_complete=False)
    regions = tuple(replace(region, blocks=tuple(
        replace(block, operations=(opaque.id, *block.operations))
        if terminal.id in block.operations else block
        for block in region.blocks)) if region.id == helper.callee else region
        for region in graph.regions)
    graph = replace(graph, regions=regions, operations=(*graph.operations, opaque))

    # The exact input-to-return copy remains present, but the helper's opaque
    # body prevents the surrounding packet continuation from becoming complete.
    report = continuation_connections(_context(graph))
    obligation = next(row for row in report["obligations"]
                      if row["site"].operation == details["helper"] and row["site"].slot == 1)
    route, = obligation["close_routes"]
    assert route["status"] == "PARTIAL", route
    helper_rows = tuple(row for row in route["helpers"]
                        if row["operation"].id == helper.id)
    assert helper_rows, route
    assert any(output["copied"] is True
               for row in helper_rows for output in row["outputs"]), helper_rows
    boundaries = list(route["boundaries"])
    for row in helper_rows:
        boundaries.extend(row.get("boundaries", ()))
    assert any(boundary["operation"].id == opaque.id
               and boundary["kind"] == "OPAQUE_OPERATION" for boundary in boundaries), route
    _assert_unproved(route)


def test_shared_budget_exhaustion_keeps_a_cursor_and_never_declares_a_complete_route():
    graph, details = lookup_fallback_program(kind="close", matcher="invoke")
    context = _context(graph, budget=1)
    match = details["edges"]["MATCH"]
    branch = context.operations[match.operation]
    choices = (
        ControlEdgeReference(details["lookup"].operation, details["lookup"].slot),
        details["matcher"].normal_result.edge,
        match,
    )
    route = packet_continuations(context, details["e0_source"],
        start=(branch.terminator.successors[match.successor_index].block, 0),
        choices=choices)
    assert route["status"] == "PARTIAL", route
    assert route["known_inventory_complete"] is False
    assert route["cursor"] is not None
    assert "packet_continuation_budget_exhausted" in route["gaps"]
    _assert_unproved(route)
