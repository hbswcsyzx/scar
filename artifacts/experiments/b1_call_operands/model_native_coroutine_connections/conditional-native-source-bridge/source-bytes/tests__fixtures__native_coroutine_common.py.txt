"""Supplied native coroutine ports, never source recovery or runtime evidence.

Migration changes the declared profile of this one test body. Capture rebuilds
every occurrence from the current graph, including explicitly selected helper
paths. It does not relabel a previous execution snapshot.
"""
from dataclasses import replace

from scar.ir.execution.calls import CallActivation
from scar.ir.execution.common import EvidencePoint, MissingEvidence
from scar.ir.execution.coordinates import (
    ControlTransfer, ExecutionRun, HostThreadInstance, InitialEntry,
    ProcessInstance, ResumeIngress,
)
from scar.ir.execution.ids import (
    CallActivationID, HostThreadInstanceID, ProcessInstanceID,
    RegionActivationID, RunID,
)
from scar.ir.execution.model import ExecutionModel
from scar.ir.execution.resumables import BodyActivationOrigin, BodyDriveExecution
from scar.ir.execution.snapshot import snapshot_for
from scar.ir.program.protocols import (
    DriverSubject, OutcomeAdapter, OutcomeAdapterRule, ProtocolClause, ProtocolProfile,
)
from scar.ir.program.resumption import ResumableKind, SuspensionFlavor, SuspendTerminator
from tests.fixtures.execution_async_pipeline_graphs import _body_path
from tests.fixtures.execution_call_graphs import _activation
from tests.fixtures.program_await_resume_graphs import await_resume_program, with_final_adapter


def migrate_native(program, details):
    body, = program.resumable_bodies
    assert body.kind in (ResumableKind.GENERATOR_COROUTINE, ResumableKind.COROUTINE)
    region = next(row for row in program.regions if row.id == body.region)
    body_operations = {site for block in region.blocks for site in block.operations}
    drivers = {row.region for row in program.driver_interfaces if row.body == body.region}
    scopes = {row.id for row in program.protocol_scopes if type(row.subject) is DriverSubject
              and row.subject.interface_region in drivers}
    conversions = tuple(row for row in program.protocol_operations if row.scope in scopes
        and type(row.contract) is OutcomeAdapter
        and row.contract.rule is OutcomeAdapterRule.GENERATOR_RETURN_TO_STOP_ITERATION)
    changed = {(row.scope, row.clause, row.operation, row.slot) for row in conversions}

    def site(value):
        key = (value.scope, value.clause, value.operation, value.slot)
        return replace(value, clause=ProtocolClause.AWAIT_COMPLETION_ADAPTER) if key in changed else value

    graph = replace(program,
        resumable_bodies=(replace(body, kind=ResumableKind.COROUTINE),),
        operations=tuple(replace(row, terminator=replace(row.terminator, flavor=SuspensionFlavor.AWAIT))
            if row.id in body_operations and type(row.terminator) is SuspendTerminator else row
            for row in program.operations),
        protocol_scopes=tuple(replace(row, profile=ProtocolProfile.COROUTINE_BODY_V1)
            if row.id in scopes else row for row in program.protocol_scopes),
        protocol_operations=tuple(replace(row, clause=ProtocolClause.AWAIT_COMPLETION_ADAPTER,
            contract=replace(row.contract, rule=OutcomeAdapterRule.COROUTINE_RETURN_TO_STOP_ITERATION))
            if row in conversions else row for row in program.protocol_operations),
        protocol_result_consumers=tuple(replace(row, site=site(row.site))
            for row in program.protocol_result_consumers))
    return graph, {**details, 'body_kind': ResumableKind.COROUTINE}


def native_resume_program(*, zero_cut=False, extra_creation=False):
    graph, details = await_resume_program(zero_cut=zero_cut, extra_creation=extra_creation)
    graph, adapters = with_final_adapter(graph, details)
    return migrate_native(graph, {**details, 'adapter_rows': adapters})


