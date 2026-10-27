"""C1 INVOKE/state fixtures, without a real callable or exception-context proof.

Completion packets are private protocol results. The fixtures do not claim to
implement Python raise normalization, implicit chaining, or runtime unwinding.
"""
from __future__ import annotations

from dataclasses import replace

from scar.ir.program.cleanup import CleanupReplace, CleanupRouteSuccessor, CleanupRouteTerminator
from scar.ir.program.control import (
    ControlScope, ControlScopeKind, PendingCompletionDefinition, ProtocolValueKind as P,
    ProtocolValueType,
)
from scar.ir.program.ids import BlockID, ControlPortID, ControlScopeID, OperationID, UseID, ValueID
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, CompletionResult, CompletionSignature,
    CompletionSuccessor, ExitKind, Footprint, FootprintKind, Operation, OperationResult,
    ProtocolValue, StateAccess, StateVersionValue, Successor, Terminator, TerminatorKind,
    Use, UseRole, ValueKind, ValueType,
)
from scar.ir.program.structured import ControlEdgeReference

from tests.fixtures.program_cleanup_graphs import resume_multistate_graph
from tests.fixtures.program_control_graphs import _source


def _protocol(name, region, block, index, kind):
    return ProtocolValue(ValueID(name), region, BlockArgument(block, index), kind)


def _state(name, region, block, index, location):
    return StateVersionValue(ValueID(name), region, BlockArgument(block, index), location)


def _use(name, value, role=UseRole.PROTOCOL):
    return Use(UseID(name), value, role)


