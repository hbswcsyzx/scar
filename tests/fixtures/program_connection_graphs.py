"""A real upstream merge, INVOKE and multiple original result consumers."""
from dataclasses import replace

from scar.ir.program.control import ProtocolValueKind, ProtocolValueType
from scar.ir.program.ids import BlockID, OperationID, ProtocolScopeID, RegionID, UseID, ValueID
from scar.ir.program.drivers import RawRequestDefinition, RawRequestKind
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, CompletionResult, CompletionSignature,
    CompletionSuccessor, DataValue, ExitKind, ExitPort, InvokeLiteralResult,
    LiteralOrigin, Operation, OperationResult, ProgramGraph, ProtocolValue,
    ReferenceValue, Region, Successor, Terminator, TerminatorKind, Use, UseRole,
    ValueKind, ValueType,
)
from scar.ir.program.protocol_connections import (
    ProtocolCallInputCase, ProtocolCallInputs, ProtocolOperationRef, ProtocolResultConsumers,
    RawOperandSource,
)
from scar.ir.program.protocols import (
    HostTerminal, OperationSiteSubject, OwnedUse, ProtocolCall, ProtocolCallRule,
    ProtocolClause, ProtocolOperation, ProtocolProfile, ProtocolScope,
    StaticProtocolGap, StaticGapReason,
)
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.program_protocol_graphs import _scope


