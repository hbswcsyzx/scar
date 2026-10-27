"""Original known-call return paths for bounded source-copy queries.

These graphs declare ordinary synchronous calls.  They do not recover a
runtime occurrence or establish Python object identity from a copied port.
"""
from dataclasses import replace

from scar.ir.program.ids import BlockID, LocationID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, DataValue, ExitKind, ExitPort,
    Operation, OperationResult, ProgramGraph, ReferenceValue, Region, StateAccess,
    StateLocation, StateVersionValue, Successor, Terminator, TerminatorKind,
    Use, UseRole, ValueKind, ValueType,
)
from scar.ir.program.protocols import OwnedUse


REFERENCE = ValueType(ValueKind.REFERENCE)
WORLD = LocationID("return.world")
STATE = ValueType(ValueKind.STATE, location=WORLD)


def _reference(name, region, block, position):
    return ReferenceValue(ValueID(name), region, BlockArgument(block, position))


def _state(name, region, block, position):
    return StateVersionValue(ValueID(name), region, BlockArgument(block, position), WORLD)


def _uses(name, *values):
    return tuple(Use(UseID(f"{name}.u.{number}"), value.id,
                     UseRole.STATE_CONTENT if isinstance(value, StateVersionValue)
                     else UseRole.DATA if isinstance(value, DataValue)
                     else UseRole.REFERENCE)
                 for number, value in enumerate(values))


def _return(name, *values):
    uses = _uses(name, *values)
    return Operation(OperationID(name), "original normal exit", (Behavior.CONTROL,),
        uses, effects_complete=True,
        terminator=Terminator(TerminatorKind.RETURN, exit="normal",
                              values=tuple(use.id for use in uses)))


def _call(name, region, callee, reference, state, *extra_inputs):
    identity = OperationID(name)
    ref = ReferenceValue(ValueID(name + ".ref"), region, OperationResult(identity, 0))
    after = StateVersionValue(ValueID(name + ".state"), region,
                              OperationResult(identity, 1), WORLD)
    uses = _uses(name, reference, *extra_inputs, state)
    operation = Operation(identity, "original synchronous call", (Behavior.CONTROL,),
        uses, (ref.id, after.id), callee=callee,
        call_arguments=tuple(use.id for use in uses), effects_complete=True)
    return operation, ref, after


def _graph(root, regions, operations, values):
    return ProgramGraph(root, tuple(regions), tuple(operations), tuple(values),
                        (StateLocation(WORLD, "one original coarse state chain"),))


