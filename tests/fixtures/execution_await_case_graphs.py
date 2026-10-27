"""The same static iterator reaches a merge through either actual CFG arm."""
from dataclasses import replace

from scar.ir.execution.calls import CallActivation
from scar.ir.execution.ids import CallActivationID
from scar.ir.execution.resumables import BodyActivationOrigin, BodyDriveExecution
from scar.ir.program.ids import BlockID, OperationID
from tests.fixtures.execution_call_graphs import _model
from tests.fixtures.program_await_case_graphs import await_case_program


def await_case_execution(*, selected=0, attach_link=True):
    if type(selected) is not int or selected not in (0, 1):
        raise ValueError('exact incoming arm required')
    program, details = await_case_program(attach_link=attach_link)
    factory_path = ((BlockID('factory.entry'), 0), (BlockID('factory.created'), 0),
        (BlockID('factory.awaitable'), selected), (BlockID(f'await.case.arm.{selected}'), 0),
        (BlockID('await.case.merge'), 0), (BlockID('factory.normal'), None))
    drive = details['drive']
    operation = next(op for op in program.operations if op.id == drive.operation)
    edge = next(index for index, successor in enumerate(operation.terminator.successors)
                if successor.source == OperationID('resume.suspend'))
    driver_path = ((BlockID('driver.entry'), 0), (BlockID('driver.ingress'), edge),
                   (BlockID('driver.outcome'), None))
    body = next(region for region in program.regions if region.id == details['body'].region)
    model, scopes, source = _model(program, (
        (program.root, factory_path, 'await.case.factory'),
        (details['driver'].region, driver_path, 'await.case.driver'),
        (body.id, ((body.entry, None),), 'await.case.body')))
    factory, driver, body_scope = scopes
    call = CallActivation(CallActivationID('await.case.call'), factory[2][details['call'].id],
        driver[0], driver[1][0], driver[2][OperationID('driver.outcome.exit')], source)
    association = BodyDriveExecution(driver[2][drive.operation], body_scope[0], body_scope[1][0],
        body_scope[2][OperationID('resume.suspend')], source)
    origin = BodyActivationOrigin(body_scope[0], factory[2][details['create'].operation], source)
    model = replace(model, call_activations=(call,), body_drive_executions=(association,),
                    body_activation_origins=(origin,))
    return program, model, {**details, 'selected': selected, 'scopes': scopes,
                            'call_activation': call, 'body_drive_execution': association,
                            'body_activation_origin': origin}
