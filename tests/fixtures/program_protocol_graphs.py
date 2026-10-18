"""Protocol connections over canonical CFG/Uses, never recovered Python execution.

The helper implementations and current native phase remain conditional source
contracts.  Names intentionally carry no protocol recognition semantics.
"""
from __future__ import annotations

from dataclasses import replace

from scar.ir.program.control import (
    ControlScope, ControlScopeKind, ExceptionPacketDefinition,
    ProtocolValueKind as P, ProtocolValueType,
)
from scar.ir.program.drivers import RawRequestDefinition, RawRequestKind
from scar.ir.program.ids import BlockID, ControlScopeID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.lifecycle import DriverLifecycle, DriveOutcomeRef
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, CompletionResult, CompletionSignature,
    CompletionSuccessor, DataValue, ExitKind, ExitPort, Footprint, FootprintKind,
    InvokeLiteralResult, LiteralOrigin, Operation, OperationResult, ProgramGraph, ProtocolValue,
    ReferenceValue, Region, StateAccess, StateVersionValue, Successor, Terminator,
    TerminatorKind, Use, UseRole, ValueKind, ValueType,
)
from scar.ir.program.state_addresses import ExistingAccess, InvokeStateOperand
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.program_control_graphs import _source
from tests.fixtures.program_driver_graphs import driver_program


REFERENCE = ValueType(ValueKind.REFERENCE)
PACKET = ProtocolValueType(P.EXCEPTION_PACKET)


def _op(graph, name):
    identity = OperationID(name) if isinstance(name, str) else name
    return next(operation for operation in graph.operations if operation.id == identity)


def _role(value):
    if isinstance(value, StateVersionValue):
        return UseRole.STATE_CONTENT
    if isinstance(value, ProtocolValue):
        return UseRole.PROTOCOL
    if isinstance(value, DataValue):
        return UseRole.DATA
    return UseRole.REFERENCE


def _clone(value, name, block, position):
    return replace(value, id=ValueID(name), origin=BlockArgument(block, position))


def _scope(region, blocks):
    return ControlScope(ControlScopeID(region.value + ".function"), region, None,
                        ControlScopeKind.FUNCTION, _source(region.value),
                        tuple(block.id for block in blocks))


def _terminal(name, payload, states, values, *, raised):
    uses = tuple(Use(UseID(f"{name}.u.{index}"), value, _role(values[value]))
                 for index, value in enumerate((payload, *states)))
    return Operation(OperationID(name), "an original host exit", (Behavior.CONTROL,), uses,
        terminator=Terminator(TerminatorKind.RAISE if raised else TerminatorKind.RETURN,
            exit="failure" if raised else "normal", values=tuple(use.id for use in uses)))


def _source_gap():
    from scar.ir.program.protocols import StaticGapReason, StaticProtocolGap
    return StaticProtocolGap(StaticGapReason.NATIVE_APPLICABILITY_UNPROVEN)


