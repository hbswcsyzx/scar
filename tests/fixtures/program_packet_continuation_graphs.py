"""Original close/C1 paths with independently observable later boundaries."""
from dataclasses import replace

from scar.ir.program.cleanup import CleanupRouteTerminator
from scar.ir.program.control import (
    LanguageCompletionKind, PendingDispatchTerminator, ProtocolValueKind, ProtocolValueType,
)
from scar.ir.program.ids import BlockID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, CompletionResult, CompletionSignature,
    CompletionSuccessor, ExitKind, ExitPort, Operation, ProtocolValue, Region,
    StateVersionValue, Terminator, TerminatorKind, Use, UseRole, ValueKind, ValueType,
)
from scar.ir.program.protocols import OwnedUse
from tests.fixtures.program_continuation_cleanup_graphs import continuation_close_cleanup_program
from tests.fixtures.program_pending_cleanup_graphs import pending_cleanup_two_cuts_program
from tests.fixtures.program_pending_payload_graphs import pending_payload_program
from tests.fixtures.program_protocol_graphs import _scope


def _explicit_transfers(graph):
    """Declare only this fixture's original pure transfer operations complete."""
    selected = tuple(operation.id for operation in graph.operations
        if operation.callee is None and not operation.results and not operation.accesses
        and operation.behaviors == (Behavior.CONTROL,)
        and (type(operation.terminator) in (PendingDispatchTerminator, CleanupRouteTerminator)
             or type(operation.terminator) is Terminator
             and operation.terminator.kind is TerminatorKind.JUMP))
    return replace(graph, operations=tuple(replace(operation, effects_complete=True)
        if operation.id in selected else operation for operation in graph.operations)), selected


def _raise_edge(graph):
    ports = {port.id: port for port in graph.control_ports}
    dispatch = next(operation for operation in graph.operations
                    if type(operation.terminator) is PendingDispatchTerminator)
    selected = next(edge for edge in dispatch.terminator.successors
                    if ports[edge.port].kind is LanguageCompletionKind.RAISE)
    return dispatch, selected


def packet_continuation_program(*, opaque_after_replace=False, complete_transitions=False,
                                two_cuts=False, packet_helper=None):
    """Keep the real cleanup replacement and its exact eventual dispatch.

    The optional operation declares incomplete effects after the first C1
    handoff. It does not fabricate a packet, state version, or native call.
    """
    if packet_helper not in (None, "known", "unknown"):
        raise ValueError("packet_helper must be known/unknown or None")
    graph, details = (pending_cleanup_two_cuts_program() if two_cuts
                      else continuation_close_cleanup_program())
    declared_transitions = ()
    if complete_transitions:
        # This NEW fixture explicitly declares its pure transfer operations.
        # C1 Enter/Resume/Replace retain effects_complete=False, as required by
        # their callback/current-state contract. No opaque helper is changed.
        graph, declared_transitions = _explicit_transfers(graph)
    opaque = None
    if opaque_after_replace:
        opaque = Operation(OperationID("packet.continuation.after-replace.opaque"),
            "unknown effects after the real C1 replacement", (Behavior.COMPUTE,),
            effects_complete=False)
        region = graph.regions[0]
        _, selected = _raise_edge(graph)
        # C1 exits and post-pop corridors remain untouched. A RAISE port may
        # land at a real handler block; unlike an exit shim, that landing may
        # contain the subsequent opaque operation before Detach/RAISE.
        blocks = tuple(replace(block, operations=(opaque.id, *block.operations))
                       if block.id == selected.block else block for block in region.blocks)
        graph = replace(graph, regions=(replace(region, blocks=blocks),),
            operations=(*graph.operations, opaque),
            control_ports=tuple(replace(port, block=selected.block, exit=None)
                if port.id == selected.port else port for port in graph.control_ports))
    helper_details = {}
    if packet_helper is not None:
        graph, helper_details = _with_packet_helper(graph, known=packet_helper == "known")
    host = next(operation for operation in graph.operations
                if operation.id == OperationID("finally.raise-exit.op"))
    return graph, {**details, **helper_details, "opaque": opaque,
        "host_packet": OwnedUse(host.id, host.uses[0].id),
        "host": host, "declared_complete_transitions": declared_transitions}


