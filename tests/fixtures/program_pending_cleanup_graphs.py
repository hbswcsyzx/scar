"""Two temporal cuts through active C1 cleanup and pending dispatch.

The graph is hand-authored from the existing continuation-close cleanup
fixture.  It is static IR evidence only; it does not execute Python or prove
native source applicability.
"""
from dataclasses import replace

from scar.ir.program.control import ProtocolValueKind as P
from scar.ir.program.ids import BlockID, ControlScopeID, OperationID, UseID, ValueID
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, CompletionResult, Footprint,
    FootprintKind, InvokeLiteralResult, Operation, OperationResult,
    ProtocolValue, ReferenceValue, StateAccess, StateVersionValue, Successor,
    Terminator, TerminatorKind, Use, UseRole,
)
from scar.ir.program.protocols import OwnedUse
from scar.ir.program.resumption import (
    FrameContextAttach, FrameContextDetach, ResumeInput, ResumeSlot,
    ResumeSlotKind, ResumeSuccessor, SavedInput, SavedRole, SavedSlot,
    SuspendTerminator, SuspensionFlavor,
)
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.program_continuation_cleanup_graphs import continuation_close_cleanup_program
from tests.fixtures.program_resumption_graphs import resumption_cleanup_program


def pending_cleanup_two_cuts_program():
    """Add a second real cut before the active cleanup's RAISE replacement.

    The original delegation cut, NORMAL/handled paths, helper RAISE source,
    C1 replacement, C0 route, and final PendingPayload dispatch remain the
    original graph records.  The added cut transports the old pending token,
    fresh replacement token, saved cleanup context, frame, delegate reference,
    and current state into a second private resume landing.
    """
    graph, details = continuation_close_cleanup_program()
    region, = graph.regions
    values = {row.id: row for row in graph.values}
    operations = {row.id: row for row in graph.operations}
    cleanup_scope_id = ControlScopeID("finally.cleanup.scope")

    world = ValueID("finally.failed.world")
    context = ValueID("finally.failed.context")
    delegate = ValueID("finally.landing.x")
    context_location = values[context].location
    world_location = values[world].location
    second_block = BlockID("finally.second-suspend")
    landing_block = BlockID("finally.second-landing")

    def formal(name, block, position, kind):
        identity = ValueID(name)
        origin = BlockArgument(block, position)
        if kind == "reference":
            value = ReferenceValue(identity, region.id, origin)
        elif kind == world_location or kind == context_location:
            value = StateVersionValue(identity, region.id, origin, kind)
        else:
            value = ProtocolValue(identity, region.id, origin, kind)
        values[identity] = value
        return identity

    # The jump from the helper's RAISE arm enters this attached block.  As in
    # the existing path, the original caller token is forwarded, never saved.
    suspend_formals = (
        formal("finally.second.input.world", second_block, 0, world_location),
        formal("finally.second.input.pending", second_block, 1, P.PENDING_COMPLETION),
        formal("finally.second.input.replacement", second_block, 2, P.PENDING_COMPLETION),
        formal("finally.second.input.caller", second_block, 3, P.DRIVE_CALLER_CONTEXT),
        formal("finally.second.input.saved-context", second_block, 4, P.SAVED_HANDLED_CONTEXT),
        formal("finally.second.input.context", second_block, 5, context_location),
        formal("finally.second.input.delegate", second_block, 6, "reference"),
    )

    detach_id = OperationID("finally.second.detach")
    detach_caller = Use(UseID("finally.second.detach.caller"), suspend_formals[3], UseRole.PROTOCOL)
    detach_context = Use(UseID("finally.second.detach.context"), suspend_formals[5], UseRole.STATE_CONTENT)
    detached_frame = ProtocolValue(ValueID("finally.second.detach.frame"), region.id,
                                   OperationResult(detach_id, 0), P.FRAME_CONTEXT)
    detached_context = StateVersionValue(ValueID("finally.second.detach.context.after"), region.id,
        OperationResult(detach_id, 1), context_location)
    values[detached_frame.id] = detached_frame
    values[detached_context.id] = detached_context
    operations[detach_id] = Operation(
        detach_id, "detach before the second temporal cut",
        (Behavior.CONTROL, Behavior.READ, Behavior.WRITE), (detach_caller, detach_context),
        (detached_frame.id, detached_context.id), effects_complete=True,
        accesses=(StateAccess(context_location, detach_context.id, AccessMode.READ_WRITE,
                              detached_context.id, Footprint(FootprintKind.WHOLE)),))

    second_suspend_id = OperationID("finally.second.suspend")
    exported = Use(UseID("finally.second.suspend.export"), suspend_formals[6], UseRole.REFERENCE)
    frame_use = Use(UseID("finally.second.suspend.frame"), detached_frame.id, UseRole.PROTOCOL)
    pending_use = Use(UseID("finally.second.suspend.pending"), suspend_formals[1], UseRole.PROTOCOL)
    replacement_use = Use(UseID("finally.second.suspend.replacement"), suspend_formals[2], UseRole.PROTOCOL)
    cleanup_context_use = Use(UseID("finally.second.suspend.saved-context"), suspend_formals[4], UseRole.PROTOCOL)
    delegate_use = Use(UseID("finally.second.suspend.delegate"), suspend_formals[6], UseRole.REFERENCE)
    handoff_world = Use(UseID("finally.second.suspend.world"), suspend_formals[0], UseRole.STATE_CONTENT)
    handoff_context = Use(UseID("finally.second.suspend.context"), detached_context.id, UseRole.STATE_CONTENT)
    landing_formals = (
        formal("finally.second.landing.world", landing_block, 0, world_location),
        formal("finally.second.landing.pending", landing_block, 1, P.PENDING_COMPLETION),
        formal("finally.second.landing.replacement", landing_block, 2, P.PENDING_COMPLETION),
        formal("finally.second.landing.frame", landing_block, 3, P.FRAME_CONTEXT),
        formal("finally.second.landing.saved-context", landing_block, 4, P.SAVED_HANDLED_CONTEXT),
        formal("finally.second.landing.context", landing_block, 5, context_location),
        formal("finally.second.landing.sent", landing_block, 6, "reference"),
        formal("finally.second.landing.delegate", landing_block, 7, "reference"),
    )
    resume = ResumeSuccessor(
        (ResumeSlot(ResumeSlotKind.STATE, context_location),
         ResumeSlot(ResumeSlotKind.SENT_VALUE),
         ResumeSlot(ResumeSlotKind.STATE, world_location)),
        landing_block,
        (ResumeInput(2), SavedInput(1), SavedInput(2), SavedInput(0),
         SavedInput(3), ResumeInput(0), ResumeInput(1), SavedInput(4)),
    )
    operations[second_suspend_id] = Operation(
        second_suspend_id, "second cut after helper RAISE has been packed",
        (Behavior.CONTROL,),
        (exported, frame_use, pending_use, replacement_use, cleanup_context_use,
         delegate_use, handoff_world, handoff_context),
        effects_complete=True,
        terminator=SuspendTerminator(
            SuspensionFlavor.YIELD, exported.id,
            (SavedSlot(SavedRole.FRAME_CONTEXT, frame_use.id),
             SavedSlot(SavedRole.PENDING_COMPLETION, pending_use.id),
             SavedSlot(SavedRole.PENDING_COMPLETION, replacement_use.id),
             SavedSlot(SavedRole.CLEANUP_CONTEXT, cleanup_context_use.id),
             SavedSlot(SavedRole.DELEGATE_REFERENCE, delegate_use.id)),
            (handoff_world.id, handoff_context.id), (resume,)),
    )

    failed_jump_id = OperationID("finally.failed.jump")
    failed_jump = operations[failed_jump_id]
    extra_delegate = Use(UseID("finally.failed.out.delegate"), delegate, UseRole.REFERENCE)
    operations[failed_jump_id] = replace(
        failed_jump,
        uses=(*failed_jump.uses, extra_delegate),
        terminator=replace(failed_jump.terminator, successors=(
            Successor(second_block, (*failed_jump.terminator.successors[0].arguments,
                                     extra_delegate.id)),)),
    )

    attach_id = OperationID("finally.second.attach")
    attach_frame = Use(UseID("finally.second.attach.frame"), landing_formals[3], UseRole.PROTOCOL)
    attach_context = Use(UseID("finally.second.attach.context"), landing_formals[5], UseRole.STATE_CONTENT)
    attached_caller = ProtocolValue(ValueID("finally.second.attach.caller"), region.id,
        OperationResult(attach_id, 0), P.DRIVE_CALLER_CONTEXT)
    attached_context = StateVersionValue(ValueID("finally.second.attach.context.after"), region.id,
        OperationResult(attach_id, 1), context_location)
    values[attached_caller.id] = attached_caller
    values[attached_context.id] = attached_context
    operations[attach_id] = Operation(
        attach_id, "attach the second resume landing",
        (Behavior.CONTROL, Behavior.READ, Behavior.WRITE), (attach_frame, attach_context),
        (attached_caller.id, attached_context.id), effects_complete=True,
        accesses=(StateAccess(context_location, attach_context.id, AccessMode.READ_WRITE,
                              attached_context.id, Footprint(FootprintKind.WHOLE)),))

    replace_target = BlockID("finally.replace-raise")
    forward_values = (landing_formals[0], landing_formals[1], landing_formals[2],
                      attached_caller.id, landing_formals[4], attached_context.id)
    jump_id = OperationID("finally.second.to-replace")
    jump_uses = tuple(Use(UseID(f"finally.second.to-replace.{index}"), value,
        UseRole.STATE_CONTENT if index in (0, 5) else UseRole.PROTOCOL)
        for index, value in enumerate(forward_values))
    operations[jump_id] = Operation(
        jump_id, "forward the resumed pending pair into CleanupReplace",
        (Behavior.CONTROL,), jump_uses, terminator=Terminator(TerminatorKind.JUMP,
            (Successor(replace_target, tuple(use.id for use in jump_uses)),)))

    region_blocks = tuple(region.blocks) + (
        Block(second_block, tuple(suspend_formals), (detach_id, second_suspend_id)),
        Block(landing_block, tuple(landing_formals), (attach_id, jump_id)),
    )
    cleanup_scope = next(row for row in graph.control_scopes if row.id == cleanup_scope_id)
    graph = replace(
        graph,
        regions=(replace(region, blocks=region_blocks),),
        operations=tuple(operations.values()),
        values=tuple(values.values()),
        control_scopes=tuple(replace(row, blocks=(*row.blocks, second_block, landing_block))
                             if row.id == cleanup_scope_id else row for row in graph.control_scopes),
        frame_context_detaches=(*graph.frame_context_detaches,
            FrameContextDetach(detach_id, detach_caller.id, detached_frame.id)),
        frame_context_attaches=(*graph.frame_context_attaches,
            FrameContextAttach(attach_id, attach_frame.id, attached_caller.id)),
    )
    helper_raise = InvokeLiteralResult(
        ControlEdgeReference(OperationID("finally.invoke"), 1), CompletionResult(0))
    host_packet = OwnedUse(OperationID("finally.raise-exit.op"),
                           UseID("finally.raise-exit.packet.out"))
    helper_raise_guard = ControlEdgeReference(OperationID("finally.invoke"), 1)
    return graph, {**details, "second_suspend": second_suspend_id,
                   "second_landing": landing_block, "second_detach": detach_id,
                   "second_replace_jump": jump_id, "helper_raise": helper_raise,
                   "helper_raise_guard": helper_raise_guard, "host_packet": host_packet}


