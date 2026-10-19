"""Canonical pending-token merges with original payload projection ports."""
from dataclasses import replace

from scar.ir.program.control import (
    ControlPort,
    LanguageCompletionKind,
    PendingCompletionDefinition,
    PendingDispatchTerminator,
    PendingPayload,
    PendingSuccessor,
    ProtocolValueKind,
    ProtocolValueType,
)
from scar.ir.program.ids import BlockID, ControlPortID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    Behavior,
    Block,
    BlockArgument,
    DataValue,
    ExitKind,
    ExitPort,
    Operation,
    OperationResult,
    ProtocolValue,
    ReferenceValue,
    Region,
    StateVersionValue,
    Successor,
    Terminator,
    TerminatorKind,
    Use,
    UseRole,
    ValueKind,
    ValueType,
)
from scar.ir.program.protocols import OwnedUse
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.program_provider_pending_graphs import shared_pending_projection_graph
from tests.fixtures.program_protocol_graphs import _scope


def pending_payload_program(*, mixed=False, active="good", dead=None,
                            different_ports=False, kind="return"):
    """Merge two real RETURN tokens before one exact payload dispatch.

    Both branches carry the first original reference unless ``mixed`` selects
    the independent second reference for B. No object identity is inferred.
    """
    if active not in ("good", "wrong") or dead not in (None, "good", "wrong"):
        raise ValueError("active/dead must select an original good/wrong payload")
    if kind not in ("return", "raise"):
        raise ValueError("kind must be return or raise")
    graph = shared_pending_projection_graph()
    operations = {row.id: row for row in graph.operations}
    branch = operations[OperationID("provider.pending.branch")]
    make_a = operations[OperationID("provider.pending.make_a")]
    make_b = operations[OperationID("provider.pending.make_b")]
    dispatch_a = operations[OperationID("provider.pending.dispatch_a")]
    dispatch_b = operations[OperationID("provider.pending.dispatch_b")]
    terminal = operations[OperationID("provider.pending.return_exit")]
    expected = OwnedUse(branch.id, branch.uses[1].id)
    if active == "wrong":
        expected = graph.values[1].origin
        branch = replace(branch, uses=tuple(
            replace(use, value=branch.uses[3].value) if index == 1 else use
            for index, use in enumerate(branch.uses)
        ))
    elif not mixed:
        branch = replace(branch, uses=tuple(
            replace(use, value=branch.uses[1].value) if index == 3 else use
            for index, use in enumerate(branch.uses)
        ))

    region = graph.regions[0]
    merge_id = BlockID("pending.payload.merge")
    pending = ProtocolValue(
        ValueID("pending.payload.merge.token"), region.id,
        BlockArgument(merge_id, 0), ProtocolValueKind.PENDING_COMPLETION,
    )
    world = StateVersionValue(
        ValueID("pending.payload.merge.world"), region.id,
        BlockArgument(merge_id, 1), graph.locations[0].id,
    )
    jumps = tuple(replace(
        operation,
        label="forward original pending token to shared dispatch",
        terminator=Terminator(TerminatorKind.JUMP, (
            Successor(merge_id, tuple(use.id for use in operation.uses)),
        )),
    ) for operation in (dispatch_a, dispatch_b))
    token_use = Use(UseID("pending.payload.dispatch.token"), pending.id, UseRole.PROTOCOL)
    world_use = Use(UseID("pending.payload.dispatch.world"), world.id, UseRole.STATE_CONTENT)
    original_edge = dispatch_a.terminator.successors[0]
    dispatch = Operation(
        OperationID("pending.payload.dispatch"), "project selected pending payload",
        (Behavior.CONTROL,), (token_use, world_use),
        terminator=PendingDispatchTerminator(token_use.id, (
            PendingSuccessor(original_edge.port, original_edge.block,
                             (PendingPayload(), world_use.id)),
        )),
    )
    merge = Block(merge_id, (pending.id, world.id), (dispatch.id,))
    blocks = (*region.blocks[:-1], merge, region.blocks[-1])
    region = replace(region, blocks=blocks)
    graph = replace(
        graph, regions=(region,),
        operations=(branch, make_a, jumps[0], make_b, jumps[1], dispatch, terminal),
        values=(*graph.values, pending, world),
        control_scopes=tuple(replace(scope, blocks=tuple(block.id for block in blocks))
                             for scope in graph.control_scopes),
        provider_envelopes=(), provider_regions=(), provider_bindings=(),
    )
    if dead is not None:
        dead_operations, dead_values, dead_definitions = [], [], []
        for index, constructor in enumerate((make_a, make_b)):
            identity = OperationID(f"pending.payload.dead.{index}")
            payload = graph.values[1 if dead == "good" else 2]
            use = Use(UseID(identity.value + ".payload"), payload.id, UseRole.REFERENCE)
            token = ProtocolValue(ValueID(identity.value + ".token"), region.id,
                                  OperationResult(identity, 0), ProtocolValueKind.PENDING_COMPLETION)
            operation = Operation(identity, "unused independent pending constructor",
                (Behavior.CONTROL,), (use,), (token.id,), effects_complete=True)
            dead_operations.append(operation)
            dead_values.append(token)
            dead_definitions.append(PendingCompletionDefinition(token.id, original_edge.port, use.id))
        replacements = dict(zip((make_a.id, make_b.id), dead_operations))
        blocks = tuple(replace(block, operations=tuple(
            identity for operation in block.operations
            for identity in ((replacements[operation].id, operation)
                             if operation in replacements else (operation,))))
            for block in graph.regions[0].blocks)
        graph = replace(graph, regions=(replace(graph.regions[0], blocks=blocks),),
            operations=(*graph.operations, *dead_operations), values=(*graph.values, *dead_values),
            pending_completions=(*graph.pending_completions, *dead_definitions))

    if different_ports:
        alternate_port = ControlPortID("pending.payload.other.return")
        alternate_exit = BlockID("pending.payload.other.exit")
        reference = ReferenceValue(ValueID("pending.payload.other.value"), region.id,
                                   BlockArgument(alternate_exit, 0))
        after = StateVersionValue(ValueID("pending.payload.other.world"), region.id,
                                  BlockArgument(alternate_exit, 1), world.location)
        uses = (Use(UseID("pending.payload.other.return.value"), reference.id, UseRole.REFERENCE),
                Use(UseID("pending.payload.other.return.world"), after.id, UseRole.STATE_CONTENT))
        other_terminal = Operation(OperationID("pending.payload.other.return"),
            "separate Q exit shim", (Behavior.CONTROL,), uses,
            terminator=Terminator(TerminatorKind.RETURN, exit="normal",
                                  values=tuple(use.id for use in uses)))
        alternate_world_use = Use(UseID("pending.payload.dispatch.other.world"),
                                  world.id, UseRole.STATE_CONTENT)
        dispatch = replace(dispatch, uses=(*dispatch.uses, alternate_world_use),
            terminator=replace(dispatch.terminator,
            successors=(*dispatch.terminator.successors,
                PendingSuccessor(alternate_port, alternate_exit,
                                 (PendingPayload(), alternate_world_use.id)))))
        new_block = Block(alternate_exit, (reference.id, after.id), (other_terminal.id,))
        graph = replace(graph,
            regions=(replace(graph.regions[0], blocks=(*graph.regions[0].blocks, new_block)),),
            operations=tuple(dispatch if operation.id == dispatch.id else operation
                             for operation in graph.operations) + (other_terminal,),
            values=(*graph.values, reference, after),
            control_ports=(*graph.control_ports,
                ControlPort(alternate_port, graph.control_scopes[0].id,
                            LanguageCompletionKind.RETURN, exit="normal")),
            pending_completions=tuple(replace(definition, port=alternate_port)
                if definition.value == make_b.results[0] else definition
                for definition in graph.pending_completions))

    if kind == "raise":
        packet_values = {value.id for value in graph.values if type(value) is ReferenceValue}
        graph = replace(graph,
            regions=tuple(replace(record, exits=(ExitPort("failure", ExitKind.RAISE,
                (ProtocolValueType(ProtocolValueKind.EXCEPTION_PACKET),
                 ValueType(ValueKind.STATE, location=world.location))),))
                for record in graph.regions),
            values=tuple(ProtocolValue(value.id, value.region, value.origin,
                                       ProtocolValueKind.EXCEPTION_PACKET)
                         if value.id in packet_values else value for value in graph.values),
            operations=tuple(replace(operation,
                uses=tuple(replace(use, role=UseRole.PROTOCOL) if use.value in packet_values
                           else use for use in operation.uses),
                terminator=replace(operation.terminator, kind=TerminatorKind.RAISE, exit="failure")
                    if operation.terminator is not None
                    and operation.terminator.kind is TerminatorKind.RETURN
                    else operation.terminator)
                for operation in graph.operations),
            control_ports=tuple(replace(port, kind=LanguageCompletionKind.RAISE, exit="failure")
                                for port in graph.control_ports))
    graph = replace(graph, control_scopes=tuple(replace(scope,
        blocks=tuple(block.id for block in graph.regions[0].blocks))
        for scope in graph.control_scopes))
    current_operations = {operation.id: operation for operation in graph.operations}
    return graph, {
        "expected": expected,
        "actual": OwnedUse(terminal.id, terminal.uses[0].id),
        "branch": current_operations[branch.id],
        "guard_a": ControlEdgeReference(branch.id, 0),
        "guard_b": ControlEdgeReference(branch.id, 1),
        "constructors": tuple(current_operations[operation.id] for operation in (make_a, make_b)),
        "definitions": graph.pending_completions,
        "merge": merge,
        "dispatch": current_operations[dispatch.id],
        "selector": OwnedUse(dispatch.id, token_use.id),
        "projection": current_operations[dispatch.id].terminator.successors[0].arguments[0],
        "terminal": current_operations[terminal.id],
        "dead": tuple(current_operations[operation.id] for operation in dead_operations)
                  if dead is not None else (),
    }


