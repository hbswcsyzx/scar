"""Small hand-authored control graphs for C0 composition tests.

These are structural examples only.  Their declared source references do not
prove source correspondence or authorize cleanup execution.
"""
from __future__ import annotations

from scar.ir.program.control import (
    ControlPort, ControlScope, ControlScopeKind, ExceptionPacketDefinition,
    LanguageCompletionKind as K, PendingCompletionDefinition,
    PendingDispatchTerminator, PendingPayload, PendingSuccessor,
    ProtocolValueKind as P,
)
from scar.ir.program.ids import (
    BlockID, ControlPortID, ControlScopeID, LocationID, OperationID, RegionID,
    UseID, ValueID,
)
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, DataValue, ExitKind, ExitPort,
    Operation, OperationResult, ProgramGraph, ProtocolValue, ReferenceValue,
    Region, Stability, StateAccess, StateLocation, StateVersionValue, Successor,
    Terminator, TerminatorKind, Use, UseRole, ValueKind, ValueType,
)
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import SourceAtomID


def _source(label: str, line: int = 1) -> SourceReference:
    return SourceReference(SourceAtomID("fixture.control." + label), "control_fixture.py",
                           "hand-authored-structure-v1", line, line, 0, 1)


def _use(label: str, value: ValueID, role: UseRole) -> Use:
    return Use(UseID(label), value, role)


def _reference(label: str, region: RegionID, block: BlockID, index: int) -> ReferenceValue:
    return ReferenceValue(ValueID(label), region, BlockArgument(block, index))


def _protocol(label: str, region: RegionID, block: BlockID, index: int,
              protocol: P) -> ProtocolValue:
    return ProtocolValue(ValueID(label), region, BlockArgument(block, index), protocol)


def _state(label: str, region: RegionID, block: BlockID, index: int,
           world: LocationID) -> StateVersionValue:
    return StateVersionValue(ValueID(label), region, BlockArgument(block, index), world)


def _jump(label: str, target: BlockID, arguments: tuple[UseID, ...]) -> Terminator:
    return Terminator(TerminatorKind.JUMP, (Successor(target, arguments),))


def _entry_and_scopes(region: RegionID, root: ControlScopeID, blocks: tuple[BlockID, ...],
                      children: tuple[ControlScope, ...] = ()) -> tuple[ControlScope, ...]:
    root_scope = ControlScope(root, region, None, ControlScopeKind.FUNCTION,
                              _source("function"), blocks)
    return (root_scope, *children)