def call_return_program(*, calls="single", depth=1, mutate=False, internal=False):
    """Return ``(graph, details)`` for a genuine identity CALL and consumer.

    The helper returns its exact entry Reference and unchanged State inputs.
    The caller consumes its own CALL outputs.  Expected and actual are chosen
    independently from those original ports, never from a discovered producer.
    """
    if calls not in ("single", "siblings", "chain") or depth not in (1, 2):
        raise ValueError("calls must be single/siblings/chain and depth must be 1/2")
    root = RegionID("return.root")
    helpers = tuple(RegionID("return.helper" + (f".{number}" if depth > 1 else ""))
                    for number in range(depth))
    entry = BlockID("return.root.entry")
    source = ReferenceValue(ValueID("return.source"), root, BlockArgument(entry, 0))
    other = _reference("return.other", root, entry, 1)
    before = _state("return.before", root, entry, 2)
    values, operations, regions = [source, other, before], [], []
    exits = (ExitPort("normal", ExitKind.NORMAL, (REFERENCE, STATE)),)
    first, returned, after = _call("return.call", root, helpers[0], source, before)
    operations.append(first)
    values.extend((returned, after))
    root_calls, root_results, root_ops = [first.id], [returned], [first.id]
    if calls != "single":
        second, returned, after = _call("return.second", root, helpers[0],
            other if calls == "siblings" else returned, after)
        operations.append(second)
        values.extend((returned, after))
        root_calls.append(second.id)
        root_results.append(returned)
        root_ops.append(second.id)
    consumer = _return("return.consume", returned, after)
    operations.append(consumer)
    root_ops.append(consumer.id)
    regions.append(Region(root, "known caller", entry,
        (Block(entry, (source.id, other.id, before.id), tuple(root_ops)),), exits))
    terminals, all_calls, helper_sources = [], list(root_calls), []
    for number, helper in enumerate(helpers):
        block = BlockID(helper.value + ".entry")
        ref = _reference(helper.value + ".input", helper, block, 0)
        state = _state(helper.value + ".before", helper, block, 1)
        values.extend((ref, state))
        local_ops = []
        if number + 1 < len(helpers):
            nested, ref, state = _call(helper.value + ".call", helper,
                                        helpers[number + 1], ref, state)
            operations.append(nested)
            local_ops.append(nested.id)
            all_calls.append(nested.id)
            values.extend((ref, state))
        else:
            if internal:
                producer = OperationID(helper.value + ".generate")
                result = ReferenceValue(ValueID(helper.value + ".generated"), helper,
                                        OperationResult(producer, 0))
                action = Operation(producer, "independent original helper producer",
                    (Behavior.COMPUTE,), _uses(producer.value, ref), (result.id,),
                    effects_complete=True)
                operations.append(action)
                local_ops.append(action.id)
                values.append(result)
                helper_sources.append(result.origin)
                ref = result
            if mutate:
                update_id = OperationID(helper.value + ".update")
                output = StateVersionValue(ValueID(helper.value + ".updated"), helper,
                                            OperationResult(update_id, 0), WORLD)
                arguments = _uses(update_id.value, state)
                update = Operation(update_id, "actual coarse state mutation",
                    (Behavior.READ, Behavior.WRITE), arguments, (output.id,),
                    (StateAccess(WORLD, arguments[0].id, AccessMode.READ_WRITE, output.id),),
                    effects_complete=True)
                operations.append(update)
                local_ops.append(update.id)
                values.append(output)
                state = output
        terminal = _return(helper.value + ".exit", ref, state)
        operations.append(terminal)
        local_ops.append(terminal.id)
        terminals.append(terminal.id)
        formals = tuple(value.id for value in values
                        if value.region == helper and value.origin in
                        (BlockArgument(block, 0), BlockArgument(block, 1)))
        regions.append(Region(helper, "known helper", block,
            (Block(block, formals, tuple(local_ops)),), exits,
            parent=root if number == 0 else helpers[number - 1]))
    return _graph(root, regions, operations, values), {
        "expected": source.origin, "other_expected": other.origin,
        "actual": OwnedUse(consumer.id, consumer.uses[0].id),
        "calls": tuple(all_calls), "root_calls": tuple(root_calls),
        "terminals": tuple(terminals), "inputs": (source.id, other.id),
        "results": tuple(value.id for value in root_results),
        "result_sources": tuple(value.origin for value in root_results),
        "helper_sources": tuple(helper_sources), "state_expected": before.origin,
        "state_actual": OwnedUse(consumer.id, consumer.uses[1].id)}


