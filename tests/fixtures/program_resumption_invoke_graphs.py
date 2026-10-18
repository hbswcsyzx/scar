"""Hand-authored C2B invoke/resume compositions.

These fixtures describe static IR relationships only. They do not prove that a
Python callable, body, or runtime invocation corresponds to the records.
"""
from __future__ import annotations

from dataclasses import replace

from scar.ir.program.control import ProtocolValueKind as P
from scar.ir.program.ids import BlockID, LocationID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, CompletionResult,
    CompletionSignature, CompletionSuccessor, ExitKind, Footprint, FootprintKind,
    Operation, OperationResult, ProtocolValue, ProtocolValueType, ReferenceValue,
    StateAccess, StateVersionValue, Terminator, TerminatorKind, Use, UseRole,
    ValueKind, ValueType,
)
from scar.ir.program.validation import validate
from scar.ir.program.resumption import (
    FrameContextAttach, FrameContextDetach, ResumeInput, ResumeSlot,
    ResumeSlotKind as I, ResumeSuccessor, SavedInput, SavedRole as S, SavedSlot,
    SuspendTerminator, SuspensionFlavor,
)

from tests.fixtures.program_resumption_graphs import resumption_invoke_program


def _operation(graph, name):
    return next(operation for operation in graph.operations
                if operation.id == OperationID(name))


def _replace_operation(graph, name, changed):
    return replace(graph, operations=tuple(
        changed if operation.id == OperationID(name) else operation
        for operation in graph.operations))


def partial_state_invoke_program():
    """INVOKE produces world+payload while forwarding current context/caller.

    The two completions each have fresh edge-local Uses for the attached
    context and drive caller. Context is not claimed as an invoke result.
    """
    graph = resumption_invoke_program()
    invoke = _operation(graph, "invoke.call")
    previous_context = UseID("invoke.call.context")
    normal_context = Use(UseID("invoke.call.normal.context"),
                         ValueID("invoke.attach.after"), UseRole.STATE_CONTENT)
    failure_context = Use(UseID("invoke.call.failure.context"),
                          ValueID("invoke.attach.after"), UseRole.STATE_CONTENT)
    uses = tuple(use for use in invoke.uses
                 if use.id not in (previous_context, UseID("invoke.call.normal.x")))
    uses = (*uses, normal_context, failure_context)
    changed = replace(
        invoke,
        uses=uses,
        invoke_arguments=(UseID("invoke.call.world"),),
        completions=(
            CompletionSignature(ExitKind.NORMAL, (
                ValueType(ValueKind.STATE, location=graph.locations[0].id),
                ValueType(ValueKind.REFERENCE),
            )),
            CompletionSignature(ExitKind.RAISE, (
                ValueType(ValueKind.STATE, location=graph.locations[0].id),
                ProtocolValueType(P.EXCEPTION_PACKET),
            )),
        ),
        effects_complete=True,
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, invoke.terminator.successors[0].block, (
                CompletionResult(0),
                UseID("invoke.call.normal.caller"),
                normal_context.id,
                CompletionResult(1),
            )),
            CompletionSuccessor(ExitKind.RAISE, invoke.terminator.successors[1].block, (
                UseID("invoke.call.failure.caller"),
                CompletionResult(0),
                CompletionResult(1),
                failure_context.id,
            )),
        )),
    )
    return _replace_operation(graph, "invoke.call", changed)