def shared_pending_graph() -> ProgramGraph:
    """Return/Raise merge through one cleanup block and typed dispatch shims."""
    region = RegionID("shared.region")
    function = ControlScopeID("shared.function")
    cleanup_scope_id = ControlScopeID("shared.cleanup.scope")
    world = LocationID("shared.world")

    entry, make_return, make_raise, cleanup, return_exit, raise_exit = map(
        BlockID, ("shared.entry", "shared.make_return", "shared.make_raise",
                  "shared.cleanup", "shared.return_exit", "shared.raise_exit"))

    # Function-entry ports: condition, return reference, exception reference,
    # traceback reference, then the canonical coarse world state.
    condition = DataValue(ValueID("shared.condition"), region,
                          BlockArgument(entry, 0), "builtins.bool")
    return_input = _reference("shared.return.input", region, entry, 1)
    exception_input = _reference("shared.exception.input", region, entry, 2)
    traceback_input = _reference("shared.traceback.input", region, entry, 3)
    world_input = _state("shared.world.input", region, entry, 4, world)

    return_ref = _reference("shared.return.path.ref", region, make_return, 0)
    return_state = _state("shared.return.path.world", region, make_return, 1, world)
    raise_exception = _reference("shared.raise.path.exception", region, make_raise, 0)
    raise_traceback = _reference("shared.raise.path.traceback", region, make_raise, 1)
    raise_state = _state("shared.raise.path.world", region, make_raise, 2, world)

    pending_arg = _protocol("shared.cleanup.pending", region, cleanup, 0, P.PENDING_COMPLETION)
    cleanup_state = _state("shared.cleanup.world", region, cleanup, 1, world)
    return_result = _reference("shared.return.result", region, return_exit, 0)
    return_world = _state("shared.return.world", region, return_exit, 1, world)
    raise_packet_result = _protocol("shared.raise.packet", region, raise_exit, 0, P.EXCEPTION_PACKET)
    raise_world = _state("shared.raise.world", region, raise_exit, 1, world)

    values = [condition, return_input, exception_input, traceback_input, world_input,
              return_ref, return_state, raise_exception, raise_traceback, raise_state,
              pending_arg, cleanup_state, return_result, return_world,
              raise_packet_result, raise_world]
    operations: list[Operation] = []

    # Split into two actual source paths; all state ports use distinct Uses.
    branch_uses = (
        _use("shared.branch.condition", condition.id, UseRole.DATA),
        _use("shared.branch.return.ref", return_input.id, UseRole.REFERENCE),
        _use("shared.branch.return.world", world_input.id, UseRole.STATE_CONTENT),
        _use("shared.branch.raise.exception", exception_input.id, UseRole.REFERENCE),
        _use("shared.branch.raise.traceback", traceback_input.id, UseRole.REFERENCE),
        _use("shared.branch.raise.world", world_input.id, UseRole.STATE_CONTENT),
    )
    branch = Operation(OperationID("shared.branch"), "branch into pending constructors",
        (Behavior.CONTROL,), branch_uses,
        terminator=Terminator(TerminatorKind.BRANCH,
            (Successor(make_return, (branch_uses[1].id, branch_uses[2].id)),
             Successor(make_raise, (branch_uses[3].id, branch_uses[4].id,
                                    branch_uses[5].id))),
            condition=branch_uses[0].id))
    operations.append(branch)

    return_payload = _use("shared.return.payload", return_ref.id, UseRole.REFERENCE)
    return_pending_value = ProtocolValue(ValueID("shared.pending.return"), region,
        OperationResult(OperationID("shared.make.return.pending"), 0), P.PENDING_COMPLETION)
    values.append(return_pending_value)
    return_pending_op = Operation(OperationID("shared.make.return.pending"), "pack Return",
        (Behavior.CONTROL,), (return_payload,), (return_pending_value.id,), effects_complete=True)
    operations.append(return_pending_op)

    raise_packet_exception = _use("shared.packet.exception", raise_exception.id, UseRole.REFERENCE)
    raise_packet_traceback = _use("shared.packet.traceback", raise_traceback.id, UseRole.REFERENCE)
    packet_value = ProtocolValue(ValueID("shared.packet.value"), region,
        OperationResult(OperationID("shared.make.packet"), 0), P.EXCEPTION_PACKET)
    values.append(packet_value)
    packet_op = Operation(OperationID("shared.make.packet"), "pack exception packet",
        (Behavior.CONTROL,), (raise_packet_exception, raise_packet_traceback),
        (packet_value.id,), effects_complete=True)
    operations.append(packet_op)

    raise_payload = _use("shared.raise.payload.packet", packet_value.id, UseRole.PROTOCOL)
    raise_pending_value = ProtocolValue(ValueID("shared.pending.raise"), region,
        OperationResult(OperationID("shared.make.raise.pending"), 0), P.PENDING_COMPLETION)
    values.append(raise_pending_value)
    raise_pending_op = Operation(OperationID("shared.make.raise.pending"), "pack Raise",
        (Behavior.CONTROL,), (raise_payload,), (raise_pending_value.id,), effects_complete=True)
    operations.append(raise_pending_op)

    return_jump_uses = (
        _use("shared.return.to.cleanup.pending", return_pending_value.id, UseRole.PROTOCOL),
        _use("shared.return.to.cleanup.world", return_state.id, UseRole.STATE_CONTENT),
    )
    return_jump = Operation(OperationID("shared.return.to.cleanup"), "return path to cleanup",
        (Behavior.CONTROL,), return_jump_uses,
        terminator=_jump("shared.return.to.cleanup", cleanup,
                         tuple(use.id for use in return_jump_uses)))
    operations.append(return_jump)

    raise_jump_uses = (
        _use("shared.raise.to.cleanup.pending", raise_pending_value.id, UseRole.PROTOCOL),
        _use("shared.raise.to.cleanup.world", raise_state.id, UseRole.STATE_CONTENT),
    )
    raise_jump = Operation(OperationID("shared.raise.to.cleanup"), "raise path to cleanup",
        (Behavior.CONTROL,), raise_jump_uses,
        terminator=_jump("shared.raise.to.cleanup", cleanup,
                         tuple(use.id for use in raise_jump_uses)))
    operations.append(raise_jump)

    # A real StateVersion write establishes the post-cleanup world.  Its effect
    # summary is intentionally incomplete and does not claim the cleanup's
    # language meaning has been recovered.
    cleanup_world_use = _use("shared.cleanup.world.before", cleanup_state.id,
                             UseRole.STATE_CONTENT)
    cleanup_world_after = StateVersionValue(ValueID("shared.cleanup.world.after"), region,
        OperationResult(OperationID("shared.cleanup.write"), 0), world)
    values.append(cleanup_world_after)
    cleanup_write = Operation(OperationID("shared.cleanup.write"), "cleanup state write",
        (Behavior.READ, Behavior.WRITE, Behavior.MEMORY), (cleanup_world_use,),
        (cleanup_world_after.id,),
        (StateAccess(world, cleanup_world_use.id, AccessMode.READ_WRITE,
                     cleanup_world_after.id),), effects_complete=False)
    operations.append(cleanup_write)

    dispatch_pending = _use("shared.dispatch.pending", pending_arg.id, UseRole.PROTOCOL)
    dispatch_return_world = _use("shared.dispatch.return.world", cleanup_world_after.id,
                                 UseRole.STATE_CONTENT)
    dispatch_raise_world = _use("shared.dispatch.raise.world", cleanup_world_after.id,
                                UseRole.STATE_CONTENT)
    dispatch = Operation(OperationID("shared.dispatch"), "pending completion dispatch",
        (Behavior.CONTROL,),
        (dispatch_pending, dispatch_return_world, dispatch_raise_world),
        terminator=PendingDispatchTerminator(dispatch_pending.id, (
            PendingSuccessor(ControlPortID("shared.port.return"), return_exit,
                             (PendingPayload(), dispatch_return_world.id)),
            PendingSuccessor(ControlPortID("shared.port.raise"), raise_exit,
                             (PendingPayload(), dispatch_raise_world.id)),
        )))
    operations.append(dispatch)

    return_exit_uses = (
        _use("shared.return.exit.payload", return_result.id, UseRole.REFERENCE),
        _use("shared.return.exit.world", return_world.id, UseRole.STATE_CONTENT),
    )
    return_exit_op = Operation(OperationID("shared.return.exit.op"), "function return shim",
        (Behavior.CONTROL,), return_exit_uses,
        terminator=Terminator(TerminatorKind.RETURN, exit="normal",
                              values=tuple(use.id for use in return_exit_uses)))
    operations.append(return_exit_op)

    raise_exit_uses = (
        _use("shared.raise.exit.packet", raise_packet_result.id, UseRole.PROTOCOL),
        _use("shared.raise.exit.world", raise_world.id, UseRole.STATE_CONTENT),
    )
    raise_exit_op = Operation(OperationID("shared.raise.exit.op"), "function raise shim",
        (Behavior.CONTROL,), raise_exit_uses,
        terminator=Terminator(TerminatorKind.RAISE, exit="exception",
                              values=tuple(use.id for use in raise_exit_uses)))
    operations.append(raise_exit_op)

    blocks = (
        Block(entry, (condition.id, return_input.id, exception_input.id,
                      traceback_input.id, world_input.id), (branch.id,)),
        Block(make_return, (return_ref.id, return_state.id),
              (return_pending_op.id, return_jump.id)),
        Block(make_raise, (raise_exception.id, raise_traceback.id, raise_state.id),
              (packet_op.id, raise_pending_op.id, raise_jump.id)),
        Block(cleanup, (pending_arg.id, cleanup_state.id), (cleanup_write.id, dispatch.id)),
        Block(return_exit, (return_result.id, return_world.id), (return_exit_op.id,)),
        Block(raise_exit, (raise_packet_result.id, raise_world.id), (raise_exit_op.id,)),
    )
    region_record = Region(region, "shared pending fixture", entry, blocks, (
        ExitPort("normal", ExitKind.NORMAL,
                 (ValueType(ValueKind.REFERENCE), ValueType(ValueKind.STATE, location=world))),
        ExitPort("exception", ExitKind.RAISE,
                 (packet_type(), ValueType(ValueKind.STATE, location=world))),
    ))
    cleanup_scope = ControlScope(cleanup_scope_id, region, function,
                                  ControlScopeKind.CLEANUP, _source("cleanup", 2), (cleanup,))
    scopes = _entry_and_scopes(region, function,
        (entry, make_return, make_raise, return_exit, raise_exit), (cleanup_scope,))
    ports = (
        ControlPort(ControlPortID("shared.port.return"), function, K.RETURN, exit="normal"),
        ControlPort(ControlPortID("shared.port.raise"), function, K.RAISE, exit="exception"),
    )
    return ProgramGraph(region, (region_record,), tuple(operations), tuple(values),
        (StateLocation(world, "fixture world", stability=Stability.UNKNOWN),),
        control_scopes=scopes, control_ports=ports,
        exception_packets=(ExceptionPacketDefinition(packet_value.id,
            raise_packet_exception.id, raise_packet_traceback.id),),
        pending_completions=(
            PendingCompletionDefinition(return_pending_value.id, ports[0].id, return_payload.id),
            PendingCompletionDefinition(raise_pending_value.id, ports[1].id, raise_payload.id),
        ))


