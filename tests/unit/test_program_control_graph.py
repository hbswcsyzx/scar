"""Core composition checks for cleanup and language completion protocols.

These graphs are hand-authored structural models.  Passing validation does not
prove source recovery, cleanup execution, exception unwinding, or runtime
identity.
"""
from dataclasses import replace

import pytest

from scar.ir.program import (
    Behavior, Block, BlockArgument, BlockID, ControlPort, ControlPortID,
    ControlScope, ControlScopeID, ControlScopeKind, DataValue, ExitPort,
    LanguageCompletionKind, Operation, OperationID, OperationResult,
    PendingCompletionDefinition, PendingDispatchTerminator, PendingPayload,
    PendingSuccessor, ProgramGraph, ProtocolValue, ProtocolValueKind,
    RegionID, ReferenceValue, StateVersionValue, Use, UseID, UseRole, ValueID,
    ValueKind, ValueType, dumps, loads,
)
from scar.ir.program.control import ExceptionPacketDefinition
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_control_graphs import (
    loop_pending_graph, loop_transfer_graph, shared_pending_graph,
)


def _issue_codes(graph):
    return {issue.code for issue in validate(graph)}


def _rejected(graph, *expected):
    codes = _issue_codes(graph)
    assert codes, "malformed graph unexpectedly passed validation"
    assert set(expected) <= codes, f"expected {expected}, got {sorted(codes)}"


def _replace_operation(graph, identity, transform):
    return replace(graph, operations=tuple(
        transform(item) if item.id == identity else item for item in graph.operations))


def _operation(graph, identity):
    return next(item for item in graph.operations if item.id == OperationID(identity))


def _with_entry_packet(graph):
    """Inject a well-formed packet that dominates the cleanup dispatch."""
    region = graph.regions[0]
    entry = next(block for block in region.blocks if block.id == region.entry)
    exception = next(v for v in graph.values if v.id == ValueID("shared.exception.input"))
    traceback = next(v for v in graph.values if v.id == ValueID("shared.traceback.input"))
    packet_id = ValueID("shared.entry.packet")
    operation_id = OperationID("shared.entry.make-packet")
    packet = ProtocolValue(packet_id, graph.root, OperationResult(operation_id, 0),
                          ProtocolValueKind.EXCEPTION_PACKET)
    exception_use = Use(UseID("shared.entry.packet.exception"), exception.id,
                        UseRole.REFERENCE)
    traceback_use = Use(UseID("shared.entry.packet.traceback"), traceback.id,
                        UseRole.REFERENCE)
    pack = Operation(operation_id, "construct entry packet", (Behavior.CONTROL,),
                     (exception_use, traceback_use), (packet_id,), effects_complete=True)
    new_entry = replace(entry, operations=(operation_id, *entry.operations))
    new_region = replace(region, blocks=tuple(new_entry if b.id == entry.id else b
                                               for b in region.blocks))
    graph = replace(graph, regions=(new_region,), operations=(*graph.operations, pack),
                    values=(*graph.values, packet),
                    exception_packets=(*graph.exception_packets,
                        ExceptionPacketDefinition(packet_id, exception_use.id,
                                                  traceback_use.id)))
    return graph, packet_id


def _dispatch_with_alias_case(graph, *, extra):
    alias = ControlPort(ControlPortID("shared.port.return.alias"),
                        ControlScopeID("shared.function"),
                        LanguageCompletionKind.RETURN, exit="normal")
    dispatch = _operation(graph, "shared.dispatch")
    edges = list(dispatch.terminator.successors)
    return_index = next(i for i, edge in enumerate(edges)
                        if edge.port == ControlPortID("shared.port.return"))
    edge = edges[return_index]
    if extra:
        new_use = Use(UseID("shared.dispatch.alias.world"),
                      ValueID("shared.cleanup.world.after"), UseRole.STATE_CONTENT)
        dispatch = replace(dispatch, uses=(*dispatch.uses, new_use))
        edges.append(PendingSuccessor(alias.id, BlockID("shared.return_exit"),
                                      (PendingPayload(), new_use.id)))
    else:
        edges[return_index] = replace(edge, port=alias.id)
    dispatch = replace(dispatch, terminator=PendingDispatchTerminator(
        dispatch.terminator.pending, tuple(edges)))
    graph = _replace_operation(graph, dispatch.id, lambda _: dispatch)
    return replace(graph, control_ports=(*graph.control_ports, alias))


def test_all_three_graphs_validate_and_roundtrip_as_v6():
    for graph in (shared_pending_graph(), loop_pending_graph(), loop_transfer_graph()):
        require_valid(graph)
        payload = dumps(graph)
        assert '"schema_version":6' in payload
        assert loads(payload) == graph
        assert dumps(loads(payload)) == payload