def request_processing_program(*, loop=False, previous_iteration=False):
    """THROW pack -> fresh Reference result -> packet, with distinct owned Uses.

    The loop variant executes the same producer before each consumer.  Its
    carried prior value has the same static producer on a backedge, but is not
    this visit's newly produced exception reference.
    """
    from scar.ir.program.ids import ProtocolScopeID
    from scar.ir.program.protocols import (
        ContractResult, OperationSiteSubject, OwnedUse, PacketConstruction, PacketRule,
        ProtocolClause as C, ProtocolOperation, ProtocolProfile as F, ProtocolScope,
        RequestOperandBinding, RequestProcessing, RequestProcessingRule as R,
    )
    region_id = RegionID("connection")
    entry, header, exit_block = (BlockID("connection.entry"), BlockID("connection.header"),
                                 BlockID("connection.exit"))
    arguments = tuple(ReferenceValue(ValueID(f"connection.input.{index}"), region_id,
                        BlockArgument(entry, index)) for index in range(4))
    condition = DataValue(ValueID("connection.again"), region_id, BlockArgument(entry, 4), "builtins.bool")
    values = [*arguments, condition]
    raw_id, process_id = OperationID("connection.a"), OperationID("connection.b")
    packet_id, other_packet_id = OperationID("connection.c"), OperationID("connection.d")
    raw = ProtocolValue(ValueID("connection.raw"), region_id, OperationResult(raw_id, 0), P.RAW_DRIVER_REQUEST)
    normalized = ReferenceValue(ValueID("connection.fresh"), region_id, OperationResult(process_id, 0))
    other_result = ReferenceValue(ValueID("connection.other.result"), region_id, OperationResult(process_id, 1))
    packet = ProtocolValue(ValueID("connection.packet"), region_id, OperationResult(packet_id, 0), P.EXCEPTION_PACKET)
    other_packet = ProtocolValue(ValueID("connection.other.packet"), region_id,
                                 OperationResult(other_packet_id, 0), P.EXCEPTION_PACKET)
    values.extend((raw, normalized, other_result, packet, other_packet))
    pack_uses = tuple(Use(UseID(f"connection.a.arg.{index}"), value.id, UseRole.REFERENCE)
                      for index, value in enumerate(arguments[:3]))
    pack = Operation(raw_id, "A", (Behavior.COMPUTE,), pack_uses, (raw.id,), effects_complete=True)
    processing_uses = (Use(UseID("connection.b.raw"), raw.id, UseRole.PROTOCOL),
        Use(UseID("connection.b.argument"), arguments[0].id, UseRole.REFERENCE))
    processing = Operation(process_id, "B", (Behavior.COMPUTE,), processing_uses,
                           (normalized.id, other_result.id), effects_complete=True)
    prior = ReferenceValue(ValueID("connection.prior"), region_id, BlockArgument(header, 0))
    if loop:
        values.append(prior)
    exception = prior.id if previous_iteration else normalized.id
    packet_uses = (Use(UseID("connection.c.exception"), exception, UseRole.REFERENCE),
                   Use(UseID("connection.c.traceback"), arguments[2].id, UseRole.REFERENCE))
    packet_op = Operation(packet_id, "C", (Behavior.CONTROL,), packet_uses,
                          (packet.id,), effects_complete=True)
    other_uses = (Use(UseID("connection.d.exception"), arguments[3].id, UseRole.REFERENCE),
                  Use(UseID("connection.d.traceback"), arguments[2].id, UseRole.REFERENCE))
    other_op = Operation(other_packet_id, "D", (Behavior.CONTROL,), other_uses,
                         (other_packet.id,), effects_complete=True)
    operations = [pack, processing, packet_op, other_op]
    by_value = {value.id: value for value in values}
    if loop:
        first = Use(UseID("connection.first"), arguments[0].id, UseRole.REFERENCE)
        jump = Operation(OperationID("connection.jump"), "E", (Behavior.CONTROL,), (first,),
            terminator=Terminator(TerminatorKind.JUMP, (Successor(header, (first.id,)),)))
        output = ProtocolValue(ValueID("connection.output"), region_id,
                               BlockArgument(exit_block, 0), P.EXCEPTION_PACKET)
        values.append(output)
        branch_uses = (Use(UseID("connection.condition"), condition.id, UseRole.DATA),
            Use(UseID("connection.next"), normalized.id, UseRole.REFERENCE),
            Use(UseID("connection.finish"), packet.id, UseRole.PROTOCOL))
        branch = Operation(OperationID("connection.branch"), "F", (Behavior.CONTROL,), branch_uses,
            terminator=Terminator(TerminatorKind.BRANCH,
                (Successor(header, (branch_uses[1].id,)), Successor(exit_block, (branch_uses[2].id,))),
                condition=branch_uses[0].id))
        terminal = _terminal("connection.exit", output.id, (), {output.id: output}, raised=True)
        blocks = (Block(entry, tuple(value.id for value in (*arguments, condition)), (pack.id, jump.id)),
                  Block(header, (prior.id,), (processing.id, packet_op.id, other_op.id, branch.id)),
                  Block(exit_block, (output.id,), (terminal.id,)))
        operations.extend((jump, branch, terminal))
    else:
        terminal = _terminal("connection.exit", packet.id, (), by_value, raised=True)
        operations.append(terminal)
        blocks = (Block(entry, tuple(value.id for value in (*arguments, condition)),
                        tuple(operation.id for operation in operations)),)
    region = Region(region_id, "conditional native request boundary", entry, blocks,
                    (ExitPort("failure", ExitKind.RAISE, (PACKET,)),))
    scope_id = ProtocolScopeID("connection.scope")
    scope = ProtocolScope(scope_id, F.CREATED_THROW_V1,
                          OperationSiteSubject(region_id, process_id), _source_gap())
    process_contract = RequestProcessing(processing_uses[0].id,
        (RequestOperandBinding(0, processing_uses[1].id),), OperationResult(process_id, 0), (),
        R.NORMALIZE_THROW_INSTANCE)
    source = ContractResult(scope_id, C.THROW_NORMALIZATION, process_id, 0,
                            OperationResult(process_id, 0))
    packet_contract = PacketConstruction(packet.id, source,
        OwnedUse(raw_id, pack_uses[2].id), PacketRule.THROW_PACKET_FROM_NORMALIZED)
    rows = (ProtocolOperation(scope_id, C.THROW_NORMALIZATION, process_id, 0, process_contract, _source_gap()),
            ProtocolOperation(scope_id, C.THROW_NORMALIZATION, packet_id, 0, packet_contract, _source_gap()))
    graph = ProgramGraph(region_id, (region,), tuple(operations), tuple(values),
        control_scopes=(_scope(region_id, blocks),),
        exception_packets=(ExceptionPacketDefinition(packet.id, *(use.id for use in packet_uses)),
                           ExceptionPacketDefinition(other_packet.id, *(use.id for use in other_uses))),
        raw_driver_requests=(RawRequestDefinition(raw.id, RawRequestKind.THROW,
                                                  tuple(use.id for use in pack_uses)),),
        protocol_scopes=(scope,), protocol_operations=rows)
    return graph, {"scope": scope_id, "processing": process_id, "pack": raw_id,
        "packet_operation": packet_id, "packet": packet.id, "other_packet": other_packet.id,
        "other_packet_operation": other_packet_id, "result": OperationResult(process_id, 0),
        "other_result": OperationResult(process_id, 1), "consumer_use": packet_uses[0].id,
        "rows": rows, "prior": prior.id if loop else None, "terminal": terminal.id}


