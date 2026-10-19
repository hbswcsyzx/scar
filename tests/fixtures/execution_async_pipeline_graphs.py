"""One dynamic capture over the canonical three-request async pipeline.

The fixture supplies a single caller, one persistent body activation with three
segments, and three actual request-driver activations.  It does not assert that
the declared pipeline was produced by native source or occurred at runtime.
"""
from dataclasses import replace

from scar.ir.execution.calls import CallActivation
from scar.ir.execution.common import EvidencePoint, MissingEvidence
from scar.ir.execution.coordinates import (
    ControlTransfer,
    ExecutionRun,
    ExecutionSegment,
    HostThreadInstance,
    InitialEntry,
    ProcessInstance,
    ResumeIngress,
    RegionActivation,
)
from scar.ir.execution.ids import (
    BlockVisitID,
    CallActivationID,
    HostThreadInstanceID,
    OperationOccurrenceID,
    ProcessInstanceID,
    RegionActivationID,
    RunID,
)
from scar.ir.execution.model import ExecutionModel
from scar.ir.execution.resumables import BodyActivationOrigin, BodyDriveExecution
from scar.ir.execution.snapshot import snapshot_for
from scar.ir.program.ids import BlockID, OperationID
from scar.ir.program.model import ExitKind, TerminatorKind
from tests.fixtures.execution_call_graphs import _activation
from tests.fixtures.program_async_pipeline_graphs import async_pipeline_program, _selected_path


def _normal_edge(operation):
    return next(index for index, edge in enumerate(operation.terminator.successors)
                if edge.kind is ExitKind.NORMAL)


def _caller_path(program, details):
    """Follow the supplied create, request, and three exact call outcomes."""
    choices = {
        details['body']['create'].operation: _normal_edge(
            next(op for op in program.operations if op.id == details['body']['create'].operation)),
        details['request']['operation'].id: _normal_edge(details['request']['operation']),
    }
    for item in details['drivers']:
        call = item['caller_call']
        host_kind = item['host_terminal'].terminator.kind
        wanted = ExitKind.RAISE if host_kind is TerminatorKind.RAISE else ExitKind.NORMAL
        choices[call.id] = next(index for index, edge in enumerate(call.terminator.successors)
                                if edge.kind is wanted)

    blocks = {row.id: row for row in details['caller'].blocks}
    operations = {row.id: row for row in program.operations}
    cursor, path, seen = details['caller'].entry, [], set()
    while cursor not in seen:
        seen.add(cursor)
        block = blocks[cursor]
        operation = operations[block.operations[-1]]
        if operation.terminator.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE):
            path.append((cursor, None))
            return tuple(path)
        selected = choices.get(operation.id)
        if selected is None:
            raise AssertionError(f'caller route has no selected edge for {operation.id}')
        path.append((cursor, selected))
        cursor = operation.terminator.successors[selected].block
    raise AssertionError('the supplied caller route must be finite')


def _body_path(program, region, start, target):
    """Find one finite original CFG route from a segment entry to its outcome."""
    blocks = {row.id: row for row in region.blocks}
    operations = {row.id: row for row in program.operations}
    target_blocks = tuple(block.id for block in region.blocks if target in block.operations)
    if len(target_blocks) != 1:
        raise AssertionError(f'{target} must occur in exactly one body block')
    destination = target_blocks[0]
    if blocks[destination].operations[-1] != target:
        raise AssertionError(f'{target} must be the segment first-outcome terminator')

    pending, predecessor = [start], {start: None}
    while pending and destination not in predecessor:
        current = pending.pop(0)
        block = blocks[current]
        terminal = operations[block.operations[-1]]
        for index, edge in enumerate(terminal.terminator.successors):
            if edge.block not in predecessor:
                predecessor[edge.block] = (current, index)
                pending.append(edge.block)
    if destination not in predecessor:
        raise AssertionError(f'{target} is not reachable from the selected body segment entry')

    reverse = [destination]
    while reverse[-1] != start:
        previous, _ = predecessor[reverse[-1]]
        reverse.append(previous)
    route = list(reversed(reverse))
    result = []
    for current, following in zip(route, route[1:]):
        terminal = operations[blocks[current].operations[-1]]
        selected = next(index for index, edge in enumerate(terminal.terminator.successors)
                        if edge.block == following)
        result.append((current, selected))
    result.append((destination, None))
    return tuple(result)