def test_pending_case_union_composes_through_cleanup_and_loop_fixed_point():
    shared = shared_pending_graph()
    loop = loop_pending_graph()
    transfers = loop_transfer_graph()
    for graph, value_id, expected in (
        (shared, "shared.cleanup.pending", {
            ControlPortID("shared.port.return"), ControlPortID("shared.port.raise")} ),
        (loop, "loop-pending.header.pending", {
            ControlPortID("loop-pending.port.return"), ControlPortID("loop-pending.port.raise")} ),
        (transfers, "loop-transfer.cleanup.pending", {
            ControlPortID("loop-transfer.port.break"),
            ControlPortID("loop-transfer.port.continue")} ),
    ):
        index = ProgramIndex(graph)
        fact = index.pending_facts(ValueID(value_id))
        assert fact.complete
        assert set(fact.ports) == expected
        assert {port.id for port in index.pending_ports(ValueID(value_id))} == expected


def test_exception_packet_has_two_uses_but_may_name_the_same_reference_value():
    graph = shared_pending_graph()
    packet = next(item for item in graph.exception_packets
                  if item.value == ValueID("shared.packet.value"))
    pack = _operation(graph, "shared.make.packet")
    exception_use = next(use for use in pack.uses if use.id == packet.exception)
    traceback_use = next(use for use in pack.uses if use.id == packet.traceback)
    assert exception_use.id != traceback_use.id

    same_actual = replace(traceback_use, value=exception_use.value)
    graph = _replace_operation(graph, pack.id, lambda op: replace(
        op, uses=tuple(same_actual if use.id == traceback_use.id else use for use in op.uses)))
    require_valid(graph)


def test_packet_cannot_be_used_as_pending_dispatch_selector():
    graph, packet_id = _with_entry_packet(shared_pending_graph())
    dispatch = _operation(graph, "shared.dispatch")
    selector_id = dispatch.terminator.pending
    dispatch = replace(dispatch, uses=tuple(
        replace(use, value=packet_id) if use.id == selector_id else use
        for use in dispatch.uses))
    graph = _replace_operation(graph, dispatch.id, lambda _: dispatch)
    _rejected(graph, "pending_dispatch_type")


@pytest.mark.parametrize("extra", [False, True], ids=["missing-required-case", "extra-case"])
def test_dispatch_case_table_must_equal_cfg_derived_pending_union(extra):
    _rejected(_dispatch_with_alias_case(shared_pending_graph(), extra=extra),
              "pending_dispatch_cases")


def test_pending_constructor_payload_kind_and_arity_are_exact():
    graph = shared_pending_graph()
    return_pending = ValueID("shared.pending.return")
    definitions = list(graph.pending_completions)
    index = next(i for i, item in enumerate(definitions) if item.value == return_pending)

    definitions[index] = replace(definitions[index], payload=None)
    _rejected(replace(graph, pending_completions=tuple(definitions)), "pending_payload")

    definitions = list(graph.pending_completions)
    definitions[index] = replace(definitions[index],
                                 port=ControlPortID("shared.port.raise"))
    _rejected(replace(graph, pending_completions=tuple(definitions)),
              "pending_payload_type")


def test_packet_result_requires_its_typed_constructor_record():
    graph = shared_pending_graph()
    graph = replace(graph, exception_packets=())
    _rejected(graph, "protocol_definition_missing")


def test_pending_value_at_function_entry_is_an_unsupported_boundary():
    graph = shared_pending_graph()
    region = graph.regions[0]
    entry = next(block for block in region.blocks if block.id == region.entry)
    pending = ProtocolValue(ValueID("shared.boundary.pending"), graph.root,
                            BlockArgument(entry.id, len(entry.arguments)),
                            ProtocolValueKind.PENDING_COMPLETION)
    new_entry = replace(entry, arguments=(*entry.arguments, pending.id))
    new_region = replace(region, blocks=tuple(new_entry if b.id == entry.id else b
                                               for b in region.blocks))
    malformed = replace(graph, regions=(new_region,), values=(*graph.values, pending))
    _rejected(malformed, "pending_origin")


def test_projection_cannot_narrow_the_actual_return_identity():
    graph = shared_pending_graph()
    values = tuple(replace(value, referent_identity="asserted-identity")
                   if value.id == ValueID("shared.return.result") else value
                   for value in graph.values)
    _rejected(replace(graph, values=values), "pending_projection_precision")