def cleanup_invoke_graph():
    """An unknown cleanup call yields both state domains on both completions.

    CompletionResult indices deliberately differ from successor parameter
    positions. Original pending/context are local Use forwards, never exported
    completion results or call arguments. RAISE constructs a fresh pending
    before a separate Replace-only block and the existing parent route.
    """
    graph = resume_multistate_graph()
    region = graph.regions[0]
    interface, = graph.cleanup_interfaces
    scope = interface.scope
    values = {value.id: value for value in graph.values}
    operations = {operation.id: operation for operation in graph.operations}
    world = values[ValueID("shared.cleanup.world")].location
    ambient = graph.handled_context_domains[0].location
    normal_block = BlockID("invoke.cleanup.normal")
    failed_block = BlockID("invoke.cleanup.failed")
    replace_block = BlockID("invoke.cleanup.replace")

    normal_pending = _protocol("invoke.normal.pending", region.id, normal_block, 0, P.PENDING_COMPLETION)
    normal_world = replace(values[ValueID("shared.cleanup.world.after")],
                           origin=BlockArgument(normal_block, 1))
    normal_context = _protocol("invoke.normal.context", region.id, normal_block, 2, P.SAVED_HANDLED_CONTEXT)
    normal_ambient = replace(values[ValueID("shared.cleanup.ambient.after")],
                             origin=BlockArgument(normal_block, 3))
    failed_packet = _protocol("invoke.failed.packet", region.id, failed_block, 0, P.EXCEPTION_PACKET)
    failed_pending = _protocol("invoke.failed.saved-pending", region.id, failed_block, 1, P.PENDING_COMPLETION)
    failed_world = _state("invoke.failed.world", region.id, failed_block, 2, world)
    failed_context = _protocol("invoke.failed.context", region.id, failed_block, 3, P.SAVED_HANDLED_CONTEXT)
    failed_ambient = _state("invoke.failed.ambient", region.id, failed_block, 4, ambient)
    replace_pending = _protocol("invoke.replace.saved-pending", region.id, replace_block, 0, P.PENDING_COMPLETION)
    replace_world = _state("invoke.replace.world", region.id, replace_block, 1, world)
    replace_new = _protocol("invoke.replace.new-pending", region.id, replace_block, 2, P.PENDING_COMPLETION)
    replace_context = _protocol("invoke.replace.context", region.id, replace_block, 3, P.SAVED_HANDLED_CONTEXT)
    replace_ambient = _state("invoke.replace.ambient", region.id, replace_block, 4, ambient)
    additions = [normal_pending, normal_context, failed_packet, failed_pending,
                 failed_world, failed_context, failed_ambient, replace_pending,
                 replace_world, replace_new, replace_context, replace_ambient]
    values[normal_world.id], values[normal_ambient.id] = normal_world, normal_ambient

    invoke_id = OperationID("shared.cleanup.write")
    input_world = _use("invoke.call.input.world", ValueID("shared.cleanup.enter.world.after"),
                       UseRole.STATE_CONTENT)
    input_ambient = _use("invoke.call.input.ambient", ValueID("shared.cleanup.enter.ambient.after"),
                         UseRole.STATE_CONTENT)
    normal_old = _use("invoke.call.normal.pending", interface.pending_argument)
    normal_saved = _use("invoke.call.normal.context", graph.cleanup_enters[0].saved_context)
    failed_old = _use("invoke.call.raise.pending", interface.pending_argument)
    failed_saved = _use("invoke.call.raise.context", graph.cleanup_enters[0].saved_context)
    operations[invoke_id] = Operation(
        invoke_id, "unknown cleanup call with private normal/raise completion",
        (Behavior.CONTROL, Behavior.READ, Behavior.WRITE),
        (input_world, input_ambient, normal_old, normal_saved, failed_old, failed_saved),
        effects_complete=False,
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, normal_block,
                (normal_old.id, CompletionResult(0), normal_saved.id, CompletionResult(1))),
            CompletionSuccessor(ExitKind.RAISE, failed_block,
                (CompletionResult(0), failed_old.id, CompletionResult(1),
                 failed_saved.id, CompletionResult(2))),
        )),
        completions=(
            CompletionSignature(ExitKind.NORMAL, (
                ValueType(ValueKind.STATE, location=world), ValueType(ValueKind.STATE, location=ambient))),
            CompletionSignature(ExitKind.RAISE, (
                ProtocolValueType(P.EXCEPTION_PACKET), ValueType(ValueKind.STATE, location=world),
                ValueType(ValueKind.STATE, location=ambient))),
        ), invoke_arguments=(input_world.id, input_ambient.id))

    resume_id = graph.cleanup_resumes[0].operation
    resume = operations[resume_id]
    operations[resume_id] = replace(resume, uses=tuple(
        replace(use, value=normal_pending.id) if use.id == graph.cleanup_resumes[0].pending else
        replace(use, value=normal_context.id) if use.id == graph.cleanup_resumes[0].context else use
        for use in resume.uses))
    resume_jump_id = graph.cleanup_resumes[0].continuation.operation
    resume_jump = operations[resume_jump_id]
    operations[resume_jump_id] = replace(resume_jump, uses=tuple(
        replace(use, value=normal_pending.id) if use.role is UseRole.PROTOCOL else use
        for use in resume_jump.uses))

    pack_id = OperationID("invoke.failed.pack")
    packet_use = _use("invoke.failed.packet.use", failed_packet.id)
    new_pending = ProtocolValue(ValueID("invoke.failed.new-pending"), region.id,
                                OperationResult(pack_id, 0), P.PENDING_COMPLETION)
    additions.append(new_pending)
    operations[pack_id] = Operation(pack_id, "pack this call's private Raise packet",
        (Behavior.CONTROL,), (packet_use,), (new_pending.id,), effects_complete=True)
    definition = PendingCompletionDefinition(new_pending.id, ControlPortID("shared.port.raise"), packet_use.id)

    failure_route_id = OperationID("invoke.failed.route")
    selector = _use("invoke.failed.route.selector", new_pending.id)
    forward_old = _use("invoke.failed.route.old", failed_pending.id)
    forward_world = _use("invoke.failed.route.world", failed_world.id, UseRole.STATE_CONTENT)
    forward_new = _use("invoke.failed.route.new", new_pending.id)
    forward_context = _use("invoke.failed.route.context", failed_context.id)
    forward_ambient = _use("invoke.failed.route.ambient", failed_ambient.id, UseRole.STATE_CONTENT)
    operations[failure_route_id] = Operation(failure_route_id, "route new Raise to active cleanup Replace",
        (Behavior.CONTROL,), (selector, forward_old, forward_world, forward_new,
                              forward_context, forward_ambient),
        terminator=CleanupRouteTerminator(selector.id, (CleanupRouteSuccessor(
            definition.port, replace_block, (forward_old.id, forward_world.id, forward_new.id,
                                              forward_context.id, forward_ambient.id)),)))

    replace_id = OperationID("invoke.cleanup.replace-action")
    old_use = _use("invoke.replace.old.use", replace_pending.id)
    new_use = _use("invoke.replace.new.use", replace_new.id)
    context_use = _use("invoke.replace.context.use", replace_context.id)
    world_use = _use("invoke.replace.world.use", replace_world.id, UseRole.STATE_CONTENT)
    ambient_use = _use("invoke.replace.ambient.use", replace_ambient.id, UseRole.STATE_CONTENT)
    world_after = StateVersionValue(ValueID("invoke.replace.world.after"), region.id,
                                    OperationResult(replace_id, 0), world)
    ambient_after = StateVersionValue(ValueID("invoke.replace.ambient.after"), region.id,
                                      OperationResult(replace_id, 1), ambient)
    additions.extend((world_after, ambient_after))
    operations[replace_id] = Operation(replace_id, "restore context and replace original transfer",
        (Behavior.CONTROL, Behavior.READ, Behavior.WRITE),
        (old_use, new_use, context_use, world_use, ambient_use),
        (world_after.id, ambient_after.id), (
            StateAccess(world, world_use.id, AccessMode.READ_WRITE, world_after.id, Footprint(FootprintKind.WHOLE)),
            StateAccess(ambient, ambient_use.id, AccessMode.READ_WRITE, ambient_after.id, Footprint(FootprintKind.WHOLE)),
        ), effects_complete=False)
    jump_id = OperationID("invoke.replace.to-route")
    jump_pending = _use("invoke.replace.jump.pending", replace_new.id)
    jump_world = _use("invoke.replace.jump.world", world_after.id, UseRole.STATE_CONTENT)
    jump_ambient = _use("invoke.replace.jump.ambient", ambient_after.id, UseRole.STATE_CONTENT)
    operations[jump_id] = Operation(jump_id, "post-pop handoff after Replace", (Behavior.CONTROL,),
        (jump_pending, jump_world, jump_ambient), terminator=Terminator(TerminatorKind.JUMP, (
            Successor(BlockID("shared.cleanup.post-pop-route"),
                       (jump_pending.id, jump_world.id, jump_ambient.id)),)))
    action = CleanupReplace(replace_id, scope, old_use.id, new_use.id,
                            context_use.id, ControlEdgeReference(jump_id, 0))

    blocks = tuple(replace(block, operations=tuple(identity for identity in block.operations
        if identity not in (resume_id, resume_jump_id))) if block.id == interface.entry else block
        for block in region.blocks)
    blocks += (
        Block(normal_block, (normal_pending.id, normal_world.id, normal_context.id, normal_ambient.id),
              (resume_id, resume_jump_id)),
        Block(failed_block, (failed_packet.id, failed_pending.id, failed_world.id,
                            failed_context.id, failed_ambient.id), (pack_id, failure_route_id)),
        Block(replace_block, (replace_pending.id, replace_world.id, replace_new.id,
                             replace_context.id, replace_ambient.id), (replace_id, jump_id)),
    )
    scopes = tuple(replace(row, blocks=(*row.blocks, normal_block, failed_block, replace_block))
                   if row.id == scope else row for row in graph.control_scopes)
    return replace(graph, regions=(replace(region, blocks=blocks),),
        values=(*values.values(), *additions), operations=tuple(operations.values()), control_scopes=scopes,
        pending_completions=(*graph.pending_completions, definition), cleanup_replacements=(action,))


