"""Copies of one internal source must compose across the same call's ports."""
from dataclasses import replace

from scar.ir.program.ids import BlockID, OperationID, UseID, ValueID
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, DataValue, ExitKind, LiteralOrigin,
    Operation, OperationResult, ReferenceValue, StateVersionValue, Successor,
    Terminator, TerminatorKind, Use, UseRole, ValueKind, ValueType,
)
from scar.ir.program.protocols import OwnedUse
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid
from tests.fixtures.program_call_return_graphs import call_return_program
from tests.fixtures.program_call_return_state_graphs import call_return_state_program


def _double_result_program():
    """One helper source returns twice; actual caller branches choose each copy."""
    graph, details = call_return_program(internal=True)
    root, helper = graph.regions
    call = next(operation for operation in graph.operations if operation.id == details["calls"][0])
    consume = next(operation for operation in graph.operations if operation.id == details["actual"].operation)
    terminal = next(operation for operation in graph.operations if operation.id == details["terminals"][0])
    values = {value.id: value for value in graph.values}
    first, previous_state = (values[identity] for identity in call.results)
    second = ReferenceValue(ValueID("export.second.result"), root.id, OperationResult(call.id, 1))
    after = replace(previous_state, origin=OperationResult(call.id, 2))
    changed_call = replace(call, results=(first.id, second.id, after.id))
    duplicate = Use(UseID("export.helper.second.result"), terminal.uses[0].value, UseRole.REFERENCE)
    changed_terminal = replace(terminal,
        uses=(terminal.uses[0], duplicate, terminal.uses[1]),
        terminator=replace(terminal.terminator,
            values=(terminal.uses[0].id, duplicate.id, terminal.uses[1].id)))
    entry = root.blocks[0]
    condition = DataValue(ValueID("export.choose.input"), root.id,
                          BlockArgument(entry.id, len(entry.arguments)), "builtins.bool")
    location = after.location
    added_values, side_blocks, side_operations, edges, branch_uses = [], [], [], [], []
    merge_id = BlockID("export.merge")
    merged = ReferenceValue(ValueID("export.merge.reference"), root.id, BlockArgument(merge_id, 0))
    merged_state = StateVersionValue(ValueID("export.merge.state"), root.id,
                                    BlockArgument(merge_id, 1), location)
    for number, copied in enumerate((first, second)):
        block_id = BlockID(f"export.side.{number}")
        reference = ReferenceValue(ValueID(f"export.side.{number}.reference"), root.id,
                                   BlockArgument(block_id, 0))
        state = StateVersionValue(ValueID(f"export.side.{number}.state"), root.id,
                                  BlockArgument(block_id, 1), location)
        sent = (Use(UseID(f"export.choose.{number}.reference"), copied.id, UseRole.REFERENCE),
                Use(UseID(f"export.choose.{number}.state"), after.id, UseRole.STATE_CONTENT))
        branch_uses.extend(sent)
        edges.append(Successor(block_id, tuple(use.id for use in sent)))
        forwarded = (Use(UseID(f"export.merge.{number}.reference"), reference.id, UseRole.REFERENCE),
                     Use(UseID(f"export.merge.{number}.state"), state.id, UseRole.STATE_CONTENT))
        jump = Operation(OperationID(f"export.merge.{number}"), "original result selection",
            (Behavior.CONTROL,), forwarded, effects_complete=True,
            terminator=Terminator(TerminatorKind.JUMP,
                (Successor(merge_id, tuple(use.id for use in forwarded)),)))
        side_operations.append(jump)
        side_blocks.append(Block(block_id, (reference.id, state.id), (jump.id,)))
        added_values.extend((reference, state))
    predicate = Use(UseID("export.choose.condition"), condition.id, UseRole.DATA)
    branch = Operation(OperationID("export.choose"), "original alternative result consumer",
        (Behavior.CONTROL,), (predicate, *branch_uses), effects_complete=True,
        terminator=Terminator(TerminatorKind.BRANCH, tuple(edges), condition=predicate.id))
    changed_consume = replace(consume, uses=(replace(consume.uses[0], value=merged.id),
                                               replace(consume.uses[1], value=merged_state.id)))
    root = replace(root, blocks=(
        replace(entry, arguments=(*entry.arguments, condition.id), operations=(call.id, branch.id)),
        *side_blocks, Block(merge_id, (merged.id, merged_state.id), (consume.id,))))
    helper = replace(helper, exits=(replace(helper.exits[0], types=(
        ValueType(ValueKind.REFERENCE), ValueType(ValueKind.REFERENCE),
        ValueType(ValueKind.STATE, location=location))),))
    replacements = {call.id: changed_call, consume.id: changed_consume, terminal.id: changed_terminal}
    graph = replace(graph, regions=(root, helper),
        operations=tuple(replacements.get(operation.id, operation) for operation in graph.operations)
            + (branch, *side_operations),
        values=tuple(after if value.id == after.id else value for value in graph.values)
            + (second, condition, merged, merged_state, *added_values))
    return graph, details["helper_sources"][0], details["actual"]


