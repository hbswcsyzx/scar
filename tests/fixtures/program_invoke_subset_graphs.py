"""Declared genuine single-completion callees, without fabricated exit paths."""
from dataclasses import replace

from scar.ir.program import (
    AccessMode, Behavior, Block, BlockArgument, BlockID, CompletionResult,
    CompletionSignature, CompletionSuccessor, DataValue, ExitKind, ExitPort,
    LiteralOrigin, LocationID, Operation, OperationID, OperationResult,
    ProgramGraph, ReferenceValue, Region, RegionID, StateAccess, StateLocation,
    StateVersionValue, Successor, Terminator, TerminatorKind, Use, UseID,
    UseRole, ValueID, ValueKind, ValueType,
)


REFERENCE = ValueType(ValueKind.REFERENCE)
WORLD = LocationID("subset.world")
STATE = ValueType(ValueKind.STATE, location=WORLD)


def _callee(prefix, kinds, parent):
    region = RegionID(prefix)
    entry = BlockID(prefix + ".entry")
    ref = ReferenceValue(ValueID(prefix + ".input"), region, BlockArgument(entry, 0))
    condition = DataValue(ValueID(prefix + ".condition"), region,
                          BlockArgument(entry, 1), "builtins.bool")
    before = StateVersionValue(ValueID(prefix + ".before"), region,
                               BlockArgument(entry, 2), WORLD)
    update_id = OperationID(prefix + ".update")
    after = StateVersionValue(ValueID(prefix + ".after"), region,
                              OperationResult(update_id, 0), WORLD)
    state_use = Use(UseID(prefix + ".update.before"), before.id, UseRole.STATE_CONTENT)
    update = Operation(update_id, "real declared state update", (Behavior.READ, Behavior.WRITE),
        (state_use,), (after.id,), (StateAccess(WORLD, state_use.id, AccessMode.READ_WRITE,
                                              after.id),), effects_complete=True)
    values = [ref, condition, before, after]
    operations = [update]
    blocks, exits = [], []
    branch_uses, successors = [], []
    for kind in kinds:
        path = prefix + "." + kind.value.lower()
        block_id = entry if len(kinds) == 1 else BlockID(path)
        if len(kinds) == 1:
            result_ref, result_state = ref.id, after.id
        else:
            output = ReferenceValue(ValueID(path + ".ref"), region, BlockArgument(block_id, 0))
            state = StateVersionValue(ValueID(path + ".state"), region,
                                      BlockArgument(block_id, 1), WORLD)
            values.extend((output, state))
            result_ref, result_state = output.id, state.id
            actuals = (Use(UseID(path + ".forward.ref"), ref.id, UseRole.REFERENCE),
                       Use(UseID(path + ".forward.state"), after.id, UseRole.STATE_CONTENT))
            branch_uses.extend(actuals)
            successors.append(Successor(block_id, tuple(use.id for use in actuals)))
        terminal_uses = (Use(UseID(path + ".exit.ref"), result_ref, UseRole.REFERENCE),
                         Use(UseID(path + ".exit.state"), result_state, UseRole.STATE_CONTENT))
        terminal = Operation(OperationID(path + ".exit"), "actual callee completion",
            (Behavior.CONTROL,), terminal_uses, effects_complete=True,
            terminator=Terminator(TerminatorKind.RETURN if kind is ExitKind.NORMAL
                                  else TerminatorKind.RAISE,
                                  exit=kind.value.lower(),
                                  values=tuple(use.id for use in terminal_uses)))
        operations.append(terminal)
        if len(kinds) > 1:
            blocks.append(Block(block_id, (result_ref, result_state), (terminal.id,)))
        exits.append(ExitPort(kind.value.lower(), kind, (REFERENCE, STATE)))
    if len(kinds) == 1:
        entry_ops = (update.id, operations[-1].id)
    else:
        test = Use(UseID(prefix + ".choose.condition"), condition.id)
        choose = Operation(OperationID(prefix + ".choose"), "real two-path callee",
            (Behavior.CONTROL,), (test, *branch_uses), effects_complete=True,
            terminator=Terminator(TerminatorKind.BRANCH, tuple(successors), condition=test.id))
        operations.append(choose)
        entry_ops = (update.id, choose.id)
    blocks.insert(0, Block(entry, (ref.id, condition.id, before.id), entry_ops))
    return (Region(region, "genuine callee completion subset", entry, tuple(blocks),
                   tuple(exits), parent=parent), tuple(operations), tuple(values))


