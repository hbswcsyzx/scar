"""Exact supplied captures of the general source-to-terminal canonical graph.

Each root invocation owns its own acquisition helper, successful method Create,
one persistent B activation and exact extraction child activations.  Labels do
not supply identity evidence; these are declarations with all proof flags off.
"""
from dataclasses import replace

from scar.ir.execution.calls import CallActivation
from scar.ir.execution.common import EvidencePoint, MissingEvidence, Unresolved
from scar.ir.execution.coordinates import (
    ControlTransfer, ExecutionRun, HostThreadInstance, InitialEntry,
    ProcessInstance, ResumeIngress,
)
from scar.ir.execution.ids import (
    CallActivationID, HostThreadInstanceID, ProcessInstanceID, RegionActivationID, RunID,
)
from scar.ir.execution.model import ExecutionModel
from scar.ir.execution.resumables import BodyActivationOrigin, BodyDriveExecution
from scar.ir.execution.snapshot import snapshot_for
from scar.ir.program.model import ExitKind
from tests.fixtures.execution_async_pipeline_graphs import _body_path
from tests.fixtures.execution_call_graphs import _activation
from tests.fixtures.program_async_pipeline_graphs import _selected_path
from tests.fixtures.program_await_general_final_graphs import await_general_final_program


_TABLES = ('activations', 'segments', 'visits', 'operations', 'values', 'uses', 'transfers')


