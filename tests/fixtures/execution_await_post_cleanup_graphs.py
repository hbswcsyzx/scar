"""Actual synchronous D cleanup paths over an unchanged two-cut body B.

Every original caller, driver, body segment, and extraction implementation gets
its own supplied occurrences.  D never acquires a resumption segment.  Missing
evidence is local to one root invocation, even when another invocation executes
the same canonical pending constructor and dispatch.
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
from scar.ir.program.model import ExitKind, OperationResult
from tests.fixtures.execution_async_pipeline_graphs import _body_path
from tests.fixtures.execution_await_outcome_graphs import _omit_suffix
from tests.fixtures.execution_call_graphs import _activation
from tests.fixtures.program_async_pipeline_graphs import _selected_path
from tests.fixtures.program_await_post_cleanup_graphs import await_post_cleanup_program


_TABLES = ('activations', 'segments', 'visits', 'operations', 'values', 'uses', 'transfers')


def await_post_cleanup_execution(mode='preserve', depth=1, instances=2,
                                 constructor_raised=False, missing_payload_use=None,
                                 missing_dispatch=None):
    """Return ``(program, model, details)`` with this D's selected C1 route.

    ``constructor_raised`` selects the conversion's real own RAISE completion;
    its other completion remains an independent, unselected static obligation.
    A replacement Return takes this D call's genuine NORMAL caller edge and
    does not fabricate an extraction operation or call in that execution.
    """
    if mode not in ('preserve', 'replace_raise', 'replace_return'):
        raise ValueError('the supplied captures cover preservation and actual replacements')
    if type(instances) is not int or instances < 1:
        raise ValueError('instances must be a positive exact integer')
    if type(constructor_raised) is not bool:
        raise TypeError('constructor_raised must be an exact bool')
    for ordinal in (missing_payload_use, missing_dispatch):
        if ordinal is not None and (type(ordinal) is not int or not 0 <= ordinal < instances):
            raise ValueError('missing evidence must select one exact captured root invocation')
    program, static = await_post_cleanup_program(mode=mode, depth=depth)
    selected_kind = ExitKind.RAISE if constructor_raised else ExitKind.NORMAL
    leg, = tuple(item for item in static['post_cleanup']['legs'] if item['kind'] is selected_kind)
    driver_choices = {edge.operation: edge.successor_index for edge in leg['choices']}
    driver_path = _selected_path(program, static['post_cleanup']['driver_region'], driver_choices)
    current_definition = leg['replacement_pending'] or leg['pending']
    canonical_values = {value.id: value for value in program.values}
    constructor = canonical_values[current_definition.value].origin
    if type(constructor) is not OperationResult:
        raise AssertionError('the active pending token must have its original canonical constructor')

    source = MissingEvidence('supplied synchronous post-conversion C1 occurrences; native/runtime behavior unproved')
    run = RunID('await.post-cleanup')
    process, thread = ProcessInstanceID('await.post-cleanup'), HostThreadInstanceID('await.post-cleanup')
    point = EvidencePoint(run, process, source)
    combined = {name: [] for name in _TABLES}
    calls, drives, origins, examples = [], [], [], []
    operations = {operation.id: operation for operation in program.operations}

    def append(rows, *, activation=True):
        for name in _TABLES:
            if name != 'activations' or activation:
                combined[name].extend(rows[name])

    for instance in range(instances):
        prefix = f'await.post-cleanup.instance.{instance}'
        rows, caller, caller_visits, caller_operations = _activation(program,
            static['caller'].id, static['caller_path'], prefix + '.caller', point, thread)
        append(rows)
        driver_scopes, instance_calls = [], []
        for ordinal, item in enumerate(static['drivers']):
            path = driver_path if ordinal == len(static['drivers']) - 1 else item['path']
            rows, activation, visits, mapped = _activation(program,
                item['driver_region'].id, path, prefix + f'.driver.{ordinal}', point, thread)
            append(rows)
            terminal = leg['terminals'][0] if ordinal == len(static['drivers']) - 1 else item['host_terminal']
            association = CallActivation(CallActivationID(prefix + f'.driver.call.{ordinal}'),
                caller_operations[item['caller_call'].id], activation, visits[0], mapped[terminal.id], source)
            calls.append(association)
            instance_calls.append(association)
            driver_scopes.append((activation, visits, mapped))

        body_activation = RegionActivationID(prefix + '.body')
        body_entries, body_segments, body_occurrences, instance_drives = [], [], [], []
        prior_outcome, literal_ids = None, set()
        for ordinal, item in enumerate(static['drivers']):
            if ordinal == 0:
                start, ingress = static['body'].entry, InitialEntry(point)
            else:
                resume = item['drive'].target
                prior = operations[static['drivers'][ordinal - 1]['outcome_source']]
                if resume.suspend != prior.id:
                    raise AssertionError('this drive must resume the preceding original body cut')
                start = prior.terminator.successors[resume.successor].block
                ingress = ResumeIngress(prior_outcome, resume.successor, point)
            path = _body_path(program, static['body'], start, item['outcome_source'])
            rows, temporary, visits, mapped = _activation(program, static['body'].id,
                path, prefix + f'.body.segment.{ordinal}', point, thread)
            rows['activations'] = tuple(replace(row, id=body_activation) for row in rows['activations'])
            rows['segments'] = tuple(replace(row, activation=body_activation, ingress=ingress)
                                     for row in rows['segments'])
            literal_values = []
            for actual in rows['values']:
                if actual.origin == temporary:
                    if actual.value in literal_ids:
                        continue
                    literal_ids.add(actual.value)
                    actual = replace(actual, origin=body_activation)
                literal_values.append(actual)
            rows['values'] = tuple(literal_values)
            append(rows, activation=ordinal == 0)
            if ordinal:
                combined['transfers'].append(ControlTransfer(prior_outcome,
                    item['drive'].target.successor, visits[0]))
            outcome = mapped[item['outcome_source']]
            association = BodyDriveExecution(driver_scopes[ordinal][2][item['drive'].operation],
                body_activation, visits[0], outcome, source)
            drives.append(association)
            instance_drives.append(association)
            body_entries.append(visits[0])
            body_segments.append(rows['segments'][0].id)
            body_occurrences.append(mapped)
            prior_outcome = outcome
        creation = caller_operations[static['primary_creation'].operation]
        origin = BodyActivationOrigin(body_activation, creation, source)
        origins.append(origin)

        frames, implementation_calls = [], []
        if mode != 'replace_return':
            for ordinal, definition in enumerate(static['stage_records']):
                rows, activation, visits, mapped = _activation(program, definition['region'].id,
                    definition['paths'][ExitKind.NORMAL], prefix + f'.implementation.{ordinal}', point, thread)
                append(rows)
                caller_operation = (caller_operations[static['extract'].id] if ordinal == 0 else
                    frames[-1]['operations'][static['stage_records'][ordinal - 1]['operation'].id])
                completion = mapped[definition['terminals'][ExitKind.NORMAL].id]
                association = CallActivation(CallActivationID(prefix + f'.implementation.call.{ordinal}'),
                    caller_operation, activation, visits[0], completion, source)
                calls.append(association)
                implementation_calls.append(association)
                frames.append({'definition': definition, 'activation': activation,
                    'entry': visits[0], 'completion': completion, 'operations': mapped})

        driver_map = driver_scopes[-1][2]
        final_block = next(block for block in static['caller'].blocks if block.id == static['caller_path'][-1][0])
        final = caller_operations[final_block.operations[-1]]
        examples.append({'caller_activation': caller, 'caller_visits': caller_visits,
            'caller_operations': caller_operations, 'driver_scopes': tuple(driver_scopes),
            'call_activations': tuple(instance_calls), 'body_activation': body_activation,
            'body_entries': tuple(body_entries), 'body_segments': tuple(body_segments),
            'body_occurrences': tuple(body_occurrences), 'body_drives': tuple(instance_drives),
            'body_origin': origin, 'creation': creation, 'advance': instance_calls[-1].caller,
            'conversion': driver_map[static['conversion'].id], 'body_outcome': instance_drives[-1].outcome,
            'driver_terminal': driver_map[leg['terminals'][0].id], 'driver_activation': driver_scopes[-1][0],
            'selected_leg': leg, 'pending_definition': current_definition,
            'pending_constructor': driver_map[constructor.operation],
            'pending_payload_use': current_definition.payload,
            'dispatch': driver_map[leg['dispatch'].id],
            'cleanup_actions': tuple(driver_map[operation.id] for operation in leg['action_operations']),
            'extraction': None if mode == 'replace_return' else caller_operations[static['extract'].id],
            'final': final, 'implementation_frames': tuple(frames),
            'implementation_calls': tuple(implementation_calls)})

    model = ExecutionModel(snapshot_for(program),
        runs=(ExecutionRun(run, source),),
        processes=(ProcessInstance(process, run, 707, source),),
        threads=(HostThreadInstance(thread, process, 808, source),),
        **{name: tuple(rows) for name, rows in combined.items()},
        call_activations=tuple(calls), body_drive_executions=tuple(drives),
        body_activation_origins=tuple(origins))
    if missing_payload_use is not None:
        example = examples[missing_payload_use]
        model = replace(model, uses=tuple(row for row in model.uses
            if (row.operation, row.use) != (example['pending_constructor'], example['pending_payload_use'])))
    if missing_dispatch is not None:
        example = examples[missing_dispatch]
        model = _omit_suffix(program, model, example['dispatch'])
        expected_call = example['call_activations'][-1]
        changed = replace(expected_call, completion=Unresolved('this D dispatch and terminal were not captured', point))
        model = replace(model, call_activations=tuple(changed if row.id == expected_call.id else row
                                                    for row in model.call_activations))
    return program, model, {'static': static, 'instances': tuple(examples),
        'source': source, 'point': point, 'mode': mode, 'constructor_raised': constructor_raised,
        'drive_outcome': static['drive_outcome'], 'missing_payload_use': missing_payload_use,
        'missing_dispatch': missing_dispatch}


__all__ = ['await_post_cleanup_execution']
