"""A correct first C1 handoff cannot discharge its later consumers."""
from dataclasses import replace

import pytest

from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.program.control import PendingPayload
from scar.ir.program.model import TerminatorKind
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.protocol_continuations import continuation_connections
from scar.ir.program.protocols import HostTerminal, OwnedUse
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.resumption import SuspendTerminator
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid
from tests.fixtures.program_packet_continuation_graphs import (
    packet_continuation_program, packet_port_branch_program,
)
from tests.fixtures.program_lookup_fallback_graphs import lookup_fallback_receiver_merge_program


def _core_valid(graph):
    require_valid(replace(graph, protocol_scopes=(), protocol_operations=(),
        protocol_call_inputs=(), protocol_result_consumers=(), protocol_bindings=()))


def _view(graph, *, budget=262144):
    index = ProgramIndex(graph)
    return continuation_connections(ConnectionContext(graph, index=index,
                                                       budget=ValidityBudget(budget)))


def _close_rows(report, details):
    rows = tuple(row for row in report["obligations"] if row["site"].operation == details["helper"])
    assert len(rows) == 2
    return rows


def _unproved(route):
    assert route["frontier_only"] is False
    assert route["source_runtime_verified"] is False
    assert route["runtime_identity_verified"] is False
    assert route["transformation_authorized"] is False


def _shared(graph, source, start, *, choices=(), budget=262144):
    from scar.ir.program.protocol_packet_routes import packet_continuations
    index = ProgramIndex(graph)
    return packet_continuations(ConnectionContext(graph, index=index, budget=ValidityBudget(budget)),
        source, start=start, choices=choices)


def test_close_route_does_not_stop_successfully_at_c1_before_a_later_opaque_operation():
    graph, details = packet_continuation_program(opaque_after_replace=True,
                                                 complete_transitions=True)
    _core_valid(graph)
    require_valid(graph)
    assert details["opaque"] is not None
    report = _view(graph)
    rows = _close_rows(report, details)
    routes = tuple(row["close_routes"][0] for row in rows)
    assert all(route["status"] == "PARTIAL" for route in routes), routes
    for route in routes:
        assert any(boundary["operation"].id == details["opaque"].id
                   and boundary["kind"] == "OPAQUE_OPERATION"
                   for boundary in route["boundaries"]), route
        assert route["gaps"]
        _unproved(route)
    assert report["source_runtime_verified"] is False
    assert report["transformation_authorized"] is False


@pytest.mark.parametrize("slot", (0, 1))
def test_close_selected_normal_and_raise_continue_through_real_c1_to_the_host_packet(slot):
    graph, details = packet_continuation_program(two_cuts=True, complete_transitions=True)
    _core_valid(graph)
    require_valid(graph)
    assert len(tuple(operation for operation in graph.operations
                     if type(operation.terminator) is SuspendTerminator)) == 2
    rows = _close_rows(_view(graph), details)
    selected = next(row for row in rows if row["site"].slot == slot)
    route, = selected["close_routes"]
    assert route["status"] == "DECLARED", route
    assert route["known_inventory_complete"] is True
    host_checks = tuple(check for check in route["checks"]
                        if check["target"] == details["host_packet"])
    assert host_checks and all(check["binding"]["match"] is True for check in host_checks), route
    assert details["host_packet"] in route["targets"]
    assert route["actions"]
    assert route["projections"]
    if slot == 1:
        # Only the RAISE packet is produced after the first cut; this asserts
        # its actual later cut, without claiming it existed before the first.
        assert route["suspensions"]
    assert all(type(check["target"]) is OwnedUse for check in route["checks"])
    _unproved(route)


def test_original_incomplete_transfer_scope_stays_partial_without_rewriting_the_old_fixture():
    graph, details = packet_continuation_program(two_cuts=True)
    _core_valid(graph)
    require_valid(graph)
    assert not details["declared_complete_transitions"]
    for row in _close_rows(_view(graph), details):
        route, = row["close_routes"]
        assert route["status"] == "PARTIAL", route
        assert route["gaps"]
        assert route["boundaries"]
        _unproved(route)