def cleanup_invoke_may_diverge_graph():
    """A reachable cleanup loop can repeat forever without popping its stack.

    The other branch still reaches INVOKE and the two finite completion paths.
    A region input is tested, so a concrete input can keep the self edge active.
    No totality or runtime correspondence is inferred from this static graph.
    """
    graph = cleanup_invoke_graph()
    region = graph.regions[0]
    interface = graph.cleanup_interfaces[0]
    operations = {row.id: row for row in graph.operations}
    values = {row.id: row for row in graph.values}
    world = values[ValueID("shared.cleanup.world")].location
    ambient = graph.handled_context_domains[0].location
    header = BlockID("invoke.cleanup.loop")
    call = BlockID("invoke.cleanup.call")
    additions = []

    def arguments(label, block):
        result = (
            _protocol(label + ".pending", region.id, block, 0, P.PENDING_COMPLETION),
            _state(label + ".world", region.id, block, 1, world),
            _protocol(label + ".context", region.id, block, 2, P.SAVED_HANDLED_CONTEXT),
            _state(label + ".ambient", region.id, block, 3, ambient),
        )
        additions.extend(result)
        return result

    loop_args = arguments("invoke.loop", header)
    call_args = arguments("invoke.call", call)
    source_ids = (interface.pending_argument, ValueID("shared.cleanup.enter.world.after"),
                  graph.cleanup_enters[0].saved_context, ValueID("shared.cleanup.enter.ambient.after"))
    roles = (UseRole.PROTOCOL, UseRole.STATE_CONTENT, UseRole.PROTOCOL, UseRole.STATE_CONTENT)
    entry_uses = tuple(_use(f"invoke.loop.entry.{i}", value, role)
                       for i, (value, role) in enumerate(zip(source_ids, roles)))
    enter_loop_id = OperationID("invoke.loop.enter")
    operations[enter_loop_id] = Operation(enter_loop_id, "carry current anchors and state into loop",
        (Behavior.CONTROL,), entry_uses, terminator=Terminator(TerminatorKind.JUMP, (
            Successor(header, tuple(use.id for use in entry_uses)),)))
    condition = _use("invoke.loop.condition", ValueID("shared.condition"), UseRole.DATA)
    loop_uses = [condition]
    edges = []
    for label, target in (("repeat", header), ("finish", call)):
        actuals = tuple(_use(f"invoke.loop.{label}.{i}", value.id, role)
                        for i, (value, role) in enumerate(zip(loop_args, roles)))
        loop_uses.extend(actuals)
        edges.append(Successor(target, tuple(use.id for use in actuals)))
    branch_id = OperationID("invoke.loop.branch")
    operations[branch_id] = Operation(branch_id, "possibly nonterminating cleanup control loop",
        (Behavior.CONTROL,), tuple(loop_uses),
        terminator=Terminator(TerminatorKind.BRANCH, tuple(edges), condition=condition.id))
    mapping = dict(zip(source_ids, (value.id for value in call_args)))
    invoke_id = OperationID("shared.cleanup.write")
    invoke = operations[invoke_id]
    operations[invoke_id] = replace(invoke, uses=tuple(
        replace(use, value=mapping.get(use.value, use.value)) for use in invoke.uses))
    blocks = tuple(replace(block, operations=tuple(identity for identity in block.operations
        if identity != invoke_id) + (enter_loop_id,)) if block.id == interface.entry else block
        for block in region.blocks)
    blocks += (Block(header, tuple(value.id for value in loop_args), (branch_id,)),
               Block(call, tuple(value.id for value in call_args), (invoke_id,)))
    loop_scope = ControlScope(ControlScopeID("invoke.cleanup.loop.scope"), region.id,
        interface.scope, ControlScopeKind.LOOP, _source("may-diverge-loop", 8), (header,))
    scopes = tuple(replace(row, blocks=(*row.blocks, call)) if row.id == interface.scope else row
                   for row in graph.control_scopes) + (loop_scope,)
    return replace(graph, regions=(replace(region, blocks=blocks),), operations=tuple(operations.values()),
                   values=(*graph.values, *additions), control_scopes=scopes)


__all__ = ["cleanup_invoke_graph", "cleanup_invoke_may_diverge_graph"]
