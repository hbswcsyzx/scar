"""Bounded edge cases for delegated lookup fallback packet frontiers.

These tests use original program ports and the real cleanup fixture.  They do
not claim that a packet frontier proves native normalization or dispatch.
"""
from dataclasses import replace

from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.program.cleanup import CleanupReplace
from scar.ir.program.ids import BlockID, OperationID, UseID
from scar.ir.program.model import (
    Behavior, BlockArgument, InvokeLiteralResult, Operation, OperationResult, Successor,
    Terminator, TerminatorKind, Use, UseRole,
)
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.protocol_continuations import continuation_connections
from scar.ir.program.protocol_connections import NormalizedThrowSource
from scar.ir.program.protocol_packet_routes import packet_frontiers
from scar.ir.program.protocols import (
    ContractResult, OwnedUse, StaticGapReason, StaticProtocolGap,
)
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid
from tests.fixtures.program_continuation_cleanup_graphs import continuation_close_cleanup_program
from tests.fixtures.program_lookup_fallback_graphs import lookup_fallback_program


def _context(graph, *, budget=65536):
    require_valid(graph)
    return ConnectionContext(graph, index=ProgramIndex(graph), budget=ValidityBudget(budget))


def _view(graph, *, budget=65536):
    return continuation_connections(_context(graph, budget=budget))


def _fallback(view, details):
    obligation = next(row for row in view["obligations"] if row["site"] == details["lookup"])
    return next(row for row in obligation.get("lookup_fallbacks", ())
                if row["binding"] == details["fallback"])


def _gap_codes(row):
    return {item if isinstance(item, str) else item["code"] for item in row["gaps"]}


def _issue_codes(row):
    return {item[0] if isinstance(item, tuple) else item["code"] for item in row["issues"]}


def test_opaque_packet_interposition_keeps_route_partial():
    graph, details = lookup_fallback_program(kind="close", matcher="invoke")
    match_edge = details["edges"]["MATCH"]
    branch = next(operation for operation in graph.operations if operation.id == match_edge.operation)
    target_id = branch.terminator.successors[match_edge.successor_index].block
    target = next(block for block in graph.regions[0].blocks if block.id == target_id)
    opaque_id = OperationID("fallback.opaque.packet.consumer")
    opaque_use = Use(UseID("fallback.opaque.packet"), target.arguments[0], UseRole.PROTOCOL)
    opaque = Operation(opaque_id, "opaque packet handling", (Behavior.COMPUTE,), (opaque_use,),
                       effects_complete=False)
    graph = replace(graph, operations=(*graph.operations, opaque),
                    regions=(replace(graph.regions[0], blocks=tuple(
                        replace(block, operations=(opaque_id, *block.operations))
                        if block.id == target_id else block for block in graph.regions[0].blocks)),))

    report = _view(graph)
    fallback = _fallback(report, details)
    path = next(row for row in fallback["paths"] if row["kind"] == "MATCH")
    assert path["route"]["status"] == "PARTIAL"
    assert "packet_route_intervening_call_unresolved" in _gap_codes(path["route"])
    assert path["route"]["frontier_only"] is True
    assert path["route"]["transformation_authorized"] is False


def test_match_route_backedge_keeps_frontier_partial_without_host_consumer():
    graph, details = lookup_fallback_program(kind="close", matcher="invoke")
    terminal = details["terminals"]["MATCH"]
    target_id = next(block.id for block in graph.regions[0].blocks
                     if terminal.id in block.operations)
    # The two original owned operands carry packet then current state back to
    # the same two block formals, preserving the graph's exact slot order.
    loop = replace(terminal, terminator=Terminator(TerminatorKind.JUMP, (
        Successor(target_id, tuple(use.id for use in terminal.uses)),)))
    graph = replace(graph, operations=tuple(loop if row.id == loop.id else row
                                            for row in graph.operations))

    report = _view(graph)
    fallback = _fallback(report, details)
    path = next(row for row in fallback["paths"] if row["kind"] == "MATCH")
    assert path["route"]["status"] == "PARTIAL"
    assert "packet_route_cycle_unresolved" in _gap_codes(path["route"])
    assert path["route"]["frontier_only"] is True
    assert path["route"]["targets"] == ()
    assert path["route"]["transformation_authorized"] is False


def test_lookup_and_matcher_result_reentry_is_cut_at_its_original_producer():
    graph, details = lookup_fallback_program(kind="close", matcher="invoke")
    ctx = _context(graph)
    sources = (details["el_source"], details["em_source"])
    for source in sources:
        operation_id = (source.operation if type(source) is ContractResult
                        else source.edge.operation if type(source) is InvokeLiteralResult
                        else source.operation)
        block_id = ctx.block_of[operation_id]
        route = packet_frontiers(ctx, source,
            start=(block_id, ctx.positions[operation_id]), cuts=(operation_id,))
        assert route["status"] == "PARTIAL"
        assert "packet_route_source_reevaluated" in route["gaps"]
        assert route["targets"] == ()
        assert route["frontier_only"] is True
        assert route["source_runtime_verified"] is False