def invoke_subset_program(kinds=(ExitKind.RAISE,), *, alternate_callee=False):
    """Return (graph, details); the RAISE landing is a real caller handler.

    Each callee exit has an actual RETURN/RAISE site after a canonical RW.
    Completion signatures are (Reference, State), while the caller's landing
    formals deliberately put State first. No source/runtime claim is supplied.
    """
    kinds = tuple(kinds)
    if not kinds or len(set(kinds)) != len(kinds) or not set(kinds) <= {ExitKind.NORMAL, ExitKind.RAISE}:
        raise ValueError("kinds must be a nonempty unique NORMAL/RAISE subset")
    root = RegionID("subset.caller")
    entry = BlockID("subset.caller.entry")
    ref = ReferenceValue(ValueID("subset.caller.input"), root, BlockArgument(entry, 0))
    condition = DataValue(ValueID("subset.caller.condition"), root,
                          BlockArgument(entry, 1), "builtins.bool")
    before = StateVersionValue(ValueID("subset.caller.before"), root,
                               BlockArgument(entry, 2), WORLD)
    inputs = (Use(UseID("subset.invoke.ref"), ref.id, UseRole.REFERENCE),
              Use(UseID("subset.invoke.condition"), condition.id),
              Use(UseID("subset.invoke.state"), before.id, UseRole.STATE_CONTENT))
    callee, child_operations, child_values = _callee("subset.callee", kinds, root)
    values = [ref, condition, before, *child_values]
    operations, blocks, edges, signatures = [], [], [], []
    landings, terminals = {}, {}
    for kind in kinds:
        name = "subset.caller." + kind.value.lower()
        block_id = BlockID(name)
        state = StateVersionValue(ValueID(name + ".state"), root, BlockArgument(block_id, 0), WORLD)
        output = ReferenceValue(ValueID(name + ".ref"), root, BlockArgument(block_id, 1))
        values.extend((state, output))
        uses = (Use(UseID(name + ".return.ref"), output.id, UseRole.REFERENCE),
                Use(UseID(name + ".return.state"), state.id, UseRole.STATE_CONTENT))
        terminal = Operation(OperationID(name + ".return"),
            "handle real exception" if kind is ExitKind.RAISE else "return actual normal result",
            (Behavior.CONTROL,), uses, effects_complete=True,
            terminator=Terminator(TerminatorKind.RETURN, exit="handled", values=tuple(use.id for use in uses)))
        operations.append(terminal)
        blocks.append(Block(block_id, (state.id, output.id), (terminal.id,)))
        signatures.append(CompletionSignature(kind, (REFERENCE, STATE)))
        edges.append(CompletionSuccessor(kind, block_id, (CompletionResult(1), CompletionResult(0))))
        landings[kind], terminals[kind] = block_id, terminal.id
    invoke = Operation(OperationID("subset.invoke"), "actual known callee invocation",
        (Behavior.CONTROL, Behavior.COMPUTE, Behavior.READ, Behavior.WRITE), inputs,
        terminator=Terminator(TerminatorKind.INVOKE, tuple(edges)), callee=callee.id,
        completions=tuple(signatures), invoke_arguments=tuple(use.id for use in inputs))
    blocks.insert(0, Block(entry, (ref.id, condition.id, before.id), (invoke.id,)))
    caller = Region(root, "caller handles actual completion", entry, tuple(blocks),
                    (ExitPort("handled", ExitKind.NORMAL, (REFERENCE, STATE)),))
    regions = [caller, callee]
    operations = [invoke, *operations, *child_operations]
    alternate = None
    if alternate_callee:
        opposite = (ExitKind.NORMAL,) if kinds != (ExitKind.NORMAL,) else (ExitKind.RAISE,)
        other, other_ops, other_values = _callee("subset.other", opposite, root)
        regions.append(other)
        operations.extend(other_ops)
        values.extend(other_values)
        alternate = other.id
    graph = ProgramGraph(root, tuple(regions), tuple(operations), tuple(values),
                         (StateLocation(WORLD, "one canonical state chain"),))
    return graph, {"invoke": invoke.id, "callee": callee.id, "alternate": alternate,
                   "landings": landings, "terminals": terminals, "before": before.id,
                   "input": ref.id, "world": WORLD}


