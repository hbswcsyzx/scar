"""Small valid CALL/INVOKE graphs for static input-origin recipes.

The declarations are fixtures, not recovered Python source or dynamic call
evidence. The optional loop carries a prior protocol request through an
original block argument so the query must retain that route separately.
"""
from scar.ir.program.control import ProtocolValueKind
from scar.ir.program.drivers import RawRequestDefinition, RawRequestKind
from scar.ir.program.ids import BlockID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, CompletionResult, CompletionSignature,
    CompletionSuccessor, DataValue, ExitKind, ExitPort, LiteralOrigin,
    Operation, OperationResult, ProgramGraph, ProtocolValue, ReferenceValue,
    Region, Successor, Terminator, TerminatorKind, Use, UseRole, ValueKind,
    ValueType, ProtocolValueType,
)


REFERENCE = ValueType(ValueKind.REFERENCE)
RAW = ProtocolValueType(ProtocolValueKind.RAW_DRIVER_REQUEST)


def _use(name, value, role):
    return Use(UseID(name), value, role)


def _block(name, arguments, operations):
    return Block(BlockID(name), tuple(item if type(item) is ValueID else ValueID(item)
                                    for item in arguments),
                 tuple(item if type(item) is OperationID else OperationID(item)
                       for item in operations))


def _region(name, entry, blocks, exits, parent=None):
    return Region(RegionID(name), name, BlockID(entry), tuple(blocks), tuple(exits), parent)


def _terminal(name, *, raised=False):
    return Operation(OperationID(name), name, (Behavior.CONTROL,),
        terminator=Terminator(TerminatorKind.RAISE if raised else TerminatorKind.RETURN,
                              exit="failure" if raised else "normal"))