def test_dispatch_must_land_on_the_exit_shim_named_by_its_port():
    graph = shared_pending_graph()
    dispatch = _operation(graph, "shared.dispatch")
    edges = list(dispatch.terminator.successors)
    return_index = next(i for i, edge in enumerate(edges)
                        if edge.port == ControlPortID("shared.port.return"))
    edges[return_index] = replace(edges[return_index], block=BlockID("shared.raise_exit"))
    dispatch = replace(dispatch, terminator=PendingDispatchTerminator(
        dispatch.terminator.pending, tuple(edges)))
    wrong_landing = _replace_operation(graph, dispatch.id, lambda _: dispatch)
    # The shared normal shim becomes unreachable, so core CFG validation
    # rejects this malformed target before C0's more specific exit-shim check.
    _rejected(wrong_landing, "unreachable_block")


def test_exit_port_payload_must_match_return_or_exception_protocol():
    graph = shared_pending_graph()
    region = graph.regions[0]
    normal, exceptional = region.exits
    wrong = replace(exceptional, types=(ValueType(ValueKind.REFERENCE), exceptional.types[1]))
    region = replace(region, exits=(normal, wrong))
    malformed = replace(graph, regions=(region,))
    _rejected(malformed, "exit_type")


def test_dispatch_cannot_reuse_the_pre_cleanup_world_version():
    graph = shared_pending_graph()
    dispatch = _operation(graph, "shared.dispatch")
    stale_id = UseID("shared.dispatch.return.world")
    dispatch = replace(dispatch, uses=tuple(
        replace(use, value=ValueID("shared.cleanup.world")) if use.id == stale_id else use
        for use in dispatch.uses))
    _rejected(_replace_operation(graph, dispatch.id, lambda _: dispatch), "stale_state")


def test_scope_partition_parent_region_and_cycle_are_checked():
    graph = shared_pending_graph()
    root, cleanup = graph.control_scopes

    bad_partition = replace(root, blocks=root.blocks[:-1])
    _rejected(replace(graph, control_scopes=(bad_partition, cleanup)),
              "control_scope_partition")

    cycle = replace(cleanup, parent=cleanup.id)
    _rejected(replace(graph, control_scopes=(root, cycle)), "control_scope_cycle")

    cross_region = replace(cleanup, region=RegionID("missing.region"))
    _rejected(replace(graph, control_scopes=(root, cross_region)), "control_scope_region")


def test_break_and_continue_use_the_nearest_active_loop():
    graph = loop_transfer_graph()
    outer = next(scope for scope in graph.control_scopes
                 if scope.kind is ControlScopeKind.LOOP)
    cleanup = next(scope for scope in graph.control_scopes
                   if scope.kind is ControlScopeKind.CLEANUP)
    inner_id = ControlScopeID("loop-transfer.inner-loop")
    inner = ControlScope(inner_id, graph.root, outer.id, ControlScopeKind.LOOP,
                         outer.source,
                         (BlockID("loop-transfer.break-path"),
                          BlockID("loop-transfer.continue-path")))
    outer = replace(outer, blocks=(BlockID("loop-transfer.header"),))
    cleanup = replace(cleanup, parent=inner_id)
    scopes = tuple(inner if item.id == inner_id else
                   outer if item.id == outer.id else
                   cleanup if item.kind is ControlScopeKind.CLEANUP else item
                   for item in graph.control_scopes)
    scopes = (*scopes, inner)
    malformed = replace(graph, control_scopes=scopes)
    _rejected(malformed, "pending_target_scope")


def test_pending_dispatch_exit_port_requires_exact_exit_payload_shape():
    graph = loop_transfer_graph()
    region = graph.regions[0]
    after = next(block for block in region.blocks if block.id == BlockID("loop-transfer.after"))
    extra = DataValue(ValueID("loop-transfer.after.unexpected-payload"), graph.root,
                      BlockArgument(after.id, len(after.arguments)), "builtins.object")
    after = replace(after, arguments=(*after.arguments, extra.id))
    region = replace(region, blocks=tuple(after if block.id == after.id else block
                                           for block in region.blocks))
    graph = replace(graph, regions=(region,), values=(*graph.values, extra))
    dispatch = _operation(graph, "loop-transfer.dispatch")
    edges = list(dispatch.terminator.successors)
    break_index = next(i for i, edge in enumerate(edges)
                       if edge.port == ControlPortID("loop-transfer.port.break"))
    edges[break_index] = replace(edges[break_index],
                                 arguments=(*edges[break_index].arguments, PendingPayload()))
    dispatch = replace(dispatch, terminator=PendingDispatchTerminator(
        dispatch.terminator.pending, tuple(edges)))
    graph = _replace_operation(graph, dispatch.id, lambda _: dispatch)
    _rejected(graph, "pending_projection_count", "pending_projection_type")