def _insert_processing(graph, *, target):
    """A real INVOKE before the gate, retaining private gate->Drive landing."""
    interface, = graph.driver_interfaces
    region = next(region for region in graph.regions if region.id == interface.region)
    entry = next(block for block in region.blocks if block.id == region.entry)
    values = {value.id: value for value in graph.values}
    gate_row, = graph.final_body_gates
    gate = _op(graph, gate_row.operation)
    roles = tuple(value for value in entry.arguments if not isinstance(values[value], StateVersionValue))
    states = tuple(value for value in entry.arguments if isinstance(values[value], StateVersionValue))
    domains = tuple(values[value].location for value in states)
    state_types = tuple(ValueType(ValueKind.STATE, location=location) for location in domains)
    identity = OperationID("boundary.helper")
    normal_block, failure_block = BlockID("boundary.normal"), BlockID("boundary.failure")
    payload_type = PACKET if target == "packet" else REFERENCE
    payload = ProtocolValue(ValueID("boundary.result"), region.id,
        BlockArgument(normal_block, 2), P.EXCEPTION_PACKET) if target == "packet" else ReferenceValue(
        ValueID("boundary.result"), region.id, BlockArgument(normal_block, 2))
    copied = [_clone(values[value], f"boundary.normal.role.{index}", normal_block, index)
              for index, value in enumerate(roles[:2])]
    normal_states = [StateVersionValue(ValueID(f"boundary.normal.state.{index}"), region.id,
        BlockArgument(normal_block, index + 3), location) for index, location in enumerate(domains)]
    packet = ProtocolValue(ValueID("boundary.error"), region.id, BlockArgument(failure_block, 0), P.EXCEPTION_PACKET)
    failure_states = [StateVersionValue(ValueID(f"boundary.failure.state.{index}"), region.id,
        BlockArgument(failure_block, index + 1), location) for index, location in enumerate(domains)]
    raw_use = Use(UseID("boundary.raw"), interface.scheduler_request, UseRole.PROTOCOL)
    state_uses = tuple(Use(UseID(f"boundary.state.{index}"), value, UseRole.STATE_CONTENT)
                       for index, value in enumerate(states))
    forwards = tuple(Use(UseID(f"boundary.forward.{index}"), value, _role(values[value]))
                     for index, value in enumerate(roles[:2]))
    normal_edge = CompletionSuccessor(ExitKind.NORMAL, normal_block,
        (*(use.id for use in forwards), CompletionResult(0),
         *(CompletionResult(index + 1) for index in range(len(states)))))
    failure_edge = CompletionSuccessor(ExitKind.RAISE, failure_block,
        tuple(CompletionResult(index) for index in range(len(states) + 1)))
    helper = Operation(identity, "opaque source-relative request boundary", (Behavior.CONTROL,),
        (raw_use, *state_uses, *forwards), effects_complete=False,
        invoke_arguments=(raw_use.id, *(use.id for use in state_uses)),
        completions=(CompletionSignature(ExitKind.NORMAL, (payload_type, *state_types)),
                     CompletionSignature(ExitKind.RAISE, (PACKET, *state_types))),
        terminator=Terminator(TerminatorKind.INVOKE, (normal_edge, failure_edge)))
    replacement = dict(zip((*roles, *states),
        (*(value.id for value in copied), payload.id, *(value.id for value in normal_states))))
    gate = replace(gate, uses=tuple(replace(use, value=replacement.get(use.value, use.value)) for use in gate.uses))
    added_values = (*copied, payload, *normal_states, packet, *failure_states)
    values.update((value.id, value) for value in added_values)
    terminal = _terminal("boundary.raise", packet.id, tuple(value.id for value in failure_states), values, raised=True)
    blocks = tuple(replace(block, operations=(helper.id,)) if block.id == entry.id else block
                   for block in region.blocks)
    blocks = (*blocks, Block(normal_block, (*(value.id for value in copied), payload.id,
                                           *(value.id for value in normal_states)), (gate.id,)),
              Block(failure_block, (packet.id, *(value.id for value in failure_states)), (terminal.id,)))
    graph = replace(graph, regions=tuple(replace(item, blocks=blocks) if item.id == region.id else item
        for item in graph.regions), operations=tuple(gate if op.id == gate.id else op for op in graph.operations)
        + (helper, terminal), values=(*graph.values, *added_values),
        control_scopes=tuple(replace(scope, blocks=tuple(block.id for block in blocks))
            if scope.region == region.id else scope for scope in graph.control_scopes))
    if target == "packet":
        reject_block = next(block for block in blocks if block.id == BlockID("driver.reject"))
        old_exit = _op(graph, reject_block.operations[-1])
        rejected = _terminal(old_exit.id.value, reject_block.arguments[0], reject_block.arguments[1:],
                             values, raised=True)
        graph = replace(graph,
            operations=tuple(rejected if op.id == old_exit.id else op for op in graph.operations),
            regions=tuple(replace(item, exits=tuple(port for port in item.exits if port.kind is ExitKind.RAISE))
                if item.id == region.id else item for item in graph.regions))
    return graph, {"processing": identity, "raw_use": raw_use.id,
        "normal_result": InvokeLiteralResult(ControlEdgeReference(identity, 0), CompletionResult(0)),
        "raise_result": InvokeLiteralResult(ControlEdgeReference(identity, 1), CompletionResult(0)),
        "state_sites": tuple(InvokeStateOperand(identity, use.id) for use in state_uses),
        "consumer": gate.id, "payload": payload.id}