def final_gate_subset_program(kind):
    """A core-valid single-completion helper violates the specialized gate contract.

    RAISE-only retains a real entry branch that can directly reach the Drive;
    this intentionally is not a valid admission corridor. No callee completion
    is invented to keep an unreachable block alive.
    """
    from tests.fixtures.program_driver_graphs import driver_program

    graph = driver_program()
    row, = graph.final_body_gates
    gate = next(op for op in graph.operations if op.id == row.operation)
    region = next(region for region in graph.regions if region.id == graph.root)
    entry = next(block for block in region.blocks if block.id == region.entry)
    selected = next(edge for edge in gate.terminator.successors if edge.kind is kind)
    selected_signature = next(signature for signature in gate.completions if signature.kind is kind)
    if kind is ExitKind.NORMAL:
        rejected = next(edge.block for edge in gate.terminator.successors if edge.kind is ExitKind.RAISE)
        reject_block = next(block for block in region.blocks if block.id == rejected)
        removed_ops = set(reject_block.operations)
        removed_values = set(reject_block.arguments)
        gate = replace(gate, completions=(selected_signature,),
                       terminator=replace(gate.terminator, successors=(selected,)))
        region = replace(region, blocks=tuple(block for block in region.blocks if block.id != rejected),
                         exits=tuple(port for port in region.exits if port.kind is not ExitKind.RAISE))
        graph = replace(graph, regions=tuple(region if item.id == region.id else item for item in graph.regions),
            operations=tuple(gate if op.id == gate.id else op for op in graph.operations if op.id not in removed_ops),
            values=tuple(value for value in graph.values if value.id not in removed_values),
            control_scopes=tuple(replace(scope, blocks=tuple(block for block in scope.blocks if block != rejected))
                                 if scope.region == region.id else scope for scope in graph.control_scopes))
    elif kind is ExitKind.RAISE:
        by_id = {value.id: value for value in graph.values}
        gating_block = BlockID("subset.gate.actual")
        formals = tuple(replace(by_id[value], id=ValueID("subset.gate.arg." + str(index)),
                                origin=BlockArgument(gating_block, index))
                        for index, value in enumerate(entry.arguments))
        replacements = dict(zip(entry.arguments, (value.id for value in formals)))
        gate_inputs = set(gate.invoke_arguments)
        gate = replace(gate, uses=tuple(replace(use, value=replacements[use.value])
                                       for use in gate.uses if use.id in gate_inputs),
            completions=(selected_signature,), terminator=replace(gate.terminator, successors=(selected,)))
        normal = next(edge for edge in graph.operations if edge.id == gate.id).terminator.successors[0]
        # Original normal roles then produced state positions are exactly the
        # entry roles/state order for this Start fixture.
        condition = DataValue(ValueID("subset.gate.condition"), region.id, LiteralOrigin(True), "builtins.bool")
        actuals, edges = [], []
        for number, target in enumerate((gating_block, normal.block)):
            edge_uses = tuple(Use(UseID(f"subset.gate.branch.{number}.{index}"), value,
                                 UseRole.STATE_CONTENT if type(by_id[value]) is StateVersionValue
                                 else UseRole.PROTOCOL if hasattr(by_id[value], "protocol") else UseRole.REFERENCE)
                              for index, value in enumerate(entry.arguments))
            actuals.extend(edge_uses)
            edges.append(Successor(target, tuple(use.id for use in edge_uses)))
        condition_use = Use(UseID("subset.gate.condition.use"), condition.id)
        branch = Operation(OperationID("subset.gate.branch"), "two actual source paths",
            (Behavior.CONTROL,), (condition_use, *actuals), effects_complete=True,
            terminator=Terminator(TerminatorKind.BRANCH, tuple(edges), condition=condition_use.id))
        region = replace(region, blocks=tuple(replace(block, operations=(branch.id,))
                                             if block.id == entry.id else block for block in region.blocks)
                         + (Block(gating_block, tuple(value.id for value in formals), (gate.id,)),))
        graph = replace(graph, regions=tuple(region if item.id == region.id else item for item in graph.regions),
            operations=tuple(gate if op.id == gate.id else op for op in graph.operations) + (branch,),
            values=(*graph.values, *formals, condition),
            control_scopes=tuple(replace(scope, blocks=(*scope.blocks, gating_block))
                                 if scope.region == region.id else scope for scope in graph.control_scopes))
    else:
        raise ValueError("kind must be NORMAL or RAISE")
    return graph, {"gate": gate.id, "drive": row.drive}


__all__ = ["invoke_subset_program", "final_gate_subset_program"]
