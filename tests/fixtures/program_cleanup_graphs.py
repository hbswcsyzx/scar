"""Hand-authored C1 cleanup compositions.

These fixtures exercise typed control/state composition only.  Their source
spans do not witness Python ``finally`` execution or handled-context effects.
"""
from __future__ import annotations

from dataclasses import replace

from scar.ir.program.cleanup import (
    CleanupEnter, CleanupInterface, CleanupReplace, CleanupResume, CleanupRouteSuccessor,
    CleanupRouteTerminator, HandledContextDomain, HandledContextRead,
)
from scar.ir.program.control import (
    ControlPort, ControlScope, ControlScopeKind, ExceptionPacketDefinition,
    LanguageCompletionKind as K, PendingCompletionDefinition,
    PendingDispatchTerminator, PendingPayload, PendingSuccessor,
    ProtocolValueKind as P,
)
from scar.ir.program.ids import (
    BlockID, ControlPortID, ControlScopeID, LocationID, OperationID, RegionID,
    UseID, ValueID,
)
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, DataValue, ExitKind, ExitPort,
    Footprint, FootprintKind, LiteralOrigin, Operation, OperationResult,
    ProtocolValue, ReferenceValue,
    StateAccess, StateLocation, StateVersionValue, Successor, Terminator,
    TerminatorKind, Use, UseRole, ValueKind, ValueType,
)
from scar.ir.program.structured import ControlEdgeReference

from tests.fixtures.program_control_graphs import (
    _protocol, _source, _state, _use, packet_type, shared_pending_graph,
)