def multi_return_program(*, mixed=False, no_terminal=False):
    """One CALL has all original Return sites, or an actual endless callee.

    ``mixed`` makes one feasible normal exit return a different entry input.
    ``no_terminal`` uses a real C1 pending Return intercepted forever by
    cleanup. It does not fabricate a Return to satisfy the call interface.
    """
    if no_terminal:
        return _nonreturning_cleanup_call_program()
    root, helper = RegionID("many.root"), RegionID("many.helper")
    entry, helper_entry = BlockID("many.root.entry"), BlockID("many.helper.entry")
    x = _reference("many.x", root, entry, 0)
    y = _reference("many.y", root, entry, 1)
    condition = DataValue(ValueID("many.condition"), root, BlockArgument(entry, 2), "builtins.bool")
    state = _state("many.before", root, entry, 3)
    hx = _reference("many.helper.x", helper, helper_entry, 0)
    hy = _reference("many.helper.y", helper, helper_entry, 1)
    hc = DataValue(ValueID("many.helper.condition"), helper,
                   BlockArgument(helper_entry, 2), "builtins.bool")
    hs = _state("many.helper.before", helper, helper_entry, 3)
    call_id = OperationID("many.call")
    output = ReferenceValue(ValueID("many.output"), root, OperationResult(call_id, 0))
    after = StateVersionValue(ValueID("many.after"), root, OperationResult(call_id, 1), WORLD)
    actuals = _uses("many.call", x, y, condition, state)
    call = Operation(call_id, "call all original helper paths", (Behavior.CONTROL,),
        actuals, (output.id, after.id), callee=helper,
        call_arguments=tuple(use.id for use in actuals), effects_complete=True)
    consumer = _return("many.consume", output, after)
    values = [x, y, condition, state, hx, hy, hc, hs, output, after]
    operations = [call, consumer]
    helper_blocks, terminals = [], []
    branch_uses, successors = [_uses("many.choose.condition", hc)[0]], []
    for number, returned in enumerate((hx, hy if mixed else hx)):
        block = BlockID(f"many.helper.path.{number}")
        ref = _reference(f"many.path.{number}.ref", helper, block, 0)
        current = _state(f"many.path.{number}.state", helper, block, 1)
        forward = _uses(f"many.path.{number}.forward", returned, hs)
        branch_uses.extend(forward)
        successors.append(Successor(block, tuple(use.id for use in forward)))
        terminal = _return(f"many.path.{number}.exit", ref, current)
        operations.append(terminal)
        values.extend((ref, current))
        helper_blocks.append(Block(block, (ref.id, current.id), (terminal.id,)))
        terminals.append(terminal.id)
    branch = Operation(OperationID("many.choose"), "two original possible Returns",
        (Behavior.CONTROL,), tuple(branch_uses), effects_complete=True,
        terminator=Terminator(TerminatorKind.BRANCH, tuple(successors),
                              condition=branch_uses[0].id))
    operations.append(branch)
    helper_blocks.insert(0, Block(helper_entry, (hx.id, hy.id, hc.id, hs.id), (branch.id,)))
    exits = (ExitPort("normal", ExitKind.NORMAL, (REFERENCE, STATE)),)
    regions = (Region(root, "caller", entry,
        (Block(entry, (x.id, y.id, condition.id, state.id), (call.id, consumer.id)),), exits),
        Region(helper, "all original exit paths", helper_entry, tuple(helper_blocks), exits, parent=root))
    return _graph(root, regions, operations, values), {
        "expected": x.origin, "actual": OwnedUse(consumer.id, consumer.uses[0].id),
        "calls": (call.id,), "terminals": tuple(terminals),
        "inputs": (x.id, y.id), "results": (output.id,)}


