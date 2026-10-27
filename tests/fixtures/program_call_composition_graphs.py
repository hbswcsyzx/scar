"""Composed original CALL-return-argument paths, without runtime recovery."""
from dataclasses import replace

from scar.ir.program.ids import BlockID, OperationID, RegionID, ValueID
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, DataValue, ExitKind, ExitPort, Operation,
    OperationResult, ReferenceValue, Region, Successor, Terminator, TerminatorKind,
)
from scar.ir.program.protocols import OwnedUse
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.program_call_return_graphs import (
    REFERENCE, STATE, _call, _graph, _reference, _return, _state, _uses,
    call_return_program, repeated_return_program,
)


def _identity_helper(name, parent):
    region, entry = RegionID(name), BlockID(name + ".entry")
    reference = _reference(name + ".input", region, entry, 0)
    state = _state(name + ".state", region, entry, 1)
    terminal = _return(name + ".exit", reference, state)
    return (Region(region, "known identity helper", entry,
                   (Block(entry, (reference.id, state.id), (terminal.id,)),),
                   (ExitPort("normal", ExitKind.NORMAL, (REFERENCE, STATE)),), parent=parent),
            terminal, (reference, state))


def call_composition_program(*, depth=1, calls="chain"):
    """Return ``(graph, details)`` with a consumer inside the actual helper.

    In the default graph the root calls H(x), then H(the first CALL result).
    Both original caller paths supply x to the helper's exact Return Use.
    The expected source remains the independently chosen root entry x; the
    actual target is the helper's original Reference return operand.
    """
    graph, original = call_return_program(calls=calls, depth=depth)
    terminal = next(operation for operation in graph.operations
                    if operation.id == original["terminals"][-1])
    return graph, {**original, "caller_actual": original["actual"],
                   "actual": OwnedUse(terminal.id, terminal.uses[0].id),
                   "consumer": terminal.id}


def distinct_call_composition_program(*, wrong_actual=False, opaque=False):
    """Known id(x) -> another helper, or an explicitly opaque original result.

    ``wrong_actual`` adds b=id(y) after a=id(x) and passes b to target. A
    separate original Use still consumes x immediately before target; source
    availability therefore cannot substitute for the target's actual value.
    ``opaque`` supplies an original result without a known callee interface.
    That result is a usable independent source, but no x -> result copy is
    declared. No synthetic alias or producer summary is added.
    """
    if wrong_actual and opaque:
        raise ValueError("wrong_actual and opaque are separate original programs")
    root, entry = RegionID("composition.root"), BlockID("composition.root.entry")
    x = _reference("composition.x", root, entry, 0)
    y = _reference("composition.y", root, entry, 1)
    before = _state("composition.before", root, entry, 2)
    target, target_terminal, target_values = _identity_helper("composition.target", root)
    values, operations, regions, calls = [x, y, before, *target_values], [], [target], []
    opaque_source = None
    if opaque:
        producer = OperationID("composition.opaque")
        returned = ReferenceValue(ValueID("composition.opaque.ref"), root, OperationResult(producer, 0))
        action = Operation(producer, "original producer without a known return-copy interface",
            (Behavior.COMPUTE,), _uses(producer.value, x), (returned.id,), effects_complete=True)
        operations.append(action)
        values.append(returned)
        current = before
        opaque_source = returned.origin
    else:
        identity, terminal, helper_values = _identity_helper("composition.identity", root)
        regions.insert(0, identity)
        operations.append(terminal)
        values.extend(helper_values)
        first, returned, current = _call("composition.first", root, identity.id, x, before)
        operations.append(first)
        values.extend((returned, current))
        calls.append(first.id)
        if wrong_actual:
            second, returned, current = _call("composition.second", root, identity.id, y, current)
            operations.append(second)
            values.extend((returned, current))
            calls.append(second.id)
    witness_use, = _uses("composition.still.available", x)
    witness = Operation(OperationID("composition.still.available"), "original x remains available",
                        (Behavior.COMPUTE,), (witness_use,), effects_complete=True)
    onward, result, after = _call("composition.onward", root, target.id, returned, current)
    consume = _return("composition.return", result, after)
    operations.extend((witness, onward, consume, target_terminal))
    values.extend((result, after))
    calls.append(onward.id)
    helper_ops = {identity for region in regions for block in region.blocks
                  for identity in block.operations}
    root_ops = tuple(operation.id for operation in operations if operation.id not in helper_ops)
    caller = Region(root, "returned source is passed to a distinct original helper", entry,
        (Block(entry, (x.id, y.id, before.id), root_ops),),
        (ExitPort("normal", ExitKind.NORMAL, (REFERENCE, STATE)),))
    return _graph(root, (caller, *regions), operations, values), {
        "expected": x.origin, "other_expected": y.origin, "opaque_expected": opaque_source,
        "actual": OwnedUse(target_terminal.id, target_terminal.uses[0].id),
        "available_actual": OwnedUse(witness.id, witness_use.id),
        "calls": tuple(calls), "target": onward.id, "consumer": target_terminal.id,
        "terminals": (target_terminal.id,)}