def pending_payload_helper_program(*, wrong_actual=False):
    """A pending-return helper feeds a distinct, genuinely called helper."""
    graph, original = pending_payload_program()
    pending_region = replace(graph.regions[0], parent=RegionID("pending.helpers.root"))
    root, entry = pending_region.parent, BlockID("pending.helpers.entry")
    world = graph.locations[0].id
    original_entry = next(block for block in pending_region.blocks if block.id == pending_region.entry)
    values_by_id = {value.id: value for value in graph.values}
    inputs = tuple(replace(values_by_id[identity],
        id=ValueID(f"pending.helpers.input.{index}"), region=root,
        origin=BlockArgument(entry, index))
        for index, identity in enumerate(original_entry.arguments))
    target, target_entry = RegionID("pending.helpers.target"), BlockID("pending.helpers.target.entry")
    target_ref = ReferenceValue(ValueID("pending.helpers.target.ref"), target,
                                BlockArgument(target_entry, 0))
    target_state = StateVersionValue(ValueID("pending.helpers.target.state"), target,
                                     BlockArgument(target_entry, 1), world)

    def uses(name, values):
        return tuple(Use(UseID(f"{name}.u.{index}"), value.id,
            UseRole.STATE_CONTENT if type(value) is StateVersionValue
            else UseRole.DATA if type(value) is DataValue else UseRole.REFERENCE)
            for index, value in enumerate(values))

    def call(name, callee, arguments):
        identity = OperationID(name)
        result = ReferenceValue(ValueID(name + ".ref"), root, OperationResult(identity, 0))
        state = StateVersionValue(ValueID(name + ".world"), root, OperationResult(identity, 1), world)
        actuals = uses(name, arguments)
        operation = Operation(identity, "original known helper CALL", (Behavior.CONTROL,),
            actuals, (result.id, state.id), effects_complete=True, callee=callee,
            call_arguments=tuple(use.id for use in actuals))
        return operation, result, state

    first, returned, after = call("pending.helpers.first", pending_region.id, inputs)
    second, result, final_state = call("pending.helpers.second", target,
                                      (inputs[2] if wrong_actual else returned, after))
    root_uses = uses("pending.helpers.exit", (result, final_state))
    root_terminal = Operation(OperationID("pending.helpers.exit"), "original caller RETURN",
        (Behavior.CONTROL,), root_uses, effects_complete=True,
        terminator=Terminator(TerminatorKind.RETURN, exit="normal",
                              values=tuple(use.id for use in root_uses)))
    target_uses = uses("pending.helpers.target.exit", (target_ref, target_state))
    target_terminal = Operation(OperationID("pending.helpers.target.exit"),
        "actual second helper consumer and RETURN", (Behavior.CONTROL,), target_uses,
        effects_complete=True, terminator=Terminator(TerminatorKind.RETURN, exit="normal",
                                                    values=tuple(use.id for use in target_uses)))
    exits = (ExitPort("normal", ExitKind.NORMAL,
                     (ValueType(ValueKind.REFERENCE), ValueType(ValueKind.STATE, location=world))),)
    root_block = Block(entry, tuple(value.id for value in inputs),
                       (first.id, second.id, root_terminal.id))
    target_block = Block(target_entry, (target_ref.id, target_state.id), (target_terminal.id,))
    root_region = Region(root, "caller of two distinct original helpers", entry, (root_block,), exits)
    target_region = Region(target, "consumer after pending projection and real return", target_entry,
                           (target_block,), exits, parent=root)
    graph = replace(graph, root=root, regions=(root_region, pending_region, target_region),
        operations=(*graph.operations, first, second, root_terminal, target_terminal),
        values=(*graph.values, *inputs, returned, after, result, final_state, target_ref, target_state),
        control_scopes=(*graph.control_scopes, _scope(root, (root_block,)),
                        _scope(target, (target_block,))))
    return graph, {"expected": inputs[1].origin,
        "actual": OwnedUse(target_terminal.id, target_uses[0].id),
        "projected_actual": original["actual"], "projection": original,
        "first_call": first, "second_call": second, "target": target_terminal,
        "returned": returned, "root_terminal": root_terminal}