def async_pipeline_execution(*, helper_stage=None, helper_raised=False):
    """Return ``(ProgramGraph, ExecutionModel, details)`` for one continuous B."""
    if type(helper_raised) is not bool:
        raise TypeError('helper_raised must be an exact bool')
    if helper_raised and helper_stage is None:
        raise ValueError('helper_raised requires helper_stage')
    program, static = async_pipeline_program(helper_stage=helper_stage)
    if helper_raised:
        # Select the real RAISE edge of the helper attached to this exact
        # SessionUpdate.  The capture ends at that call; later driver calls
        # remain declarations but are not invented as dynamic occurrences.
        item_index = helper_stage
        original = static['drivers'][item_index]
        operation = next(row for row in program.operations if row.id == original['update'].operation)
        raise_index = next(index for index, edge in enumerate(operation.terminator.successors)
                           if edge.kind.value == 'RAISE')
        choices = dict(original['path_choices'])
        choices[operation.id] = raise_index
        path = _selected_path(program, original['driver_region'], choices)
        block_ids = {row.id: row for row in original['driver_region'].blocks}
        terminal_id = block_ids[path[-1][0]].operations[-1]
        terminal = next(row for row in program.operations if row.id == terminal_id)
        changed = dict(original, path_choices=choices, path=path, host_terminal=terminal,
                       host_kind=terminal.terminator.kind)
        driver_rows = list(static['drivers'])
        driver_rows[item_index] = changed
        # A raised helper exits the persistent body call before any later
        # request/driver pair can occur in this captured invocation.
        static = dict(static, drivers=tuple(driver_rows[:item_index + 1]))
    source = MissingEvidence('hand-authored async occurrence links; no runtime/source proof')
    run, process = RunID('async.pipeline.run'), ProcessInstanceID('async.pipeline.process')
    thread = HostThreadInstanceID('async.pipeline.thread')
    point = EvidencePoint(run, process, source)
    names = ('activations', 'segments', 'visits', 'operations', 'values', 'uses', 'transfers')
    combined = {name: [] for name in names}

    def add_rows(rows, *, include_activation=True):
        for name in names:
            if name == 'activations' and not include_activation:
                continue
            combined[name].extend(rows[name])

    # The caller creates B and R once, then forwards those original values
    # through three separate calls.  Its selected call edge follows each
    # driver's actual host terminal kind (the third is a real RAISE).
    caller_rows, caller_activation, caller_visits, caller_ops = _activation(
        program, static['caller'].id, _caller_path(program, static),
        'async.pipeline.caller', point, thread)
    add_rows(caller_rows)

    call_rows = []
    driver_scopes = []
    driver_operation_maps = []
    for number, item in enumerate(static['drivers']):
        rows, activation, visits, operation_ids = _activation(
            program, item['driver_region'].id, item['path'],
            f'async.pipeline.driver.{number}', point, thread)
        add_rows(rows)
        driver_scopes.append((activation, visits, operation_ids))
        driver_operation_maps.append(operation_ids)
        call_occurrence = caller_ops[item['caller_call'].id]
        entry_visit = visits[0]
        completion = operation_ids[item['host_terminal'].id]
        call_rows.append(CallActivation(
            CallActivationID(f'async.pipeline.call.{number}'), call_occurrence,
            activation, entry_visit, completion, source))

    # Each body segment follows the exact static Resume successor selected by
    # the next driver's BodyResume record.  All segments share one activation.
    body = static['body']
    region = body['region']
    body_activation = RegionActivationID('async.pipeline.body')
    body_targets = (body['await1'], body['await2'], body['async_yield'])[:len(static['drivers'])]
    segment_rows, body_entries, body_operation_maps = [], [], []
    previous_suspend = None
    body_literal_values = set()
    for number, target_operation in enumerate(body_targets):
        if number == 0:
            start = region.entry
            ingress = InitialEntry(point)
        else:
            drive_target = static['drivers'][number]['drive'].target
            previous_static = body_targets[number - 1]
            if drive_target.suspend != previous_static.id:
                raise AssertionError('Resume target must name the exact preceding body suspension')
            start = previous_static.terminator.successors[drive_target.successor].block
            ingress = ResumeIngress(previous_suspend, drive_target.successor, point)
        path = _body_path(program, region, start, target_operation.id)
        rows, temporary_activation, visits, operation_ids = _activation(
            program, region.id, path, f'async.pipeline.body.segment.{number}', point, thread)
        segment = rows['segments'][0]
        segment = replace(segment, activation=body_activation, ingress=ingress)
        rows['segments'] = (segment,)
        rows['activations'] = tuple(replace(row, id=body_activation) for row in rows['activations'])
        body_values = []
        for row in rows['values']:
            if row.origin == temporary_activation:
                if row.value in body_literal_values:
                    continue
                body_literal_values.add(row.value)
                row = replace(row, origin=body_activation)
            body_values.append(row)
        rows['values'] = tuple(body_values)
        add_rows(rows, include_activation=(number == 0))
        if number:
            assert previous_suspend is not None
            combined['transfers'].append(ControlTransfer(
                previous_suspend, drive_target.successor, visits[0]))
        segment_rows.append(segment.id)
        body_entries.append(visits[0])
        body_operation_maps.append(operation_ids)
        previous_suspend = operation_ids[target_operation.id]

    drive_rows = []
    for number, item in enumerate(static['drivers']):
        driver_activation, _, driver_ops = driver_scopes[number]
        body_outcome = item['outcome'].source
        body_operation = body_targets[number]
        if body_outcome != body_operation.id:
            raise AssertionError('static outcome must select this segment first outcome')
        drive_rows.append(BodyDriveExecution(
            driver_ops[item['drive'].operation], body_activation, body_entries[number],
            body_operation_maps[number][body_outcome], source))

    creation_occurrence = caller_ops[body['create'].operation]
    origin = BodyActivationOrigin(body_activation, creation_occurrence, source)
    model = ExecutionModel(
        snapshot_for(program),
        runs=(ExecutionRun(run, source),),
        processes=(ProcessInstance(process, run, 101, source),),
        threads=(HostThreadInstance(thread, process, 202, source),),
        activations=tuple(combined['activations']), segments=tuple(combined['segments']),
        visits=tuple(combined['visits']), operations=tuple(combined['operations']),
        values=tuple(combined['values']), uses=tuple(combined['uses']),
        transfers=tuple(combined['transfers']), call_activations=tuple(call_rows),
        body_drive_executions=tuple(drive_rows), body_activation_origins=(origin,))

    driver_occurrences = tuple(driver_operation_maps[number][item['drive'].operation]
                               for number, item in enumerate(static['drivers']))
    update_occurrences = tuple(driver_operation_maps[number][item['update'].operation]
                               for number, item in enumerate(static['drivers']))
    details = {
        'source': source,
        'root_activation': caller_activation,
        'root_path': tuple(caller_visits),
        'caller_operations': caller_ops,
        'call_activations': tuple(call_rows),
        'driver_activations': tuple(row[0] for row in driver_scopes),
        'driver_entries': tuple(row[1][0] for row in driver_scopes),
        'driver_occurrences': driver_occurrences,
        'session_update_occurrences': update_occurrences,
        'body_activation': body_activation,
        'body_segments': tuple(segment_rows),
        'body_entries': tuple(body_entries),
        'body_outcomes': tuple(body_operation_maps[number][target.id]
                               for number, target in enumerate(body_targets)),
        'body_drive_occurrences': tuple(row.drive for row in drive_rows),
        'body_creation_occurrence': creation_occurrence,
        'static': static,
    }
    return program, model, details


__all__ = ['async_pipeline_execution']