def packet_type():
    from scar.ir.program.control import ProtocolValueType
    return ProtocolValueType(P.EXCEPTION_PACKET)


def loop_pending_graph() -> ProgramGraph:
    """A loop-header pending BlockArgument gets Return and backedge Raise."""
    region, world = RegionID("loop-pending.region"), LocationID("loop-pending.world")
    function, loop = ControlScopeID("loop-pending.function"), ControlScopeID("loop-pending.loop")
    entry, header, body, dispatch_block, return_exit, raise_exit = map(BlockID,
        ("loop-pending.entry", "loop-pending.header", "loop-pending.body",
         "loop-pending.dispatch", "loop-pending.return-exit", "loop-pending.raise-exit"))

    entry_ref = _reference("loop-pending.entry.ref", region, entry, 0)
    entry_exception = _reference("loop-pending.entry.exception", region, entry, 1)
    entry_traceback = _reference("loop-pending.entry.traceback", region, entry, 2)
    entry_condition = DataValue(ValueID("loop-pending.entry.condition"), region,
                                BlockArgument(entry, 3), "builtins.bool")
    entry_world = _state("loop-pending.entry.world", region, entry, 4, world)
    header_pending = _protocol("loop-pending.header.pending", region, header, 0,
                               P.PENDING_COMPLETION)
    header_ref = _reference("loop-pending.header.ref", region, header, 1)
    header_exception = _reference("loop-pending.header.exception", region, header, 2)
    header_traceback = _reference("loop-pending.header.traceback", region, header, 3)
    header_condition = DataValue(ValueID("loop-pending.header.condition"), region,
                                 BlockArgument(header, 4), "builtins.bool")
    header_world = _state("loop-pending.header.world", region, header, 5, world)
    body_ref = _reference("loop-pending.body.ref", region, body, 0)
    body_exception = _reference("loop-pending.body.exception", region, body, 1)
    body_traceback = _reference("loop-pending.body.traceback", region, body, 2)
    body_condition = DataValue(ValueID("loop-pending.body.condition"), region,
                               BlockArgument(body, 3), "builtins.bool")
    body_world = _state("loop-pending.body.world", region, body, 4, world)
    dispatch_pending = _protocol("loop-pending.dispatch.pending", region, dispatch_block, 0,
                                 P.PENDING_COMPLETION)
    dispatch_ref = _reference("loop-pending.dispatch.ref", region, dispatch_block, 1)
    dispatch_world = _state("loop-pending.dispatch.world", region, dispatch_block, 2, world)
    return_result = _reference("loop-pending.return.result", region, return_exit, 0)
    return_world = _state("loop-pending.return.world", region, return_exit, 1, world)
    raise_packet_result = _protocol("loop-pending.raise.packet", region, raise_exit, 0,
                                    P.EXCEPTION_PACKET)
    raise_world = _state("loop-pending.raise.world", region, raise_exit, 1, world)
    values = [entry_ref, entry_exception, entry_traceback, entry_condition, entry_world,
              header_pending, header_ref, header_exception, header_traceback,
              header_condition, header_world, body_ref, body_exception, body_traceback,
              body_condition, body_world, dispatch_pending, dispatch_ref, dispatch_world,
              return_result, return_world, raise_packet_result, raise_world]
    operations: list[Operation] = []

    ret_payload = _use("loop-pending.return.payload", entry_ref.id, UseRole.REFERENCE)
    ret_pending = ProtocolValue(ValueID("loop-pending.return.token"), region,
        OperationResult(OperationID("loop-pending.make.return"), 0), P.PENDING_COMPLETION)
    values.append(ret_pending)
    make_return = Operation(OperationID("loop-pending.make.return"), "construct initial Return",
        (Behavior.CONTROL,), (ret_payload,), (ret_pending.id,), effects_complete=True)
    operations.append(make_return)

    entry_to_header = (
        _use("loop-pending.entry.to-header.pending", ret_pending.id, UseRole.PROTOCOL),
        _use("loop-pending.entry.to-header.ref", entry_ref.id, UseRole.REFERENCE),
        _use("loop-pending.entry.to-header.exception", entry_exception.id, UseRole.REFERENCE),
        _use("loop-pending.entry.to-header.traceback", entry_traceback.id, UseRole.REFERENCE),
        _use("loop-pending.entry.to-header.condition", entry_condition.id, UseRole.DATA),
        _use("loop-pending.entry.to-header.world", entry_world.id, UseRole.STATE_CONTENT),
    )
    enter_header = Operation(OperationID("loop-pending.enter-header"), "enter loop header",
        (Behavior.CONTROL,), entry_to_header,
        terminator=_jump("loop-pending.enter-header", header,
                         tuple(use.id for use in entry_to_header)))
    operations.append(enter_header)

    header_uses = (
        _use("loop-pending.header.condition.use", header_condition.id, UseRole.DATA),
        _use("loop-pending.header.to-body.ref", header_ref.id, UseRole.REFERENCE),
        _use("loop-pending.header.to-body.exception", header_exception.id, UseRole.REFERENCE),
        _use("loop-pending.header.to-body.traceback", header_traceback.id, UseRole.REFERENCE),
        _use("loop-pending.header.to-body.condition", header_condition.id, UseRole.DATA),
        _use("loop-pending.header.to-body.world", header_world.id, UseRole.STATE_CONTENT),
        _use("loop-pending.header.to-dispatch.pending", header_pending.id, UseRole.PROTOCOL),
        _use("loop-pending.header.to-dispatch.ref", header_ref.id, UseRole.REFERENCE),
        _use("loop-pending.header.to-dispatch.world", header_world.id, UseRole.STATE_CONTENT),
    )
    header_branch = Operation(OperationID("loop-pending.branch"), "loop header branch",
        (Behavior.CONTROL,), header_uses,
        terminator=Terminator(TerminatorKind.BRANCH,
            (Successor(body, tuple(use.id for use in header_uses[1:6])),
             Successor(dispatch_block, tuple(use.id for use in header_uses[6:9]))),
            condition=header_uses[0].id))
    operations.append(header_branch)

    packet_exc = _use("loop-pending.packet.exception", body_exception.id, UseRole.REFERENCE)
    packet_tb = _use("loop-pending.packet.traceback", body_traceback.id, UseRole.REFERENCE)
    packet = ProtocolValue(ValueID("loop-pending.packet"), region,
        OperationResult(OperationID("loop-pending.make.packet"), 0), P.EXCEPTION_PACKET)
    values.append(packet)
    make_packet = Operation(OperationID("loop-pending.make.packet"), "construct loop Raise packet",
        (Behavior.CONTROL,), (packet_exc, packet_tb), (packet.id,), effects_complete=True)
    operations.append(make_packet)
    raise_payload = _use("loop-pending.raise.payload", packet.id, UseRole.PROTOCOL)
    raise_pending = ProtocolValue(ValueID("loop-pending.raise.token"), region,
        OperationResult(OperationID("loop-pending.make.raise"), 0), P.PENDING_COMPLETION)
    values.append(raise_pending)
    make_raise = Operation(OperationID("loop-pending.make.raise"), "construct backedge Raise",
        (Behavior.CONTROL,), (raise_payload,), (raise_pending.id,), effects_complete=True)
    operations.append(make_raise)
    backedge_uses = (
        _use("loop-pending.backedge.pending", raise_pending.id, UseRole.PROTOCOL),
        _use("loop-pending.backedge.ref", body_ref.id, UseRole.REFERENCE),
        _use("loop-pending.backedge.exception", body_exception.id, UseRole.REFERENCE),
        _use("loop-pending.backedge.traceback", body_traceback.id, UseRole.REFERENCE),
        _use("loop-pending.backedge.condition", body_condition.id, UseRole.DATA),
        _use("loop-pending.backedge.world", body_world.id, UseRole.STATE_CONTENT),
    )
    backedge = Operation(OperationID("loop-pending.backedge"), "carry Raise to header",
        (Behavior.CONTROL,), backedge_uses,
        terminator=_jump("loop-pending.backedge", header,
                         tuple(use.id for use in backedge_uses)))
    operations.append(backedge)

    dispatch_pending_use = _use("loop-pending.dispatch.pending.use", dispatch_pending.id,
                                UseRole.PROTOCOL)
    dispatch_return_world = _use("loop-pending.dispatch.return.world", dispatch_world.id,
                                 UseRole.STATE_CONTENT)
    dispatch_raise_world = _use("loop-pending.dispatch.raise.world", dispatch_world.id,
                                UseRole.STATE_CONTENT)
    dispatch = Operation(OperationID("loop-pending.dispatch"), "dispatch loop-carried union",
        (Behavior.CONTROL,), (dispatch_pending_use, dispatch_return_world, dispatch_raise_world),
        terminator=PendingDispatchTerminator(dispatch_pending_use.id, (
            PendingSuccessor(ControlPortID("loop-pending.port.return"), return_exit,
                             (PendingPayload(), dispatch_return_world.id)),
            PendingSuccessor(ControlPortID("loop-pending.port.raise"), raise_exit,
                             (PendingPayload(), dispatch_raise_world.id)),
        )))
    operations.append(dispatch)

    return_exit_uses = (_use("loop-pending.return.payload.exit", return_result.id, UseRole.REFERENCE),
                        _use("loop-pending.return.state.exit", return_world.id, UseRole.STATE_CONTENT))
    return_op = Operation(OperationID("loop-pending.return.exit.op"), "return exit",
        (Behavior.CONTROL,), return_exit_uses,
        terminator=Terminator(TerminatorKind.RETURN, exit="normal",
                              values=tuple(use.id for use in return_exit_uses)))
    operations.append(return_op)
    raise_exit_uses = (_use("loop-pending.raise.packet.exit", raise_packet_result.id, UseRole.PROTOCOL),
                       _use("loop-pending.raise.state.exit", raise_world.id, UseRole.STATE_CONTENT))
    raise_op = Operation(OperationID("loop-pending.raise.exit.op"), "raise exit",
        (Behavior.CONTROL,), raise_exit_uses,
        terminator=Terminator(TerminatorKind.RAISE, exit="exception",
                              values=tuple(use.id for use in raise_exit_uses)))
    operations.append(raise_op)

    blocks = (
        Block(entry, (entry_ref.id, entry_exception.id, entry_traceback.id,
                      entry_condition.id, entry_world.id), (make_return.id, enter_header.id)),
        Block(header, (header_pending.id, header_ref.id, header_exception.id,
                       header_traceback.id, header_condition.id, header_world.id),
              (header_branch.id,)),
        Block(body, (body_ref.id, body_exception.id, body_traceback.id,
                     body_condition.id, body_world.id),
              (make_packet.id, make_raise.id, backedge.id)),
        Block(dispatch_block, (dispatch_pending.id, dispatch_ref.id, dispatch_world.id),
              (dispatch.id,)),
        Block(return_exit, (return_result.id, return_world.id), (return_op.id,)),
        Block(raise_exit, (raise_packet_result.id, raise_world.id), (raise_op.id,)),
    )
    region_record = Region(region, "loop pending fixed-point fixture", entry, blocks, (
        ExitPort("normal", ExitKind.NORMAL,
                 (ValueType(ValueKind.REFERENCE), ValueType(ValueKind.STATE, location=world))),
        ExitPort("exception", ExitKind.RAISE,
                 (packet_type(), ValueType(ValueKind.STATE, location=world))),
    ))
    loop_scope = ControlScope(loop, region, function, ControlScopeKind.LOOP,
                              _source("loop", 2), (header, body))
    scopes = _entry_and_scopes(region, function,
        (entry, dispatch_block, return_exit, raise_exit), (loop_scope,))
    ports = (
        ControlPort(ControlPortID("loop-pending.port.return"), function, K.RETURN,
                    exit="normal"),
        ControlPort(ControlPortID("loop-pending.port.raise"), function, K.RAISE,
                    exit="exception"),
    )
    return ProgramGraph(region, (region_record,), tuple(operations), tuple(values),
        (StateLocation(world, "loop pending world", stability=Stability.UNKNOWN),),
        control_scopes=scopes, control_ports=ports,
        exception_packets=(ExceptionPacketDefinition(packet.id, packet_exc.id, packet_tb.id),),
        pending_completions=(
            PendingCompletionDefinition(ret_pending.id, ports[0].id, ret_payload.id),
            PendingCompletionDefinition(raise_pending.id, ports[1].id, raise_payload.id),
        ))