def await_general_final_execution(*, zero_cut=True, depth=1, instances=2,
        child_raised=False, missing_acquisition_call=None, missing_helper_return=None,
        missing_child_call=None, missing_child_use=None):
    """Return one graph/model with independent complete or partial instances.

    Missing-call switches omit only the indicated canonical association;
    missing terminal capture omits its original occurrence/Uses and declares
    completion unresolved.  An intact second instance cannot supply either.
    """
    if type(instances) is not int or instances < 1:
        raise ValueError('instances must be a positive exact integer')
    if type(child_raised) is not bool:
        raise TypeError('child_raised must be an exact bool')
    for name, value in (('missing_acquisition_call', missing_acquisition_call),
                        ('missing_helper_return', missing_helper_return)):
        if value is not None and (type(value) is not int or not 0 <= value < instances):
            raise ValueError(name + ' must name a captured instance')
    for name, item, stages in (('missing_child_call', missing_child_call, depth - 1),
                                ('missing_child_use', missing_child_use, depth)):
        if item is not None and (type(item) is not tuple or len(item) != 2
                or any(type(index) is not int for index in item)
                or not 0 <= item[0] < instances or not 0 <= item[1] < stages):
            raise ValueError(name + ' must name an exact (instance, stage) pair')

    program, static = await_general_final_program(zero_cut=zero_cut, depth=depth)
    source = MissingEvidence('supplied general-await full chain; no native or runtime identity proof')
    run = RunID('await.general.final.run')
    process = ProcessInstanceID('await.general.final.process')
    thread = HostThreadInstanceID('await.general.final.thread')
    point = EvidencePoint(run, process, source)
    combined = {name: [] for name in _TABLES}
    calls, drives, origins, examples = [], [], [], []
    operations = {operation.id: operation for operation in program.operations}
    selected_kind = ExitKind.RAISE if child_raised else ExitKind.NORMAL
    caller_choices = {**static['caller_choices'], static['extract'].id:
        next(index for index, edge in enumerate(static['extract'].terminator.successors)
             if edge.kind is selected_kind)}
    caller_path = _selected_path(program, static['caller'], caller_choices)

    def append(rows, *, first=True):
        for name in _TABLES:
            if name != 'activations' or first:
                combined[name].extend(rows[name])

    for number in range(instances):
        prefix = f'await.general.final.instance.{number}'
        rows, caller_activation, caller_visits, caller_map = _activation(program,
            static['caller'].id, caller_path, prefix + '.caller', point, thread)
        append(rows)
        rows, helper_activation, helper_visits, helper_map = _activation(program,
            static['helper'].id, static['helper_path'], prefix + '.acquisition', point, thread)
        append(rows)
        helper_completion = helper_map[static['helper_return'].id]
        acquisition_call = CallActivation(CallActivationID(prefix + '.acquire'),
            caller_map[static['get'].id], helper_activation, helper_visits[0],
            helper_completion, source)
        if missing_helper_return == number:
            combined['operations'] = [row for row in combined['operations'] if row.id != helper_completion]
            combined['uses'] = [row for row in combined['uses'] if row.operation != helper_completion]
            combined['values'] = [row for row in combined['values'] if row.origin != helper_completion]
            acquisition_call = replace(acquisition_call, completion=Unresolved(
                'this acquisition helper Return occurrence was not captured', point))
        if missing_acquisition_call != number:
            calls.append(acquisition_call)

        driver_scopes, driver_calls = [], []
        for ordinal, item in enumerate(static['drivers']):
            rows, activation, visits, occurrence_map = _activation(program,
                item['driver_region'].id, item['path'], prefix + f'.driver.{ordinal}', point, thread)
            append(rows)
            driver_scopes.append((activation, visits, occurrence_map))
            call = CallActivation(CallActivationID(prefix + f'.drive.{ordinal}'),
                caller_map[item['caller_call'].id], activation, visits[0],
                occurrence_map[item['host_terminal'].id], source)
            calls.append(call)
            driver_calls.append(call)

        body_activation = RegionActivationID(prefix + '.body')
        previous_suspend = None
        body_literals = set()
        body_entries, body_segments, body_maps, body_drives = [], [], [], []
        region = static['body']
        for ordinal, item in enumerate(static['drivers']):
            outcome = operations[item['outcome_source']]
            if ordinal == 0:
                start, ingress = region.entry, InitialEntry(point)
            else:
                resume = item['drive'].target
                previous = operations[static['drivers'][ordinal - 1]['outcome_source']]
                if resume.suspend != previous.id:
                    raise AssertionError('Resume must name this persistent body previous cut')
                start = previous.terminator.successors[resume.successor].block
                ingress = ResumeIngress(previous_suspend, resume.successor, point)
            path = _body_path(program, region, start, outcome.id)
            rows, temporary, visits, occurrence_map = _activation(program, region.id,
                path, prefix + f'.body.segment.{ordinal}', point, thread)
            segment = replace(rows['segments'][0], activation=body_activation, ingress=ingress)
            rows['segments'] = (segment,)
            rows['activations'] = tuple(replace(row, id=body_activation) for row in rows['activations'])
            actual_values = []
            for value in rows['values']:
                if value.origin == temporary:
                    if value.value in body_literals:
                        continue
                    body_literals.add(value.value)
                    value = replace(value, origin=body_activation)
                actual_values.append(value)
            rows['values'] = tuple(actual_values)
            append(rows, first=ordinal == 0)
            if ordinal:
                combined['transfers'].append(ControlTransfer(previous_suspend,
                    item['drive'].target.successor, visits[0]))
            body_entries.append(visits[0])
            body_segments.append(segment.id)
            body_maps.append(occurrence_map)
            actual_outcome = occurrence_map[outcome.id]
            association = BodyDriveExecution(driver_scopes[ordinal][2][item['drive'].operation],
                body_activation, visits[0], actual_outcome, source)
            drives.append(association)
            body_drives.append(association)
            previous_suspend = actual_outcome
        creation = helper_map[static['helper_create'].operation]
        origin = BodyActivationOrigin(body_activation, creation, source)
        origins.append(origin)

        frames = []
        for ordinal, definition in enumerate(static['stage_records']):
            rows, activation, visits, occurrence_map = _activation(program,
                definition['region'].id, definition['paths'][selected_kind],
                prefix + f'.implementation.{ordinal}', point, thread)
            append(rows)
            frames.append({'definition': definition, 'activation': activation,
                'visits': visits, 'operations': occurrence_map, 'entry': visits[0],
                'completion': occurrence_map[definition['terminals'][selected_kind].id],
                'terminal': definition['terminals'][selected_kind]})
        root_call = CallActivation(CallActivationID(prefix + '.implementation.root'),
            caller_map[static['extract'].id], frames[0]['activation'],
            frames[0]['entry'], frames[0]['completion'], source)
        calls.append(root_call)
        nested_calls = []
        for ordinal, (parent, child) in enumerate(zip(frames, frames[1:])):
            link = CallActivation(CallActivationID(prefix + f'.implementation.{ordinal}.child'),
                parent['operations'][parent['definition']['operation'].id], child['activation'],
                child['entry'], child['completion'], source)
            nested_calls.append(link)
            if missing_child_call != (number, ordinal):
                calls.append(link)
        if missing_child_use is not None and missing_child_use[0] == number:
            frame = frames[missing_child_use[1]]
            terminal_use = frame['definition']['terminal_payloads'][selected_kind]
            terminal_occurrence = frame['operations'][terminal_use.operation]
            combined['uses'] = [row for row in combined['uses']
                if (row.operation, row.use) != (terminal_occurrence, terminal_use.use)]
        final_operation = operations[next(block for block in static['caller'].blocks
            if block.id == caller_path[-1][0]).operations[-1]]
        examples.append({'caller_activation': caller_activation, 'caller_visits': caller_visits,
            'caller_operations': caller_map, 'caller_path': caller_path,
            'helper_activation': helper_activation, 'helper_visits': helper_visits,
            'helper_operations': helper_map, 'acquisition_call': acquisition_call,
            'driver_scopes': tuple(driver_scopes), 'call_activations': tuple(driver_calls),
            'body_activation': body_activation, 'body_entries': tuple(body_entries),
            'body_segments': tuple(body_segments), 'body_occurrences': tuple(body_maps),
            'body_drives': tuple(body_drives), 'body_origin': origin, 'creation': creation,
            'decoy_creation': caller_map[static['outer_creations'][0].operation],
            'acquisition': caller_map[static['get'].id],
            'advance': caller_map[static['calls'][-1].id],
            'conversion': driver_scopes[-1][2][static['conversion'].id],
            'driver_terminal': driver_calls[-1].completion,
            'body_outcome': body_drives[-1].outcome,
            'extraction': caller_map[static['extract'].id],
            'final': caller_map[final_operation.id],
            'implementation_frames': tuple(frames), 'implementation_root_call': root_call,
            'implementation_nested_calls': tuple(nested_calls), 'implementation_kind': selected_kind})

    model = ExecutionModel(snapshot_for(program), runs=(ExecutionRun(run, source),),
        processes=(ProcessInstance(process, run, 303, source),),
        threads=(HostThreadInstance(thread, process, 404, source),),
        **{name: tuple(rows) for name, rows in combined.items()},
        call_activations=tuple(calls), body_drive_executions=tuple(drives),
        body_activation_origins=tuple(origins))
    return program, model, {'static': static, 'instances': tuple(examples),
        'implementation_instances': tuple(examples), 'source': source, 'point': point,
        'adapter_rows': static['final_rows'], 'zero_cut': zero_cut, 'depth': depth,
        'child_raised': child_raised, 'drive_outcome': static['drive_outcome'],
        'missing_acquisition_call': missing_acquisition_call,
        'missing_helper_return': missing_helper_return,
        'missing_child_call': missing_child_call, 'missing_child_use': missing_child_use}


__all__ = ['await_general_final_execution']