def _nonreturning_cleanup_call_program():
    """Use the existing C1 protocol, with a captured Return and no exit site."""
    from tests.fixtures.program_cleanup_graphs import resume_multistate_graph

    graph = resume_multistate_graph()
    callee, = graph.regions
    interface, = graph.cleanup_interfaces
    cleanup_entry = next(block for block in callee.blocks if block.id == interface.entry)
    remove_blocks = {BlockID(name) for name in (
        "shared.make_raise", "shared.cleanup.post-pop-route", "shared.dispatch.block",
        "shared.return_exit", "shared.raise_exit")}
    preserved_ops = {identity for block in callee.blocks if block.id not in remove_blocks
                     for identity in (block.operations[:3] if block.id == cleanup_entry.id
                                      else block.operations)}
    operations = [operation for operation in graph.operations if operation.id in preserved_ops]
    branch = next(operation for operation in operations if operation.id == OperationID("shared.branch"))
    edge = next(edge for edge in branch.terminator.successors if edge.block == BlockID("shared.make_return"))
    branch = replace(branch, uses=tuple(use for use in branch.uses if use.id in edge.arguments),
                     terminator=Terminator(TerminatorKind.JUMP, (edge,)))
    operations = [branch if operation.id == branch.id else operation for operation in operations]
    values = [value for value in graph.values
              if not (isinstance(value.origin, BlockArgument) and value.origin.block in remove_blocks)
              and not (isinstance(value.origin, OperationResult)
                       and value.origin.operation not in preserved_ops)]
    by_value = {value.id: value for value in values}
    loop = BlockID("return.cleanup.forever")
    loop_values, into_uses, back_uses = [], [], []
    for number, name in enumerate(("shared.cleanup.world.after", "shared.cleanup.ambient.after")):
        actual = by_value[ValueID(name)]
        formal = StateVersionValue(ValueID(f"return.cleanup.loop.state.{number}"), callee.id,
                                    BlockArgument(loop, number), actual.location)
        loop_values.append(formal)
        into_uses.append(Use(UseID(f"return.cleanup.into.{number}"), actual.id, UseRole.STATE_CONTENT))
        back_uses.append(Use(UseID(f"return.cleanup.back.{number}"), formal.id, UseRole.STATE_CONTENT))
    into = Operation(OperationID("return.cleanup.into"), "cleanup retains its active pending Return",
        (Behavior.CONTROL,), tuple(into_uses), effects_complete=True,
        terminator=Terminator(TerminatorKind.JUMP,
            (Successor(loop, tuple(use.id for use in into_uses)),)))
    back = Operation(OperationID("return.cleanup.back"), "cleanup does not resume or replace",
        (Behavior.CONTROL,), tuple(back_uses), effects_complete=True,
        terminator=Terminator(TerminatorKind.JUMP,
            (Successor(loop, tuple(use.id for use in back_uses)),)))
    operations.extend((into, back))
    values.extend(loop_values)
    blocks = tuple(replace(block, operations=(*cleanup_entry.operations[:3], into.id))
                   if block.id == cleanup_entry.id else block
                   for block in callee.blocks if block.id not in remove_blocks)
    blocks += (Block(loop, tuple(value.id for value in loop_values), (back.id,)),)
    normal = next(exit_ for exit_ in callee.exits if exit_.kind is ExitKind.NORMAL)
    root, entry = RegionID("return.cleanup.caller"), BlockID("return.cleanup.caller.entry")
    callee = replace(callee, blocks=blocks, exits=(normal,), parent=root)
    old_entry = next(block for block in callee.blocks if block.id == callee.entry)
    inputs = tuple(replace(by_value[identity], id=ValueID(f"return.cleanup.input.{number}"),
                           region=root, origin=BlockArgument(entry, number))
                   for number, identity in enumerate(old_entry.arguments))
    call_id = OperationID("return.cleanup.call")
    outputs = (ReferenceValue(ValueID("return.cleanup.result"), root, OperationResult(call_id, 0)),
        *(StateVersionValue(ValueID(f"return.cleanup.result.state.{number}"), root,
                             OperationResult(call_id, number), type_.location)
          for number, type_ in enumerate(normal.types[1:], 1)))
    uses = _uses("return.cleanup.call", *inputs)
    call = Operation(call_id, "CALL whose declared Return is intercepted by C1",
        (Behavior.CONTROL,), uses, tuple(value.id for value in outputs), callee=callee.id,
        call_arguments=tuple(use.id for use in uses), effects_complete=True)
    consumer = _return("return.cleanup.consume", *outputs)
    caller = Region(root, "caller retains declared ports without inventing their execution", entry,
        (Block(entry, tuple(value.id for value in inputs), (call.id, consumer.id)),), (normal,))
    preserved_values = {value.id for value in values}
    graph = replace(graph, root=root, regions=(caller, callee),
        operations=(*operations, call, consumer), values=(*values, *inputs, *outputs),
        cleanup_resumes=(), exception_packets=(),
        control_ports=tuple(port for port in graph.control_ports if port.exit == normal.name),
        pending_completions=tuple(row for row in graph.pending_completions if row.value in preserved_values),
        control_scopes=tuple(replace(scope,
            blocks=tuple(block for block in scope.blocks if block not in remove_blocks)
                + ((loop,) if scope.id == interface.scope else ()))
            for scope in graph.control_scopes))
    source = next(value for value, original in zip(inputs, old_entry.arguments)
                  if original == ValueID("shared.return.input"))
    return graph, {"expected": source.origin, "actual": OwnedUse(consumer.id, consumer.uses[0].id),
        "calls": (call.id,), "terminals": (), "inputs": tuple(value.id for value in inputs),
        "results": (outputs[0].id,), "cleanup": interface.scope}