def test_raw_throw_with_unknown_e0_and_original_guard_stays_partial():
    graph, details = lookup_fallback_program(kind="throw", matcher="invoke")
    unknown_packet = StaticProtocolGap(StaticGapReason.NATIVE_APPLICABILITY_UNPROVEN)
    request = NormalizedThrowSource(details["raw"], unknown_packet)
    guard = ControlEdgeReference(details["prior"]["lookup"]["operation"].id, 0)
    binding = replace(details["fallback"], request=request, guard=guard)
    graph = replace(graph, protocol_bindings=tuple(
        binding if row == details["fallback"] else row for row in graph.protocol_bindings))
    details = {**details, "fallback": binding}

    report = _view(graph)
    fallback = _fallback(report, details)
    assert fallback["status"] == "PARTIAL"
    assert "normalized_packet_source_unproved" in _gap_codes(fallback)
    assert "lookup_fallback_packet_source_unresolved" in _gap_codes(fallback)
    assert "protocol_lookup_fallback_guard" not in _issue_codes(fallback)
    assert fallback["transformation_authorized"] is False
    assert all(path["route"]["frontier_only"] is True for path in fallback["paths"])


def test_cleanup_replace_reports_active_new_raise_as_frontier_not_dispatch():
    graph, details = continuation_close_cleanup_program()
    source = BlockArgument(BlockID("finally.failed"), 0)
    ctx = _context(graph)
    values = {value.id: value for value in graph.values}
    # The original failed-block JUMP has incomplete effects and must remain an
    # opaque frontier. Start at the already reached cleanup action to inspect
    # its actual active replacement token without claiming that JUMP is known.
    replacement_block = ctx.block_of[details["replacement"]]
    route = packet_frontiers(ctx, source,
        start=(replacement_block, ctx.positions[details["replacement"]]))

    assert route["status"] == "PARTIAL"
    assert "packet_route_override_applicability_unproved" in route["gaps"]
    assert "packet_route_pending_continuation_unproved" in route["gaps"]
    assert route["frontier_only"] is True
    assert route["transformation_authorized"] is False
    assert len(route["overrides"]) == 1
    override = route["overrides"][0]
    assert type(override["action"]) is CleanupReplace
    assert override["action"].operation == details["replacement"]
    assert override["source_applicability_verified"] is False
    assert override["definition"].value == next(
        value.id for value in graph.values if value.origin == OperationResult(details["pending_pack"], 0))
    # The older pending return is not an input to this later replacement.
    assert all(source_row["definition"].value != next(
        definition.value for definition in graph.pending_completions
        if values[definition.value].origin == OperationResult(OperationID("finally.original"), 0))
        for target in route["targets"] if isinstance(target, dict)
        for source_row in target["sources"])


def test_cleanup_enter_uses_original_active_token_not_later_dead_pack():
    graph, details = continuation_close_cleanup_program()
    ctx = _context(graph)
    enter, = graph.cleanup_enters
    actual = OwnedUse(enter.operation, enter.pending)
    values = {value.id: value for value in graph.values}
    active = next(definition for definition in graph.pending_completions
                  if values[definition.value].origin == OperationResult(OperationID("finally.original"), 0))
    later = next(definition for definition in graph.pending_completions
                 if values[definition.value].origin == OperationResult(details["pending_pack"], 0))

    assert ctx.owned_use(enter.operation, enter.pending).value != later.value
    assert ctx.bind(OperationResult(OperationID("finally.original"), 0), actual)["match"] is True
    assert ctx.bind(OperationResult(details["pending_pack"], 0), actual)["match"] is False
    assert later.value != active.value

    # The packet frontier sees the actual CleanupEnter token and ignores the
    # later pack.  This token denotes a RETURN completion, so it is a known
    # non-packet C1 pending source rather than a successful packet dispatch.
    block_id = ctx.block_of[enter.operation]
    route = packet_frontiers(ctx, OperationResult(OperationID("finally.original"), 0),
        start=(block_id, ctx.positions[enter.operation]))
    entering = next(target for target in route["targets"]
                    if isinstance(target, dict) and target.get("action") == enter)
    assert tuple(source_row["definition"] for source_row in entering["sources"]) == (active,)
    assert route["status"] == "CONTRADICTED"
    assert any(check["kind"] == "C1_PENDING" and check["binding"]["match"] is False
               for check in route["checks"])
