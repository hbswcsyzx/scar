"""One dynamic capture of the split general-await helper and body drive."""

from dataclasses import replace

from scar.ir.execution.calls import CallActivation
from scar.ir.execution.ids import CallActivationID
from scar.ir.execution.resumables import BodyActivationOrigin, BodyDriveExecution
from scar.ir.program.ids import BlockID, OperationID
from tests.fixtures.execution_call_graphs import _model
from tests.fixtures.program_await_general_graphs import await_general_program


def await_general_execution(*, attach_link=True, result_kind=None):
    """Return the real parent, helper, driver and persistent-body occurrences."""
    if result_kind is None:
        program, static = await_general_program(attach_link=attach_link)
    else:
        program, static = await_general_program(attach_link=attach_link,
                                                result_kind=result_kind)

    drive = static["drive"]
    drive_operation = next(row for row in program.operations if row.id == drive.operation)
    outcome_source = next(edge.source for edge in drive_operation.terminator.successors
                          if edge.source == OperationID("resume.suspend"))
    selected_drive_edge = next(index for index, edge in enumerate(drive_operation.terminator.successors)
                               if edge.source == outcome_source)
    body_region = next(row for row in program.regions if row.id == static["body"].region)
    paths = (
        (program.root, (
            (BlockID("factory.entry"), 0),
            (BlockID("factory.created"), 0),
            (BlockID("factory.awaitable"), 0),
            (BlockID("factory.normal"), None),
        ), "await.general.factory"),
        (static["helper"].id, (
            (static["helper_entry"], 0),
            (BlockID("await.general.helper.lookup.normal"), 0),
            (BlockID("await.general.helper.call.normal"), 0),
            (BlockID("await.general.helper.accepted"), None),
        ), "await.general.helper"),
        (static["driver"].region, (
            (BlockID("driver.entry"), 0),
            (BlockID("driver.ingress"), selected_drive_edge),
            (BlockID("driver.outcome"), None),
        ), "await.general.driver"),
        (body_region.id, ((body_region.entry, None),), "await.general.body"),
    )
    model, scopes, source = _model(program, paths)
    factory, helper, driver, body = scopes
    get_occurrence = factory[2][static["get"].id]
    helper_return = helper[2][static["helper_return"].id]
    acquisition_call = CallActivation(
        CallActivationID("await.general.get.helper"), get_occurrence,
        helper[0], helper[1][0], helper_return, source)

    caller_call = factory[2][static["call"].id]
    driver_completion = driver[2][OperationID("driver.outcome.exit")]
    drive_call = CallActivation(
        CallActivationID("await.general.driver.call"), caller_call,
        driver[0], driver[1][0], driver_completion, source)
    drive_occurrence = driver[2][drive.operation]
    body_outcome = body[2][outcome_source]
    body_execution = BodyDriveExecution(
        drive_occurrence, body[0], body[1][0], body_outcome, source)
    creation = helper[2][static["helper_create_operation"].id]
    body_origin = BodyActivationOrigin(body[0], creation, source)
    model = replace(model, call_activations=(acquisition_call, drive_call),
        body_drive_executions=(body_execution,), body_activation_origins=(body_origin,))
    return program, model, {
        **static, "source": source, "scopes": scopes,
        "factory_activation": factory[0], "factory_visits": factory[1],
        "factory_operations": factory[2], "helper_activation": helper[0],
        "helper_visits": helper[1], "helper_operations": helper[2],
        "driver_activation": driver[0], "driver_visits": driver[1],
        "driver_operations": driver[2], "body_activation": body[0],
        "body_visits": body[1], "body_operations": body[2],
        "acquisition_call": acquisition_call, "driver_call": drive_call,
        "drive_occurrence": drive_occurrence, "body_outcome": body_outcome,
        "body_execution": body_execution, "body_origin": body_origin,
        "selected_drive_edge": selected_drive_edge,
    }


__all__ = ["await_general_execution"]