def merged_connection_program(*, attach=True, omit_right=False, swap_argument=False,
                              omit_consumer=False, opaque_consumer=False, raw_operands=False):
    region = RegionID("merge.connection")
    names = ("entry", "left", "right", "merge", "later", "normal", "raised", "choose", "third")
    blocks = {name: BlockID("merge." + name) for name in names}
    values, operations, records = [], [], []
    condition = ValueID("merge.condition")
    values.append(DataValue(condition, region, LiteralOrigin(True), "builtins.bool"))
    condition_use = Use(UseID("merge.condition.use"), condition)
    branch = Operation(OperationID("merge.branch"), "original branch", (Behavior.CONTROL,),
        (condition_use,), terminator=Terminator(TerminatorKind.BRANCH,
            successors=(Successor(blocks["left"], ()),
                        Successor(blocks["choose" if omit_right else "right"], ())),
            condition=condition_use.id))
    operations.append(branch)
    records.append(Block(blocks["entry"], (), (branch.id,)))
    if omit_right:
        use = Use(UseID("merge.choose.condition"), condition)
        choose = Operation(OperationID("merge.choose.branch"), "another original branch", (Behavior.CONTROL,),
            (use,), terminator=Terminator(TerminatorKind.BRANCH,
                successors=(Successor(blocks["right"], ()), Successor(blocks["third"], ())),
                condition=use.id))
        operations.append(choose)
        records.append(Block(blocks["choose"], (), (choose.id,)))
    producers, guards, raw_sources, raw_definitions = {}, {}, {}, []
    branches = ("left", "right", "third") if omit_right else ("left", "right")
    for name in branches:
        identity = OperationID("merge." + name + ".produce")
        produced = tuple(ValueID(f"merge.{name}.value.{index}") for index in range(2))
        values.extend(ReferenceValue(value, region, OperationResult(identity, index))
                      for index, value in enumerate(produced))
        producer = Operation(identity, "original two result producer", (Behavior.COMPUTE,),
                             results=produced, effects_complete=True)
        prefix = (producer,)
        if raw_operands:
            pack_id, raw_id = OperationID(f"merge.{name}.pack"), ValueID(f"merge.{name}.raw")
            operand = Use(UseID(f"merge.{name}.pack.operand"), produced[1], UseRole.REFERENCE)
            pack = Operation(pack_id, "original raw pack", (Behavior.COMPUTE,), (operand,),
                             (raw_id,), effects_complete=True)
            values.append(ProtocolValue(raw_id, region, OperationResult(pack_id, 0),
                                         ProtocolValueKind.RAW_DRIVER_REQUEST))
            raw_definitions.append(RawRequestDefinition(raw_id, RawRequestKind.THROW, (operand.id,)))
            use = Use(UseID(f"merge.{name}.anchor.raw"), raw_id, UseRole.PROTOCOL)
            anchor = Operation(OperationID(f"merge.{name}.anchor"), "original raw consumer",
                               (Behavior.COMPUTE,), (use,), effects_complete=True)
            raw_sources[name] = OwnedUse(anchor.id, use.id)
            prefix += (pack, anchor)
        uses = tuple(Use(UseID(f"merge.{name}.forward.{index}"), value, UseRole.REFERENCE)
                     for index, value in enumerate(produced))
        jump = Operation(OperationID("merge." + name + ".jump"), "original forward", (Behavior.CONTROL,),
            uses, terminator=Terminator(TerminatorKind.JUMP,
                successors=(Successor(blocks["merge"], tuple(use.id for use in uses)),)))
        operations.extend((*prefix, jump))
        records.append(Block(blocks[name], (), (*(op.id for op in prefix), jump.id)))
        producers[name], guards[name] = producer, ControlEdgeReference(jump.id, 0)
    merge_values = tuple(ValueID(f"merge.formal.{index}") for index in range(2))
    later_values = tuple(ValueID(f"merge.later.formal.{index}") for index in range(2))
    for block, formals in ((blocks["merge"], merge_values), (blocks["later"], later_values)):
        values.extend(ReferenceValue(value, region, BlockArgument(block, index))
                      for index, value in enumerate(formals))
    forward = tuple(Use(UseID(f"merge.downstream.forward.{index}"), value, UseRole.REFERENCE)
                    for index, value in enumerate(merge_values))
    jump = Operation(OperationID("merge.downstream.jump"), "original downstream copy", (Behavior.CONTROL,),
        forward, terminator=Terminator(TerminatorKind.JUMP,
            successors=(Successor(blocks["later"], tuple(use.id for use in forward)),)))
    operations.append(jump)
    records.append(Block(blocks["merge"], merge_values, (jump.id,)))
    call_id = OperationID("merge.call")
    args = tuple(Use(UseID(f"merge.call.argument.{index}"), value, UseRole.REFERENCE)
                 for index, value in enumerate(later_values))
    result, packet = ValueID("merge.result"), ValueID("merge.packet")
    values.extend((ReferenceValue(result, region, BlockArgument(blocks["normal"], 0)),
                   ProtocolValue(packet, region, BlockArgument(blocks["raised"], 0),
                                 ProtocolValueKind.EXCEPTION_PACKET)))
    reference = ValueType(ValueKind.REFERENCE)
    packet_type = ProtocolValueType(ProtocolValueKind.EXCEPTION_PACKET)
    call = Operation(call_id, "original raising call", (Behavior.CONTROL,), args,
        completions=(CompletionSignature(ExitKind.NORMAL, (reference,)),
                     CompletionSignature(ExitKind.RAISE, (packet_type,))),
        invoke_arguments=tuple(use.id for use in args),
        terminator=Terminator(TerminatorKind.INVOKE, successors=(
            CompletionSuccessor(ExitKind.NORMAL, blocks["normal"], (CompletionResult(0),)),
            CompletionSuccessor(ExitKind.RAISE, blocks["raised"], (CompletionResult(0),)))))
    operations.append(call)
    records.append(Block(blocks["later"], later_values, (call.id,)))
    observers = []
    for index in range(2):
        use = Use(UseID(f"merge.observe.{index}.input"), result, UseRole.REFERENCE)
        operation = Operation(OperationID(f"merge.observe.{index}"), "original consumer",
                              (Behavior.COMPUTE,), (use,), effects_complete=not opaque_consumer)
        operations.append(operation)
        observers.append(OwnedUse(operation.id, use.id))
    terminal_ids = {}
    for name, value, raised in (("normal", result, False), ("raised", packet, True)):
        use = Use(UseID("merge." + name + ".output"), value,
                  UseRole.PROTOCOL if raised else UseRole.REFERENCE)
        operation = Operation(OperationID("merge." + name + ".return"), "original terminal",
            (Behavior.CONTROL,), (use,), effects_complete=True,
            terminator=Terminator(TerminatorKind.RAISE if raised else TerminatorKind.RETURN,
                exit=name, values=(use.id,)))
        operations.append(operation)
        terminal_ids[name] = operation.id
        prefix = tuple(target.operation for target in observers) if not raised else ()
        records.append(Block(blocks[name], (value,), (*prefix, operation.id)))
    gap = StaticProtocolGap(StaticGapReason.NATIVE_APPLICABILITY_UNPROVEN)
    scope = ProtocolScope(ProtocolScopeID("merge.scope"), ProtocolProfile.CREATED_THROW_V1,
                         OperationSiteSubject(region, call.id), gap)
    source = InvokeLiteralResult(ControlEdgeReference(call.id, 0), CompletionResult(0))
    row = ProtocolOperation(scope.id, ProtocolClause.THROW_NORMALIZATION, call.id, 0,
        ProtocolCall(args[0].id, (args[1].id,), source, (), ProtocolCallRule.EXCEPTION_CONSTRUCTOR), gap)
    site = ProtocolOperationRef(row.scope, row.clause, row.operation, row.slot)
    cases = tuple(ProtocolCallInputCase(guards[name], OperationResult(producers[name].id, 0),
        ((RawOperandSource(raw_sources["right" if swap_argument and name == "left" else name], 0)
          if raw_operands else OperationResult(producers["right" if swap_argument and name == "left" else name].id, 1)),), None)
        for name in branches if not (omit_right and name == "right"))
    targets = (*observers, HostTerminal(terminal_ids["normal"]))
    graph = ProgramGraph(root=region, values=tuple(values), operations=tuple(operations),
        regions=(Region(region, "original conditional pipeline", blocks["entry"], tuple(records),
            (ExitPort("normal", ExitKind.NORMAL, (reference,)),
             ExitPort("raised", ExitKind.RAISE, (packet_type,)))),),
        protocol_scopes=(scope,), protocol_operations=(row,),
        control_scopes=(_scope(region, records),),
        raw_driver_requests=tuple(raw_definitions),
        protocol_call_inputs=(ProtocolCallInputs(site, cases),) if attach else (),
        protocol_result_consumers=(ProtocolResultConsumers(site,
            targets[:1] if omit_consumer else targets),) if attach else ())
    return graph, {"row": row, "site": site, "source": source, "producers": producers,
                   "call": call, "guards": guards, "targets": targets,
                   "merge": blocks["merge"], "observers": tuple(observers)}