def resume_multistate_graph():
    """Return/Raise share an entry; Resume carries two state domains forward.

    The second state domain is an abstract handled-context cell.  Enter,
    unknown cleanup work and Resume all thread both domains, so a route cannot
    silently restore the entry world or drop the ambient context cell.
    """
    graph = shared_pending_graph()
    region = graph.regions[0]
    region_id = region.id
    world = graph.locations[0].id
    ambient = LocationID("shared.ambient-context")
    function = next(scope for scope in graph.control_scopes
                    if scope.kind is ControlScopeKind.FUNCTION)
    cleanup = next(scope for scope in graph.control_scopes
                   if scope.kind is ControlScopeKind.CLEANUP)
    protected_id = ControlScopeID("shared.protected")
    protected_blocks = (BlockID("shared.make_return"), BlockID("shared.make_raise"))
    cleanup_entry = BlockID("shared.cleanup")

    original_blocks = {block.id: block for block in region.blocks}
    ambient_args = {
        block.id: StateVersionValue(
            ValueID("shared.ambient.arg." + block.id.value), region_id,
            BlockArgument(block.id, len(block.arguments)), ambient)
        for block in region.blocks
    }

    # Add the new state port to every existing block and preserve it on each
    # original control edge.  Action outputs replace the source value later.
    blocks = []
    for block in region.blocks:
        blocks.append(replace(block, arguments=(*block.arguments, ambient_args[block.id].id)))

    values = [*graph.values, *ambient_args.values()]
    operations: list[Operation] = []
    op_by_id = {operation.id: operation for operation in graph.operations}
    entry_ambient_use_by_branch: dict[OperationID, tuple[Use, ...]] = {}

    def add_ambient_to_edges(operation: Operation, source: ValueID) -> Operation:
        term = operation.terminator
        if term is None or not getattr(term, "successors", ()):
            return operation
        uses = list(operation.uses)
        successors = []
        ambient_uses = []
        for index, edge in enumerate(term.successors):
            use = _use(f"shared.{operation.id.value}.ambient.{index}", source,
                       UseRole.STATE_CONTENT)
            uses.append(use)
            ambient_uses.append(use)
            successors.append(replace(edge, arguments=(*edge.arguments, use.id)))
        entry_ambient_use_by_branch[operation.id] = tuple(ambient_uses)
        return replace(operation, uses=tuple(uses),
                       terminator=replace(term, successors=tuple(successors)))

    for operation in graph.operations:
        if operation.id == OperationID("shared.dispatch"):
            continue  # Replaced by route → function-scope pending dispatch below.
        if operation.id in (OperationID("shared.branch"),
                            OperationID("shared.return.to.cleanup"),
                            OperationID("shared.raise.to.cleanup")):
            operation = add_ambient_to_edges(operation,
                ambient_args[next(block.id for block in region.blocks
                                  if operation.id in block.operations)].id)
            if operation.id in (OperationID("shared.return.to.cleanup"),
                                OperationID("shared.raise.to.cleanup")):
                port = (ControlPortID("shared.port.return")
                        if operation.id == OperationID("shared.return.to.cleanup")
                        else ControlPortID("shared.port.raise"))
                pending_selector = next(use for use in operation.uses
                    if use.id in (UseID("shared.return.to.cleanup.pending"),
                                  UseID("shared.raise.to.cleanup.pending")))
                state_uses = tuple(use for use in operation.uses
                                   if use.role is UseRole.STATE_CONTENT)
                pending_forward = _use(f"{operation.id.value}.route.pending",
                                       pending_selector.value, UseRole.PROTOCOL)
                route_uses = (*operation.uses, pending_forward)
                operation = replace(operation, uses=route_uses,
                    terminator=CleanupRouteTerminator(pending_selector.id, (
                        CleanupRouteSuccessor(port, cleanup_entry,
                            (pending_forward.id, *(use.id for use in state_uses))),
                    )))
        elif operation.id in (OperationID("shared.return.exit.op"),
                              OperationID("shared.raise.exit.op")):
            source_block = next(block.id for block in region.blocks
                                if operation.id in block.operations)
            ambient_use = _use(f"{operation.id.value}.ambient.exit",
                               ambient_args[source_block].id, UseRole.STATE_CONTENT)
            term = operation.terminator
            operation = replace(operation,
                uses=(*operation.uses, ambient_use),
                terminator=replace(term, values=(*term.values, ambient_use.id)))
        elif operation.id == OperationID("shared.cleanup.write"):
            # Enter first advances every domain.  The cleanup's incomplete
            # effect then advances every domain again, preserving unknown
            # callback/write effects instead of restoring stale entry state.
            before_world = ValueID("shared.cleanup.enter.world.after")
            before_ambient = ValueID("shared.cleanup.enter.ambient.after")
            world_use = next(use for use in operation.uses
                             if use.id == UseID("shared.cleanup.world.before"))
            world_use = replace(world_use, value=before_world)
            ambient_use = _use("shared.cleanup.ambient.before", before_ambient,
                               UseRole.STATE_CONTENT)
            world_after = next(value for value in operation.results
                               if value == ValueID("shared.cleanup.world.after"))
            ambient_after = StateVersionValue(
                ValueID("shared.cleanup.ambient.after"), region_id,
                OperationResult(operation.id, 1), ambient)
            values.append(ambient_after)
            accesses = tuple(
                replace(access, before=world_use.id,
                        footprint=Footprint(FootprintKind.WHOLE))
                if access.location == world else access
                for access in operation.accesses)
            accesses = (*accesses, StateAccess(
                ambient, ambient_use.id, AccessMode.READ_WRITE, ambient_after.id,
                Footprint(FootprintKind.WHOLE)))
            operation = replace(operation,
                uses=tuple(world_use if use.id == world_use.id else use
                           for use in operation.uses) + (ambient_use,),
                results=(world_after, ambient_after.id), accesses=accesses)
        operations.append(operation)

    # Entry is the first operation of the cleanup scope and installs the
    # incoming pending/context into fresh post-action state versions.
    pending_argument = ValueID("shared.cleanup.pending")
    world_argument = ValueID("shared.cleanup.world")
    ambient_argument = ambient_args[cleanup_entry].id
    enter_id = OperationID("shared.cleanup.enter")
    saved_context = ProtocolValue(
        ValueID("shared.cleanup.saved-context"), region_id,
        OperationResult(enter_id, 0), P.SAVED_HANDLED_CONTEXT)
    enter_world_after = StateVersionValue(
        ValueID("shared.cleanup.enter.world.after"), region_id,
        OperationResult(enter_id, 1), world)
    enter_ambient_after = StateVersionValue(
        ValueID("shared.cleanup.enter.ambient.after"), region_id,
        OperationResult(enter_id, 2), ambient)
    values.extend((saved_context, enter_world_after, enter_ambient_after))
    enter_pending_use = _use("shared.cleanup.enter.pending", pending_argument,
                             UseRole.PROTOCOL)
    enter_world_use = _use("shared.cleanup.enter.world.before", world_argument,
                           UseRole.STATE_CONTENT)
    enter_ambient_use = _use("shared.cleanup.enter.ambient.before", ambient_argument,
                             UseRole.STATE_CONTENT)
    enter = Operation(enter_id, "enter cleanup and save handled context",
        (Behavior.CONTROL, Behavior.READ, Behavior.WRITE),
        (enter_pending_use, enter_world_use, enter_ambient_use),
        (saved_context.id, enter_world_after.id, enter_ambient_after.id),
        (StateAccess(world, enter_world_use.id, AccessMode.READ_WRITE,
                     enter_world_after.id, Footprint(FootprintKind.WHOLE)),
         StateAccess(ambient, enter_ambient_use.id, AccessMode.READ_WRITE,
                     enter_ambient_after.id, Footprint(FootprintKind.WHOLE))), effects_complete=False)
    operations.append(enter)

    read_id = OperationID("shared.cleanup.handled-context-read")
    exception_result = ReferenceValue(
        ValueID("shared.cleanup.current-exception"), region_id,
        OperationResult(read_id, 0))
    values.append(exception_result)
    read_use = _use("shared.cleanup.handled-context.read", enter_ambient_after.id,
                    UseRole.STATE_CONTENT)
    read = Operation(read_id, "read abstract handled-context domain",
        (Behavior.CONTROL, Behavior.READ), (read_use,), (exception_result.id,),
        (StateAccess(ambient, read_use.id, AccessMode.READ, footprint=Footprint(FootprintKind.WHOLE)),), effects_complete=True)
    operations.append(read)

    # CleanupResume is adjacent to its JUMP.  The JUMP enters a parent-scope
    # route block; the route then picks the corresponding C0 port.
    resume_id = OperationID("shared.cleanup.resume")
    cleanup_write_ambient_after = ValueID("shared.cleanup.ambient.after")
    resume_world_after = StateVersionValue(
        ValueID("shared.cleanup.resume.world.after"), region_id,
        OperationResult(resume_id, 0), world)
    resume_ambient_after = StateVersionValue(
        ValueID("shared.cleanup.resume.ambient.after"), region_id,
        OperationResult(resume_id, 1), ambient)
    values.extend((resume_world_after, resume_ambient_after))
    resume_pending = _use("shared.cleanup.resume.pending", pending_argument,
                          UseRole.PROTOCOL)
    resume_context = _use("shared.cleanup.resume.context", saved_context.id,
                          UseRole.PROTOCOL)
    resume_world = _use("shared.cleanup.resume.world", ValueID("shared.cleanup.world.after"),
                        UseRole.STATE_CONTENT)
    resume_ambient = _use("shared.cleanup.resume.ambient", cleanup_write_ambient_after,
                          UseRole.STATE_CONTENT)
    resume = Operation(resume_id, "restore context and resume pending completion",
        (Behavior.CONTROL, Behavior.READ, Behavior.WRITE),
        (resume_pending, resume_context, resume_world, resume_ambient),
        (resume_world_after.id, resume_ambient_after.id),
        (StateAccess(world, resume_world.id, AccessMode.READ_WRITE,
                     resume_world_after.id, Footprint(FootprintKind.WHOLE)),
         StateAccess(ambient, resume_ambient.id, AccessMode.READ_WRITE,
                     resume_ambient_after.id, Footprint(FootprintKind.WHOLE))), effects_complete=False)
    operations.append(resume)

    resume_route = BlockID("shared.cleanup.post-pop-route")
    resume_jump_id = OperationID("shared.cleanup.resume.to-route")
    jump_pending = _use("shared.cleanup.resume.to-route.pending", pending_argument,
                        UseRole.PROTOCOL)
    jump_world = _use("shared.cleanup.resume.to-route.world", resume_world_after.id,
                      UseRole.STATE_CONTENT)
    jump_ambient = _use("shared.cleanup.resume.to-route.ambient", resume_ambient_after.id,
                        UseRole.STATE_CONTENT)
    resume_jump = Operation(resume_jump_id, "handoff after cleanup Resume",
        (Behavior.CONTROL,), (jump_pending, jump_world, jump_ambient),
        terminator=Terminator(TerminatorKind.JUMP, (Successor(resume_route,
            (jump_pending.id, jump_world.id, jump_ambient.id)),)))
    operations.append(resume_jump)

    # The route is a single post-pop corridor in the cleanup's lexical parent.
    route_pending = _protocol("shared.cleanup.route.pending", region_id, resume_route, 0,
                              P.PENDING_COMPLETION)
    route_world = _state("shared.cleanup.route.world", region_id, resume_route, 1, world)
    route_ambient = _state("shared.cleanup.route.ambient", region_id, resume_route, 2, ambient)
    dispatch_block = BlockID("shared.dispatch.block")
    dispatch_pending_value = _protocol("shared.dispatch.pending", region_id, dispatch_block, 0,
                                       P.PENDING_COMPLETION)
    dispatch_world_value = _state("shared.dispatch.world", region_id, dispatch_block, 1, world)
    dispatch_ambient_value = _state("shared.dispatch.ambient", region_id, dispatch_block, 2, ambient)
    values.extend((route_pending, route_world, route_ambient,
                   dispatch_pending_value, dispatch_world_value, dispatch_ambient_value))
    route_pending_use = _use("shared.cleanup.route.pending.selector", route_pending.id,
                             UseRole.PROTOCOL)
    route_uses = [route_pending_use]
    route_cases = []
    return_port = ControlPortID("shared.port.return")
    raise_port = ControlPortID("shared.port.raise")
    for label, port in (("return", return_port), ("raise", raise_port)):
        case_pending = _use(f"shared.cleanup.route.{label}.pending", route_pending.id,
                            UseRole.PROTOCOL)
        case_world = _use(f"shared.cleanup.route.{label}.world", route_world.id,
                          UseRole.STATE_CONTENT)
        case_ambient = _use(f"shared.cleanup.route.{label}.ambient", route_ambient.id,
                            UseRole.STATE_CONTENT)
        route_uses.extend((case_pending, case_world, case_ambient))
        route_cases.append(CleanupRouteSuccessor(port, dispatch_block,
            (case_pending.id, case_world.id, case_ambient.id)))
    route_id = OperationID("shared.cleanup.route")
    route = Operation(route_id, "recompute remaining completion route",
        (Behavior.CONTROL,), tuple(route_uses),
        terminator=CleanupRouteTerminator(route_pending_use.id, tuple(route_cases)))
    operations.append(route)

    dispatch_pending_use = _use("shared.dispatch.pending.selector", dispatch_pending_value.id,
                                 UseRole.PROTOCOL)
    dispatch_return_world = _use("shared.dispatch.return.world", dispatch_world_value.id,
                                 UseRole.STATE_CONTENT)
    dispatch_return_ambient = _use("shared.dispatch.return.ambient", dispatch_ambient_value.id,
                                   UseRole.STATE_CONTENT)
    dispatch_raise_world = _use("shared.dispatch.raise.world", dispatch_world_value.id,
                                UseRole.STATE_CONTENT)
    dispatch_raise_ambient = _use("shared.dispatch.raise.ambient", dispatch_ambient_value.id,
                                  UseRole.STATE_CONTENT)
    dispatch = Operation(OperationID("shared.dispatch"), "pending completion dispatch",
        (Behavior.CONTROL,), (dispatch_pending_use, dispatch_return_world,
        dispatch_return_ambient, dispatch_raise_world, dispatch_raise_ambient),
        terminator=PendingDispatchTerminator(dispatch_pending_use.id, (
            PendingSuccessor(return_port, BlockID("shared.return_exit"), (
                PendingPayload(), dispatch_return_world.id, dispatch_return_ambient.id)),
            PendingSuccessor(raise_port, BlockID("shared.raise_exit"), (
                PendingPayload(), dispatch_raise_world.id, dispatch_raise_ambient.id)),
        )))
    operations.append(dispatch)

    # Finish building the cleanup block and newly introduced dispatch corridor.
    original_cleanup_block = next(block for block in blocks if block.id == cleanup_entry)
    cleanup_block = replace(original_cleanup_block,
        operations=(enter.id, read.id, OperationID("shared.cleanup.write"),
                    resume.id, resume_jump.id))
    blocks = [cleanup_block if block.id == cleanup_entry else block for block in blocks]
    blocks.extend((
        Block(resume_route, (route_pending.id, route_world.id, route_ambient.id),
              (route.id,)),
        Block(dispatch_block, (dispatch_pending_value.id, dispatch_world_value.id,
                               dispatch_ambient_value.id), (dispatch.id,)),
    ))

    # Exit shims already received the second current-state argument above; the
    # payload projection remains a Reference/ExceptionPacket and state separate.
    return_exit = BlockID("shared.return_exit")
    raise_exit = BlockID("shared.raise_exit")
    return_exit_ambient = ambient_args[return_exit]
    raise_exit_ambient = ambient_args[raise_exit]
    new_blocks = blocks
    # Replace the original lexical partition with one protected sibling and
    # the cleanup interface.  The exit and dispatch shims remain function-owned.
    root_blocks = tuple(block.id for block in new_blocks
                        if block.id not in protected_blocks and block.id != cleanup_entry)
    protected_scope = ControlScope(protected_id, region_id, function.id,
        ControlScopeKind.BLOCK, _source("protected", 2), protected_blocks)
    cleanup_scope = replace(cleanup, blocks=(cleanup_entry,))
    function_scope = replace(function, blocks=root_blocks)
    scopes = tuple(function_scope if scope.id == function.id else
                   cleanup_scope if scope.id == cleanup.id else scope
                   for scope in graph.control_scopes)
    scopes = (*scopes, protected_scope)

    new_exits = []
    for exit_port in region.exits:
        new_exits.append(replace(exit_port,
            types=(*exit_port.types, ValueType(ValueKind.STATE, location=ambient))))
    region = replace(region, blocks=tuple(new_blocks), exits=tuple(new_exits))
    graph = replace(graph, regions=(region,), operations=tuple(operations), values=tuple(values),
        locations=(*graph.locations, StateLocation(ambient, "ambient handled-exception context")),
        control_scopes=scopes,
        handled_context_domains=(HandledContextDomain(region_id, ambient),),
        cleanup_interfaces=(CleanupInterface(cleanup.id, protected_id, cleanup_entry,
                                               ValueID("shared.cleanup.pending")),),
        cleanup_enters=(CleanupEnter(enter.id, cleanup.id, enter_pending_use.id,
                                     saved_context.id),),
        cleanup_resumes=(CleanupResume(resume.id, cleanup.id, resume_pending.id,
            resume_context.id, ControlEdgeReference(resume_jump.id, 0)),),
        handled_context_reads=(HandledContextRead(read.id, exception_result.id),))
    return graph