def repeated_return_program(*, stale=False):
    """Each header visit re-executes a source before an identity CALL.

    The stale consumer uses the prior visit's carried CALL output after the
    source has been executed again. Equal static producer roots on a backedge
    must not turn that old incarnation into this evaluation's source copy.
    """
    root, helper = RegionID("repeat.root"), RegionID("repeat.helper")
    entry, header, finish = (BlockID("repeat.entry"), BlockID("repeat.header"),
                              BlockID("repeat.finish"))
    helper_entry = BlockID("repeat.helper.entry")
    initial = _reference("repeat.initial", root, entry, 0)
    condition = DataValue(ValueID("repeat.again"), root, BlockArgument(entry, 1), "builtins.bool")
    before = _state("repeat.before", root, entry, 2)
    prior = _reference("repeat.prior", root, header, 0)
    current = _state("repeat.current", root, header, 1)
    generate_id = OperationID("repeat.generate")
    fresh = ReferenceValue(ValueID("repeat.fresh"), root, OperationResult(generate_id, 0))
    generate = Operation(generate_id, "new source evaluation on every visit", (Behavior.COMPUTE,),
                         results=(fresh.id,), effects_complete=True)
    call, returned, after = _call("repeat.call", root, helper, fresh, current)
    consume_use = _uses("repeat.consume", prior if stale else returned)[0]
    consumer = Operation(OperationID("repeat.consume"), "inspect fresh or carried source",
                         (Behavior.COMPUTE,), (consume_use,), effects_complete=True)
    first_uses = _uses("repeat.first", initial, before)
    jump = Operation(OperationID("repeat.jump"), "enter loop", (Behavior.CONTROL,), first_uses,
        effects_complete=True, terminator=Terminator(TerminatorKind.JUMP,
            (Successor(header, tuple(use.id for use in first_uses)),)))
    last_ref = _reference("repeat.final.ref", root, finish, 0)
    last_state = _state("repeat.final.state", root, finish, 1)
    branch_uses = _uses("repeat.choose", condition, returned, after, returned, after)
    branch = Operation(OperationID("repeat.choose"), "repeat or return", (Behavior.CONTROL,),
        branch_uses, effects_complete=True,
        terminator=Terminator(TerminatorKind.BRANCH,
            (Successor(header, tuple(use.id for use in branch_uses[1:3])),
             Successor(finish, tuple(use.id for use in branch_uses[3:5]))),
            condition=branch_uses[0].id))
    terminal = _return("repeat.exit", last_ref, last_state)
    helper_ref = _reference("repeat.helper.ref", helper, helper_entry, 0)
    helper_state = _state("repeat.helper.state", helper, helper_entry, 1)
    helper_terminal = _return("repeat.helper.exit", helper_ref, helper_state)
    exits = (ExitPort("normal", ExitKind.NORMAL, (REFERENCE, STATE)),)
    regions = (Region(root, "source reset loop", entry,
        (Block(entry, (initial.id, condition.id, before.id), (jump.id,)),
         Block(header, (prior.id, current.id), (generate.id, call.id, consumer.id, branch.id)),
         Block(finish, (last_ref.id, last_state.id), (terminal.id,))), exits),
        Region(helper, "identity helper", helper_entry,
        (Block(helper_entry, (helper_ref.id, helper_state.id), (helper_terminal.id,)),), exits, parent=root))
    return _graph(root, regions,
        (jump, generate, call, consumer, branch, terminal, helper_terminal),
        (initial, condition, before, prior, current, fresh, returned, after, last_ref, last_state,
         helper_ref, helper_state)), {
        "expected": fresh.origin, "actual": OwnedUse(consumer.id, consume_use.id),
        "calls": (call.id,), "terminals": (helper_terminal.id,),
        "inputs": (initial.id,), "results": (returned.id,), "source": generate.id}