def normal_pending_two_cuts_program():
    """Carry the pre-cleanup pending Return across two cuts before resuming C1."""
    graph = resumption_cleanup_program(replace_pending=False)
    region, = graph.regions
    values = {row.id: row for row in graph.values}
    operations = {row.id: row for row in graph.operations}
    landing = next(row for row in region.blocks if row.id == BlockID("finally.landing"))
    landing_world = ValueID("finally.landing.world")
    landing_pending = ValueID("finally.landing.pending")
    landing_frame = ValueID("finally.landing.frame")
    landing_saved = ValueID("finally.landing.saved-context")
    landing_context = ValueID("finally.landing.context")
    landing_value = ValueID("finally.landing.x")
    assert {landing_world, landing_pending, landing_frame, landing_saved,
            landing_context, landing_value} <= set(landing.arguments)
    assert isinstance(values[landing_world], StateVersionValue)
    assert isinstance(values[landing_pending], ProtocolValue)
    assert values[landing_pending].protocol is P.PENDING_COMPLETION
    assert isinstance(values[landing_frame], ProtocolValue)
    assert values[landing_frame].protocol is P.FRAME_CONTEXT
    assert isinstance(values[landing_saved], ProtocolValue)
    assert values[landing_saved].protocol is P.SAVED_HANDLED_CONTEXT
    assert isinstance(values[landing_context], StateVersionValue)
    assert isinstance(values[landing_value], ReferenceValue)
    context_location = values[landing_context].location
    world_location = values[landing_world].location
    caller = ValueID("finally.landing.attach.caller")
    attached_context = ValueID("finally.landing.attach.after")
    second_block = BlockID("finally.second-normal-landing")

    detach_id = OperationID("finally.second-normal.detach")
    detach_caller = Use(UseID("finally.second-normal.detach.caller"), caller, UseRole.PROTOCOL)
    detach_context = Use(UseID("finally.second-normal.detach.context"), attached_context,
                         UseRole.STATE_CONTENT)
    detached_frame = ProtocolValue(ValueID("finally.second-normal.detach.frame"), region.id,
        OperationResult(detach_id, 0), P.FRAME_CONTEXT)
    detached_context = StateVersionValue(ValueID("finally.second-normal.detach.context.after"),
        region.id, OperationResult(detach_id, 1), context_location)
    values[detached_frame.id] = detached_frame
    values[detached_context.id] = detached_context
    operations[detach_id] = Operation(detach_id, "detach before the second normal cut",
        (Behavior.CONTROL, Behavior.READ, Behavior.WRITE), (detach_caller, detach_context),
        (detached_frame.id, detached_context.id), effects_complete=True,
        accesses=(StateAccess(context_location, detach_context.id, AccessMode.READ_WRITE,
                              detached_context.id, Footprint(FootprintKind.WHOLE)),))

    resume_args = (
        StateVersionValue(ValueID("finally.second-normal.landing.world"), region.id,
                          BlockArgument(second_block, 0), world_location),
        ProtocolValue(ValueID("finally.second-normal.landing.pending"), region.id,
                      BlockArgument(second_block, 1), P.PENDING_COMPLETION),
        ProtocolValue(ValueID("finally.second-normal.landing.frame"), region.id,
                      BlockArgument(second_block, 2), P.FRAME_CONTEXT),
        ProtocolValue(ValueID("finally.second-normal.landing.saved-context"), region.id,
                      BlockArgument(second_block, 3), P.SAVED_HANDLED_CONTEXT),
        StateVersionValue(ValueID("finally.second-normal.landing.context"), region.id,
                          BlockArgument(second_block, 4), context_location),
        ReferenceValue(ValueID("finally.second-normal.landing.sent"), region.id,
                       BlockArgument(second_block, 5)),
    )
    values.update((row.id, row) for row in resume_args)

    export = Use(UseID("finally.second-normal.suspend.export"), landing_value,
                 UseRole.REFERENCE)
    frame_use = Use(UseID("finally.second-normal.suspend.frame"), detached_frame.id,
                    UseRole.PROTOCOL)
    pending_use = Use(UseID("finally.second-normal.suspend.pending"), landing_pending,
                      UseRole.PROTOCOL)
    saved_context_use = Use(UseID("finally.second-normal.suspend.saved-context"),
                            landing_saved, UseRole.PROTOCOL)
    handoff_world = Use(UseID("finally.second-normal.suspend.world"), landing_world,
                        UseRole.STATE_CONTENT)
    handoff_context = Use(UseID("finally.second-normal.suspend.context"), detached_context.id,
                          UseRole.STATE_CONTENT)
    suspend_id = OperationID("finally.second-normal.suspend")
    resume = ResumeSuccessor(
        (ResumeSlot(ResumeSlotKind.STATE, context_location),
         ResumeSlot(ResumeSlotKind.SENT_VALUE),
         ResumeSlot(ResumeSlotKind.STATE, world_location)),
        second_block,
        (ResumeInput(2), SavedInput(1), SavedInput(0), SavedInput(2),
         ResumeInput(0), ResumeInput(1)),
    )
    operations[suspend_id] = Operation(suspend_id, "second cut preserving old Return pending",
        (Behavior.CONTROL,), (export, frame_use, pending_use, saved_context_use,
                              handoff_world, handoff_context), effects_complete=True,
        terminator=SuspendTerminator(SuspensionFlavor.YIELD, export.id,
            (SavedSlot(SavedRole.FRAME_CONTEXT, frame_use.id),
             SavedSlot(SavedRole.PENDING_COMPLETION, pending_use.id),
             SavedSlot(SavedRole.CLEANUP_CONTEXT, saved_context_use.id)),
            (handoff_world.id, handoff_context.id), (resume,)))

    attach_id = OperationID("finally.second-normal.attach")
    attach_frame = Use(UseID("finally.second-normal.attach.frame"), resume_args[2].id,
                       UseRole.PROTOCOL)
    attach_context = Use(UseID("finally.second-normal.attach.context"), resume_args[4].id,
                         UseRole.STATE_CONTENT)
    attached_caller = ProtocolValue(ValueID("finally.second-normal.attach.caller"), region.id,
        OperationResult(attach_id, 0), P.DRIVE_CALLER_CONTEXT)
    attached_after = StateVersionValue(ValueID("finally.second-normal.attach.context.after"),
        region.id, OperationResult(attach_id, 1), context_location)
    values[attached_caller.id] = attached_caller
    values[attached_after.id] = attached_after
    operations[attach_id] = Operation(attach_id, "attach the second normal resume landing",
        (Behavior.CONTROL, Behavior.READ, Behavior.WRITE), (attach_frame, attach_context),
        (attached_caller.id, attached_after.id), effects_complete=True,
        accesses=(StateAccess(context_location, attach_context.id, AccessMode.READ_WRITE,
                              attached_after.id, Footprint(FootprintKind.WHOLE)),))

    jump_id = OperationID("finally.landing.jump")
    target_values = {
        UseID("finally.landing.jump.0"): resume_args[0].id,
        UseID("finally.landing.jump.1"): resume_args[1].id,
        UseID("finally.landing.jump.2"): attached_caller.id,
        UseID("finally.landing.jump.3"): attached_after.id,
        UseID("finally.landing.jump.4"): resume_args[3].id,
    }
    operations[jump_id] = replace(operations[jump_id], uses=tuple(
        replace(use, value=target_values[use.id]) for use in operations[jump_id].uses))

    first_landing = replace(landing, operations=(landing.operations[0], detach_id, suspend_id))
    second_landing = Block(second_block, tuple(row.id for row in resume_args),
                           (attach_id, jump_id))
    region = replace(region, blocks=tuple(first_landing if row.id == landing.id else row
                                          for row in region.blocks) + (second_landing,))
    graph = replace(
        graph,
        regions=(region,),
        operations=tuple(operations.values()),
        values=tuple(values.values()),
        control_scopes=tuple(replace(scope, blocks=(*scope.blocks, second_block))
                             if scope.id == ControlScopeID("finally.cleanup.scope") else scope
                             for scope in graph.control_scopes),
        frame_context_detaches=(*graph.frame_context_detaches,
            FrameContextDetach(detach_id, detach_caller.id, detached_frame.id)),
        frame_context_attaches=(*graph.frame_context_attaches,
            FrameContextAttach(attach_id, attach_frame.id, attached_caller.id)),
    )
    return graph, {
        "first_suspend": OperationID("finally.suspend"),
        "second_suspend": suspend_id,
        "expected": OwnedUse(OperationID("finally.original"),
                             UseID("finally.original.payload")),
        "actual": OwnedUse(OperationID("finally.return"), UseID("finally.return.value")),
    }