def loop_transfer_graph() -> ProgramGraph:
    """Break/Continue pending values share a cleanup and keep distinct targets."""
    region, world = RegionID("loop-transfer.region"), LocationID("loop-transfer.world")
    function, loop = ControlScopeID("loop-transfer.function"), ControlScopeID("loop-transfer.loop")
    cleanup_scope_id = ControlScopeID("loop-transfer.cleanup.scope")
    entry, header, break_path, continue_path, cleanup, after = map(BlockID,
        ("loop-transfer.entry", "loop-transfer.header", "loop-transfer.break-path",
         "loop-transfer.continue-path", "loop-transfer.cleanup", "loop-transfer.after"))

    entry_ref = _reference("loop-transfer.entry.ref", region, entry, 0)
    entry_condition = DataValue(ValueID("loop-transfer.entry.condition"), region,
                                BlockArgument(entry, 1), "builtins.bool")
    entry_world = _state("loop-transfer.entry.world", region, entry, 2, world)
    header_ref = _reference("loop-transfer.header.ref", region, header, 0)
    header_condition = DataValue(ValueID("loop-transfer.header.condition"), region,
                                 BlockArgument(header, 1), "builtins.bool")
    header_world = _state("loop-transfer.header.world", region, header, 2, world)
    break_ref = _reference("loop-transfer.break.ref", region, break_path, 0)
    break_condition = DataValue(ValueID("loop-transfer.break.condition"), region,
                                BlockArgument(break_path, 1), "builtins.bool")
    break_world = _state("loop-transfer.break.world", region, break_path, 2, world)
    continue_ref = _reference("loop-transfer.continue.ref", region, continue_path, 0)
    continue_condition = DataValue(ValueID("loop-transfer.continue.condition"), region,
                                   BlockArgument(continue_path, 1), "builtins.bool")
    continue_world = _state("loop-transfer.continue.world", region, continue_path, 2, world)
    pending_arg = _protocol("loop-transfer.cleanup.pending", region, cleanup, 0,
                            P.PENDING_COMPLETION)
    cleanup_ref = _reference("loop-transfer.cleanup.ref", region, cleanup, 1)
    cleanup_world = _state("loop-transfer.cleanup.world", region, cleanup, 2, world)
    cleanup_condition = DataValue(ValueID("loop-transfer.cleanup.condition"), region,
                                  BlockArgument(cleanup, 3), "builtins.bool")
    after_ref = _reference("loop-transfer.after.ref", region, after, 0)
    after_world = _state("loop-transfer.after.world", region, after, 1, world)
    values = [entry_ref, entry_condition, entry_world, header_ref, header_condition,
              header_world, break_ref, break_condition, break_world, continue_ref,
              continue_condition, continue_world, pending_arg, cleanup_ref,
              cleanup_world, cleanup_condition, after_ref, after_world]
    operations: list[Operation] = []

    enter_uses = (_use("loop-transfer.enter.ref", entry_ref.id, UseRole.REFERENCE),
                  _use("loop-transfer.enter.condition", entry_condition.id, UseRole.DATA),
                  _use("loop-transfer.enter.world", entry_world.id, UseRole.STATE_CONTENT))
    enter = Operation(OperationID("loop-transfer.enter"), "enter loop header",
        (Behavior.CONTROL,), enter_uses,
        terminator=_jump("loop-transfer.enter", header, tuple(u.id for u in enter_uses)))
    operations.append(enter)

    branch_uses = (
        _use("loop-transfer.header.condition.use", header_condition.id, UseRole.DATA),
        _use("loop-transfer.header.break.ref", header_ref.id, UseRole.REFERENCE),
        _use("loop-transfer.header.break.condition", header_condition.id, UseRole.DATA),
        _use("loop-transfer.header.break.world", header_world.id, UseRole.STATE_CONTENT),
        _use("loop-transfer.header.continue.ref", header_ref.id, UseRole.REFERENCE),
        _use("loop-transfer.header.continue.condition", header_condition.id, UseRole.DATA),
        _use("loop-transfer.header.continue.world", header_world.id, UseRole.STATE_CONTENT),
    )
    branch = Operation(OperationID("loop-transfer.branch"), "choose loop transfer",
        (Behavior.CONTROL,), branch_uses,
        terminator=Terminator(TerminatorKind.BRANCH,
            (Successor(break_path, tuple(u.id for u in branch_uses[1:4])),
             Successor(continue_path, tuple(u.id for u in branch_uses[4:7]))),
            condition=branch_uses[0].id))
    operations.append(branch)

    break_pending = ProtocolValue(ValueID("loop-transfer.pending.break"), region,
        OperationResult(OperationID("loop-transfer.make.break"), 0), P.PENDING_COMPLETION)
    values.append(break_pending)
    make_break = Operation(OperationID("loop-transfer.make.break"), "construct Break",
        (Behavior.CONTROL,), (), (break_pending.id,), effects_complete=True)
    operations.append(make_break)
    continue_pending = ProtocolValue(ValueID("loop-transfer.pending.continue"), region,
        OperationResult(OperationID("loop-transfer.make.continue"), 0), P.PENDING_COMPLETION)
    values.append(continue_pending)
    make_continue = Operation(OperationID("loop-transfer.make.continue"), "construct Continue",
        (Behavior.CONTROL,), (), (continue_pending.id,), effects_complete=True)
    operations.append(make_continue)

    break_jump_uses = (_use("loop-transfer.break.to-cleanup.pending", break_pending.id,
                            UseRole.PROTOCOL),
                       _use("loop-transfer.break.to-cleanup.ref", break_ref.id,
                            UseRole.REFERENCE),
                       _use("loop-transfer.break.to-cleanup.world", break_world.id,
                            UseRole.STATE_CONTENT),
                       _use("loop-transfer.break.to-cleanup.condition", break_condition.id,
                            UseRole.DATA))
    break_jump = Operation(OperationID("loop-transfer.break.to-cleanup"), "Break to cleanup",
        (Behavior.CONTROL,), break_jump_uses,
        terminator=_jump("loop-transfer.break.to-cleanup", cleanup,
                         tuple(u.id for u in break_jump_uses)))
    operations.append(break_jump)
    continue_jump_uses = (_use("loop-transfer.continue.to-cleanup.pending", continue_pending.id,
                              UseRole.PROTOCOL),
                          _use("loop-transfer.continue.to-cleanup.ref", continue_ref.id,
                              UseRole.REFERENCE),
                          _use("loop-transfer.continue.to-cleanup.world", continue_world.id,
                              UseRole.STATE_CONTENT),
                          _use("loop-transfer.continue.to-cleanup.condition", continue_condition.id,
                              UseRole.DATA))
    continue_jump = Operation(OperationID("loop-transfer.continue.to-cleanup"),
        "Continue to cleanup", (Behavior.CONTROL,), continue_jump_uses,
        terminator=_jump("loop-transfer.continue.to-cleanup", cleanup,
                         tuple(u.id for u in continue_jump_uses)))
    operations.append(continue_jump)

    cleanup_world_use = _use("loop-transfer.cleanup.world.before", cleanup_world.id,
                             UseRole.STATE_CONTENT)
    cleanup_world_after = StateVersionValue(ValueID("loop-transfer.cleanup.world.after"),
        region, OperationResult(OperationID("loop-transfer.cleanup.write"), 0), world)
    values.append(cleanup_world_after)
    cleanup_write = Operation(OperationID("loop-transfer.cleanup.write"), "cleanup state write",
        (Behavior.READ, Behavior.WRITE, Behavior.MEMORY), (cleanup_world_use,),
        (cleanup_world_after.id,),
        (StateAccess(world, cleanup_world_use.id, AccessMode.READ_WRITE,
                     cleanup_world_after.id),), effects_complete=False)
    operations.append(cleanup_write)

    dispatch_pending = _use("loop-transfer.dispatch.pending", pending_arg.id, UseRole.PROTOCOL)
    break_ref_use = _use("loop-transfer.dispatch.break.ref", cleanup_ref.id, UseRole.REFERENCE)
    break_world_use = _use("loop-transfer.dispatch.break.world", cleanup_world_after.id,
                           UseRole.STATE_CONTENT)
    continue_ref_use = _use("loop-transfer.dispatch.continue.ref", cleanup_ref.id,
                            UseRole.REFERENCE)
    continue_condition_use = _use("loop-transfer.dispatch.continue.condition",
                                  cleanup_condition.id, UseRole.DATA)
    continue_world_use = _use("loop-transfer.dispatch.continue.world", cleanup_world_after.id,
                              UseRole.STATE_CONTENT)
    dispatch = Operation(OperationID("loop-transfer.dispatch"), "dispatch loop transfer",
        (Behavior.CONTROL,), (dispatch_pending, break_ref_use, break_world_use,
                              continue_ref_use, continue_condition_use, continue_world_use),
        terminator=PendingDispatchTerminator(dispatch_pending.id, (
            PendingSuccessor(ControlPortID("loop-transfer.port.break"), after,
                             (break_ref_use.id, break_world_use.id)),
            PendingSuccessor(ControlPortID("loop-transfer.port.continue"), header,
                             (continue_ref_use.id, continue_condition_use.id,
                              continue_world_use.id)),
        )))
    operations.append(dispatch)

    after_uses = (_use("loop-transfer.after.return.ref", after_ref.id, UseRole.REFERENCE),
                  _use("loop-transfer.after.return.world", after_world.id, UseRole.STATE_CONTENT))
    return_op = Operation(OperationID("loop-transfer.after.return"), "return after loop",
        (Behavior.CONTROL,), after_uses,
        terminator=Terminator(TerminatorKind.RETURN, exit="normal",
                              values=tuple(u.id for u in after_uses)))
    operations.append(return_op)

    blocks = (
        Block(entry, (entry_ref.id, entry_condition.id, entry_world.id), (enter.id,)),
        Block(header, (header_ref.id, header_condition.id, header_world.id), (branch.id,)),
        Block(break_path, (break_ref.id, break_condition.id, break_world.id),
              (make_break.id, break_jump.id)),
        Block(continue_path, (continue_ref.id, continue_condition.id, continue_world.id),
              (make_continue.id, continue_jump.id)),
        Block(cleanup, (pending_arg.id, cleanup_ref.id, cleanup_world.id,
                        cleanup_condition.id),
              (cleanup_write.id, dispatch.id)),
        Block(after, (after_ref.id, after_world.id), (return_op.id,)),
    )
    region_record = Region(region, "loop transfer fixture", entry, blocks, (
        ExitPort("normal", ExitKind.NORMAL,
                 (ValueType(ValueKind.REFERENCE), ValueType(ValueKind.STATE, location=world))),
    ))
    loop_scope = ControlScope(loop, region, function, ControlScopeKind.LOOP,
                              _source("transfer.loop", 2), (header, break_path, continue_path))
    cleanup_scope = ControlScope(cleanup_scope_id, region, loop, ControlScopeKind.CLEANUP,
                                 _source("transfer.cleanup", 3), (cleanup,))
    scopes = _entry_and_scopes(region, function, (entry, after), (loop_scope, cleanup_scope))
    ports = (
        ControlPort(ControlPortID("loop-transfer.port.break"), loop, K.BREAK, block=after),
        ControlPort(ControlPortID("loop-transfer.port.continue"), loop, K.CONTINUE,
                    block=header),
    )
    return ProgramGraph(region, (region_record,), tuple(operations), tuple(values),
        (StateLocation(world, "loop transfer world", stability=Stability.UNKNOWN),),
        control_scopes=scopes, control_ports=ports,
        pending_completions=(
            PendingCompletionDefinition(break_pending.id, ports[0].id),
            PendingCompletionDefinition(continue_pending.id, ports[1].id),
        ))


__all__ = ["loop_pending_graph", "loop_transfer_graph", "shared_pending_graph"]