def _with_packet_helper(graph, *, known):
    """Project the packet, then actually invoke a separate identity helper.

    Whole packets can be original INVOKE operands/results. No pending/context
    token is a call actual; the body caller token is an independent edge copy.
    """
    _, selected = _raise_edge(graph)
    body = graph.regions[0]
    landing = next(block for block in body.blocks if block.id == selected.block)
    values = {value.id: value for value in graph.values}
    packet, world, context, caller = tuple(values[identity] for identity in landing.arguments)
    helper, helper_entry = RegionID("packet.continuation.identity"), BlockID("packet.continuation.identity.entry")
    helper_formals = tuple(replace(value, id=ValueID(f"packet.continuation.identity.formal.{index}"),
        region=helper, origin=BlockArgument(helper_entry, index))
        for index, value in enumerate((packet, world, context)))
    helper_uses = tuple(Use(UseID(f"packet.continuation.identity.return.{index}"), value.id,
        UseRole.PROTOCOL if index == 0 else UseRole.STATE_CONTENT)
        for index, value in enumerate(helper_formals))
    helper_terminal = Operation(OperationID("packet.continuation.identity.return"),
        "return the exact original packet and state ports", (Behavior.CONTROL,), helper_uses,
        effects_complete=True, terminator=Terminator(TerminatorKind.RETURN, exit="normal",
                                                    values=tuple(use.id for use in helper_uses)))
    signature = (ProtocolValueType(ProtocolValueKind.EXCEPTION_PACKET),
                 ValueType(ValueKind.STATE, location=world.location),
                 ValueType(ValueKind.STATE, location=context.location))
    helper_block = Block(helper_entry, tuple(value.id for value in helper_formals), (helper_terminal.id,))
    helper_region = Region(helper, "known packet identity helper", helper_entry,
        (helper_block,), (ExitPort("normal", ExitKind.NORMAL, signature),), parent=body.id)
    after_id = BlockID("packet.continuation.helper.normal")
    after = tuple(replace(value, id=ValueID(f"packet.continuation.helper.normal.{index}"),
        origin=BlockArgument(after_id, index)) for index, value in enumerate((packet, world, context, caller)))
    uses = tuple(Use(UseID(f"packet.continuation.helper.argument.{index}"), value.id,
        UseRole.PROTOCOL if index == 0 else UseRole.STATE_CONTENT)
        for index, value in enumerate((packet, world, context)))
    caller_forward = Use(UseID("packet.continuation.helper.caller.forward"), caller.id, UseRole.PROTOCOL)
    invoke = Operation(OperationID("packet.continuation.helper.invoke"),
        "actual packet helper invocation", (Behavior.CONTROL,), (*uses, caller_forward),
        effects_complete=known, callee=helper if known else None,
        invoke_arguments=tuple(use.id for use in uses),
        completions=(CompletionSignature(ExitKind.NORMAL, signature),),
        terminator=Terminator(TerminatorKind.INVOKE, (CompletionSuccessor(ExitKind.NORMAL, after_id,
            (CompletionResult(0), CompletionResult(1), CompletionResult(2), caller_forward.id)),)))
    substitution = {value.id: replacement.id for value, replacement in zip(
        (packet, world, context, caller), after)}
    carried_operations = set(landing.operations)
    operations = tuple(replace(operation, uses=tuple(replace(use,
        value=substitution.get(use.value, use.value)) for use in operation.uses))
        if operation.id in carried_operations else operation for operation in graph.operations)
    blocks = tuple(replace(block, operations=(invoke.id,)) if block.id == landing.id else block
                   for block in body.blocks)
    after_block = Block(after_id, tuple(value.id for value in after), landing.operations)
    # The existing raise port becomes a real handler landing before the call.
    # The exact exit-shim constraint therefore continues to protect all ports
    # that are still declared as exits, without forbidding this handler path.
    graph = replace(graph,
        regions=(replace(body, blocks=(*blocks, after_block)),
                 *((helper_region,) if known else ())),
        operations=(*operations, invoke, *((helper_terminal,) if known else ())),
        values=(*graph.values, *after, *(helper_formals if known else ())),
        control_ports=tuple(replace(port, block=selected.block, exit=None)
            if port.id == selected.port else port for port in graph.control_ports),
        control_scopes=tuple(replace(scope, blocks=(*scope.blocks, after_id))
            if selected.block in scope.blocks else scope for scope in graph.control_scopes)
            + ((_scope(helper, (helper_block,)),) if known else ()))
    return graph, {"packet_helper": invoke, "packet_helper_kind": "known" if known else "unknown",
        "packet_helper_terminal": helper_terminal if known else None,
        "packet_helper_input": OwnedUse(invoke.id, uses[0].id)}


def packet_port_branch_program():
    """Distinct RAISE ports preserve their original independent payloads."""
    graph, details = pending_payload_program(mixed=True, different_ports=True, kind="raise")
    graph, transfers = _explicit_transfers(graph)
    return graph, {**details, "declared_complete_transitions": transfers}


__all__ = ["packet_continuation_program", "packet_port_branch_program"]