def pending_payload_loop_program(*, stale=False, unseeded=False, fresh_source=True):
    """Each header visit evaluates a source and constructs a new token.

    The old carried token is a real different evaluation. The unsupported
    ``unseeded`` variant deliberately exposes an entry pending boundary for
    the existing core's pending-origin rejection, not a query-only failure.
    """
    from scar.ir.program.ids import LocationID
    from scar.ir.program.model import ProgramGraph, StateLocation

    region, entry, header, finish, exit_id = map(
        lambda pair: pair[0](pair[1]), (
            (RegionID, "pending.loop"), (BlockID, "pending.loop.entry"),
            (BlockID, "pending.loop.header"), (BlockID, "pending.loop.finish"),
            (BlockID, "pending.loop.exit")))
    location = LocationID("pending.loop.world")
    reference = ReferenceValue(ValueID("pending.loop.initial"), region, BlockArgument(entry, 0))
    condition = DataValue(ValueID("pending.loop.again"), region, BlockArgument(entry, 1), "builtins.bool")
    before = StateVersionValue(ValueID("pending.loop.before"), region,
                               BlockArgument(entry, 2), location)
    first_id, source_id, pack_id = map(OperationID, (
        "pending.loop.pack.initial", "pending.loop.generate", "pending.loop.pack.current"))
    first_token = ProtocolValue(ValueID("pending.loop.initial.token"), region,
        BlockArgument(entry, 3) if unseeded else OperationResult(first_id, 0),
        ProtocolValueKind.PENDING_COMPLETION)
    prior = ProtocolValue(ValueID("pending.loop.carried.token"), region,
                          BlockArgument(header, 0), ProtocolValueKind.PENDING_COMPLETION)
    current = StateVersionValue(ValueID("pending.loop.current.world"), region,
                                BlockArgument(header, 1), location)
    source = ReferenceValue(ValueID("pending.loop.fresh"), region, OperationResult(source_id, 0))
    fresh_token = ProtocolValue(ValueID("pending.loop.fresh.token"), region,
                                OperationResult(pack_id, 0), ProtocolValueKind.PENDING_COMPLETION)
    final_token = ProtocolValue(ValueID("pending.loop.final.token"), region,
                                BlockArgument(finish, 0), ProtocolValueKind.PENDING_COMPLETION)
    final_state = StateVersionValue(ValueID("pending.loop.final.world"), region,
                                    BlockArgument(finish, 1), location)
    result = ReferenceValue(ValueID("pending.loop.result"), region, BlockArgument(exit_id, 0))
    after = StateVersionValue(ValueID("pending.loop.after"), region,
                              BlockArgument(exit_id, 1), location)
    port = ControlPortID("pending.loop.return")

    def own(name, *values):
        return tuple(Use(UseID(f"{name}.u.{index}"), value.id,
            UseRole.PROTOCOL if type(value) is ProtocolValue
            else UseRole.STATE_CONTENT if type(value) is StateVersionValue
            else UseRole.DATA if type(value) is DataValue else UseRole.REFERENCE)
            for index, value in enumerate(values))

    initial_use, = own(first_id.value, reference)
    first_pack = Operation(first_id, "initial independent pending seed", (Behavior.CONTROL,),
        (initial_use,), (first_token.id,), effects_complete=True)
    jump_uses = own("pending.loop.enter", first_token, before)
    jump = Operation(OperationID("pending.loop.enter"), "enter actual pending loop",
        (Behavior.CONTROL,), jump_uses, effects_complete=True,
        terminator=Terminator(TerminatorKind.JUMP,
            (Successor(header, tuple(use.id for use in jump_uses)),)))
    generate = Operation(source_id, "source is evaluated on every header visit",
                          (Behavior.COMPUTE,), results=(source.id,), effects_complete=True)
    payload, = own(pack_id.value, source if fresh_source else reference)
    pack = Operation(pack_id, "token is constructed on every header visit", (Behavior.CONTROL,),
                      (payload,), (fresh_token.id,), effects_complete=True)
    branch_uses = own("pending.loop.choose", condition, prior if unseeded else fresh_token, current,
                     prior if stale or unseeded else fresh_token, current)
    branch = Operation(OperationID("pending.loop.choose"), "repeat or dispatch exact token",
        (Behavior.CONTROL,), branch_uses, effects_complete=True,
        terminator=Terminator(TerminatorKind.BRANCH, (
            Successor(header, tuple(use.id for use in branch_uses[1:3])),
            Successor(finish, tuple(use.id for use in branch_uses[3:5]))),
            condition=branch_uses[0].id))
    dispatch_uses = own("pending.loop.dispatch", final_token, final_state)
    dispatch = Operation(OperationID("pending.loop.dispatch"), "project this selected token",
        (Behavior.CONTROL,), dispatch_uses, terminator=PendingDispatchTerminator(dispatch_uses[0].id,
            (PendingSuccessor(port, exit_id, (PendingPayload(), dispatch_uses[1].id)),)))
    exit_uses = own("pending.loop.return", result, after)
    terminal = Operation(OperationID("pending.loop.return"), "real loop return shim",
        (Behavior.CONTROL,), exit_uses, effects_complete=True,
        terminator=Terminator(TerminatorKind.RETURN, exit="normal",
                              values=tuple(use.id for use in exit_uses)))
    blocks = (
        Block(entry, (reference.id, condition.id, before.id, *(() if not unseeded else (first_token.id,))),
              (jump.id,) if unseeded else (first_pack.id, jump.id)),
        Block(header, (prior.id, current.id),
              (generate.id, branch.id) if unseeded else (generate.id, pack.id, branch.id)),
        Block(finish, (final_token.id, final_state.id), (dispatch.id,)),
        Block(exit_id, (result.id, after.id), (terminal.id,)),
    )
    scope = _scope(region, blocks)
    graph = ProgramGraph(region,
        (Region(region, "pending evaluation-relative loop", entry, blocks,
            (ExitPort("normal", ExitKind.NORMAL,
                (ValueType(ValueKind.REFERENCE), ValueType(ValueKind.STATE, location=location))),)),),
        ((jump, generate, branch, dispatch, terminal) if unseeded else
         (first_pack, jump, generate, pack, branch, dispatch, terminal)),
        (reference, condition, before, first_token, prior, current, source,
         *(() if unseeded else (fresh_token,)), final_token, final_state, result, after),
        (StateLocation(location, "coarse world"),),
        control_scopes=(scope,),
        control_ports=(ControlPort(port, scope.id, LanguageCompletionKind.RETURN, exit="normal"),),
        pending_completions=() if unseeded else
                            (PendingCompletionDefinition(first_token.id, port, initial_use.id),
                             PendingCompletionDefinition(fresh_token.id, port, payload.id)))
    return graph, {"expected": source.origin if fresh_source else reference.origin,
        "actual": OwnedUse(terminal.id, exit_uses[0].id),
        "source": generate, "constructor": pack, "carried": prior,
        "branch": branch, "dispatch": dispatch, "unseeded": first_token if unseeded else None}


__all__ = ["pending_payload_program", "pending_payload_helper_program", "pending_payload_loop_program"]