def cleanup_return_resume_graph():
    """Public name emphasizing that this is a Return/Raise Resume fixture."""
    return resume_multistate_graph()


def nested_cleanup_fallthrough_and_replace_graph():
    """An inner Fallthrough resumes outer cleanup; inner Return replaces both.

    The outer cleanup's original token is a Return or Raise.  The inner cleanup
    normally forwards its local Fallthrough into the still active outer
    finalbody.  Its other CFG path constructs a new Return, replaces the inner
    Fallthrough, then routes to Replace the outer token before final dispatch.
    """
    graph = resume_multistate_graph()
    region = graph.regions[0]
    region_id = region.id
    world = graph.locations[0].id
    ambient = graph.locations[1].id
    function = next(scope for scope in graph.control_scopes
                    if scope.kind is ControlScopeKind.FUNCTION)
    outer_cleanup = next(scope for scope in graph.control_scopes
                         if scope.kind is ControlScopeKind.CLEANUP)
    outer_protected = next(scope for scope in graph.control_scopes
                           if scope.kind is ControlScopeKind.BLOCK
                           and scope.parent == function.id)

    outer_entry = BlockID("shared.cleanup")
    outer_pending_entry = ValueID("shared.cleanup.pending")
    outer_context_value = ValueID("shared.cleanup.saved-context")
    outer_world_after_work = ValueID("shared.cleanup.world.after")
    outer_ambient_after_work = ValueID("shared.cleanup.ambient.after")
    old_outer_resume = OperationID("shared.cleanup.resume")
    old_outer_handoff = OperationID("shared.cleanup.resume.to-route")

    inner_protected_id = ControlScopeID("nested.inner.protected")
    inner_cleanup_id = ControlScopeID("nested.inner.cleanup")
    inner_protected_block = BlockID("nested.inner.protected.entry")
    inner_entry = BlockID("nested.inner.cleanup.entry")
    inner_resume_block = BlockID("nested.inner.cleanup.resume")
    inner_make_return_block = BlockID("nested.inner.cleanup.make-return")
    inner_replace_block = BlockID("nested.inner.cleanup.replace")
    inner_route_block = BlockID("nested.inner.cleanup.post-pop-route")
    inner_fallthrough_dispatch_block = BlockID("nested.inner.fallthrough-dispatch")
    outer_resume_block = BlockID("nested.outer.cleanup.resume")
    outer_replace_block = BlockID("nested.outer.cleanup.replace")

    values = [value for value in graph.values
              if value.id not in (ValueID("shared.cleanup.resume.world.after"),
                                  ValueID("shared.cleanup.resume.ambient.after"))]
    operations = [operation for operation in graph.operations
                  if operation.id not in (old_outer_resume, old_outer_handoff)]
    blocks = [block for block in region.blocks
              if block.id != outer_entry]
    outer_entry_record = next(block for block in region.blocks if block.id == outer_entry)

    # After its own entry/write, the outer cleanup activates a nested protected
    # body.  The old outer pending and this activation's saved context travel
    # through the inner cleanup as separate, typed operands.
    outer_to_inner_id = OperationID("nested.outer.cleanup.to-inner")
    outer_to_inner_uses = (
        _use("nested.outer.to-inner.pending", outer_pending_entry, UseRole.PROTOCOL),
        _use("nested.outer.to-inner.context", outer_context_value, UseRole.PROTOCOL),
        _use("nested.outer.to-inner.world", outer_world_after_work, UseRole.STATE_CONTENT),
        _use("nested.outer.to-inner.ambient", outer_ambient_after_work, UseRole.STATE_CONTENT),
    )
    outer_to_inner = Operation(outer_to_inner_id, "enter nested protected region",
        (Behavior.CONTROL,), outer_to_inner_uses,
        terminator=Terminator(TerminatorKind.JUMP, (Successor(inner_protected_block,
            tuple(use.id for use in outer_to_inner_uses)),)))
    operations.append(outer_to_inner)
    blocks.append(replace(outer_entry_record,
        operations=(*outer_entry_record.operations[:3], outer_to_inner.id)))

    # Inner protected body constructs a Fallthrough token and enters its own
    # cleanup while preserving the outer activation's distinct anchors.
    inner_outer_pending = _protocol("nested.inner.protected.outer-pending", region_id,
                                    inner_protected_block, 0, P.PENDING_COMPLETION)
    inner_outer_context = _protocol("nested.inner.protected.outer-context", region_id,
                                    inner_protected_block, 1, P.SAVED_HANDLED_CONTEXT)
    inner_protected_world = _state("nested.inner.protected.world", region_id,
                                   inner_protected_block, 2, world)
    inner_protected_ambient = _state("nested.inner.protected.ambient", region_id,
                                     inner_protected_block, 3, ambient)
    values.extend((inner_outer_pending, inner_outer_context,
                   inner_protected_world, inner_protected_ambient))
    fallthrough_port = ControlPortID("nested.inner.port.fallthrough")
    fallthrough_pending_id = OperationID("nested.inner.make-fallthrough")
    fallthrough_pending = ProtocolValue(ValueID("nested.inner.pending.fallthrough"), region_id,
        OperationResult(fallthrough_pending_id, 0), P.PENDING_COMPLETION)
    values.append(fallthrough_pending)
    fallthrough_pack = Operation(fallthrough_pending_id, "construct inner fallthrough",
        (Behavior.CONTROL,), results=(fallthrough_pending.id,), effects_complete=True)
    operations.append(fallthrough_pack)

    inner_pending_entry = _protocol("nested.inner.cleanup.pending", region_id, inner_entry, 0,
                                    P.PENDING_COMPLETION)
    inner_outer_pending_entry = _protocol("nested.inner.cleanup.outer-pending", region_id,
                                          inner_entry, 1, P.PENDING_COMPLETION)
    inner_outer_context_entry = _protocol("nested.inner.cleanup.outer-context", region_id,
                                          inner_entry, 2, P.SAVED_HANDLED_CONTEXT)
    inner_world_entry = _state("nested.inner.cleanup.world", region_id, inner_entry, 3, world)
    inner_ambient_entry = _state("nested.inner.cleanup.ambient", region_id, inner_entry, 4, ambient)
    values.extend((inner_pending_entry, inner_outer_pending_entry,
                   inner_outer_context_entry, inner_world_entry, inner_ambient_entry))

    into_inner_id = OperationID("nested.inner.protected.to-cleanup")
    into_inner_selector = _use("nested.inner.to-cleanup.selector", fallthrough_pending.id,
                               UseRole.PROTOCOL)
    into_inner_case = (
        _use("nested.inner.to-cleanup.pending", fallthrough_pending.id, UseRole.PROTOCOL),
        _use("nested.inner.to-cleanup.outer-pending", inner_outer_pending.id, UseRole.PROTOCOL),
        _use("nested.inner.to-cleanup.outer-context", inner_outer_context.id, UseRole.PROTOCOL),
        _use("nested.inner.to-cleanup.world", inner_protected_world.id, UseRole.STATE_CONTENT),
        _use("nested.inner.to-cleanup.ambient", inner_protected_ambient.id, UseRole.STATE_CONTENT),
    )
    into_inner = Operation(into_inner_id, "route to inner cleanup entry",
        (Behavior.CONTROL,), (into_inner_selector, *into_inner_case),
        terminator=CleanupRouteTerminator(into_inner_selector.id, (
            CleanupRouteSuccessor(fallthrough_port, inner_entry,
                                  tuple(use.id for use in into_inner_case)),
        )))
    operations.append(into_inner)
    blocks.append(Block(inner_protected_block,
        (inner_outer_pending.id, inner_outer_context.id,
         inner_protected_world.id, inner_protected_ambient.id),
        (fallthrough_pack.id, into_inner.id)))

    # The inner Enter gets its own saved context; the outer saved context is
    # passed as an independent ordinary protocol value for outer Resume/Replace.
    inner_enter_id = OperationID("nested.inner.enter")
    inner_saved_context = ProtocolValue(ValueID("nested.inner.saved-context"), region_id,
        OperationResult(inner_enter_id, 0), P.SAVED_HANDLED_CONTEXT)
    inner_enter_world_after = StateVersionValue(ValueID("nested.inner.enter.world.after"),
        region_id, OperationResult(inner_enter_id, 1), world)
    inner_enter_ambient_after = StateVersionValue(ValueID("nested.inner.enter.ambient.after"),
        region_id, OperationResult(inner_enter_id, 2), ambient)
    values.extend((inner_saved_context, inner_enter_world_after, inner_enter_ambient_after))
    ie_pending_use = _use("nested.inner.enter.pending", inner_pending_entry.id, UseRole.PROTOCOL)
    ie_world_use = _use("nested.inner.enter.world.before", inner_world_entry.id,
                        UseRole.STATE_CONTENT)
    ie_ambient_use = _use("nested.inner.enter.ambient.before", inner_ambient_entry.id,
                          UseRole.STATE_CONTENT)
    inner_enter = Operation(inner_enter_id, "enter inner cleanup",
        (Behavior.CONTROL, Behavior.READ, Behavior.WRITE),
        (ie_pending_use, ie_world_use, ie_ambient_use),
        (inner_saved_context.id, inner_enter_world_after.id, inner_enter_ambient_after.id),
        (StateAccess(world, ie_world_use.id, AccessMode.READ_WRITE,
                     inner_enter_world_after.id, Footprint(FootprintKind.WHOLE)),
         StateAccess(ambient, ie_ambient_use.id, AccessMode.READ_WRITE,
                     inner_enter_ambient_after.id, Footprint(FootprintKind.WHOLE))),
        effects_complete=False)
    operations.append(inner_enter)

    # The bool is intentionally just a structural branch condition.  Both CFG
    # edges remain in the conservative declared graph even though its literal
    # is False; no path pruning or source truth is claimed.
    cleanup_condition = DataValue(ValueID("nested.inner.cleanup.choice"), region_id,
                                  LiteralOrigin(False), "builtins.bool")
    values.append(cleanup_condition)
    inner_resume_args = (
        _protocol("nested.inner.resume.pending", region_id, inner_resume_block, 0,
                  P.PENDING_COMPLETION),
        _protocol("nested.inner.resume.outer-pending", region_id, inner_resume_block, 1,
                  P.PENDING_COMPLETION),
        _protocol("nested.inner.resume.outer-context", region_id, inner_resume_block, 2,
                  P.SAVED_HANDLED_CONTEXT),
        _protocol("nested.inner.resume.context", region_id, inner_resume_block, 3,
                  P.SAVED_HANDLED_CONTEXT),
        _state("nested.inner.resume.world", region_id, inner_resume_block, 4, world),
        _state("nested.inner.resume.ambient", region_id, inner_resume_block, 5, ambient),
    )
    inner_make_return_args = (
        _protocol("nested.inner.make-return.saved-pending", region_id, inner_make_return_block, 0,
                  P.PENDING_COMPLETION),
        _protocol("nested.inner.make-return.outer-pending", region_id, inner_make_return_block, 1,
                  P.PENDING_COMPLETION),
        _protocol("nested.inner.make-return.outer-context", region_id, inner_make_return_block, 2,
                  P.SAVED_HANDLED_CONTEXT),
        _protocol("nested.inner.make-return.context", region_id, inner_make_return_block, 3,
                  P.SAVED_HANDLED_CONTEXT),
        _state("nested.inner.make-return.world", region_id, inner_make_return_block, 4, world),
        _state("nested.inner.make-return.ambient", region_id, inner_make_return_block, 5, ambient),
    )
    values.extend((*inner_resume_args, *inner_make_return_args))
    choice_use = _use("nested.inner.cleanup.choice", cleanup_condition.id, UseRole.DATA)
    branch_uses = [choice_use]
    branch_edges = []
    for label, target, forwarded in (
        ("resume", inner_resume_block, (inner_pending_entry.id,
         inner_outer_pending_entry.id, inner_outer_context_entry.id,
         inner_saved_context.id, inner_enter_world_after.id, inner_enter_ambient_after.id)),
        ("replace", inner_make_return_block, (inner_pending_entry.id,
         inner_outer_pending_entry.id, inner_outer_context_entry.id,
         inner_saved_context.id, inner_enter_world_after.id, inner_enter_ambient_after.id)),
    ):
        case_uses = tuple(_use(f"nested.inner.branch.{label}.{i}", value,
            UseRole.STATE_CONTENT if i >= 4 else UseRole.PROTOCOL)
            for i, value in enumerate(forwarded))
        branch_uses.extend(case_uses)
        branch_edges.append(Successor(target, tuple(use.id for use in case_uses)))
    inner_branch_id = OperationID("nested.inner.cleanup.branch")
    inner_branch = Operation(inner_branch_id, "choose inner Resume or replacement",
        (Behavior.CONTROL,), tuple(branch_uses),
        terminator=Terminator(TerminatorKind.BRANCH, tuple(branch_edges),
                              condition=choice_use.id))
    operations.append(inner_branch)

    # Inner Resume action and its exact post-pop route handoff.
    inner_resume_world_after = StateVersionValue(ValueID("nested.inner.resume.world.after"),
        region_id, OperationResult(OperationID("nested.inner.resume"), 0), world)
    inner_resume_ambient_after = StateVersionValue(
        ValueID("nested.inner.resume.ambient.after"), region_id,
        OperationResult(OperationID("nested.inner.resume"), 1), ambient)
    values.extend((inner_resume_world_after, inner_resume_ambient_after))
    ir_pending_use = _use("nested.inner.resume.pending.use", inner_resume_args[0].id,
                         UseRole.PROTOCOL)
    ir_context_use = _use("nested.inner.resume.context.use", inner_resume_args[3].id,
                          UseRole.PROTOCOL)
    ir_world_use = _use("nested.inner.resume.world.use", inner_resume_args[4].id,
                        UseRole.STATE_CONTENT)
    ir_ambient_use = _use("nested.inner.resume.ambient.use", inner_resume_args[5].id,
                          UseRole.STATE_CONTENT)
    inner_resume_op = Operation(OperationID("nested.inner.resume"), "resume inner fallthrough",
        (Behavior.CONTROL, Behavior.READ, Behavior.WRITE),
        (ir_pending_use, ir_context_use, ir_world_use, ir_ambient_use),
        (inner_resume_world_after.id, inner_resume_ambient_after.id),
        (StateAccess(world, ir_world_use.id, AccessMode.READ_WRITE,
                     inner_resume_world_after.id, Footprint(FootprintKind.WHOLE)),
         StateAccess(ambient, ir_ambient_use.id, AccessMode.READ_WRITE,
                     inner_resume_ambient_after.id, Footprint(FootprintKind.WHOLE))),
        effects_complete=False)
    operations.append(inner_resume_op)

    # Fresh inner Return is created during this cleanup activation and the
    # first op in its replacement block consumes original/new/context distinctly.
    replacement_ref = ReferenceValue(ValueID("nested.inner.return.none"), region_id,
        LiteralOrigin(None), referent_identity=None, targets=(), selector=Footprint())
    values.append(replacement_ref)
    make_new_return_id = OperationID("nested.inner.make-return")
    replacement_ref_use = _use("nested.inner.new-return.payload", replacement_ref.id,
                               UseRole.REFERENCE)
    inner_replacement = ProtocolValue(ValueID("nested.inner.pending.return"), region_id,
        OperationResult(make_new_return_id, 0), P.PENDING_COMPLETION)
    values.append(inner_replacement)
    make_new_return = Operation(make_new_return_id, "construct new Return in inner cleanup",
        (Behavior.CONTROL,), (replacement_ref_use,), (inner_replacement.id,),
        effects_complete=True)
    operations.append(make_new_return)
    inner_replace_args = (
        _protocol("nested.inner.replace.saved-pending", region_id, inner_replace_block, 0,
                  P.PENDING_COMPLETION),
        _protocol("nested.inner.replace.outer-pending", region_id, inner_replace_block, 1,
                  P.PENDING_COMPLETION),
        _protocol("nested.inner.replace.outer-context", region_id, inner_replace_block, 2,
                  P.SAVED_HANDLED_CONTEXT),
        _protocol("nested.inner.replace.context", region_id, inner_replace_block, 3,
                  P.SAVED_HANDLED_CONTEXT),
        _protocol("nested.inner.replace.new-pending", region_id, inner_replace_block, 4,
                  P.PENDING_COMPLETION),
        _state("nested.inner.replace.world", region_id, inner_replace_block, 5, world),
        _state("nested.inner.replace.ambient", region_id, inner_replace_block, 6, ambient),
    )
    values.extend(inner_replace_args)
    new_return_to_replace_id = OperationID("nested.inner.new-return.to-replace")
    new_return_to_replace_uses = (
        _use("nested.inner.new-return.old-pending", inner_make_return_args[0].id,
             UseRole.PROTOCOL),
        _use("nested.inner.new-return.outer-pending", inner_make_return_args[1].id,
             UseRole.PROTOCOL),
        _use("nested.inner.new-return.outer-context", inner_make_return_args[2].id,
             UseRole.PROTOCOL),
        _use("nested.inner.new-return.inner-context", inner_make_return_args[3].id,
             UseRole.PROTOCOL),
        _use("nested.inner.new-return.new-pending", inner_replacement.id,
             UseRole.PROTOCOL),
        _use("nested.inner.new-return.world", inner_make_return_args[4].id,
             UseRole.STATE_CONTENT),
        _use("nested.inner.new-return.ambient", inner_make_return_args[5].id,
             UseRole.STATE_CONTENT),
    )
    new_return_to_replace = Operation(new_return_to_replace_id,
        "forward fresh pending to inner Replace", (Behavior.CONTROL,),
        new_return_to_replace_uses,
        terminator=Terminator(TerminatorKind.JUMP, (Successor(inner_replace_block,
            tuple(use.id for use in new_return_to_replace_uses)),)))
    operations.append(new_return_to_replace)
    inner_replace_world_after = StateVersionValue(ValueID("nested.inner.replace.world.after"),
        region_id, OperationResult(OperationID("nested.inner.replace"), 0), world)
    inner_replace_ambient_after = StateVersionValue(
        ValueID("nested.inner.replace.ambient.after"), region_id,
        OperationResult(OperationID("nested.inner.replace"), 1), ambient)
    values.extend((inner_replace_world_after, inner_replace_ambient_after))
    irp_saved = _use("nested.inner.replace.saved.use", inner_replace_args[0].id, UseRole.PROTOCOL)
    irp_new = _use("nested.inner.replace.new.use", inner_replace_args[4].id, UseRole.PROTOCOL)
    irp_context = _use("nested.inner.replace.context.use", inner_replace_args[3].id, UseRole.PROTOCOL)
    irp_world = _use("nested.inner.replace.world.use", inner_replace_args[5].id, UseRole.STATE_CONTENT)
    irp_ambient = _use("nested.inner.replace.ambient.use", inner_replace_args[6].id, UseRole.STATE_CONTENT)
    inner_replace_op = Operation(OperationID("nested.inner.replace"), "replace inner pending",
        (Behavior.CONTROL, Behavior.READ, Behavior.WRITE),
        (irp_saved, irp_new, irp_context, irp_world, irp_ambient),
        (inner_replace_world_after.id, inner_replace_ambient_after.id),
        (StateAccess(world, irp_world.id, AccessMode.READ_WRITE,
                     inner_replace_world_after.id, Footprint(FootprintKind.WHOLE)),
         StateAccess(ambient, irp_ambient.id, AccessMode.READ_WRITE,
                     inner_replace_ambient_after.id, Footprint(FootprintKind.WHOLE))),
        effects_complete=False)
    operations.append(inner_replace_op)

    # Both inner action exits go through one parent-scope selector.  Its
    # Fallthrough case keeps the outer token/context; Return replaces outer.
    inner_route_pending = _protocol("nested.inner.route.pending", region_id, inner_route_block, 0,
                                    P.PENDING_COMPLETION)
    inner_route_outer_pending = _protocol("nested.inner.route.outer-pending", region_id,
                                          inner_route_block, 1, P.PENDING_COMPLETION)
    inner_route_outer_context = _protocol("nested.inner.route.outer-context", region_id,
                                          inner_route_block, 2, P.SAVED_HANDLED_CONTEXT)
    inner_route_world = _state("nested.inner.route.world", region_id, inner_route_block, 3, world)
    inner_route_ambient = _state("nested.inner.route.ambient", region_id, inner_route_block, 4, ambient)
    values.extend((inner_route_pending, inner_route_outer_pending, inner_route_outer_context,
                   inner_route_world, inner_route_ambient))

    outer_resume_args = (
        _protocol("nested.outer.resume.pending", region_id, outer_resume_block, 0,
                  P.PENDING_COMPLETION),
        _protocol("nested.outer.resume.context", region_id, outer_resume_block, 1,
                  P.SAVED_HANDLED_CONTEXT),
        _state("nested.outer.resume.world", region_id, outer_resume_block, 2, world),
        _state("nested.outer.resume.ambient", region_id, outer_resume_block, 3, ambient),
    )
    outer_replace_args = (
        _protocol("nested.outer.replace.new-pending", region_id, outer_replace_block, 0,
                  P.PENDING_COMPLETION),
        _protocol("nested.outer.replace.saved-pending", region_id, outer_replace_block, 1,
                  P.PENDING_COMPLETION),
        _protocol("nested.outer.replace.context", region_id, outer_replace_block, 2,
                  P.SAVED_HANDLED_CONTEXT),
        _state("nested.outer.replace.world", region_id, outer_replace_block, 3, world),
        _state("nested.outer.replace.ambient", region_id, outer_replace_block, 4, ambient),
    )
    values.extend((*outer_resume_args, *outer_replace_args))

    # The inner Fallthrough route has completed all inner cleanup obligations.
    # It therefore lands in a C0 dispatch-only block. C0 then resumes the still
    # active outer cleanup at its local continuation.
    fallthrough_dispatch_args = (
        _protocol("nested.inner.fallthrough-dispatch.pending", region_id,
                  inner_fallthrough_dispatch_block, 0, P.PENDING_COMPLETION),
        _protocol("nested.inner.fallthrough-dispatch.outer-pending", region_id,
                  inner_fallthrough_dispatch_block, 1, P.PENDING_COMPLETION),
        _protocol("nested.inner.fallthrough-dispatch.outer-context", region_id,
                  inner_fallthrough_dispatch_block, 2, P.SAVED_HANDLED_CONTEXT),
        _state("nested.inner.fallthrough-dispatch.world", region_id,
               inner_fallthrough_dispatch_block, 3, world),
        _state("nested.inner.fallthrough-dispatch.ambient", region_id,
               inner_fallthrough_dispatch_block, 4, ambient),
    )
    values.extend(fallthrough_dispatch_args)
    fallthrough_dispatch_uses = (
        _use("nested.inner.fallthrough-dispatch.selector", fallthrough_dispatch_args[0].id,
             UseRole.PROTOCOL),
        _use("nested.inner.fallthrough-dispatch.outer-pending", fallthrough_dispatch_args[1].id,
             UseRole.PROTOCOL),
        _use("nested.inner.fallthrough-dispatch.outer-context", fallthrough_dispatch_args[2].id,
             UseRole.PROTOCOL),
        _use("nested.inner.fallthrough-dispatch.world", fallthrough_dispatch_args[3].id,
             UseRole.STATE_CONTENT),
        _use("nested.inner.fallthrough-dispatch.ambient", fallthrough_dispatch_args[4].id,
             UseRole.STATE_CONTENT),
    )
    fallthrough_dispatch_id = OperationID("nested.inner.fallthrough.dispatch")
    fallthrough_dispatch = Operation(fallthrough_dispatch_id,
        "dispatch inner fallthrough to outer cleanup continuation",
        (Behavior.CONTROL,), fallthrough_dispatch_uses,
        terminator=PendingDispatchTerminator(fallthrough_dispatch_uses[0].id, (
            PendingSuccessor(fallthrough_port, outer_resume_block,
                tuple(use.id for use in fallthrough_dispatch_uses[1:])),
        )))
    operations.append(fallthrough_dispatch)

    inner_resume_jump_id = OperationID("nested.inner.resume.to-route")
    inner_resume_jump_uses = (
        _use("nested.inner.resume.to-route.pending", inner_resume_args[0].id, UseRole.PROTOCOL),
        _use("nested.inner.resume.to-route.outer-pending", inner_resume_args[1].id, UseRole.PROTOCOL),
        _use("nested.inner.resume.to-route.outer-context", inner_resume_args[2].id, UseRole.PROTOCOL),
        _use("nested.inner.resume.to-route.world", inner_resume_world_after.id, UseRole.STATE_CONTENT),
        _use("nested.inner.resume.to-route.ambient", inner_resume_ambient_after.id, UseRole.STATE_CONTENT),
    )
    inner_resume_jump = Operation(inner_resume_jump_id, "handoff after inner Resume",
        (Behavior.CONTROL,), inner_resume_jump_uses,
        terminator=Terminator(TerminatorKind.JUMP, (Successor(inner_route_block,
            tuple(use.id for use in inner_resume_jump_uses)),)))
    operations.append(inner_resume_jump)
    inner_replace_jump_id = OperationID("nested.inner.replace.to-route")
    inner_replace_jump_uses = (
        _use("nested.inner.replace.to-route.pending", inner_replace_args[4].id, UseRole.PROTOCOL),
        _use("nested.inner.replace.to-route.outer-pending", inner_replace_args[1].id, UseRole.PROTOCOL),
        _use("nested.inner.replace.to-route.outer-context", inner_replace_args[2].id, UseRole.PROTOCOL),
        _use("nested.inner.replace.to-route.world", inner_replace_world_after.id, UseRole.STATE_CONTENT),
        _use("nested.inner.replace.to-route.ambient", inner_replace_ambient_after.id, UseRole.STATE_CONTENT),
    )
    inner_replace_jump = Operation(inner_replace_jump_id, "handoff after inner Replace",
        (Behavior.CONTROL,), inner_replace_jump_uses,
        terminator=Terminator(TerminatorKind.JUMP, (Successor(inner_route_block,
            tuple(use.id for use in inner_replace_jump_uses)),)))
    operations.append(inner_replace_jump)

    inner_route_selector = _use("nested.inner.route.selector", inner_route_pending.id,
                                UseRole.PROTOCOL)
    inner_route_uses = [inner_route_selector]
    inner_route_successors = []
    for label, port, target in (
        ("fallthrough", fallthrough_port, inner_fallthrough_dispatch_block),
        ("replace-return", ControlPortID("shared.port.return"), outer_replace_block),
    ):
        case_uses = (
            _use(f"nested.inner.route.{label}.pending", inner_route_pending.id,
                 UseRole.PROTOCOL),
            _use(f"nested.inner.route.{label}.outer-pending", inner_route_outer_pending.id,
                 UseRole.PROTOCOL),
            _use(f"nested.inner.route.{label}.outer-context", inner_route_outer_context.id,
                 UseRole.PROTOCOL),
            _use(f"nested.inner.route.{label}.world", inner_route_world.id,
                 UseRole.STATE_CONTENT),
            _use(f"nested.inner.route.{label}.ambient", inner_route_ambient.id,
                 UseRole.STATE_CONTENT),
        )
        inner_route_uses.extend(case_uses)
        inner_route_successors.append(CleanupRouteSuccessor(
            port, target, tuple(use.id for use in case_uses)))
    inner_route_id = OperationID("nested.inner.route")
    inner_route_op = Operation(inner_route_id, "route inner completion after pop",
        (Behavior.CONTROL,), tuple(inner_route_uses),
        terminator=CleanupRouteTerminator(inner_route_selector.id,
                                          tuple(inner_route_successors)))
    operations.append(inner_route_op)

    outer_resume_world_after = StateVersionValue(ValueID("nested.outer.resume.world.after"),
        region_id, OperationResult(OperationID("nested.outer.resume"), 0), world)
    outer_resume_ambient_after = StateVersionValue(
        ValueID("nested.outer.resume.ambient.after"), region_id,
        OperationResult(OperationID("nested.outer.resume"), 1), ambient)
    outer_replace_world_after = StateVersionValue(ValueID("nested.outer.replace.world.after"),
        region_id, OperationResult(OperationID("nested.outer.replace"), 0), world)
    outer_replace_ambient_after = StateVersionValue(
        ValueID("nested.outer.replace.ambient.after"), region_id,
        OperationResult(OperationID("nested.outer.replace"), 1), ambient)
    values.extend((outer_resume_world_after, outer_resume_ambient_after,
                   outer_replace_world_after, outer_replace_ambient_after))

    or_pending = _use("nested.outer.resume.pending.use", outer_resume_args[0].id,
                      UseRole.PROTOCOL)
    or_context = _use("nested.outer.resume.context.use", outer_resume_args[1].id,
                      UseRole.PROTOCOL)
    or_world = _use("nested.outer.resume.world.use", outer_resume_args[2].id,
                    UseRole.STATE_CONTENT)
    or_ambient = _use("nested.outer.resume.ambient.use", outer_resume_args[3].id,
                      UseRole.STATE_CONTENT)
    outer_resume_op = Operation(OperationID("nested.outer.resume"), "resume original outer token",
        (Behavior.CONTROL, Behavior.READ, Behavior.WRITE),
        (or_pending, or_context, or_world, or_ambient),
        (outer_resume_world_after.id, outer_resume_ambient_after.id),
        (StateAccess(world, or_world.id, AccessMode.READ_WRITE,
                     outer_resume_world_after.id, Footprint(FootprintKind.WHOLE)),
         StateAccess(ambient, or_ambient.id, AccessMode.READ_WRITE,
                     outer_resume_ambient_after.id, Footprint(FootprintKind.WHOLE))),
        effects_complete=False)
    operations.append(outer_resume_op)
    replace_jump_from_outer_id = OperationID("nested.outer.resume.to-route")
    replace_jump_from_outer_uses = (
        _use("nested.outer.resume.to-route.pending", outer_resume_args[0].id, UseRole.PROTOCOL),
        _use("nested.outer.resume.to-route.world", outer_resume_world_after.id,
             UseRole.STATE_CONTENT),
        _use("nested.outer.resume.to-route.ambient", outer_resume_ambient_after.id,
             UseRole.STATE_CONTENT),
    )
    replace_jump_from_outer = Operation(replace_jump_from_outer_id,
        "handoff after outer Resume", (Behavior.CONTROL,), replace_jump_from_outer_uses,
        terminator=Terminator(TerminatorKind.JUMP, (Successor(BlockID("shared.cleanup.post-pop-route"),
            tuple(use.id for use in replace_jump_from_outer_uses)),)))
    operations.append(replace_jump_from_outer)

    op_saved = _use("nested.outer.replace.saved.use", outer_replace_args[1].id,
                    UseRole.PROTOCOL)
    op_new = _use("nested.outer.replace.new.use", outer_replace_args[0].id,
                 UseRole.PROTOCOL)
    op_context = _use("nested.outer.replace.context.use", outer_replace_args[2].id,
                     UseRole.PROTOCOL)
    op_world = _use("nested.outer.replace.world.use", outer_replace_args[3].id,
                   UseRole.STATE_CONTENT)
    op_ambient = _use("nested.outer.replace.ambient.use", outer_replace_args[4].id,
                     UseRole.STATE_CONTENT)
    outer_replace_op = Operation(OperationID("nested.outer.replace"), "replace outer completion",
        (Behavior.CONTROL, Behavior.READ, Behavior.WRITE),
        (op_saved, op_new, op_context, op_world, op_ambient),
        (outer_replace_world_after.id, outer_replace_ambient_after.id),
        (StateAccess(world, op_world.id, AccessMode.READ_WRITE,
                     outer_replace_world_after.id, Footprint(FootprintKind.WHOLE)),
         StateAccess(ambient, op_ambient.id, AccessMode.READ_WRITE,
                     outer_replace_ambient_after.id, Footprint(FootprintKind.WHOLE))),
        effects_complete=False)
    operations.append(outer_replace_op)
    outer_replace_jump_id = OperationID("nested.outer.replace.to-route")
    outer_replace_jump_uses = (
        _use("nested.outer.replace.to-route.pending", outer_replace_args[0].id,
             UseRole.PROTOCOL),
        _use("nested.outer.replace.to-route.world", outer_replace_world_after.id,
             UseRole.STATE_CONTENT),
        _use("nested.outer.replace.to-route.ambient", outer_replace_ambient_after.id,
             UseRole.STATE_CONTENT),
    )
    outer_replace_jump = Operation(outer_replace_jump_id, "handoff after outer Replace",
        (Behavior.CONTROL,), outer_replace_jump_uses,
        terminator=Terminator(TerminatorKind.JUMP, (Successor(BlockID("shared.cleanup.post-pop-route"),
            tuple(use.id for use in outer_replace_jump_uses)),)))
    operations.append(outer_replace_jump)

    # Update lexical scope ownership and attach the new inner interface.
    outer_cleanup = replace(outer_cleanup,
        blocks=(*outer_cleanup.blocks, outer_resume_block, outer_replace_block,
                inner_route_block, inner_fallthrough_dispatch_block))
    inner_protected_scope = ControlScope(inner_protected_id, region_id, outer_cleanup.id,
        ControlScopeKind.BLOCK, _source("nested.inner.protected", 3), (inner_protected_block,))
    inner_cleanup_scope = ControlScope(inner_cleanup_id, region_id, outer_cleanup.id,
        ControlScopeKind.CLEANUP, _source("nested.inner.cleanup", 4),
        (inner_entry, inner_resume_block, inner_make_return_block, inner_replace_block))
    function = replace(function, blocks=tuple(
        block for block in function.blocks if block != outer_entry))
    scopes = tuple(function if scope.id == function.id else
                   outer_cleanup if scope.id == outer_cleanup.id else scope
                   for scope in graph.control_scopes)
    scopes = (*scopes, inner_protected_scope, inner_cleanup_scope)

    # Materialize new block records.  Values in each successor tuple use the
    # exact block-argument order declared above.
    new_blocks = [
        Block(inner_entry,
            (inner_pending_entry.id, inner_outer_pending_entry.id,
             inner_outer_context_entry.id, inner_world_entry.id, inner_ambient_entry.id),
            (inner_enter.id, inner_branch.id)),
        Block(inner_resume_block, tuple(value.id for value in inner_resume_args),
            (inner_resume_op.id, inner_resume_jump.id)),
        Block(inner_make_return_block, tuple(value.id for value in inner_make_return_args),
            (make_new_return.id, new_return_to_replace.id)),
        Block(inner_replace_block, tuple(value.id for value in inner_replace_args),
            (inner_replace_op.id, inner_replace_jump.id)),
        Block(inner_route_block,
            (inner_route_pending.id, inner_route_outer_pending.id,
             inner_route_outer_context.id, inner_route_world.id, inner_route_ambient.id),
            (inner_route_op.id,)),
        Block(inner_fallthrough_dispatch_block,
            tuple(value.id for value in fallthrough_dispatch_args),
            (fallthrough_dispatch.id,)),
        Block(outer_resume_block, tuple(value.id for value in outer_resume_args),
            (outer_resume_op.id, replace_jump_from_outer.id)),
        Block(outer_replace_block, tuple(value.id for value in outer_replace_args),
            (outer_replace_op.id, outer_replace_jump.id)),
    ]
    blocks.extend(new_blocks)
    region = replace(region, blocks=tuple(blocks))

    inner_interface = CleanupInterface(inner_cleanup_id, inner_protected_id,
                                       inner_entry, inner_pending_entry.id)
    inner_enter_record = CleanupEnter(inner_enter.id, inner_cleanup_id,
                                     ie_pending_use.id, inner_saved_context.id)
    inner_resume_record = CleanupResume(inner_resume_op.id, inner_cleanup_id,
        ir_pending_use.id, ir_context_use.id,
        ControlEdgeReference(inner_resume_jump.id, 0))
    inner_replace_record = CleanupReplace(inner_replace_op.id, inner_cleanup_id,
        irp_saved.id, irp_new.id, irp_context.id,
        ControlEdgeReference(inner_replace_jump.id, 0))
    outer_resume_record = CleanupResume(outer_resume_op.id, outer_cleanup.id,
        or_pending.id, or_context.id, ControlEdgeReference(replace_jump_from_outer.id, 0))
    outer_replace_record = CleanupReplace(outer_replace_op.id, outer_cleanup.id,
        op_saved.id, op_new.id, op_context.id,
        ControlEdgeReference(outer_replace_jump.id, 0))

    # The inner Fallthrough is a local continuation inside the outer cleanup;
    # its other case leaves both cleanups and is therefore replaced twice.
    fallthrough_port_record = ControlPort(fallthrough_port, outer_cleanup.id,
        K.FALLTHROUGH, block=outer_resume_block)
    pending_definitions = (*graph.pending_completions,
        PendingCompletionDefinition(fallthrough_pending.id, fallthrough_port),
        PendingCompletionDefinition(inner_replacement.id,
            ControlPortID("shared.port.return"), replacement_ref_use.id))
    return replace(graph, regions=(region,), operations=tuple(operations), values=tuple(values),
        control_scopes=scopes,
        control_ports=(*graph.control_ports, fallthrough_port_record),
        pending_completions=pending_definitions,
        cleanup_interfaces=(*graph.cleanup_interfaces, inner_interface),
        cleanup_enters=(*graph.cleanup_enters, inner_enter_record),
        cleanup_resumes=(outer_resume_record, inner_resume_record),
        cleanup_replacements=(inner_replace_record, outer_replace_record))


