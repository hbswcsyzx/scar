"""Original CALL/INVOKE state ports, without runtime or native identity claims."""
from scar.ir.program.control import ExceptionPacketDefinition, ProtocolValueKind, ProtocolValueType
from scar.ir.program.ids import BlockID, LocationID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, CompletionResult, CompletionSignature,
    CompletionSuccessor, DataValue, ExitKind, ExitPort, InvokeLiteralResult,
    LiteralOrigin, Operation, OperationResult, ProgramGraph, ProtocolValue,
    ReferenceValue, Region, StateAccess, StateLocation, StateVersionValue,
    Successor, Terminator, TerminatorKind, Use, UseRole, ValueKind, ValueType,
)
from scar.ir.program.protocols import OwnedUse
from scar.ir.program.state_addresses import InvokeStateOperand
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.program_protocol_graphs import _scope


REFERENCE = ValueType(ValueKind.REFERENCE)
BOOLEAN = ValueType(ValueKind.DATA, "builtins.bool")
PACKET = ProtocolValueType(ProtocolValueKind.EXCEPTION_PACKET)


def call_return_state_program(*, normal_write=False, two_callers=False):
    """Return a valid declared program and original endpoints for source queries.

    The callee preserves both domains on NORMAL by default. RAISE writes only
    world and returns context/packet/world in that order. Each caller has its
    RAISE edge first and a separate forwarded-reference landing prefix, so
    neither successor nor formal positions equal completion-slot positions.

    ``normal_write`` retains the same reference while changing world on NORMAL.
    ``two_callers`` adds a distinct, alternative invocation of the same callee;
    it does not supply a dynamic occurrence context for an internal source.
    """
    root, callee = RegionID("return-state.root"), RegionID("return-state.helper")
    world, context = LocationID("return-state.world"), LocationID("return-state.context")
    world_type = ValueType(ValueKind.STATE, location=world)
    context_type = ValueType(ValueKind.STATE, location=context)
    values, operations, packet_definitions = [], [], []

    def formal(name, region, block, ordinal, type_):
        origin, identity = BlockArgument(block, ordinal), ValueID(name)
        if type_.kind is ValueKind.REFERENCE:
            value = ReferenceValue(identity, region, origin)
        elif type_.kind is ValueKind.DATA:
            value = DataValue(identity, region, origin, type_.data_type)
        elif type_.kind is ValueKind.STATE:
            value = StateVersionValue(identity, region, origin, type_.location)
        else:
            value = ProtocolValue(identity, region, origin, type_.protocol)
        values.append(value)
        return value

    def use(name, value):
        role = (UseRole.STATE_CONTENT if isinstance(value, StateVersionValue) else
                UseRole.PROTOCOL if isinstance(value, ProtocolValue) else
                UseRole.DATA if isinstance(value, DataValue) else UseRole.REFERENCE)
        return Use(UseID(name), value.id, role)

    def owned(operation, item):
        return OwnedUse(operation.id, item.id)

    def write(name, region, before):
        identity = OperationID(name)
        actual = use(name + ".before", before)
        after = StateVersionValue(ValueID(name + ".after"), region,
                                  OperationResult(identity, 0), world)
        values.append(after)
        operation = Operation(identity, "original coarse world write",
            (Behavior.READ, Behavior.WRITE), (actual,), (after.id,),
            (StateAccess(world, actual.id, AccessMode.READ_WRITE, after.id),),
            effects_complete=True)
        operations.append(operation)
        return operation, after

    entry = BlockID("return-state.helper.entry")
    normal = BlockID("return-state.helper.normal")
    failure = BlockID("return-state.helper.failure")
    arguments = tuple(formal(f"return-state.helper.input.{index}", callee, entry, index, type_)
        for index, type_ in enumerate((REFERENCE, REFERENCE, BOOLEAN, world_type, context_type)))
    n = tuple(formal(f"return-state.helper.normal.{index}", callee, normal, index, type_)
        for index, type_ in enumerate((REFERENCE, world_type, context_type)))
    r = tuple(formal(f"return-state.helper.failure.{index}", callee, failure, index, type_)
        for index, type_ in enumerate((REFERENCE, world_type, context_type)))
    choose = OperationID("return-state.helper.choose")
    condition = use(choose.value + ".condition", arguments[2])
    n_actuals = tuple(use(choose.value + f".normal.{i}", value)
                      for i, value in enumerate((arguments[0], arguments[3], arguments[4])))
    r_actuals = tuple(use(choose.value + f".failure.{i}", value)
                      for i, value in enumerate((arguments[1], arguments[3], arguments[4])))
    branch = Operation(choose, "original helper normal or raise", (Behavior.CONTROL,),
        (condition, *n_actuals, *r_actuals), effects_complete=True,
        terminator=Terminator(TerminatorKind.BRANCH,
            (Successor(normal, tuple(item.id for item in n_actuals)),
             Successor(failure, tuple(item.id for item in r_actuals))), condition=condition.id))
    operations.append(branch)
    normal_operations, normal_state = [], n[1]
    normal_writer = None
    if normal_write:
        normal_writer, normal_state = write("return-state.helper.normal.write", callee, n[1])
        normal_operations.append(normal_writer.id)
    returned = tuple(use(f"return-state.helper.return.{i}", value)
                     for i, value in enumerate((n[0], normal_state, n[2])))
    normal_exit = Operation(OperationID("return-state.helper.return"), "original helper RETURN",
        (Behavior.CONTROL,), returned, effects_complete=True,
        terminator=Terminator(TerminatorKind.RETURN, exit="normal",
                              values=tuple(item.id for item in returned)))
    operations.append(normal_exit)
    normal_operations.append(normal_exit.id)

    writer, raised_state = write("return-state.helper.failure.write", callee, r[1])
    traceback = ReferenceValue(ValueID("return-state.helper.traceback.none"), callee,
                               LiteralOrigin(None), targets=())
    values.append(traceback)
    pack_id = OperationID("return-state.helper.pack")
    exception_use, traceback_use = use(pack_id.value + ".exception", r[0]), use(pack_id.value + ".traceback", traceback)
    packet = ProtocolValue(ValueID(pack_id.value + ".value"), callee,
                           OperationResult(pack_id, 0), ProtocolValueKind.EXCEPTION_PACKET)
    values.append(packet)
    pack = Operation(pack_id, "original exception packet construction", (Behavior.CONTROL,),
                     (exception_use, traceback_use), (packet.id,), effects_complete=True)
    packet_definitions.append(ExceptionPacketDefinition(packet.id, exception_use.id, traceback_use.id))
    raised = tuple(use(f"return-state.helper.raise.{i}", value)
                   for i, value in enumerate((r[2], packet, raised_state)))
    failure_exit = Operation(OperationID("return-state.helper.raise"), "original helper RAISE",
        (Behavior.CONTROL,), raised, effects_complete=True,
        terminator=Terminator(TerminatorKind.RAISE, exit="failure",
                              values=tuple(item.id for item in raised)))
    operations.extend((pack, failure_exit))
    callee_blocks = (Block(entry, tuple(value.id for value in arguments), (branch.id,)),
        Block(normal, tuple(value.id for value in n), tuple(normal_operations)),
        Block(failure, tuple(value.id for value in r), (writer.id, pack.id, failure_exit.id)))
    normal_types = (REFERENCE, world_type, context_type)
    failure_types = (context_type, PACKET, world_type)
    helper = Region(callee, "declared two-domain helper", entry, callee_blocks,
        (ExitPort("normal", ExitKind.NORMAL, normal_types),
         ExitPort("failure", ExitKind.RAISE, failure_types)), parent=root)

    root_entry = BlockID("return-state.root.entry")
    root_inputs = tuple(formal(f"return-state.root.input.{i}", root, root_entry, i, type_)
        for i, type_ in enumerate((REFERENCE, REFERENCE, REFERENCE, BOOLEAN, BOOLEAN, world_type, context_type)))
    root_blocks, callers, entry_actuals, entry_edges = [], {}, [], []
    for label in (("a", "b") if two_callers else ("a",)):
        prefix = "return-state.call." + label
        call_block, n_block, r_block = (BlockID(prefix + suffix) for suffix in (".entry", ".normal", ".raise"))
        inputs = tuple(formal(prefix + f".input.{i}", root, call_block, i, type_)
            for i, type_ in enumerate((REFERENCE, REFERENCE, BOOLEAN, world_type, context_type)))
        actual_values = (root_inputs[0 if label == "a" else 1], root_inputs[2],
                         root_inputs[4], root_inputs[5], root_inputs[6])
        ingress = tuple(use(prefix + f".entry.{i}", value) for i, value in enumerate(actual_values))
        entry_actuals.extend(ingress)
        entry_edges.append(Successor(call_block, tuple(item.id for item in ingress)))
        actuals = tuple(use(prefix + f".argument.{i}", value) for i, value in enumerate(inputs))
        n_forward, r_forward = use(prefix + ".normal.forward", inputs[0]), use(prefix + ".raise.forward", inputs[0])
        n_formals = tuple(formal(prefix + f".normal.{i}", root, n_block, i, type_)
            for i, type_ in enumerate((REFERENCE, context_type, REFERENCE, world_type)))
        r_formals = tuple(formal(prefix + f".raise.{i}", root, r_block, i, type_)
            for i, type_ in enumerate((REFERENCE, world_type, context_type, PACKET)))
        invocation = Operation(OperationID(prefix), "original known-callee INVOKE", (Behavior.CONTROL,),
            (*actuals, n_forward, r_forward), effects_complete=True, callee=callee,
            invoke_arguments=tuple(item.id for item in actuals),
            completions=(CompletionSignature(ExitKind.RAISE, failure_types),
                         CompletionSignature(ExitKind.NORMAL, normal_types)),
            terminator=Terminator(TerminatorKind.INVOKE, (
                CompletionSuccessor(ExitKind.RAISE, r_block,
                    (r_forward.id, CompletionResult(2), CompletionResult(0), CompletionResult(1))),
                CompletionSuccessor(ExitKind.NORMAL, n_block,
                    (n_forward.id, CompletionResult(2), CompletionResult(0), CompletionResult(1))))))
        operations.append(invocation)
        root_blocks.append(Block(call_block, tuple(value.id for value in inputs), (invocation.id,)))
        consumers = {}
        for kind, block, payload, w, c, formals_ in (
                (ExitKind.NORMAL, n_block, n_formals[2], n_formals[3], n_formals[1], n_formals),
                (ExitKind.RAISE, r_block, r_formals[3], r_formals[1], r_formals[2], r_formals)):
            name = prefix + ".consume." + kind.value.lower()
            payload_use, world_use, context_use = use(name + ".payload", payload), use(name + ".world", w), use(name + ".context", c)
            consumer = Operation(OperationID(name), "original payload and current-state consumer",
                (Behavior.READ,), (payload_use, world_use, context_use), accesses=(
                    StateAccess(world, world_use.id, AccessMode.READ),
                    StateAccess(context, context_use.id, AccessMode.READ)), effects_complete=True)
            terminal_uses = tuple(use(name + f".exit.{i}", value) for i, value in enumerate((payload, w, c)))
            terminal = Operation(OperationID(name + ".exit"), "original caller completion",
                (Behavior.CONTROL,), terminal_uses, effects_complete=True,
                terminator=Terminator(TerminatorKind.RETURN if kind is ExitKind.NORMAL else TerminatorKind.RAISE,
                    exit="normal" if kind is ExitKind.NORMAL else "failure",
                    values=tuple(item.id for item in terminal_uses)))
            operations.extend((consumer, terminal))
            root_blocks.append(Block(block, tuple(value.id for value in formals_), (consumer.id, terminal.id)))
            consumers[kind] = {"operation": consumer, "payload": owned(consumer, payload_use),
                               "world": owned(consumer, world_use), "context": owned(consumer, context_use)}
        callers[label] = {"operation": invocation, "arguments": tuple(owned(invocation, item) for item in actuals),
            "world_site": InvokeStateOperand(invocation.id, actuals[3].id), "consumers": consumers,
            "normal_formals": n_formals, "raise_formals": r_formals,
            "normal_world": InvokeLiteralResult(ControlEdgeReference(invocation.id, 1), CompletionResult(1)),
            "normal_reference": InvokeLiteralResult(ControlEdgeReference(invocation.id, 1), CompletionResult(0)),
            "raise_world": InvokeLiteralResult(ControlEdgeReference(invocation.id, 0), CompletionResult(2)),
            "raise_context": InvokeLiteralResult(ControlEdgeReference(invocation.id, 0), CompletionResult(0))}
    enter_id = OperationID("return-state.root.enter")
    if two_callers:
        root_condition = use(enter_id.value + ".condition", root_inputs[3])
        entry_uses = (root_condition, *entry_actuals)
        entry_term = Terminator(TerminatorKind.BRANCH, tuple(entry_edges), condition=root_condition.id)
    else:
        entry_uses, entry_term = tuple(entry_actuals), Terminator(TerminatorKind.JUMP, tuple(entry_edges))
    enter = Operation(enter_id, "original caller selection", (Behavior.CONTROL,),
                      entry_uses, effects_complete=True, terminator=entry_term)
    operations.append(enter)
    root_blocks.insert(0, Block(root_entry, tuple(value.id for value in root_inputs), (enter.id,)))
    root_region = Region(root, "declared callers", root_entry, tuple(root_blocks), (
        ExitPort("normal", ExitKind.NORMAL, normal_types),
        ExitPort("failure", ExitKind.RAISE, (PACKET, world_type, context_type))))
    graph = ProgramGraph(root, (root_region, helper), tuple(operations), tuple(values),
        locations=(StateLocation(world, "original coarse world"), StateLocation(context, "independent context domain")),
        control_scopes=(_scope(root, root_blocks), _scope(callee, callee_blocks)),
        exception_packets=tuple(packet_definitions))
    return graph, {"callers": callers, "world": world, "context": context,
        "callee": helper, "callee_arguments": arguments, "raise_writer": writer,
        "raise_world": raised_state.origin, "normal_writer": normal_writer,
        "normal_return": normal_exit, "raise_return": failure_exit}
