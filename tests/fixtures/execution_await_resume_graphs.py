"""Finite supplied captures of direct/await calls into one persistent B.

These are canonical declarations, not runtime recovery. Each ordinary callee
has its exact CallActivation; each body resume has its real preceding Suspend,
current entry port and first outcome. No Work or fictitious cut is inserted.
"""
from dataclasses import replace

from scar.ir.execution.calls import CallActivation
from scar.ir.execution.common import EvidencePoint, MissingEvidence
from scar.ir.execution.coordinates import (ControlTransfer, ExecutionRun,
    HostThreadInstance, InitialEntry, ProcessInstance, ResumeIngress)
from scar.ir.execution.ids import (CallActivationID, HostThreadInstanceID,
    ProcessInstanceID, RegionActivationID, RunID)
from scar.ir.execution.model import ExecutionModel
from scar.ir.execution.resumables import BodyActivationOrigin, BodyDriveExecution
from scar.ir.execution.snapshot import snapshot_for
from tests.fixtures.execution_async_pipeline_graphs import _body_path
from tests.fixtures.execution_call_graphs import _activation
from tests.fixtures.program_await_resume_graphs import await_resume_program, with_final_adapter


def await_resume_execution(*, zero_cut=False, instances=1, extra_creation=True,
                           attach_final_adapter=True):
    """Return ``(program, model, details)`` with original current/cut endpoints.

    Each root invocation evaluates both static Create sites again. Its own B
    activation is shared only by that invocation's direct and await drivers.
    """
    if type(instances) is not int or instances < 1:
        raise ValueError('instances must be a positive exact integer')
    program, static = await_resume_program(zero_cut=zero_cut, extra_creation=extra_creation)
    adapter_rows = ()
    if attach_final_adapter:
        program, adapter_rows = with_final_adapter(program, static)
    source = MissingEvidence('supplied direct/await multi-cut occurrence associations; no native runtime proof')
    run = RunID('await.resume.run')
    process = ProcessInstanceID('await.resume.process')
    thread = HostThreadInstanceID('await.resume.thread')
    point = EvidencePoint(run, process, source)
    names = ('activations', 'segments', 'visits', 'operations', 'values', 'uses', 'transfers')
    combined = {name: [] for name in names}
    calls, drives, origins, examples = [], [], [], []

    def append(rows, *, activation=True):
        for name in names:
            if name != 'activations' or activation:
                combined[name].extend(rows[name])

    operations = {operation.id: operation for operation in program.operations}
    for instance in range(instances):
        prefix = f'await.resume.instance.{instance}'
        caller_rows, caller_activation, caller_visits, caller_operations = _activation(
            program, static['caller'].id, static['caller_path'], prefix + '.caller', point, thread)
        append(caller_rows)
        driver_scopes, instance_calls = [], []
        for ordinal, item in enumerate(static['drivers']):
            rows, activation, visits, occurrence_map = _activation(program,
                item['driver_region'].id, item['path'], prefix + f'.driver.{ordinal}', point, thread)
            append(rows)
            driver_scopes.append((activation, visits, occurrence_map))
            call = CallActivation(CallActivationID(prefix + f'.call.{ordinal}'),
                caller_operations[item['caller_call'].id], activation, visits[0],
                occurrence_map[item['host_terminal'].id], source)
            calls.append(call)
            instance_calls.append(call)

        body_activation = RegionActivationID(prefix + '.body')
        previous_suspend = None
        body_entries, body_segments, body_occurrences, instance_drives = [], [], [], []
        body_literals = set()
        region = static['body']
        for ordinal, item in enumerate(static['drivers']):
            target = operations[item['outcome_source']]
            if ordinal == 0:
                start, ingress = region.entry, InitialEntry(point)
            else:
                resume = item['drive'].target
                previous = operations[static['drivers'][ordinal - 1]['outcome_source']]
                if resume.suspend != previous.id:
                    raise AssertionError('this resume must name the immediately preceding real cut')
                start = previous.terminator.successors[resume.successor].block
                ingress = ResumeIngress(previous_suspend, resume.successor, point)
            path = _body_path(program, region, start, target.id)
            rows, temporary, visits, occurrence_map = _activation(program, region.id,
                path, prefix + f'.body.segment.{ordinal}', point, thread)
            segment = replace(rows['segments'][0], activation=body_activation, ingress=ingress)
            rows['segments'] = (segment,)
            rows['activations'] = tuple(replace(row, id=body_activation) for row in rows['activations'])
            values = []
            for value in rows['values']:
                if value.origin == temporary:
                    if value.value in body_literals:
                        continue
                    body_literals.add(value.value)
                    value = replace(value, origin=body_activation)
                values.append(value)
            rows['values'] = tuple(values)
            append(rows, activation=ordinal == 0)
            if ordinal:
                combined['transfers'].append(ControlTransfer(previous_suspend,
                    item['drive'].target.successor, visits[0]))
            body_entries.append(visits[0])
            body_segments.append(segment.id)
            body_occurrences.append(occurrence_map)
            outcome = occurrence_map[target.id]
            driver_map = driver_scopes[ordinal][2]
            association = BodyDriveExecution(driver_map[item['drive'].operation], body_activation,
                                             visits[0], outcome, source)
            drives.append(association)
            instance_drives.append(association)
            previous_suspend = outcome
        creation = caller_operations[static['primary_creation'].operation]
        origin = BodyActivationOrigin(body_activation, creation, source)
        origins.append(origin)
        examples.append({'caller_activation': caller_activation, 'caller_visits': caller_visits,
            'caller_operations': caller_operations, 'driver_scopes': tuple(driver_scopes),
            'call_activations': tuple(instance_calls), 'body_activation': body_activation,
            'body_entries': tuple(body_entries), 'body_segments': tuple(body_segments),
            'body_occurrences': tuple(body_occurrences), 'body_drives': tuple(instance_drives),
            'body_origin': origin, 'creation': creation,
            'decoy_creation': None if static['decoy_creation'] is None else
                              caller_operations[static['decoy_creation'].operation],
            'acquisition': caller_operations[static['get'].id],
            'extraction': caller_operations[static['extract'].id],
            'final': caller_operations[static['final'].id]})
    model = ExecutionModel(snapshot_for(program),
        runs=(ExecutionRun(run, source),),
        processes=(ProcessInstance(process, run, 303, source),),
        threads=(HostThreadInstance(thread, process, 404, source),),
        **{name: tuple(rows) for name, rows in combined.items()},
        call_activations=tuple(calls), body_drive_executions=tuple(drives),
        body_activation_origins=tuple(origins))
    return program, model, {'static': static, 'instances': tuple(examples), 'source': source,
                            'point': point, 'adapter_rows': adapter_rows, 'zero_cut': zero_cut}


__all__ = ['await_resume_execution']