def generator_protocol_program(*, target="start"):
    """Real YIELD item or processed SENT/THROW consumer; metadata is conditional."""
    from scar.ir.program.ids import ProtocolScopeID
    from scar.ir.program.protocols import (
        DriverSubject, ProtocolClause as C, ProtocolOperation, ProtocolProfile as F,
        ProtocolScope, RequestProcessing, RequestProcessingRule as R,
    )
    graph = driver_program(target=target)
    interface, = graph.driver_interfaces
    scope_id = ProtocolScopeID("generator.scope")
    scope = ProtocolScope(scope_id, F.GENERATOR_BODY_V1, DriverSubject(interface.region), _source_gap())
    if target == "start":
        graph = replace(graph, protocol_scopes=(scope,))
        return graph, {"scope": scope_id, "drive": graph.body_drives[0].operation,
            "source": graph.operations[0].id, "target": target}
    graph, details = _insert_processing(graph, target=target)
    rule = R.NORMALIZE_THROW_INSTANCE if target == "packet" else R.CHECK_SEND
    rows = tuple(ProtocolOperation(scope_id, C.REQUEST_PROCESSING, details["processing"], slot,
        RequestProcessing(details["raw_use"], (), details[result], details["state_sites"], rule), _source_gap())
        for slot, result in ((0, "normal_result"), (1, "raise_result")))
    graph = replace(graph, protocol_scopes=(scope,), protocol_operations=rows)
    if target == "value":
        graph = _adapt_return(graph, scope_id)
    return graph, {**details, "scope": scope_id, "drive": graph.body_drives[0].operation, "target": target}