def nested_consumer_program():
    """Two independent merges can each replace the result before consumers.

    Either single incoming guard is insufficient to prove a must copy. The
    actual source still has possible consumers, including when none are listed.
    """
    graph, details = merged_connection_program(omit_consumer=True)
    region = graph.regions[0]
    normal = next(block for block in region.blocks if block.id.value == "merge.normal")
    source_value = normal.arguments[0]
    condition = next(value.id for value in graph.values if value.id.value == "merge.condition")
    values, operations, blocks = list(graph.values), list(graph.operations), []
    latest = source_value
    current_block = normal.id
    all_guards = []
    for level in range(2):
        identity = OperationID(f"nested.branch.{level}")
        yes, no, merge = (BlockID(f"nested.{level}.{name}") for name in ("keep", "replace", "merge"))
        test = Use(UseID(f"nested.test.{level}"), condition)
        branch = Operation(identity, "original conditional replacement", (Behavior.CONTROL,), (test,),
            terminator=Terminator(TerminatorKind.BRANCH,
                successors=(Successor(yes, ()), Successor(no, ())), condition=test.id))
        operations.append(branch)
        blocks.append(Block(current_block, normal.arguments if level == 0 else (latest,), (branch.id,)))
        other_id, other_value = OperationID(f"nested.other.{level}"), ValueID(f"nested.other.value.{level}")
        other = Operation(other_id, "original alternative source", (Behavior.COMPUTE,),
                          results=(other_value,), effects_complete=True)
        values.append(ReferenceValue(other_value, region.id, OperationResult(other_id, 0)))
        operations.append(other)
        for name, block, value, prefix in (("keep", yes, latest, ()), ("replace", no, other_value, (other.id,))):
            actual = Use(UseID(f"nested.{level}.{name}.forward"), value, UseRole.REFERENCE)
            jump = Operation(OperationID(f"nested.{level}.{name}.jump"), "original merge operand",
                (Behavior.CONTROL,), (actual,), terminator=Terminator(TerminatorKind.JUMP,
                    successors=(Successor(merge, (actual.id,)),)))
            operations.append(jump)
            blocks.append(Block(block, (), (*prefix, jump.id)))
            all_guards.append(ControlEdgeReference(jump.id, 0))
        latest = ValueID(f"nested.merge.value.{level}")
        values.append(ReferenceValue(latest, region.id, BlockArgument(merge, 0)))
        current_block = merge
    original_consumers = set(normal.operations)
    operations = [replace(op, uses=tuple(replace(use, value=latest) if use.value == source_value else use
                   for use in op.uses)) if op.id in original_consumers else op for op in operations]
    blocks.append(Block(current_block, (latest,), normal.operations))
    new_region = replace(region, blocks=tuple(block for block in region.blocks if block.id != normal.id) + tuple(blocks))
    graph = replace(graph, regions=(new_region,), values=tuple(values), operations=tuple(operations),
                    control_scopes=(_scope(region.id, new_region.blocks),))
    return graph, {**details, "guards": tuple(all_guards)}