def test_internal_source_export_combines_two_simultaneous_call_result_copies():
    graph, source, actual = _double_result_program()
    require_valid(graph)
    report = ProgramIndex(graph).source_binding(source, actual)
    assert report["match"] is True, report
    assert report["routes"]
    assert report["source_runtime_verified"] is report["transformation_authorized"] is False


def test_unchanged_internal_domain_exports_through_both_actual_invoke_completions():
    graph, details = call_return_state_program()
    root, helper = graph.regions
    call = details["callers"]["a"]
    normal_consumer = call["consumers"][ExitKind.NORMAL]["operation"]
    raise_consumer = call["consumers"][ExitKind.RAISE]["operation"]
    operations = {operation.id: operation for operation in graph.operations}
    merge_id = BlockID("export.invoke.merge")
    reference = ReferenceValue(ValueID("export.invoke.reference"), root.id, BlockArgument(merge_id, 0))
    world = StateVersionValue(ValueID("export.invoke.world"), root.id,
                              BlockArgument(merge_id, 1), details["world"])
    context = StateVersionValue(ValueID("export.invoke.context"), root.id,
                                BlockArgument(merge_id, 2), details["context"])
    blocks = []
    for block in root.blocks:
        if block.operations[0] not in (normal_consumer.id, raise_consumer.id):
            blocks.append(block)
            continue
        normal = block.operations[0] == normal_consumer.id
        consumer = operations[block.operations[0]]
        payload = call["normal_formals"][2] if normal else call["raise_formals"][0]
        state_values = (payload.id, consumer.uses[1].value, consumer.uses[2].value)
        forwarded = tuple(Use(UseID(f"export.invoke.{normal}.{number}"), value,
            UseRole.REFERENCE if number == 0 else UseRole.STATE_CONTENT)
            for number, value in enumerate(state_values))
        terminal = operations[block.operations[-1]]
        operations[terminal.id] = replace(terminal, uses=forwarded,
            terminator=Terminator(TerminatorKind.JUMP,
                (Successor(merge_id, tuple(use.id for use in forwarded)),)))
        blocks.append(block)
    returned = (Use(UseID("export.invoke.result"), reference.id, UseRole.REFERENCE),
                Use(UseID("export.invoke.result.world"), world.id, UseRole.STATE_CONTENT),
                Use(UseID("export.invoke.result.context"), context.id, UseRole.STATE_CONTENT))
    terminal = Operation(OperationID("export.invoke.return"), "original completion merge",
        (Behavior.CONTROL,), returned, effects_complete=True,
        terminator=Terminator(TerminatorKind.RETURN, exit="normal",
                              values=tuple(use.id for use in returned)))
    blocks.append(Block(merge_id, (reference.id, world.id, context.id), (terminal.id,)))
    old_scope = next(scope for scope in graph.control_scopes if scope.region == root.id)
    graph = replace(graph, regions=(replace(root, blocks=tuple(blocks),
        exits=tuple(port for port in root.exits if port.kind is ExitKind.NORMAL)), helper),
        operations=tuple(operations.values()) + (terminal,),
        values=(*graph.values, reference, world, context),
        control_scopes=tuple(replace(scope, blocks=(*scope.blocks, merge_id))
            if scope is old_scope else scope for scope in graph.control_scopes))
    require_valid(graph)
    source = details["callee_arguments"][4].origin
    report = ProgramIndex(graph).source_binding(source, OwnedUse(terminal.id, returned[2].id))
    assert report["match"] is True, report
    assert report["routes"]
    assert report["source_runtime_verified"] is report["transformation_authorized"] is False