@pytest.mark.parametrize("kind", ("known", "unknown"))
def test_projected_packet_reaches_a_real_helper_and_only_an_exact_return_summary_can_continue(kind):
    graph, details = packet_continuation_program(two_cuts=True, complete_transitions=True,
                                                 packet_helper=kind)
    _core_valid(graph)
    require_valid(graph)
    helper = details["packet_helper"]
    assert helper.terminator.kind is TerminatorKind.INVOKE
    assert len(helper.terminator.successors) == 1
    assert (helper.callee is not None) is (kind == "known")
    routes = tuple(row["close_routes"][0] for row in _close_rows(_view(graph), details))
    for route in routes:
        if kind == "known":
            assert route["status"] == "DECLARED", route
            checks = tuple(check for check in route["checks"]
                           if check["target"] == details["host_packet"])
            assert checks and all(check["binding"]["match"] is True for check in checks), route
            assert details["host_packet"] in route["targets"]
        else:
            assert route["status"] == "PARTIAL", route
            assert any(boundary["operation"].id == helper.id and boundary["kind"] == "UNKNOWN_CALL"
                       for boundary in route["boundaries"]), route
        _unproved(route)


def test_selected_raise_port_does_not_visit_the_sibling_ports_wrong_packet():
    graph, details = packet_port_branch_program()
    _core_valid(graph)
    require_valid(graph)
    start = details["merge"].id, 0
    route = _shared(graph, details["expected"], start, choices=(details["guard_a"],))
    assert route["status"] == "DECLARED", route
    assert details["actual"] in route["targets"]
    dispatch = details["dispatch"].terminator
    assert all(type(edge.arguments[0]) is PendingPayload for edge in dispatch.successors)
    sibling_block = dispatch.successors[1].block
    sibling_operation_ids = {identity for region in graph.regions for block in region.blocks
                             if block.id == sibling_block for identity in block.operations}
    assert all(target.operation not in sibling_operation_ids for target in route["targets"]), route
    _unproved(route)


def test_another_selected_input_guard_cannot_borrow_the_good_sibling_packet_route():
    graph, details = packet_port_branch_program()
    _core_valid(graph)
    require_valid(graph)
    route = _shared(graph, details["expected"], (details["merge"].id, 0),
                    choices=(details["guard_b"],))
    assert route["status"] != "DECLARED", route
    assert not any(check["target"] == details["actual"] and check["binding"]["match"] is True
                   for check in route["checks"]), route
    _unproved(route)


def test_a_truncated_full_continuation_retains_a_cursor_and_cannot_close_its_consumer_inventory():
    graph, details = packet_continuation_program(two_cuts=True, complete_transitions=True)
    _core_valid(graph)
    require_valid(graph)
    row = details["rows"][1]
    operation = next(operation for operation in graph.operations if operation.id == row.operation)
    edge = operation.terminator.successors[row.slot]
    route = _shared(graph, row.contract.result, (edge.block, 0),
                    choices=(ControlEdgeReference(operation.id, row.slot),), budget=1)
    assert route["status"] != "DECLARED"
    assert route["known_inventory_complete"] is False
    assert route["cursor"]
    assert route["gaps"]
    _unproved(route)


def test_every_fallback_leg_keeps_both_receiver_cases_and_their_own_continuation_choices():
    """Input tuple correlation alone is not a per-case continuation receipt."""
    graph, details = lookup_fallback_receiver_merge_program()
    require_valid(graph)
    report = _view(graph)
    lookup = next(row for row in report["obligations"] if row["site"] == details["lookup"])
    fallback = next(row for row in lookup["lookup_fallbacks"]
                    if row["binding"] == details["fallback"])
    expected_cases = next(row.cases for row in graph.protocol_call_inputs
                          if row.site == details["lookup"])
    assert len(expected_cases) == 2
    assert {path["kind"] for path in fallback["paths"]} == {"MATCH", "NO_MATCH", "MATCHER_RAISE"}
    for path in fallback["paths"]:
        cases = path.get("continuation_cases", ())
        assert len(cases) == len(expected_cases), path
        assert tuple(item["case"] for item in cases) == expected_cases
        target_operation = details["terminals"][path["kind"]]
        target = OwnedUse(target_operation.id, target_operation.uses[0].id)
        for item in cases:
            own = item["case"].guard
            assert own in item["choices"]
            assert path["edge"] in item["choices"]
            assert sum(guard in item["choices"] for guard in details["receiver_guards"]) == 1
            route = item["continuation"]
            assert route["source"] == path["source"]
            assert route["status"] == "DECLARED", item
            assert route["known_inventory_complete"] is True
            assert target in route["targets"]
            assert any(check["target"] == target and check["binding"]["match"] is True
                       for check in route["checks"]), item
            _unproved(route)