def helper_diamond_program():
    """A merge in the intermediate helper, with a RAW anchor in its caller."""
    from tests.fixtures.program_request_helper_graphs import helper_request_program
    graph, details = helper_request_program(depth=2)
    region = graph.regions[1]
    entry = region.blocks[0]
    middle = next(op for op in graph.operations if op.id == entry.operations[0])
    values, operations, blocks, guards = list(graph.values), list(graph.operations), [], []
    condition = ValueID("diamond.condition")
    values.append(DataValue(condition, region.id, LiteralOrigin(True), "builtins.bool"))
    test = Use(UseID("diamond.test"), condition)
    left, right, merge = (BlockID("diamond." + name) for name in ("left", "right", "merge"))
    branch = Operation(OperationID("diamond.branch"), "original helper branch", (Behavior.CONTROL,),
        (test,), terminator=Terminator(TerminatorKind.BRANCH,
            successors=(Successor(left, ()), Successor(right, ())), condition=test.id))
    operations.append(branch)
    blocks.append(replace(entry, operations=(branch.id,)))
    formals = tuple(ValueID(f"diamond.formal.{index}") for index in range(len(entry.arguments)))
    values.extend(ReferenceValue(value, region.id, BlockArgument(merge, index))
                  for index, value in enumerate(formals))
    for name, block in (("left", left), ("right", right)):
        uses = tuple(Use(UseID(f"diamond.{name}.{index}"), value, UseRole.REFERENCE)
                     for index, value in enumerate(entry.arguments))
        jump = Operation(OperationID("diamond." + name + ".jump"), "original helper merge", (Behavior.CONTROL,),
            uses, terminator=Terminator(TerminatorKind.JUMP,
                successors=(Successor(merge, tuple(use.id for use in uses)),)))
        operations.append(jump)
        blocks.append(Block(block, (), (jump.id,)))
        guards.append(ControlEdgeReference(jump.id, 0))
    replacements = dict(zip(entry.arguments, formals))
    operations = [replace(op, uses=tuple(replace(use, value=replacements[use.value])
                   if use.value in replacements else use for use in op.uses))
                   if op.id == middle.id else op for op in operations]
    blocks.append(Block(merge, formals, entry.operations))
    new_region = replace(region, blocks=tuple(blocks))
    graph = replace(graph, regions=tuple(new_region if row.id == region.id else row for row in graph.regions),
                    operations=tuple(operations), values=tuple(values))
    return graph, {**details, "helper_guards": tuple(guards)}