def capture_program(program, details, *, instances=1, label='native.coroutine',
                    body_paths=None, extra_calls=()):
    """Rebuild selected caller/driver/body/helper paths on this exact program.

    ``extra_calls`` are explicit dictionaries with label, parent, caller,
    region, path and completion. Parent is 'caller', ('driver', ordinal),
    ('body', ordinal), or ('extra', earlier_label). A driver whose captured
    path has no BodyDrive produces no invented body segment.
    """
    if type(instances) is not int or instances < 1:
        raise ValueError('instances must be a positive exact integer')
    source = MissingEvidence('supplied native coroutine paths; no source/native runtime proof')
    run, process, thread = RunID(label), ProcessInstanceID(label), HostThreadInstanceID(label)
    point = EvidencePoint(run, process, source)
    names = ('activations', 'segments', 'visits', 'operations', 'values', 'uses', 'transfers')
    combined = {name: [] for name in names}
    calls, drives, origins, examples = [], [], [], []
    definitions = {row.id: row for row in program.operations}
    body_paths = {} if body_paths is None else body_paths

    def append(rows, *, activation=True):
        for name in names:
            if name != 'activations' or activation:
                combined[name].extend(rows[name])

    for instance in range(instances):
        prefix = f'{label}.{instance}'
        rows, caller, caller_visits, caller_ops = _activation(program, details['caller'].id,
            details['caller_path'], prefix + '.caller', point, thread)
        append(rows)
        driver_scopes, instance_calls = [], []
        for ordinal, item in enumerate(details['drivers']):
            rows, activation, visits, occurrences = _activation(program, item['driver_region'].id,
                item['path'], prefix + f'.driver.{ordinal}', point, thread)
            append(rows)
            driver_scopes.append((activation, visits, occurrences))
            association = CallActivation(CallActivationID(prefix + f'.driver.call.{ordinal}'),
                caller_ops[item['caller_call'].id], activation, visits[0],
                occurrences[item['host_terminal'].id], source)
            calls.append(association)
            instance_calls.append(association)
        body_activation = RegionActivationID(prefix + '.body')
        body_entries, body_segments, body_occurrences, active_drives, active_ordinals = [], [], [], [], []
        body_scopes = {}
        previous_suspend, previous_source = None, None
        body_literals = {}
        body = details['body']
        for ordinal, item in enumerate(details['drivers']):
            drive = item.get('drive')
            if drive is None or drive.operation not in driver_scopes[ordinal][2]:
                continue
            outcome = definitions[item['outcome_source']]
            if previous_suspend is None:
                start, ingress = body.entry, InitialEntry(point)
            else:
                resume = drive.target
                previous = definitions[previous_source]
                assert resume.suspend == previous.id
                start = previous.terminator.successors[resume.successor].block
                ingress = ResumeIngress(previous_suspend, resume.successor, point)
            path = body_paths.get(ordinal)
            if path is None:
                path = _body_path(program, body, start, outcome.id)
            rows, temporary, visits, occurrences = _activation(program, body.id,
                path, prefix + f'.body.{ordinal}', point, thread)
            segment = replace(rows['segments'][0], activation=body_activation, ingress=ingress)
            rows['segments'] = (segment,)
            rows['activations'] = tuple(replace(row, id=body_activation) for row in rows['activations'])
            values, literal_copies = [], {}
            for row in rows['values']:
                if row.origin == temporary:
                    if row.value in body_literals:
                        literal_copies[row.id] = body_literals[row.value]
                        continue
                    body_literals[row.value] = row.id
                    row = replace(row, origin=body_activation)
                values.append(row)
            rows['values'] = tuple(values)
            rows['uses'] = tuple(replace(row, value=literal_copies[row.value])
                                 if row.value in literal_copies else row for row in rows['uses'])
            append(rows, activation=not body_entries)
            if previous_suspend is not None:
                combined['transfers'].append(ControlTransfer(previous_suspend, drive.target.successor, visits[0]))
            selected = occurrences[outcome.id]
            association = BodyDriveExecution(driver_scopes[ordinal][2][drive.operation],
                body_activation, visits[0], selected, source)
            drives.append(association)
            active_drives.append(association)
            active_ordinals.append(ordinal)
            body_entries.append(visits[0])
            body_segments.append(segment.id)
            body_occurrences.append(occurrences)
            body_scopes[ordinal] = (body_activation, visits, occurrences)
            previous_suspend, previous_source = selected, outcome.id
        origin = None
        if body_entries:
            origin = BodyActivationOrigin(body_activation,
                caller_ops[details['primary_creation'].operation], source)
            origins.append(origin)
        extra_scopes, extra_associations = {}, {}
        for item in extra_calls:
            parent = item['parent']
            if parent == 'caller':
                parent_map = caller_ops
            elif parent[0] == 'driver':
                parent_map = driver_scopes[parent[1]][2]
            elif parent[0] == 'body':
                parent_map = body_scopes[parent[1]][2]
            elif parent[0] == 'extra':
                parent_map = extra_scopes[parent[1]][2]
            else:
                raise ValueError('unknown supplied extra-call parent')
            rows, activation, visits, occurrences = _activation(program, item['region'], item['path'],
                prefix + '.extra.' + item['label'], point, thread)
            append(rows)
            extra_scopes[item['label']] = (activation, visits, occurrences)
            association = CallActivation(CallActivationID(prefix + '.extra.call.' + item['label']),
                parent_map[item['caller']], activation, visits[0], occurrences[item['completion']], source)
            calls.append(association)
            extra_associations[item['label']] = association
        examples.append({'caller_activation': caller, 'caller_visits': caller_visits,
            'caller_operations': caller_ops, 'driver_scopes': tuple(driver_scopes),
            'call_activations': tuple(instance_calls),
            'body_activation': body_activation if body_entries else None,
            'body_entries': tuple(body_entries), 'body_segments': tuple(body_segments),
            'body_occurrences': tuple(body_occurrences), 'body_scopes': body_scopes,
            'body_drives': tuple(active_drives), 'active_driver_ordinals': tuple(active_ordinals),
            'body_origin': origin, 'creation': caller_ops[details['primary_creation'].operation],
            'extra_scopes': extra_scopes, 'extra_call_activations': extra_associations})
    model = ExecutionModel(snapshot_for(program), runs=(ExecutionRun(run, source),),
        processes=(ProcessInstance(process, run, 801, source),),
        threads=(HostThreadInstance(thread, process, 802, source),),
        **{name: tuple(rows) for name, rows in combined.items()},
        call_activations=tuple(calls), body_drive_executions=tuple(drives),
        body_activation_origins=tuple(origins))
    return model, {'static': details, 'instances': tuple(examples), 'source': source,
                   'point': point, 'thread': thread}
