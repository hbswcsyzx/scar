"""One finite P3 capture for the same-graph self-await pipeline."""
from dataclasses import replace

from scar.ir.execution.calls import CallActivation
from scar.ir.execution.resumables import BodyActivationOrigin, BodyDriveExecution
from scar.ir.execution.ids import CallActivationID
from scar.ir.program.ids import BlockID, OperationID
from tests.fixtures.execution_call_graphs import _model
from tests.fixtures.program_await_pipeline_graphs import await_self_pipeline_program


def await_self_pipeline_execution(*, attach_link=True):
    """Return a ProgramGraph, ExecutionModel and details for one selected N path."""
    program, static = await_self_pipeline_program(attach_link=attach_link)
    factory_path = (
        (BlockID("factory.entry"), 0),
        (BlockID("factory.created"), 0),
        (BlockID("factory.awaitable"), 0),
        (BlockID("factory.normal"), None),
    )
    drive = static["drive"]
    driver_drive = next(operation for operation in program.operations
                        if operation.id == drive.operation)
    outcome_source = next(successor.source for successor in driver_drive.terminator.successors
                          if successor.source == OperationID("resume.suspend"))
    selected_drive_edge = next(index for index, successor in enumerate(driver_drive.terminator.successors)
                               if successor.source == outcome_source)
    driver_path = (
        (BlockID("driver.entry"), 0),
        (BlockID("driver.ingress"), selected_drive_edge),
        (BlockID("driver.outcome"), None),
    )
    body_region = next(region for region in program.regions if region.id == static["body"].region)
    body_path = ((body_region.entry, None),)
    paths = (
        (program.root, factory_path, "await.pipeline.factory"),
        (static["driver"].region, driver_path, "await.pipeline.driver"),
        (body_region.id, body_path, "await.pipeline.body"),
    )
    model, scopes, source = _model(program, paths)
    factory_activation, factory_visits, factory_operations = scopes[0]
    driver_activation, driver_visits, driver_operations = scopes[1]
    body_activation, body_visits, body_operations = scopes[2]
    call_occurrence = factory_operations[static["call"].id]
    completion = driver_operations[OperationID("driver.outcome.exit")]
    call_link = CallActivation(CallActivationID("await.pipeline.call"), call_occurrence,
        driver_activation, driver_visits[0], completion, source)
    drive_occurrence = driver_operations[drive.operation]
    body_outcome = body_operations[outcome_source]
    body_link = BodyDriveExecution(drive_occurrence, body_activation,
        body_visits[0], body_outcome, source)
    creation = factory_operations[static["create"].operation]
    origin = BodyActivationOrigin(body_activation, creation, source)
    model = replace(model,
        call_activations=(call_link,),
        body_drive_executions=(body_link,),
        body_activation_origins=(origin,))
    return program, model, {
        **static, "source": source, "factory_activation": factory_activation,
        "factory_visits": factory_visits, "factory_operations": factory_operations,
        "driver_activation": driver_activation, "driver_visits": driver_visits,
        "driver_operations": driver_operations, "body_activation": body_activation,
        "body_visits": body_visits, "body_operations": body_operations,
        "drive_occurrence": drive_occurrence, "body_outcome": body_outcome,
        "call_activation": call_link, "body_drive_execution": body_link,
        "body_activation_origin": origin, "selected_drive_edge": selected_drive_edge,
    }


__all__ = ["await_self_pipeline_execution"]