def _adapt_return(graph, scope_id):
    """Construct StopIteration on NORMAL, propagate actual constructor failure.

    Both branches eventually RAISE at the host boundary.  No old generic
    body-Return -> host-Return shortcut is retained as a Python positive.
    """
    from scar.ir.program.protocols import (
        DriveResult, OutcomeAdapter, OutcomeAdapterRule as R, ProtocolClause as C,
        ProtocolOperation,
    )
    drive, = graph.body_drives
    drive_op = _op(graph, drive.operation)
    edge, = drive_op.terminator.successors
    interface, = graph.driver_interfaces
    region = next(region for region in graph.regions if region.id == interface.region)
    landing = next(block for block in region.blocks if block.id == edge.block)
    old_exit = _op(graph, landing.operations[-1])
    values = {value.id: value for value in graph.values}
    payload, *states = landing.arguments
    domains = tuple(values[value].location for value in states)
    state_types = tuple(ValueType(ValueKind.STATE, location=location) for location in domains)
    identity = OperationID("adapter.construct")
    input_use = Use(UseID("adapter.input"), payload, UseRole.REFERENCE)
    state_uses = tuple(Use(UseID(f"adapter.state.{index}"), value, UseRole.STATE_CONTENT)
                       for index, value in enumerate(states))
    normal_block, failure_block = BlockID("adapter.normal"), BlockID("adapter.failure")
    exception = ReferenceValue(ValueID("adapter.exception"), region.id, BlockArgument(normal_block, 0))
    failure = ProtocolValue(ValueID("adapter.error"), region.id, BlockArgument(failure_block, 0), P.EXCEPTION_PACKET)
    new_values = [exception, failure]
    current = {}
    for block_id in (normal_block, failure_block):
        current[block_id] = tuple(StateVersionValue(ValueID(f"{block_id.value}.state.{index}"), region.id,
            BlockArgument(block_id, index + 1), location) for index, location in enumerate(domains))
        new_values.extend(current[block_id])
    edges = (CompletionSuccessor(ExitKind.NORMAL, normal_block,
                 tuple(CompletionResult(index) for index in range(len(states) + 1))),
             CompletionSuccessor(ExitKind.RAISE, failure_block,
                 tuple(CompletionResult(index) for index in range(len(states) + 1))))
    adapter = Operation(identity, "actual exception construction boundary", (Behavior.CONTROL,),
        (input_use, *state_uses), effects_complete=False,
        invoke_arguments=(input_use.id, *(use.id for use in state_uses)),
        completions=(CompletionSignature(ExitKind.NORMAL, (REFERENCE, *state_types)),
                     CompletionSignature(ExitKind.RAISE, (PACKET, *state_types))),
        terminator=Terminator(TerminatorKind.INVOKE, edges))
    tb = ReferenceValue(ValueID("adapter.none"), region.id, LiteralOrigin(None), targets=())
    packet_id = OperationID("adapter.packet")
    packet = ProtocolValue(ValueID("adapter.packet.value"), region.id, OperationResult(packet_id, 0), P.EXCEPTION_PACKET)
    new_values.extend((tb, packet))
    packet_uses = (Use(UseID("adapter.packet.exception"), exception.id, UseRole.REFERENCE),
                   Use(UseID("adapter.packet.traceback"), tb.id, UseRole.REFERENCE))
    pack = Operation(packet_id, "packet of the actual constructor result", (Behavior.CONTROL,),
                     packet_uses, (packet.id,), effects_complete=True)
    values.update((value.id, value) for value in new_values)
    normal_exit = _terminal("adapter.normal.exit", packet.id,
        tuple(value.id for value in current[normal_block]), values, raised=True)
    failure_exit = _terminal("adapter.failure.exit", failure.id,
        tuple(value.id for value in current[failure_block]), values, raised=True)
    blocks = tuple(replace(block, operations=(*block.operations[:-1], adapter.id))
                   if block.id == landing.id else block for block in region.blocks)
    blocks = (*blocks,
        Block(normal_block, (exception.id, *(value.id for value in current[normal_block])),
              (pack.id, normal_exit.id)),
        Block(failure_block, (failure.id, *(value.id for value in current[failure_block])), (failure_exit.id,)))
    rows = tuple(ProtocolOperation(scope_id, C.HOST_ADAPTER, adapter.id, index,
        OutcomeAdapter(DriveResult(DriveOutcomeRef(drive.operation, edge.source), 0), input_use.id,
            InvokeLiteralResult(ControlEdgeReference(adapter.id, index), CompletionResult(0)),
            R.GENERATOR_RETURN_TO_STOP_ITERATION), _source_gap()) for index in range(2))
    return replace(graph,
        regions=tuple(replace(item, blocks=blocks,
            exits=tuple(port for port in item.exits if port.kind is ExitKind.RAISE))
            if item.id == region.id else item for item in graph.regions),
        operations=tuple(op for op in graph.operations if op.id != old_exit.id)
            + (adapter, pack, normal_exit, failure_exit), values=(*graph.values, *new_values),
        control_scopes=tuple(replace(scope, blocks=tuple(block.id for block in blocks))
            if scope.region == region.id else scope for scope in graph.control_scopes),
        exception_packets=(*graph.exception_packets,
            ExceptionPacketDefinition(packet.id, *(use.id for use in packet_uses))),
        protocol_operations=(*graph.protocol_operations, *rows))