def input_origin_program(*, invoke_middle=True, loop=False, recursive=False,
                         second_caller=True):
    """Return ``(graph, details)`` for a two-layer raw CALL/INVOKE route.

    Two same-typed actuals are deliberately reversed at distinct call sites:
    one request pack receives literal None and the other receives an ordinary
    reference result. With ``loop=True``, a second request producer feeds a
    header argument through a real backedge.
    """
    root_id, middle_id, driver_id = map(RegionID, ("inputs.root", "inputs.middle", "inputs.driver"))
    make_id = OperationID("inputs.make.non_none")
    none_value_id = ValueID("inputs.source.none")
    produced_value_id = ValueID("inputs.source.produced")
    values = [
        ReferenceValue(none_value_id, root_id, LiteralOrigin(None), targets=()),
        ReferenceValue(produced_value_id, root_id, OperationResult(make_id, 0)),
    ]
    root_operations = [Operation(make_id, "make non-None reference", (Behavior.COMPUTE,),
                                  results=(produced_value_id,))]
    raw_values, raw_rows, caller_rows = {}, [], []

    def request_pack(name, source_value):
        op_id = OperationID(name)
        value_id = ValueID(name + ".raw")
        operand = _use(name + ".operand", source_value, UseRole.REFERENCE)
        op = Operation(op_id, "pack raw SEND request", (Behavior.COMPUTE,), (operand,),
                       (value_id,), effects_complete=True)
        raw = ProtocolValue(value_id, root_id, OperationResult(op_id, 0),
                            ProtocolValueKind.RAW_DRIVER_REQUEST)
        row = RawRequestDefinition(value_id, RawRequestKind.SEND, (operand.id,))
        values.append(raw)
        root_operations.append(op)
        raw_values[name] = value_id
        raw_rows.append(row)
        return value_id

    none_raw = request_pack("inputs.rawpack.none", none_value_id)
    value_raw = request_pack("inputs.rawpack.value", produced_value_id)
    middle_raw = ProtocolValue(ValueID("inputs.middle.raw"), middle_id,
                               BlockArgument(BlockID("inputs.middle.entry"), 0),
                               ProtocolValueKind.RAW_DRIVER_REQUEST)
    middle_payload = ReferenceValue(ValueID("inputs.middle.payload"), middle_id,
                                    BlockArgument(BlockID("inputs.middle.entry"), 1))
    driver_raw = ProtocolValue(ValueID("inputs.driver.raw"), driver_id,
                               BlockArgument(BlockID("inputs.driver.entry"), 0),
                               ProtocolValueKind.RAW_DRIVER_REQUEST)
    values.extend((middle_raw, middle_payload, driver_raw))

    caller_arguments = (("inputs.call.none", none_raw, none_value_id),)
    if second_caller:
        caller_arguments += (("inputs.call.value", value_raw, produced_value_id),)
    for name, raw_value, payload_value in caller_arguments:
        raw_use = _use(name + ".raw", raw_value, UseRole.PROTOCOL)
        payload_use = _use(name + ".payload", payload_value, UseRole.REFERENCE)
        root_operations.append(Operation(
            OperationID(name), "CALL shared middle", (Behavior.CONTROL,),
            (raw_use, payload_use), callee=middle_id,
            call_arguments=(raw_use.id, payload_use.id)))
        caller_rows.append(OperationID(name))
    root_operations.append(_terminal("inputs.root.done"))
    root = _region("inputs.root", "inputs.root.entry", (
        _block("inputs.root.entry", (), tuple(op.id.value for op in root_operations)),
    ), (ExitPort("normal", ExitKind.NORMAL, ()),))

    middle_operations = []
    middle_blocks = []
    middle_values = []
    middle_raw_id = middle_raw.id
    middle_payload_id = middle_payload.id
    middle_entry_args = (middle_raw_id, middle_payload_id)
    raw_for_driver = middle_raw_id
    if loop:
        header_id, body_id, exit_id = (BlockID("inputs.middle.header"),
                                       BlockID("inputs.middle.body"),
                                       BlockID("inputs.middle.exit"))
        header_raw = ProtocolValue(ValueID("inputs.middle.header.raw"), middle_id,
                                   BlockArgument(header_id, 0),
                                   ProtocolValueKind.RAW_DRIVER_REQUEST)
        header_payload = ReferenceValue(ValueID("inputs.middle.header.payload"), middle_id,
                                        BlockArgument(header_id, 1))
        body_payload = ReferenceValue(ValueID("inputs.middle.body.payload"), middle_id,
                                      BlockArgument(body_id, 0))
        exit_raw = ProtocolValue(ValueID("inputs.middle.exit.raw"), middle_id,
                                 BlockArgument(exit_id, 0), ProtocolValueKind.RAW_DRIVER_REQUEST)
        exit_payload = ReferenceValue(ValueID("inputs.middle.exit.payload"), middle_id,
                                      BlockArgument(exit_id, 1))
        loop_condition = DataValue(ValueID("inputs.middle.loop.condition"), middle_id,
                                   LiteralOrigin(True), "builtins.bool")
        loop_raw_id = ValueID("inputs.middle.loop.raw")
        loop_raw_op_id = OperationID("inputs.middle.rawpack.loop")
        loop_raw_operand = _use("inputs.middle.rawpack.loop.operand", body_payload.id,
                                UseRole.REFERENCE)
        loop_raw_op = Operation(loop_raw_op_id, "fresh raw request on loop body",
                                (Behavior.COMPUTE,), (loop_raw_operand,), (loop_raw_id,),
                                effects_complete=True)
        loop_raw = ProtocolValue(loop_raw_id, middle_id, OperationResult(loop_raw_op_id, 0),
                                 ProtocolValueKind.RAW_DRIVER_REQUEST)
        middle_values.extend((header_raw, header_payload, body_payload, exit_raw,
                              exit_payload, loop_condition, loop_raw))
        raw_rows.append(RawRequestDefinition(loop_raw_id, RawRequestKind.SEND,
                                             (loop_raw_operand.id,)))

        enter_raw = _use("inputs.middle.enter.raw", middle_raw_id, UseRole.PROTOCOL)
        enter_payload = _use("inputs.middle.enter.payload", middle_payload_id,
                             UseRole.REFERENCE)
        enter = Operation(OperationID("inputs.middle.enter"), "enter loop header",
            (Behavior.CONTROL,), (enter_raw, enter_payload),
            terminator=Terminator(TerminatorKind.JUMP, (Successor(header_id,
                (enter_raw.id, enter_payload.id)),)))
        observe_raw = _use("inputs.middle.observe.raw", header_raw.id, UseRole.PROTOCOL)
        observe = Operation(OperationID("inputs.middle.observe"), "observe carried raw request",
                            (Behavior.COMPUTE,), (observe_raw,), effects_complete=True)
        condition_use = _use("inputs.middle.loop.test", loop_condition.id, UseRole.DATA)
        body_arg = _use("inputs.middle.branch.body.payload", header_payload.id,
                        UseRole.REFERENCE)
        exit_raw_arg = _use("inputs.middle.branch.exit.raw", header_raw.id, UseRole.PROTOCOL)
        exit_payload_arg = _use("inputs.middle.branch.exit.payload", header_payload.id,
                                 UseRole.REFERENCE)
        branch = Operation(OperationID("inputs.middle.branch"), "loop or exit",
            (Behavior.CONTROL,), (condition_use, body_arg, exit_raw_arg, exit_payload_arg),
            terminator=Terminator(TerminatorKind.BRANCH, (
                Successor(body_id, (body_arg.id,)),
                Successor(exit_id, (exit_raw_arg.id, exit_payload_arg.id))),
                condition=condition_use.id))
        back_raw = _use("inputs.middle.back.raw", loop_raw_id, UseRole.PROTOCOL)
        back_payload = _use("inputs.middle.back.payload", body_payload.id, UseRole.REFERENCE)
        backedge = Operation(OperationID("inputs.middle.backedge"), "loop backedge",
            (Behavior.CONTROL,), (back_raw, back_payload),
            terminator=Terminator(TerminatorKind.JUMP, (Successor(header_id,
                (back_raw.id, back_payload.id)),)))
        middle_operations.extend((enter, observe, branch, loop_raw_op, backedge))
        middle_blocks.extend((
            _block("inputs.middle.entry", middle_entry_args, (enter.id.value,)),
            _block(header_id.value, (header_raw.id.value, header_payload.id.value),
                   (observe.id.value, branch.id.value)),
            _block(body_id.value, (body_payload.id.value,),
                   (loop_raw_op.id.value, backedge.id.value)),
            _block(exit_id.value, (exit_raw.id.value, exit_payload.id.value), ()),
        ))
        raw_for_driver = exit_raw.id
    else:
        middle_blocks.append(_block("inputs.middle.entry", middle_entry_args, ()))

    if recursive:
        recursive_raw = _use("inputs.middle.recursive.raw", middle_raw_id if not loop else header_raw.id,
                             UseRole.PROTOCOL)
        recursive_payload_value = middle_payload_id if not loop else header_payload.id
        recursive_payload = _use("inputs.middle.recursive.payload", recursive_payload_value,
                                 UseRole.REFERENCE)
        self_call = Operation(OperationID("inputs.middle.recursive.call"), "recursive CALL",
            (Behavior.CONTROL,), (recursive_raw, recursive_payload), callee=middle_id,
            call_arguments=(recursive_raw.id, recursive_payload.id))
        middle_operations.insert(0, self_call)
        recursive_block_index = 1 if loop else 0
        recursive_block = middle_blocks[recursive_block_index]
        entry_operations = list(recursive_block.operations)
        entry_operations.insert(0, self_call.id)
        middle_blocks[recursive_block_index] = Block(
            recursive_block.id, recursive_block.arguments, tuple(entry_operations))

    if invoke_middle:
        normal_id, caught_id = BlockID("inputs.middle.normal"), BlockID("inputs.middle.caught")
        actual_raw = _use("inputs.middle.invoke.raw", raw_for_driver, UseRole.PROTOCOL)
        invoke = Operation(OperationID("inputs.middle.invoke.driver"), "INVOKE driver",
            (Behavior.CONTROL,), (actual_raw,), callee=driver_id,
            completions=(CompletionSignature(ExitKind.NORMAL, ()),
                         CompletionSignature(ExitKind.RAISE, ())),
            invoke_arguments=(actual_raw.id,), effects_complete=True,
            terminator=Terminator(TerminatorKind.INVOKE, (
                CompletionSuccessor(ExitKind.NORMAL, normal_id, ()),
                CompletionSuccessor(ExitKind.RAISE, caught_id, ()))))
        normal_done, caught_done = (_terminal("inputs.middle.normal.done"),
                                    _terminal("inputs.middle.caught.done"))
        middle_operations.extend((invoke, normal_done, caught_done))
        if loop:
            middle_blocks[-1] = Block(middle_blocks[-1].id,
                                      middle_blocks[-1].arguments, (invoke.id,))
        else:
            entry_block = middle_blocks[0]
            middle_blocks[0] = Block(entry_block.id, entry_block.arguments,
                                     (*entry_block.operations, invoke.id))
        middle_blocks.extend((
            _block(normal_id.value, (), (normal_done.id.value,)),
            _block(caught_id.value, (), (caught_done.id.value,))))
        middle_idempotent_exit = (ExitPort("normal", ExitKind.NORMAL, ()),)
        driver_exits = (ExitPort("normal", ExitKind.NORMAL, ()),
                        ExitPort("failure", ExitKind.RAISE, ()))
    else:
        actual_raw = _use("inputs.middle.call.raw", raw_for_driver, UseRole.PROTOCOL)
        call_driver = Operation(OperationID("inputs.middle.call.driver"), "CALL driver",
            (Behavior.CONTROL,), (actual_raw,), callee=driver_id,
            call_arguments=(actual_raw.id,))
        done = _terminal("inputs.middle.call.done")
        middle_operations.extend((call_driver, done))
        if loop:
            middle_blocks[-1] = Block(middle_blocks[-1].id,
                                      middle_blocks[-1].arguments,
                                      (call_driver.id, done.id))
        else:
            entry_block = middle_blocks[0]
            middle_blocks[0] = Block(entry_block.id, entry_block.arguments,
                                     (*entry_block.operations, call_driver.id,
                                      done.id))
        middle_idempotent_exit = (ExitPort("normal", ExitKind.NORMAL, ()),)
        driver_exits = (ExitPort("normal", ExitKind.NORMAL, ()),)

    middle = _region("inputs.middle", "inputs.middle.entry", middle_blocks,
                     middle_idempotent_exit, parent=root_id)
    driver_consume_use = _use("inputs.driver.consume.raw", driver_raw.id, UseRole.PROTOCOL)
    driver_consume = Operation(OperationID("inputs.driver.consume"), "consume raw request",
                               (Behavior.COMPUTE,), (driver_consume_use,), effects_complete=True)
    driver_done, driver_fail = _terminal("inputs.driver.done"), _terminal(
        "inputs.driver.fail", raised=True)
    driver_operations = [driver_consume, driver_done]
    driver_blocks = []
    if invoke_middle:
        driver_route_value = DataValue(ValueID("inputs.driver.route"), driver_id,
                                       LiteralOrigin(True), "builtins.bool")
        driver_route_condition = _use("inputs.driver.route.condition",
                                      driver_route_value.id, UseRole.DATA)
        driver_route = Operation(OperationID("inputs.driver.route"), "route driver exit",
            (Behavior.CONTROL,), (driver_route_condition,), effects_complete=True,
            terminator=Terminator(TerminatorKind.BRANCH, (
                Successor(BlockID("inputs.driver.normal"), ()),
                Successor(BlockID("inputs.driver.failure"), ())),
                condition=driver_route_condition.id))
        driver_operations.append(driver_route)
        driver_operations.append(driver_fail)
        driver_blocks.extend((
            _block("inputs.driver.entry", (driver_raw.id,),
                   (driver_consume.id, driver_route.id)),
            _block("inputs.driver.normal", (), (driver_done.id,)),
            _block("inputs.driver.failure", (), (driver_fail.id,)),
        ))
        values.append(driver_route_value)
    else:
        driver_blocks.append(_block("inputs.driver.entry", (driver_raw.id,),
                                     (driver_consume.id, driver_done.id)))
    driver = _region("inputs.driver", "inputs.driver.entry", driver_blocks,
                     driver_exits, parent=middle_id)

    graph = ProgramGraph(root_id, (root, middle, driver),
        (*root_operations, *middle_operations, *driver_operations),
        (*values, *middle_values), raw_driver_requests=tuple(raw_rows))
    details = {
        "caller_operations": tuple(caller_rows),
        "middle": middle_id,
        "driver": driver_id,
        "driver_consumer": driver_consume.id,
        "driver_consumer_use": driver_consume_use.id,
        "middle_formal": middle_raw.id,
        "middle_payload_formal": middle_payload.id,
        "raw_values": tuple(raw_values.values()),
        "raw_definitions": tuple(raw_rows),
        "none_value": none_value_id,
        "produced_value": produced_value_id,
        "make_operation": make_id,
        "loop_observer": (OperationID("inputs.middle.observe"),
                          UseID("inputs.middle.observe.raw")) if loop else None,
        "loop_raw": ValueID("inputs.middle.loop.raw") if loop else None,
        "middle_to_driver": (OperationID("inputs.middle.invoke.driver") if invoke_middle
                             else OperationID("inputs.middle.call.driver")),
        "invoke_middle": invoke_middle,
        "loop": loop,
        "recursive": recursive,
    }
    return graph, details


__all__ = ["input_origin_program"]
