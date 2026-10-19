"""Supplied occurrences of one persistent C1 body and its await consumers."""
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
from scar.ir.program.cleanup import CleanupRouteTerminator
from scar.ir.program.control import PendingDispatchTerminator
from scar.ir.program.model import ExitKind, OperationResult, TerminatorKind
from tests.fixtures.execution_async_pipeline_graphs import _body_path
from tests.fixtures.execution_await_outcome_graphs import _omit_suffix
from tests.fixtures.execution_call_graphs import _activation
from tests.fixtures.program_async_pipeline_graphs import _selected_path
from tests.fixtures.program_await_cleanup_final_graphs import await_cleanup_final_program


_TABLES = ('activations', 'segments', 'visits', 'operations', 'values', 'uses', 'transfers')


def await_cleanup_final_execution(body_raised=False, depth=1, instances=2, child_raised=False,
                                  missing_payload_use=None, missing_dispatch=None,
                                  missing_second_resume=None):
    if type(instances) is not int or instances < 1:
        raise ValueError('instances must be a positive exact integer')
    if type(child_raised) is not bool:
        raise TypeError('child_raised must be exact bool')
    for index in (missing_payload_use, missing_dispatch, missing_second_resume):
        if index is not None and (type(index) is not int or not 0 <= index < instances):
            raise ValueError('missing capture must select this instance')
    program, static = await_cleanup_final_program(body_raised=body_raised, depth=depth)
    source = MissingEvidence('supplied C1/await source-to-terminal associations; native execution unproved')
    run, process, thread = RunID('await.cleanup'), ProcessInstanceID('await.cleanup'), HostThreadInstanceID('await.cleanup')
    point = EvidencePoint(run, process, source)
    combined = {name: [] for name in _TABLES}
    calls, drives, origins, examples = [], [], [], []
    operations = {op.id: op for op in program.operations}
    values = {value.id: value for value in program.values}
    ports = {port.id: port for port in program.control_ports}
    wanted = 'RAISE' if body_raised else 'RETURN'
    definition, = tuple(row for row in program.pending_completions if ports[row.port].kind.value == wanted)
    constructor = values[definition.value].origin
    if type(constructor) is not OperationResult:
        raise AssertionError('the selected pending payload keeps its original constructor')

    def append(rows, activation=True):
        for name in _TABLES:
            if activation or name != 'activations':
                combined[name].extend(rows[name])

    for instance in range(instances):
        prefix = f'await.cleanup.instance.{instance}'
        choices = {next(block for block in static['caller'].blocks if block.id == block_id).operations[-1]: edge
                   for block_id, edge in static['caller_path'] if edge is not None}
        if not body_raised and child_raised:
            choices[static['extract'].id] = next(number for number, edge in enumerate(
                static['extract'].terminator.successors) if edge.kind is ExitKind.RAISE)
        caller_path = _selected_path(program, static['caller'], choices)
        rows, caller, visits, caller_ops = _activation(program, static['caller'].id,
            caller_path, prefix + '.caller', point, thread)
        append(rows)
        driver_scopes, instance_calls = [], []
        for ordinal, item in enumerate(static['drivers']):
            rows, activation, entered, mapped = _activation(program, item['driver_region'].id,
                item['path'], prefix + f'.driver.{ordinal}', point, thread)
            append(rows)
            association = CallActivation(CallActivationID(prefix + f'.call.{ordinal}'),
                caller_ops[item['caller_call'].id], activation, entered[0], mapped[item['host_terminal'].id], source)
            calls.append(association)
            instance_calls.append(association)
            driver_scopes.append((activation, entered, mapped))
        body_activation, previous = RegionActivationID(prefix + '.body'), None
        body_entries, body_segments, body_maps, instance_drives, body_visits = [], [], [], [], []
        literal_ids = set()
        for ordinal, item in enumerate(static['drivers']):
            if ordinal == 0:
                start, ingress = static['body'].entry, InitialEntry(point)
            else:
                resume = item['drive'].target
                prior = operations[static['drivers'][ordinal - 1]['outcome_source']]
                if resume.suspend != prior.id:
                    raise AssertionError('the current drive must resume the preceding real cut')
                start = prior.terminator.successors[resume.successor].block
                ingress = ResumeIngress(previous, resume.successor, point)
            path = _body_path(program, static['body'], start, item['outcome_source'])
            # Route has distinct typed port edges to the same merge block.
            # The generic block-path helper cannot choose their occurrence;
            # keep this supplied capture's actual current pending port.
            body_blocks = {block.id: block for block in static['body'].blocks}
            selected_port = (definition.port if ordinal == 2 else next(port.id
                for port in program.control_ports if port.kind.value == 'RETURN'))
            path = tuple((block, next(number for number, edge in enumerate(term.successors)
                         if edge.port == selected_port))
                if type(term := operations[body_blocks[block].operations[-1]].terminator)
                    in (CleanupRouteTerminator, PendingDispatchTerminator) else (block, selected)
                for block, selected in path)
            rows, temporary, entered, mapped = _activation(program, static['body'].id,
                path, prefix + f'.body.segment.{ordinal}', point, thread)
            rows['activations'] = tuple(replace(row, id=body_activation) for row in rows['activations'])
            rows['segments'] = tuple(replace(row, activation=body_activation, ingress=ingress)
                                     for row in rows['segments'])
            kept = []
            for value in rows['values']:
                if value.origin == temporary:
                    if value.value in literal_ids:
                        continue
                    literal_ids.add(value.value)
                    value = replace(value, origin=body_activation)
                kept.append(value)
            rows['values'] = tuple(kept)
            append(rows, activation=ordinal == 0)
            if ordinal:
                combined['transfers'].append(ControlTransfer(previous, item['drive'].target.successor, entered[0]))
            current = mapped[item['outcome_source']]
            association = BodyDriveExecution(driver_scopes[ordinal][2][item['drive'].operation],
                body_activation, entered[0], current, source)
            drives.append(association)
            instance_drives.append(association)
            body_entries.append(entered[0])
            body_segments.append(rows['segments'][0].id)
            body_visits.append(entered)
            body_maps.append(mapped)
            previous = current
        creation = caller_ops[static['primary_creation'].operation]
        origin = BodyActivationOrigin(body_activation, creation, source)
        origins.append(origin)
        frames, implementation_calls = [], []
        if not body_raised:
            selected_kind = ExitKind.RAISE if child_raised else ExitKind.NORMAL
            for number, record in enumerate(static['stage_records']):
                rows, activation, entered, mapped = _activation(program, record['region'].id,
                    record['paths'][selected_kind], prefix + f'.implementation.{number}', point, thread)
                append(rows)
                completion = mapped[record['terminals'][selected_kind].id]
                caller_occurrence = (caller_ops[static['extract'].id] if number == 0 else
                    frames[-1]['operations'][static['stage_records'][number - 1]['operation'].id])
                association = CallActivation(CallActivationID(prefix + f'.implementation.call.{number}'),
                    caller_occurrence, activation, entered[0], completion, source)
                calls.append(association)
                implementation_calls.append(association)
                frames.append({'definition': record, 'activation': activation, 'entry': entered[0],
                    'operations': mapped, 'completion': completion})
        constructor_occurrence = next(mapped[constructor.operation] for mapped in body_maps
                                      if constructor.operation in mapped)
        dispatch_occurrence = body_maps[-1][static['pending_projection'].id]
        final_static = operations[next(block for block in static['caller'].blocks
                                      if block.id == caller_path[-1][0]).operations[-1]]
        examples.append({'caller_activation': caller, 'caller_operations': caller_ops,
            'caller_visits': visits, 'driver_scopes': tuple(driver_scopes),
            'call_activations': tuple(instance_calls), 'body_activation': body_activation,
            'body_entries': tuple(body_entries), 'body_segments': tuple(body_segments),
            'body_visits': tuple(body_visits), 'body_occurrences': tuple(body_maps),
            'body_drives': tuple(instance_drives), 'body_origin': origin, 'creation': creation,
            'advance': instance_calls[-1].caller, 'body_outcome': instance_drives[-1].outcome,
            'extraction': None if body_raised else caller_ops[static['extract'].id],
            'final': caller_ops[final_static.id], 'final_definition': final_static,
            'pending_constructor': constructor_occurrence, 'pending_definition': definition,
            'pending_payload_use': definition.payload, 'dispatch': dispatch_occurrence,
            'implementation_frames': tuple(frames), 'implementation_calls': tuple(implementation_calls)})
    model = ExecutionModel(snapshot_for(program), runs=(ExecutionRun(run, source),),
        processes=(ProcessInstance(process, run, 505, source),),
        threads=(HostThreadInstance(thread, process, 606, source),),
        **{name: tuple(rows) for name, rows in combined.items()}, call_activations=tuple(calls),
        body_drive_executions=tuple(drives), body_activation_origins=tuple(origins))
    if missing_payload_use is not None:
        example = examples[missing_payload_use]
        model = replace(model, uses=tuple(row for row in model.uses if
            (row.operation, row.use) != (example['pending_constructor'], definition.payload)))
    if missing_dispatch is not None:
        example = examples[missing_dispatch]
        model = _omit_suffix(program, model, example['dispatch'])
        model = replace(model, body_drive_executions=tuple(replace(row,
            outcome=Unresolved('dispatch and its terminal were not captured', point))
            if row.drive == example['body_drives'][-1].drive else row for row in model.body_drive_executions))
    if missing_second_resume is not None:
        example = examples[missing_second_resume]
        omitted = set(example['body_visits'][-1])
        identities = {row.id for row in model.operations if row.visit in omitted}
        model = replace(model,
            segments=tuple(row for row in model.segments if row.id != example['body_segments'][-1]),
            visits=tuple(row for row in model.visits if row.id not in omitted),
            operations=tuple(row for row in model.operations if row.id not in identities),
            values=tuple(row for row in model.values if row.origin not in omitted and row.origin not in identities),
            uses=tuple(row for row in model.uses if row.operation not in identities),
            transfers=tuple(row for row in model.transfers if row.operation not in identities and row.target not in omitted),
            body_drive_executions=tuple(replace(row,
                entry=Unresolved('second Resume ingress was not captured', point),
                outcome=Unresolved('second Resume outcome was not captured', point))
                if row.drive == example['body_drives'][-1].drive else row for row in model.body_drive_executions))
    return program, model, {'static': static, 'instances': tuple(examples), 'source': source,
        'point': point, 'body_raised': body_raised, 'child_raised': child_raised,
        'drive_outcome': static['drive_outcome'], 'missing_payload_use': missing_payload_use,
        'missing_dispatch': missing_dispatch, 'missing_second_resume': missing_second_resume}


__all__ = ['await_cleanup_final_execution']