def no_entry_throw_program(*, selected=ExitKind.NORMAL, reject=False):
    """One real helper, two actual post-state edges, no fabricated BodyDrive.

    Both helper alternatives end at host RAISE; a NORMAL helper completion is
    not a normal host outcome.  Only the selected no-entry transition may seed F.
    """
    from scar.ir.program.ids import ProtocolScopeID
    from scar.ir.program.protocols import (
        NoEntryOutcome, OperationSiteSubject, ProtocolClause as C,
        ProtocolOperation, ProtocolProfile as F, ProtocolScope, HostTerminal,
    )
    base = driver_program()
    interface, = base.driver_interfaces
    driver = next(region for region in base.regions if region.id == interface.region)
    entry = next(block for block in driver.blocks if block.id == driver.entry)
    values = {value.id: value for value in base.values}
    kept_values = tuple(value for value in base.values if value.region != driver.id or value.id in entry.arguments)
    states = tuple(value for value in entry.arguments if isinstance(values[value], StateVersionValue))
    domains = tuple(values[value].location for value in states)
    state_types = tuple(ValueType(ValueKind.STATE, location=location) for location in domains)
    helper_id = OperationID("preentry.source")
    owner_use = Use(UseID("preentry.instance"), interface.receiver, UseRole.REFERENCE)
    raw_use = Use(UseID("preentry.raw"), interface.scheduler_request, UseRole.PROTOCOL)
    state_uses = tuple(Use(UseID(f"preentry.state.{index}"), value, UseRole.STATE_CONTENT)
                       for index, value in enumerate(states))
    added_values, blocks, terminals, edges, owner_formals = [], [], [], [], []
    forwarded = []
    for index, kind in enumerate((ExitKind.NORMAL, ExitKind.RAISE)):
        block_id = BlockID(f"preentry.edge.{index}")
        owner = ReferenceValue(ValueID(f"preentry.owner.{index}"), driver.id, BlockArgument(block_id, 0))
        packet = ProtocolValue(ValueID(f"preentry.packet.{index}"), driver.id,
                               BlockArgument(block_id, 1), P.EXCEPTION_PACKET)
        current = tuple(StateVersionValue(ValueID(f"preentry.after.{index}.{number}"), driver.id,
            BlockArgument(block_id, number + 2), location) for number, location in enumerate(domains))
        added_values.extend((owner, packet, *current))
        values.update((value.id, value) for value in (owner, packet, *current))
        forward = Use(UseID(f"preentry.forward.{index}"), interface.receiver, UseRole.REFERENCE)
        forwarded.append(forward)
        edges.append(CompletionSuccessor(kind, block_id,
            (forward.id, *(CompletionResult(number) for number in range(len(states) + 1)))))
        terminal = _terminal(f"preentry.exit.{index}", packet.id, tuple(value.id for value in current),
                             values, raised=True)
        terminals.append(terminal)
        blocks.append(Block(block_id, (owner.id, packet.id, *(value.id for value in current)), (terminal.id,)))
        owner_formals.append(owner.id)
    helper = Operation(helper_id, "real callback-capable transition", (Behavior.CONTROL,),
        (owner_use, raw_use, *state_uses, *forwarded), effects_complete=False,
        invoke_arguments=(owner_use.id, raw_use.id, *(use.id for use in state_uses)),
        completions=tuple(CompletionSignature(kind, (PACKET, *state_types)) for kind in (ExitKind.NORMAL, ExitKind.RAISE)),
        terminator=Terminator(TerminatorKind.INVOKE, tuple(edges)))
    blocks = (replace(entry, operations=(helper.id,)), *blocks)
    driver = replace(driver, blocks=blocks, exits=(ExitPort("failure", ExitKind.RAISE, (PACKET, *state_types)),))
    scope_id = ProtocolScopeID("preentry.scope")
    scope = ProtocolScope(scope_id, F.CREATED_THROW_V1,
                          OperationSiteSubject(driver.id, helper.id), _source_gap())
    edge_index = 0 if selected is ExitKind.NORMAL else 1
    edge = ControlEdgeReference(helper.id, edge_index)
    clause = C.PREENTRY_REJECT if reject else (
        C.INITIAL_THROW_DELIVERED if selected is ExitKind.NORMAL else C.INITIAL_THROW_CONSTRUCTOR_FAILURE)
    contract = NoEntryOutcome(owner_use.id, raw_use.id,
        InvokeLiteralResult(edge, CompletionResult(0)),
        tuple(InvokeStateOperand(helper.id, use.id) for use in state_uses), edge,
        HostTerminal(terminals[edge_index].id))
    row = ProtocolOperation(scope_id, clause, helper.id, edge_index, contract, _source_gap())
    old_driver_ops = {identity for block in next(region for region in base.regions
        if region.id == interface.region).blocks for identity in block.operations}
    graph = replace(base, regions=tuple(driver if region.id == driver.id else region for region in base.regions),
        operations=tuple(op for op in base.operations if op.id not in old_driver_ops) + (helper, *terminals),
        values=(*kept_values, *added_values),
        control_scopes=tuple(_scope(driver.id, blocks) if scope.region == driver.id else scope
                             for scope in base.control_scopes),
        body_drives=(), final_body_gates=(), driver_lifecycles=(DriverLifecycle(driver.id),),
        protocol_scopes=(scope,), protocol_operations=(row,))
    return graph, {"scope": scope_id, "processing": helper.id, "row": row,
        "selected_edge": edge_index, "owner": interface.receiver,
        "owner_formals": tuple(owner_formals), "terminals": tuple(op.id for op in terminals),
        "state_sites": contract.state_sites, "reject": reject}