def duplicate_argument_composition_program(*, duplicate=True):
    """A returned source is passed in two distinct actual/formal positions.

    Both real target branches merge into one Reference consumer. With duplicate
    inputs, each branch supplies the source via a different formal. With x/y
    inputs, no unguarded query can discard the branch supplying y.
    """
    root, entry = RegionID("duplicate.root"), BlockID("duplicate.root.entry")
    x = _reference("duplicate.x", root, entry, 0)
    y = _reference("duplicate.y", root, entry, 1)
    condition = DataValue(ValueID("duplicate.condition"), root, BlockArgument(entry, 2), "builtins.bool")
    before = _state("duplicate.before", root, entry, 3)
    identity, identity_terminal, identity_values = _identity_helper("duplicate.identity", root)
    first, returned, current = _call("duplicate.first", root, identity.id, x, before)
    target, target_entry = RegionID("duplicate.target"), BlockID("duplicate.target.entry")
    merge = BlockID("duplicate.target.merge")
    left = _reference("duplicate.target.left", target, target_entry, 0)
    right = _reference("duplicate.target.right", target, target_entry, 1)
    test = DataValue(ValueID("duplicate.target.condition"), target,
                     BlockArgument(target_entry, 2), "builtins.bool")
    target_state = _state("duplicate.target.state", target, target_entry, 3)
    merged = _reference("duplicate.target.merged", target, merge, 0)
    merged_state = _state("duplicate.target.merged.state", target, merge, 1)
    target_terminal = _return("duplicate.target.exit", merged, merged_state)
    branch_uses = _uses("duplicate.choose", test, left, target_state, right, target_state)
    branch = Operation(OperationID("duplicate.choose"), "original selection of two incoming formals",
        (Behavior.CONTROL,), branch_uses, effects_complete=True,
        terminator=Terminator(TerminatorKind.BRANCH,
            (Successor(merge, tuple(use.id for use in branch_uses[1:3])),
             Successor(merge, tuple(use.id for use in branch_uses[3:5]))),
            condition=branch_uses[0].id))
    # _call orders (reference, extra inputs..., state), matching these formals.
    onward, output, after = _call("duplicate.onward", root, target, returned, current,
                                   returned if duplicate else y, condition)
    consumer = _return("duplicate.return", output, after)
    target_region = Region(target, "all original formal alternatives", target_entry,
        (Block(target_entry, (left.id, right.id, test.id, target_state.id), (branch.id,)),
         Block(merge, (merged.id, merged_state.id), (target_terminal.id,))),
        (ExitPort("normal", ExitKind.NORMAL, (REFERENCE, STATE)),), parent=root)
    caller = Region(root, "caller with distinct owned actual Uses", entry,
        (Block(entry, (x.id, y.id, condition.id, before.id), (first.id, onward.id, consumer.id)),),
        (ExitPort("normal", ExitKind.NORMAL, (REFERENCE, STATE)),))
    graph = _graph(root, (caller, identity, target_region),
        (first, onward, consumer, identity_terminal, branch, target_terminal),
        (x, y, condition, before, *identity_values, returned, current, output, after,
         left, right, test, target_state, merged, merged_state))
    return graph, {"expected": x.origin, "other_expected": y.origin,
        "actual": OwnedUse(target_terminal.id, target_terminal.uses[0].id),
        "calls": (first.id, onward.id), "target": onward.id,
        "arguments": tuple(OwnedUse(onward.id, use.id) for use in onward.uses),
        "guards": (ControlEdgeReference(branch.id, 0), ControlEdgeReference(branch.id, 1)),
        "consumer": target_terminal.id, "terminals": (target_terminal.id,)}


def loop_call_composition_program(*, stale=False):
    """Pass the fresh/old carried return through another actual helper call."""
    graph, original = repeated_return_program(stale=stale)
    operations = {operation.id: operation for operation in graph.operations}
    values = {value.id: value for value in graph.values}
    previous = operations[original["actual"].operation]
    root = next(region for region in graph.regions if region.id == graph.root)
    identity_call = operations[original["calls"][0]]
    reference = values[previous.uses[0].value]
    state = values[identity_call.results[1]]
    target, terminal, target_values = _identity_helper("loop.composition.target", root.id)
    onward, output, after = _call(previous.id.value, root.id, target.id, reference, state)
    operations[previous.id] = onward
    # This new real CALL advances state: both actual branch continuations must
    # forward its poststate instead of the earlier identity CALL poststate.
    for identity, operation in tuple(operations.items()):
        if operation.terminator is not None and operation.terminator.kind is TerminatorKind.BRANCH:
            operations[identity] = replace(operation, uses=tuple(
                replace(use, value=after.id) if use.value == state.id else use
                for use in operation.uses))
    operations[terminal.id] = terminal
    graph = replace(graph, regions=(*graph.regions, target),
        operations=tuple(operations.values()), values=(*graph.values, output, after, *target_values))
    return graph, {**original, "actual": OwnedUse(terminal.id, terminal.uses[0].id),
                   "calls": (*original["calls"], onward.id), "target": onward.id,
                   "consumer": terminal.id}