def local_loop_transfers_in_cleanup_graph():
    """Break/Continue inside cleanup keep its outer pending/context separate.

    The loop's C0 dispatch handles its local Break and Continue ports.  Both
    paths carry the cleanup's original pending token, saved context, and all
    current state domains as independent block arguments.  Only the later
    CleanupResume consumes the outer obligation.
    """
    graph = resume_multistate_graph()
    region = graph.regions[0]
    region_id = region.id
    world, ambient = (location.id for location in graph.locations)
    cleanup_scope = next(scope for scope in graph.control_scopes
                         if scope.kind is ControlScopeKind.CLEANUP)
    cleanup_entry = BlockID("shared.cleanup")
    after_block = BlockID("cleanup.loop.after")
    loop_id = ControlScopeID("cleanup.loop")
    header = BlockID("cleanup.loop.header")
    break_path = BlockID("cleanup.loop.break")
    continue_path = BlockID("cleanup.loop.continue")
    dispatch_block = BlockID("cleanup.loop.dispatch")
    pending = ValueID("shared.cleanup.pending")
    saved_context = ValueID("shared.cleanup.saved-context")
    world_after_write = ValueID("shared.cleanup.world.after")
    ambient_after_write = ValueID("shared.cleanup.ambient.after")

    def bool_argument(label, block, index):
        return DataValue(ValueID(label), region_id, BlockArgument(block, index),
                         "builtins.bool")

    header_args = (
        _protocol("cleanup.loop.header.pending", region_id, header, 0, P.PENDING_COMPLETION),
        _protocol("cleanup.loop.header.context", region_id, header, 1, P.SAVED_HANDLED_CONTEXT),
        bool_argument("cleanup.loop.header.condition", header, 2),
        _state("cleanup.loop.header.world", region_id, header, 3, world),
        _state("cleanup.loop.header.ambient", region_id, header, 4, ambient),
    )
    path_args = {}
    for label, block in (("break", break_path), ("continue", continue_path)):
        path_args[label] = (
            _protocol(f"cleanup.loop.{label}.pending", region_id, block, 0,
                      P.PENDING_COMPLETION),
            _protocol(f"cleanup.loop.{label}.context", region_id, block, 1,
                      P.SAVED_HANDLED_CONTEXT),
            bool_argument(f"cleanup.loop.{label}.condition", block, 2),
            _state(f"cleanup.loop.{label}.world", region_id, block, 3, world),
            _state(f"cleanup.loop.{label}.ambient", region_id, block, 4, ambient),
        )
    dispatch_args = (
        _protocol("cleanup.loop.dispatch.pending", region_id, dispatch_block, 0,
                  P.PENDING_COMPLETION),
        _protocol("cleanup.loop.dispatch.outer-pending", region_id, dispatch_block, 1,
                  P.PENDING_COMPLETION),
        _protocol("cleanup.loop.dispatch.context", region_id, dispatch_block, 2,
                  P.SAVED_HANDLED_CONTEXT),
        bool_argument("cleanup.loop.dispatch.condition", dispatch_block, 3),
        _state("cleanup.loop.dispatch.world", region_id, dispatch_block, 4, world),
        _state("cleanup.loop.dispatch.ambient", region_id, dispatch_block, 5, ambient),
    )
    after_args = (
        _protocol("cleanup.loop.after.pending", region_id, after_block, 0,
                  P.PENDING_COMPLETION),
        _protocol("cleanup.loop.after.context", region_id, after_block, 1,
                  P.SAVED_HANDLED_CONTEXT),
        _state("cleanup.loop.after.world", region_id, after_block, 2, world),
        _state("cleanup.loop.after.ambient", region_id, after_block, 3, ambient),
    )
    values = [*graph.values, *header_args, *path_args["break"],
              *path_args["continue"], *dispatch_args, *after_args]
    condition = DataValue(ValueID("cleanup.loop.condition.literal"), region_id,
                          LiteralOrigin(True), "builtins.bool")
    values.append(condition)
    operations = []

    enter_uses = (
        _use("cleanup.loop.enter.pending", pending, UseRole.PROTOCOL),
        _use("cleanup.loop.enter.context", saved_context, UseRole.PROTOCOL),
        _use("cleanup.loop.enter.condition", condition.id, UseRole.DATA),
        _use("cleanup.loop.enter.world", world_after_write, UseRole.STATE_CONTENT),
        _use("cleanup.loop.enter.ambient", ambient_after_write, UseRole.STATE_CONTENT),
    )
    enter_to_loop_id = OperationID("cleanup.loop.enter-header")
    enter_to_loop = Operation(enter_to_loop_id, "continue cleanup in local loop",
        (Behavior.CONTROL,), enter_uses,
        terminator=Terminator(TerminatorKind.JUMP, (Successor(header,
            tuple(use.id for use in enter_uses)),)))

    header_condition_use = _use("cleanup.loop.header.condition.use", header_args[2].id,
                                UseRole.DATA)
    branch_uses = [header_condition_use]
    branch_edges = []
    for label in ("break", "continue"):
        actuals = (
            _use(f"cleanup.loop.branch.{label}.pending", header_args[0].id, UseRole.PROTOCOL),
            _use(f"cleanup.loop.branch.{label}.context", header_args[1].id, UseRole.PROTOCOL),
            _use(f"cleanup.loop.branch.{label}.condition", header_args[2].id, UseRole.DATA),
            _use(f"cleanup.loop.branch.{label}.world", header_args[3].id, UseRole.STATE_CONTENT),
            _use(f"cleanup.loop.branch.{label}.ambient", header_args[4].id, UseRole.STATE_CONTENT),
        )
        branch_uses.extend(actuals)
        branch_edges.append(Successor(break_path if label == "break" else continue_path,
                                      tuple(use.id for use in actuals)))
    branch_id = OperationID("cleanup.loop.branch")
    branch = Operation(branch_id, "choose local Break or Continue",
        (Behavior.CONTROL,), tuple(branch_uses),
        terminator=Terminator(TerminatorKind.BRANCH, tuple(branch_edges),
                              condition=header_condition_use.id))

    break_port, continue_port = (ControlPortID("cleanup.loop.port.break"),
                                 ControlPortID("cleanup.loop.port.continue"))
    made_pending = {}
    path_ops = {}
    for label, port, args in (("break", break_port, path_args["break"]),
                               ("continue", continue_port, path_args["continue"])):
        construct_id = OperationID(f"cleanup.loop.make-{label}")
        pending_value = ProtocolValue(ValueID(f"cleanup.loop.pending.{label}"), region_id,
            OperationResult(construct_id, 0), P.PENDING_COMPLETION)
        values.append(pending_value)
        made_pending[label] = pending_value
        construct = Operation(construct_id, f"construct local {label.title()}",
            (Behavior.CONTROL,), results=(pending_value.id,), effects_complete=True)
        jump_id = OperationID(f"cleanup.loop.{label}-to-dispatch")
        jump_uses = (
            _use(f"cleanup.loop.{label}.new-pending", pending_value.id, UseRole.PROTOCOL),
            _use(f"cleanup.loop.{label}.outer-pending", args[0].id, UseRole.PROTOCOL),
            _use(f"cleanup.loop.{label}.context", args[1].id, UseRole.PROTOCOL),
            _use(f"cleanup.loop.{label}.condition", args[2].id, UseRole.DATA),
            _use(f"cleanup.loop.{label}.world", args[3].id, UseRole.STATE_CONTENT),
            _use(f"cleanup.loop.{label}.ambient", args[4].id, UseRole.STATE_CONTENT),
        )
        jump = Operation(jump_id, f"handoff local {label.title()}",
            (Behavior.CONTROL,), jump_uses,
            terminator=Terminator(TerminatorKind.JUMP, (Successor(dispatch_block,
                tuple(use.id for use in jump_uses)),)))
        path_ops[label] = (construct, jump)

    dispatch_selector = _use("cleanup.loop.dispatch.selector", dispatch_args[0].id,
                             UseRole.PROTOCOL)
    dispatch_uses = [dispatch_selector]
    successors = []
    for label, port, target in (("break", break_port, after_block),
                                 ("continue", continue_port, header)):
        carried = (
            _use(f"cleanup.loop.dispatch.{label}.outer-pending", dispatch_args[1].id,
                 UseRole.PROTOCOL),
            _use(f"cleanup.loop.dispatch.{label}.context", dispatch_args[2].id,
                 UseRole.PROTOCOL),
        )
        if label == "continue":
            carried = (*carried, _use("cleanup.loop.dispatch.continue.condition",
                                      dispatch_args[3].id, UseRole.DATA))
        carried = (*carried,
            _use(f"cleanup.loop.dispatch.{label}.world", dispatch_args[4].id,
                 UseRole.STATE_CONTENT),
            _use(f"cleanup.loop.dispatch.{label}.ambient", dispatch_args[5].id,
                 UseRole.STATE_CONTENT))
        dispatch_uses.extend(carried)
        successors.append(PendingSuccessor(port, target,
                                           tuple(use.id for use in carried)))
    dispatch_id = OperationID("cleanup.loop.pending-dispatch")
    dispatch = Operation(dispatch_id, "dispatch local Break and Continue",
        (Behavior.CONTROL,), tuple(dispatch_uses),
        terminator=PendingDispatchTerminator(dispatch_selector.id, tuple(successors)))

    # The common post-loop block resumes the original outer transfer.  It is
    # never fed the loop's local Break/Continue token.
    resume_id = OperationID("shared.cleanup.resume")
    resume = next(op for op in graph.operations if op.id == resume_id)
    resume_pending = next(use for use in resume.uses if use.id == UseID("shared.cleanup.resume.pending"))
    resume_context = next(use for use in resume.uses if use.id == UseID("shared.cleanup.resume.context"))
    resume_world = next(use for use in resume.uses if use.id == UseID("shared.cleanup.resume.world"))
    resume_ambient = next(use for use in resume.uses if use.id == UseID("shared.cleanup.resume.ambient"))
    resume = replace(resume, uses=tuple(
        replace(use, value={resume_pending.id: after_args[0].id,
                            resume_context.id: after_args[1].id,
                            resume_world.id: after_args[2].id,
                            resume_ambient.id: after_args[3].id}.get(use.id, use.value))
        for use in resume.uses))

    resume_jump = next(op for op in graph.operations
                       if op.id == OperationID("shared.cleanup.resume.to-route"))
    resume_jump_pending = next(use for use in resume_jump.uses
                               if use.id == UseID("shared.cleanup.resume.to-route.pending"))
    resume_jump = replace(resume_jump, uses=tuple(
        replace(use, value=after_args[0].id) if use.id == resume_jump_pending.id else use
        for use in resume_jump.uses))
    old_cleanup_block = next(block for block in region.blocks if block.id == cleanup_entry)
    cleanup_entry_block = replace(old_cleanup_block,
        operations=(*old_cleanup_block.operations[:3], enter_to_loop.id))
    new_ops = [resume_jump if op.id == resume_jump.id else op for op in graph.operations
               if op.id not in (
        resume.id, branch_id, dispatch_id, enter_to_loop_id,
        *[op.id for pair in path_ops.values() for op in pair])]
    new_ops.extend((enter_to_loop, branch,
                    *[op for pair in path_ops.values() for op in pair],
                    dispatch, resume))
    blocks = [cleanup_entry_block if block.id == cleanup_entry else block
              for block in region.blocks]
    blocks.extend((
        Block(header, tuple(value.id for value in header_args), (branch.id,)),
        Block(break_path, tuple(value.id for value in path_args["break"]),
              tuple(op.id for op in path_ops["break"])),
        Block(continue_path, tuple(value.id for value in path_args["continue"]),
              tuple(op.id for op in path_ops["continue"])),
        Block(dispatch_block, tuple(value.id for value in dispatch_args), (dispatch.id,)),
        Block(after_block, tuple(value.id for value in after_args),
              (resume.id, resume_jump.id)),
    ))
    region = replace(region, blocks=tuple(blocks))
    loop_scope = ControlScope(loop_id, region_id, cleanup_scope.id, ControlScopeKind.LOOP,
                              _source("cleanup.local-loop", 5),
                              (header, break_path, continue_path, dispatch_block))
    cleanup_scope = replace(cleanup_scope, blocks=(*cleanup_scope.blocks, after_block))
    scopes = tuple(cleanup_scope if scope.id == cleanup_scope.id else scope
                   for scope in graph.control_scopes)
    scopes = (*scopes, loop_scope)
    ports = (
        ControlPort(break_port, loop_id, K.BREAK, block=after_block),
        ControlPort(continue_port, loop_id, K.CONTINUE, block=header),
    )
    pending_definitions = (
        PendingCompletionDefinition(made_pending["break"].id, break_port),
        PendingCompletionDefinition(made_pending["continue"].id, continue_port),
    )
    return replace(graph, regions=(region,), operations=tuple(new_ops), values=tuple(values),
        control_scopes=scopes, control_ports=(*graph.control_ports, *ports),
        pending_completions=(*graph.pending_completions, *pending_definitions))


__all__ = [
    "cleanup_return_resume_graph", "nested_cleanup_fallthrough_and_replace_graph",
    "resume_multistate_graph", "local_loop_transfers_in_cleanup_graph",
]