def suspended_partial_state_invoke_program():
    """A real cut restores state/context before the partial-state INVOKE.

    The start ingress saves only the frame fragment and reference ``x``. World
    and handled-context state arrive as new resume inputs; the landing attaches
    the restored frame before invoking. The INVOKE then produces a fresh world
    on each completion while forwarding the current attached context/caller.
    """
    graph = partial_state_invoke_program()
    region_id = graph.root
    world_location, context_location = (location.id for location in graph.locations)

    # The original input arguments remain at the new body entry. The old entry
    # becomes a private temporal landing with fresh state and saved-value args.
    start_id = BlockID("invoke.start")
    landing_id = BlockID("invoke.entry")
    entry_positions = {ValueID("invoke.x"): 0, ValueID("invoke.world"): 1,
                       ValueID("invoke.context"): 2}
    values = [replace(value, origin=BlockArgument(start_id, entry_positions[value.id]))
              if value.id in entry_positions else value for value in graph.values]

    def add_value(name, origin, kind):
        value_id = ValueID(name)
        if kind == "reference":
            value = ReferenceValue(value_id, region_id, origin)
        elif kind == world_location or kind == context_location:
            value = StateVersionValue(value_id, region_id, origin, kind)
        else:
            value = ProtocolValue(value_id, region_id, origin, kind)
        values.append(value)
        return value_id

    start_x, start_world, start_context = (
        ValueID("invoke.x"), ValueID("invoke.world"), ValueID("invoke.context"))
    resume_frame = add_value("invoke.resume.frame", BlockArgument(landing_id, 0), P.FRAME_CONTEXT)
    resume_x = add_value("invoke.resume.x", BlockArgument(landing_id, 1), "reference")
    resume_world = add_value("invoke.resume.world", BlockArgument(landing_id, 2), world_location)
    resume_context = add_value("invoke.resume.context", BlockArgument(landing_id, 3), context_location)
    resume_sent = add_value("invoke.resume.sent", BlockArgument(landing_id, 4), "reference")
    resume_caller = add_value("invoke.resume.caller",
                              OperationResult(OperationID("invoke.resume.attach"), 0),
                              P.DRIVE_CALLER_CONTEXT)
    resume_context_after = add_value("invoke.resume.attach.after",
                                     OperationResult(OperationID("invoke.resume.attach"), 1),
                                     context_location)
    start_frame = add_value("invoke.start.detach.frame",
                            OperationResult(OperationID("invoke.start.detach"), 0),
                            P.FRAME_CONTEXT)
    start_context_after = add_value("invoke.start.detach.after",
                                   OperationResult(OperationID("invoke.start.detach"), 1),
                                   context_location)

    start_detach_caller = Use(UseID("invoke.start.detach.caller"),
                              ValueID("invoke.attach.caller"), UseRole.PROTOCOL)
    start_detach_context = Use(UseID("invoke.start.detach.context"),
                               ValueID("invoke.attach.after"), UseRole.STATE_CONTENT)
    start_detach = Operation(
        OperationID("invoke.start.detach"), "detach before suspension",
        (Behavior.CONTROL, Behavior.READ, Behavior.WRITE),
        (start_detach_caller, start_detach_context), (start_frame, start_context_after),
        accesses=(StateAccess(context_location, start_detach_context.id,
                              AccessMode.READ_WRITE, start_context_after,
                              Footprint(FootprintKind.WHOLE)),),
        effects_complete=True,
    )
    export = Use(UseID("invoke.start.suspend.export"), start_x, UseRole.REFERENCE)
    saved_frame = Use(UseID("invoke.start.suspend.frame"), start_frame, UseRole.PROTOCOL)
    saved_x = Use(UseID("invoke.start.suspend.x"), start_x, UseRole.REFERENCE)
    handoff_world = Use(UseID("invoke.start.suspend.world"), start_world,
                        UseRole.STATE_CONTENT)
    handoff_context = Use(UseID("invoke.start.suspend.context"), start_context_after,
                          UseRole.STATE_CONTENT)
    suspend_term = SuspendTerminator(
        SuspensionFlavor.YIELD, export.id,
        (SavedSlot(S.FRAME_CONTEXT, saved_frame.id), SavedSlot(S.VALUE, saved_x.id)),
        (handoff_world.id, handoff_context.id),
        (ResumeSuccessor(
            (ResumeSlot(I.STATE, world_location), ResumeSlot(I.STATE, context_location),
             ResumeSlot(I.SENT_VALUE)),
            landing_id,
            (SavedInput(0), SavedInput(1), ResumeInput(0), ResumeInput(1), ResumeInput(2)),
        ),),
    )
    suspend = Operation(
        OperationID("invoke.start.suspend"), "yield before invocation",
        (Behavior.CONTROL,), (export, saved_frame, saved_x, handoff_world, handoff_context),
        effects_complete=True, terminator=suspend_term,
    )

    resume_frame_use = Use(UseID("invoke.resume.attach.frame"), resume_frame,
                           UseRole.PROTOCOL)
    resume_context_use = Use(UseID("invoke.resume.attach.context"), resume_context,
                             UseRole.STATE_CONTENT)
    resume_attach = Operation(
        OperationID("invoke.resume.attach"), "attach restored frame",
        (Behavior.CONTROL, Behavior.READ, Behavior.WRITE),
        (resume_frame_use, resume_context_use), (resume_caller, resume_context_after),
        accesses=(StateAccess(context_location, resume_context_use.id,
                              AccessMode.READ_WRITE, resume_context_after,
                              Footprint(FootprintKind.WHOLE)),),
        effects_complete=True,
    )

    # Rebind each existing invoke operand to the landing's current values;
    # actual x and sent value are explicit, distinct invocation operands.
    invoke = _operation(graph, "invoke.call")
    rebound = []
    for use in invoke.uses:
        value = {
            UseID("invoke.call.world"): resume_world,
            UseID("invoke.call.normal.caller"): resume_caller,
            UseID("invoke.call.failure.caller"): resume_caller,
            UseID("invoke.call.normal.context"): resume_context_after,
            UseID("invoke.call.failure.context"): resume_context_after,
        }.get(use.id, use.value)
        rebound.append(replace(use, value=value))
    saved_x_actual = Use(UseID("invoke.call.saved-x"), resume_x, UseRole.REFERENCE)
    sent_actual = Use(UseID("invoke.call.sent"), resume_sent, UseRole.REFERENCE)
    rebound_call = replace(invoke, uses=(*rebound, saved_x_actual, sent_actual),
                           invoke_arguments=(UseID("invoke.call.world"),
                                             saved_x_actual.id, sent_actual.id))

    old_blocks = []
    for block in graph.regions[0].blocks:
        if block.id == landing_id:
            old_blocks.append(Block(landing_id,
                (resume_frame, resume_x, resume_world, resume_context, resume_sent),
                (resume_attach.id, rebound_call.id)))
        else:
            old_blocks.append(block)
    start_block = Block(start_id, (start_x, start_world, start_context), (
        OperationID("invoke.initial"), OperationID("invoke.attach"), start_detach.id,
        suspend.id))
    region = replace(graph.regions[0], entry=start_id,
                     blocks=(*old_blocks, start_block))
    scopes = tuple(replace(scope, blocks=(*scope.blocks, start_id))
                   for scope in graph.control_scopes)
    return replace(
        graph,
        regions=(region,),
        operations=tuple(rebound_call if operation.id == invoke.id else operation
                         for operation in graph.operations)
                   + (start_detach, suspend, resume_attach),
        values=tuple(values),
        control_scopes=scopes,
        frame_context_attaches=(*graph.frame_context_attaches,
                                FrameContextAttach(resume_attach.id, resume_frame_use.id,
                                                   resume_caller)),
        frame_context_detaches=(*graph.frame_context_detaches,
                                FrameContextDetach(start_detach.id, start_detach_caller.id,
                                                   start_frame)),
    )