def recursive_return_program():
    """A real base Return and a recursive Return, with no invented unroll."""
    root, helper = RegionID("recursive.root"), RegionID("recursive.helper")
    entry, helper_entry = BlockID("recursive.root.entry"), BlockID("recursive.helper.entry")
    base, recur = BlockID("recursive.base"), BlockID("recursive.recur")
    source = _reference("recursive.source", root, entry, 0)
    condition = DataValue(ValueID("recursive.condition"), root, BlockArgument(entry, 1), "builtins.bool")
    state = _state("recursive.state", root, entry, 2)
    call, output, after = _call("recursive.call", root, helper, source, state, condition)
    consumer = _return("recursive.consume", output, after)
    ref = _reference("recursive.helper.ref", helper, helper_entry, 0)
    test = DataValue(ValueID("recursive.helper.condition"), helper,
                      BlockArgument(helper_entry, 1), "builtins.bool")
    current = _state("recursive.helper.state", helper, helper_entry, 2)
    base_ref = _reference("recursive.base.ref", helper, base, 0)
    base_state = _state("recursive.base.state", helper, base, 1)
    base_terminal = _return("recursive.base.exit", base_ref, base_state)
    recur_ref = _reference("recursive.recur.ref", helper, recur, 0)
    recur_test = DataValue(ValueID("recursive.recur.condition"), helper,
                           BlockArgument(recur, 1), "builtins.bool")
    recur_state = _state("recursive.recur.state", helper, recur, 2)
    self_call, self_ref, self_state = _call("recursive.self", helper, helper,
                                          recur_ref, recur_state, recur_test)
    recursive_terminal = _return("recursive.recur.exit", self_ref, self_state)
    branch_uses = _uses("recursive.choose", test, ref, current, ref, test, current)
    choose = Operation(OperationID("recursive.choose"), "real base or recursive path",
        (Behavior.CONTROL,), branch_uses, effects_complete=True,
        terminator=Terminator(TerminatorKind.BRANCH,
            (Successor(base, tuple(use.id for use in branch_uses[1:3])),
             Successor(recur, tuple(use.id for use in branch_uses[3:6]))),
            condition=branch_uses[0].id))
    exits = (ExitPort("normal", ExitKind.NORMAL, (REFERENCE, STATE)),)
    regions = (Region(root, "caller of recursive helper", entry,
        (Block(entry, (source.id, condition.id, state.id), (call.id, consumer.id)),), exits),
        Region(helper, "static recursion with a real base", helper_entry,
        (Block(helper_entry, (ref.id, test.id, current.id), (choose.id,)),
         Block(base, (base_ref.id, base_state.id), (base_terminal.id,)),
         Block(recur, (recur_ref.id, recur_test.id, recur_state.id),
               (self_call.id, recursive_terminal.id))), exits, parent=root))
    return _graph(root, regions,
        (call, consumer, choose, base_terminal, self_call, recursive_terminal),
        (source, condition, state, output, after, ref, test, current, base_ref, base_state,
         recur_ref, recur_test, recur_state, self_ref, self_state)), {
        "expected": source.origin, "actual": OwnedUse(consumer.id, consumer.uses[0].id),
        "calls": (call.id, self_call.id),
        "terminals": (base_terminal.id, recursive_terminal.id),
        "inputs": (source.id,), "results": (output.id,)}