def closed_request_program(*, kind=RawRequestKind.NEXT):
    """Conditional Closed+raw helper paths, without a new Drive/F seed.

    The Closed predicate is part of the source implementation's applicability,
    not a writable phase fact.  An old packet/return carrier is available so a
    wrong-source host output remains core-valid and can be rejected precisely.
    """
    from scar.ir.program.protocols import (
        DriverSubject, ProtocolClause as C, ProtocolOperation, ProtocolProfile as F,
        RequestProcessing, RequestProcessingRule as R,
    )
    graph, details = no_entry_throw_program(reject=True)
    interface, = graph.driver_interfaces
    driver = next(region for region in graph.regions if region.id == interface.region)
    entry = next(block for block in driver.blocks if block.id == driver.entry)
    old_packet = ProtocolValue(ValueID("closed.old.packet"), driver.id,
        BlockArgument(entry.id, len(entry.arguments)), P.EXCEPTION_PACKET)
    old_value = ReferenceValue(ValueID("closed.old.return"), driver.id,
        BlockArgument(entry.id, len(entry.arguments) + 1))
    values = {value.id: value for value in (*graph.values, old_packet, old_value)}
    helper = _op(graph, details["processing"])
    if kind is RawRequestKind.CLOSE:
        normal = helper.terminator.successors[0]
        landing = next(block for block in driver.blocks if block.id == normal.block)
        result_id = landing.arguments[1]
        result = values[result_id]
        values[result_id] = ReferenceValue(result_id, driver.id, result.origin)
        helper = replace(helper, completions=tuple(replace(signature,
            types=(REFERENCE, *signature.types[1:])) if signature.kind is ExitKind.NORMAL else signature
            for signature in helper.completions))
        normal_terminal = _terminal(details["terminals"][0].value, result_id,
            landing.arguments[2:], values, raised=False)
    else:
        normal_terminal = _op(graph, details["terminals"][0])
    blocks = tuple(replace(block, arguments=(*block.arguments, old_packet.id, old_value.id))
                   if block.id == entry.id else block for block in driver.blocks)
    state_types = tuple(ValueType(ValueKind.STATE, location=values[value].location)
                        for value in entry.arguments if isinstance(values[value], StateVersionValue))
    exits = driver.exits if kind is not RawRequestKind.CLOSE else (
        *driver.exits, ExitPort("normal", ExitKind.NORMAL, (REFERENCE, *state_types)))
    rule = {RawRequestKind.NEXT: R.CHECK_NEXT, RawRequestKind.SEND: R.CHECK_SEND,
            RawRequestKind.THROW: R.CHECK_THROW, RawRequestKind.CLOSE: R.CHECK_CLOSE}[kind]
    scope = replace(graph.protocol_scopes[0], profile=F.GENERATOR_BODY_V1,
                    subject=DriverSubject(interface.region))
    raw_use = details["row"].contract.effective_request_use
    rows = tuple(ProtocolOperation(scope.id, C.RAW_ADMISSION, helper.id, index,
        RequestProcessing(raw_use, (), InvokeLiteralResult(ControlEdgeReference(helper.id, index),
            CompletionResult(0)), details["state_sites"], rule), _source_gap()) for index in range(2))
    graph = replace(graph,
        regions=tuple(replace(region, blocks=blocks, exits=exits) if region.id == driver.id else region
                      for region in graph.regions),
        operations=tuple(helper if op.id == helper.id else normal_terminal if op.id == normal_terminal.id
                         else op for op in graph.operations),
        values=tuple(values[value.id] for value in graph.values) + (old_packet, old_value),
        protocol_scopes=(scope,), protocol_operations=rows)
    return graph, {**details, "scope": scope.id, "kind": kind,
        "old_packet": old_packet.id, "old_return": old_value.id}


__all__ = ["request_processing_program", "generator_protocol_program", "no_entry_throw_program",
           "closed_request_program"]
