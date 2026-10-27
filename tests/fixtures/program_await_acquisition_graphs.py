"""Core-valid acquisition examples for general ``__await__`` results.

The outer site reuses the canonical lookup/call/advance fixture.  Its
AWAIT_CALL's NORMAL result is also a real ResumableCreate handle.  The five
function-environment captures are represented by distinct original invoke
Uses; they are not added to ProtocolCall.argument_uses (the Python method call
still has no user arguments).
"""
from dataclasses import replace

from scar.ir.program.control import ControlScope, ControlScopeKind, ProtocolValueKind as P
from scar.ir.program.drivers import CreationCapture, NormalResultPort, ResumableCreate
from scar.ir.program.environments import (
    EnvironmentInterface, EnvironmentMember, EnvironmentRole, FunctionEntryLayout,
)
from scar.ir.program.ids import (
    BlockID, ControlScopeID, EnvironmentInterfaceID, OperationID, RegionID,
    UseID, ValueID,
)
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, ExitKind, ExitPort, Footprint,
    FootprintKind, Operation, OperationResult, ProgramGraph, ProtocolValue, ReferenceValue,
    Region, StateAccess, StateLocation, StateVersionValue, Terminator,
    TerminatorKind, Use, UseRole, ValueKind, ValueType,
)
from scar.ir.program.resumption import (
    FrameContextAttach, FrameContextDetach, FrameContextInitial, ResumableBody,
    ResumableKind,
)
from scar.ir.v2.ids import OperationDefinitionID
from tests.fixtures.program_control_graphs import _source
from tests.fixtures.program_continuation_graphs import (
    continuation_site_program, with_continuation_connections,
)
from tests.fixtures.program_driver_graphs import driver_rule


_ENVIRONMENT_ROLES = (
    EnvironmentRole.FUNCTION_OBJECT,
    EnvironmentRole.GLOBALS_NAMESPACE,
    EnvironmentRole.BUILTINS_NAMESPACE,
    EnvironmentRole.DEFAULTS,
    EnvironmentRole.KEYWORD_DEFAULTS,
)


def _empty_suspend_body(kind, context_location, parent):
    """A zero-suspend body with the minimum complete function environment."""
    region_id = RegionID("await.acquisition.body")
    entry_id = BlockID("await.acquisition.body.entry")
    references = tuple(
        ReferenceValue(ValueID(f"await.acquisition.body.env.{index}"), region_id,
                       BlockArgument(entry_id, index))
        for index in range(len(_ENVIRONMENT_ROLES))
    )
    initial_state = StateVersionValue(
        ValueID("await.acquisition.body.state.initial"), region_id,
        BlockArgument(entry_id, len(references)), context_location)

    initial_id = OperationID("await.acquisition.body.frame.initial")
    initial_frame = ProtocolValue(ValueID("await.acquisition.body.frame"), region_id,
                                  OperationResult(initial_id, 0), P.FRAME_CONTEXT)
    initial = Operation(initial_id, "initialize frame context", (Behavior.CONTROL,),
                        results=(initial_frame.id,), effects_complete=True)

    attach_id = OperationID("await.acquisition.body.frame.attach")
    attach_frame = Use(UseID("await.acquisition.body.frame.attach.input"),
                       initial_frame.id, UseRole.PROTOCOL)
    attach_state = Use(UseID("await.acquisition.body.frame.attach.state"),
                       initial_state.id, UseRole.STATE_CONTENT)
    attached = ProtocolValue(ValueID("await.acquisition.body.caller.context"), region_id,
                             OperationResult(attach_id, 0), P.DRIVE_CALLER_CONTEXT)
    attached_state = StateVersionValue(ValueID("await.acquisition.body.state.attached"),
                                       region_id, OperationResult(attach_id, 1), context_location)
    attach = Operation(attach_id, "attach frame context",
        (Behavior.CONTROL, Behavior.READ, Behavior.WRITE), (attach_frame, attach_state),
        (attached.id, attached_state.id), accesses=(StateAccess(
            context_location, attach_state.id, AccessMode.READ_WRITE, attached_state.id,
            Footprint(FootprintKind.WHOLE)),), effects_complete=True)

    detach_id = OperationID("await.acquisition.body.frame.detach")
    detach_caller = Use(UseID("await.acquisition.body.frame.detach.input"),
                        attached.id, UseRole.PROTOCOL)
    detach_state = Use(UseID("await.acquisition.body.frame.detach.state"),
                       attached_state.id, UseRole.STATE_CONTENT)
    detached_frame = ProtocolValue(ValueID("await.acquisition.body.frame.detached"),
                                   region_id, OperationResult(detach_id, 0), P.FRAME_CONTEXT)
    detached_state = StateVersionValue(ValueID("await.acquisition.body.state.detached"),
                                       region_id, OperationResult(detach_id, 1), context_location)
    detach = Operation(detach_id, "detach frame context",
        (Behavior.CONTROL, Behavior.READ, Behavior.WRITE), (detach_caller, detach_state),
        (detached_frame.id, detached_state.id), accesses=(StateAccess(
            context_location, detach_state.id, AccessMode.READ_WRITE, detached_state.id,
            Footprint(FootprintKind.WHOLE)),), effects_complete=True)

    returned = Use(UseID("await.acquisition.body.return.value"), references[0].id,
                   UseRole.REFERENCE)
    return_state = Use(UseID("await.acquisition.body.return.state"),
                       detached_state.id, UseRole.STATE_CONTENT)
    return_id = OperationID("await.acquisition.body.return")
    terminal = Operation(return_id, "return from acquired iterator body",
        (Behavior.CONTROL,), (returned, return_state),
        terminator=Terminator(TerminatorKind.RETURN, exit="normal",
                              values=(returned.id, return_state.id)))

    region = Region(region_id, "general await iterator body", entry_id,
        (Block(entry_id, (*[item.id for item in references], initial_state.id),
               (initial_id, attach_id, detach_id, return_id)),),
        (ExitPort("normal", ExitKind.NORMAL, (
            ValueType(ValueKind.REFERENCE),
            ValueType(ValueKind.STATE, location=context_location))),),
        parent=parent)
    environment_id = EnvironmentInterfaceID("await.acquisition.body.environment")
    environment = EnvironmentInterface(environment_id, region_id,
        OperationDefinitionID("await.acquisition.body.code"), tuple(
            EnvironmentMember(role, value.id)
            for role, value in zip(_ENVIRONMENT_ROLES, references)))
    layout = FunctionEntryLayout(environment_id, ())
    scope = ControlScope(ControlScopeID("await.acquisition.body.function"), region_id,
        None, ControlScopeKind.FUNCTION, _source("await.acquisition.body"), (entry_id,))
    body = ResumableBody(region_id, kind, context_location)
    initial_row = FrameContextInitial(initial_id, initial_frame.id)
    attach_row = FrameContextAttach(attach_id, attach_frame.id, attached.id)
    detach_row = FrameContextDetach(detach_id, detach_caller.id, detached_frame.id)
    values = (*references, initial_state, initial_frame, attached, attached_state,
              detached_frame, detached_state)
    operations = (initial, attach, detach, terminal)
    return {
        "region": region, "environment": environment, "layout": layout,
        "scope": scope, "body": body, "values": values, "operations": operations,
        "initial": initial_row, "attach": attach_row, "detach": detach_row,
        "environment_formals": tuple(value.id for value in references),
    }