def old_world_after_invoke_program():
    """A normal exit that incorrectly uses the pre-invoke world version."""
    graph = partial_state_invoke_program()
    operation = _operation(graph, "invoke.normal.exit")
    uses = tuple(replace(use, value=ValueID("invoke.world"))
                 if use.id == UseID("invoke.normal.world.out") else use
                 for use in operation.uses)
    return _replace_operation(graph, "invoke.normal.exit", replace(operation, uses=uses))


def old_context_at_invoke_program():
    """A completion forwards the pre-Attach context instead of current state."""
    graph = partial_state_invoke_program()
    operation = _operation(graph, "invoke.call")
    uses = tuple(replace(use, value=ValueID("invoke.context"))
                 if use.id == UseID("invoke.call.normal.context") else use
                 for use in operation.uses)
    return _replace_operation(graph, "invoke.call", replace(operation, uses=uses))


def precut_world_after_suspension_program():
    graph = suspended_partial_state_invoke_program()
    operation = _operation(graph, "invoke.call")
    uses = tuple(replace(use, value=ValueID("invoke.world"))
                 if use.id == UseID("invoke.call.world") else use
                 for use in operation.uses)
    return _replace_operation(graph, "invoke.call", replace(operation, uses=uses))


def precut_context_after_suspension_program():
    graph = suspended_partial_state_invoke_program()
    operation = _operation(graph, "invoke.call")
    uses = tuple(replace(use, value=ValueID("invoke.context"))
                 if use.id == UseID("invoke.call.normal.context") else use
                 for use in operation.uses)
    return _replace_operation(graph, "invoke.call", replace(operation, uses=uses))


def direct_call_to_resumable_body_program():
    graph = partial_state_invoke_program()
    operation = _operation(graph, "invoke.attach")
    changed = replace(operation, callee=RegionID("invoke-resume"),
                      call_arguments=tuple(use.id for use in operation.uses))
    return _replace_operation(graph, "invoke.attach", changed)


def direct_invoke_to_resumable_body_program():
    graph = partial_state_invoke_program()
    operation = _operation(graph, "invoke.call")
    return _replace_operation(graph, "invoke.call",
                              replace(operation, callee=RegionID("invoke-resume")))


def issue_codes(graph):
    return {issue.code for issue in validate(graph)}