def await_acquisition_program(*, result_kind=ResumableKind.GENERATOR):
    """Return a core graph where general ``__await__`` returns a known body.

    ``GENERATOR`` is an ordinary iterator result. ``GENERATOR_COROUTINE`` is
    the known-invalid general ``__await__`` result for the qualification
    negative. The returned result remains the exact AWAIT_CALL NORMAL port and
    the exact receiver of the original first-advance operation.
    """
    if type(result_kind) is not ResumableKind or result_kind not in (
            ResumableKind.GENERATOR, ResumableKind.GENERATOR_COROUTINE):
        raise ValueError("result_kind must be GENERATOR or GENERATOR_COROUTINE")

    graph, details = continuation_site_program(kind="await", request="next")
    graph, details = with_continuation_connections(graph, details)
    call_view = details["await_call"]
    call_id = call_view["operation"].id
    call = next(operation for operation in graph.operations if operation.id == call_id)
    lookup_result = call_view["operation"].uses[0]
    context_location = graph.locations[0].id

    # Environment captures are original invoke Uses, distinct from the
    # zero-argument protocol-call argument tuple. The receiver is the actual
    # bound-method result; the other four references are independent existing
    # root inputs in this declared model.
    root_inputs = details["root_inputs"]
    extra_captures = tuple(Use(UseID(f"await.acquisition.capture.{index}"),
        root_inputs[index + 1], UseRole.REFERENCE) for index in range(4))
    receiver_use = lookup_result
    state_use = call.uses[-1]
    call = replace(call, uses=(receiver_use, *extra_captures, state_use),
                   invoke_arguments=(receiver_use.id,
                       *(use.id for use in extra_captures), state_use.id))
    graph = replace(graph, operations=tuple(call if operation.id == call_id else operation
                                            for operation in graph.operations))

    body_parts = _empty_suspend_body(result_kind, context_location, graph.root)
    create = ResumableCreate(call_id, body_parts["region"].id,
        receiver_use.id,
        tuple(CreationCapture(formal, source.id) for formal, source in zip(
            body_parts["environment_formals"], (receiver_use, *extra_captures))),
        NormalResultPort(0), driver_rule())

    graph = replace(graph,
        regions=(*graph.regions, body_parts["region"]),
        operations=(*graph.operations, *body_parts["operations"]),
        values=(*graph.values, *body_parts["values"]),
        control_scopes=(*graph.control_scopes, body_parts["scope"]),
        environments=(body_parts["environment"],),
        function_entries=(body_parts["layout"],),
        resumable_bodies=(body_parts["body"],),
        frame_context_initials=(body_parts["initial"],),
        frame_context_attaches=(body_parts["attach"],),
        frame_context_detaches=(body_parts["detach"],),
        resumable_creates=(create,))

    # Keep the details tied to the actual replaced canonical operation.
    updated_call = dict(call_view)
    updated_call["operation"] = call
    details = {**details, "await_call": updated_call, "create": create,
        "created_body": body_parts["body"], "body_region": body_parts["region"],
        "body_environment": body_parts["environment"],
        "capture_uses": (receiver_use, *extra_captures),
        "iterator_value": call_view["normal_values"][0],
        "advance_receiver": next(use for use in details["advance"]["operation"].uses
                                  if use.id == details["advance_rows"][0].contract.receiver_use)}
    return graph, details


__all__ = ["await_acquisition_program"]
