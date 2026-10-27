"""Two independent captures of real general/W -> B BodyRaise continuations.

Every synchronous wrapper and driver has its own activation. Only B persists
across its real segments. W/B identities are external declarations, with all
native/runtime proof flags left off.
"""
from dataclasses import replace

from scar.ir.execution.calls import CallActivation
from scar.ir.execution.common import EvidencePoint, MissingEvidence, Unresolved
from scar.ir.execution.content import ObjectIdentity, ObjectRef, ValueDenotation
from scar.ir.execution.coordinates import (
    ControlTransfer, ExecutionRun, HostThreadInstance, InitialEntry,
    ProcessInstance, ResumeIngress,
)
from scar.ir.execution.ids import (
    CallActivationID, DenotationID, HostThreadInstanceID, ProcessInstanceID,
    RegionActivationID, RunID,
)
from scar.ir.execution.model import ExecutionModel
from scar.ir.execution.resumables import BodyActivationOrigin, BodyDriveExecution
from scar.ir.execution.snapshot import external_artifact, snapshot_for
from scar.ir.program.cleanup import CleanupRouteTerminator
from scar.ir.program.control import PendingDispatchTerminator
from scar.ir.program.drivers import BodyDriveResult
from scar.ir.program.ids import BlockID, ValueID
from scar.ir.program.model import ExitKind, OperationResult
from scar.ir.v2.evidence import EvidenceEndpoint, EvidenceGraph, EvidenceNodeKind
from scar.ir.v2.ids import ObjectID
from tests.fixtures.execution_async_pipeline_graphs import _body_path
from tests.fixtures.execution_call_graphs import _activation
from tests.fixtures.program_await_raise_sources_graphs import await_raise_source_program


_TABLES = ('activations', 'segments', 'visits', 'operations', 'values', 'uses', 'transfers')


def await_raise_source_execution(source_kind='general', zero_cut=True, cleanup_mode=None,
        instances=2, missing_inner_call=None, missing_source_call=None, missing_body_use=None):
    if type(instances) is not int or instances < 1:
        raise ValueError('instances must be a positive exact integer')
    for label, selected in (('missing_source_call', missing_source_call),
                            ('missing_body_use', missing_body_use)):
        if selected is not None and (type(selected) is not int or not 0 <= selected < instances):
            raise ValueError(label + ' must select this captured instance')
    if missing_inner_call is not None and (source_kind != 'wrapper'
            or type(missing_inner_call) is not tuple or len(missing_inner_call) != 2
            or any(type(index) is not int for index in missing_inner_call)
            or not 0 <= missing_inner_call[0] < instances
            or not 0 <= missing_inner_call[1] < (1 if zero_cut else 3)):
        raise ValueError('missing_inner_call must select a real (wrapper instance, advance)')
    program, static = await_raise_source_program(source_kind, zero_cut, cleanup_mode)
    source = MissingEvidence('supplied independent source/BodyRaise associations; no native runtime proof')
    run = RunID('await.raise.sources.run')
    process = ProcessInstanceID('await.raise.sources.process')
    thread = HostThreadInstanceID('await.raise.sources.thread')
    point = EvidencePoint(run, process, source)
    combined = {name: [] for name in _TABLES}
    calls, drives, origins, examples, assignments, objects = [], [], [], [], {}, []
    operations = {operation.id: operation for operation in program.operations}
    blocks = {block.id: block for region in program.regions for block in region.blocks}
    ports = {port.id: port for port in program.control_ports}

    def append(rows, *, activation=True):
        for name in _TABLES:
            if name != 'activations' or activation:
                combined[name].extend(rows[name])

    def denote(owner, definition, name):
        matches = tuple(value for value in combined['values']
                        if value.origin == owner and value.value == definition)
        if len(matches) != 1:
            raise AssertionError('object declaration must identify one original occurrence')
        assignments[matches[0].id] = name

    def terminal_slots(occurrence, terminal):
        slots = tuple(next(row for row in combined['uses']
            if (row.operation, row.use) == (occurrence, identity))
            for identity in terminal.terminator.values)
        return slots, tuple(next(row for row in combined['values'] if row.id == use.value) for use in slots)

    for instance in range(instances):
        prefix = f'await.raise.sources.instance.{instance}'
        captured, caller, caller_visits, caller_ops = _activation(program, static['caller'].id,
            static['caller_path'], prefix + '.caller', point, thread)
        append(captured)
        instance_calls, outer_calls, inner_calls = [], [], []
        wrapper_scopes, driver_scopes = [], []
        helper_scope, acquisition_call = None, None
        body_name, wrapper_name, decoy_name = prefix + '.B', prefix + '.W', prefix + '.decoy'
        capture_names = tuple(prefix + f'.capture.{slot}' for slot in range(len(static['capture_formals'])))
        if source_kind == 'general':
            captured, helper_activation, entered, helper_ops = _activation(program,
                static['helper'].id, static['helper_path'], prefix + '.acquisition', point, thread)
            append(captured)
            helper_scope = (helper_activation, entered, helper_ops)
            acquisition_call = CallActivation(CallActivationID(prefix + '.acquire'),
                caller_ops[static['get'].id], helper_activation, entered[0],
                helper_ops[static['helper_return'].id], source)
            instance_calls.append(acquisition_call)
            if missing_source_call != instance:
                calls.append(acquisition_call)
            creation = helper_ops[static['primary_creation'].operation]
        else:
            objects.extend((body_name, wrapper_name, decoy_name, *capture_names))
            visits_by_block = {visit.block: visit.id for visit in captured['visits']}
            for number in range(2):
                block = BlockID(f'await.resume.create.{number}.normal')
                denote(visits_by_block[block], ValueID(block.value + '.arg.0'), body_name)
            block = BlockID('await.resume.create.1.normal')
            denote(visits_by_block[block], ValueID(block.value + '.arg.1'), decoy_name)
            block = BlockID('await.resume.acquired')
            for slot, name in enumerate((wrapper_name, body_name, decoy_name)):
                denote(visits_by_block[block], ValueID(block.value + f'.arg.{slot}'), name)
            for number in range(0 if zero_cut else 2):
                block = BlockID(f'await.resume.call.{number}.normal')
                for slot, name in enumerate((body_name, decoy_name, wrapper_name)):
                    denote(visits_by_block[block], ValueID(block.value + f'.arg.{slot}'), name)
            creation = caller_ops[static['primary_creation'].operation]

        for ordinal, item in enumerate(static['drivers']):
            wrapper_map = None
            if source_kind == 'wrapper':
                wrapper = item['wrapper']
                captured, activation, entered, wrapper_map = _activation(program,
                    wrapper['region'].id, wrapper['path'], prefix + f'.wrapper.{ordinal}', point, thread)
                append(captured)
                wrapper_scopes.append((activation, entered, wrapper_map))
                denote(entered[0], wrapper['entry'][0], wrapper_name)
                denote(wrapper_map[wrapper['read'].id], wrapper['read_body'], body_name)
                selected_kind = ExitKind.RAISE if zero_cut or ordinal == 2 else ExitKind.NORMAL
                association = CallActivation(CallActivationID(prefix + f'.outer.{ordinal}'),
                    caller_ops[item['caller_call'].id], activation, entered[0],
                    wrapper_map[wrapper['terminals'][selected_kind].id], source)
                outer_calls.append(association)
                instance_calls.append(association)
                if not (missing_source_call == instance and ordinal == 0):
                    calls.append(association)
            captured, activation, entered, driver_map = _activation(program,
                item['driver_region'].id, item['path'], prefix + f'.driver.{ordinal}', point, thread)
            append(captured)
            driver_scopes.append((activation, entered, driver_map))
            if source_kind == 'wrapper':
                denote(entered[0], blocks[item['driver_region'].entry].arguments[0], body_name)
                ingress = next(visit for visit in captured['visits']
                               if visit.block.value.endswith('driver.ingress'))
                denote(ingress.id, blocks[ingress.block].arguments[0], body_name)
            association = CallActivation(CallActivationID(prefix + f'.driver.call.{ordinal}'),
                caller_ops[item['caller_call'].id] if wrapper_map is None else
                    wrapper_map[item['wrapper']['inner_call'].id],
                activation, entered[0], driver_map[item['host_terminal'].id], source)
            inner_calls.append(association)
            instance_calls.append(association)
            if missing_inner_call != (instance, ordinal):
                calls.append(association)

        body_activation = RegionActivationID(prefix + '.body')
        previous, literal_ids = None, set()
        body_entries, body_segments, body_maps, body_visits, instance_drives = [], [], [], [], []
        region = static['body']
        for ordinal, item in enumerate(static['drivers']):
            if ordinal == 0:
                start, ingress = region.entry, InitialEntry(point)
            else:
                target = item['drive'].target
                prior = operations[static['drivers'][ordinal - 1]['outcome_source']]
                if target.suspend != prior.id:
                    raise AssertionError('Resume must use this persistent B immediately preceding cut')
                start = prior.terminator.successors[target.successor].block
                ingress = ResumeIngress(previous, target.successor, point)
            path = _body_path(program, region, start, item['outcome_source'])
            if not zero_cut:
                wanted = 'RAISE' if ordinal == 2 else 'RETURN'
                selected_port = next(definition.port for definition in static['pending_definitions']
                                     if ports[definition.port].kind.value == wanted)
                path = tuple((block, next(number for number, edge in enumerate(term.successors)
                    if edge.port == selected_port)) if type(term := operations[blocks[block].operations[-1]].terminator)
                    in (CleanupRouteTerminator, PendingDispatchTerminator) else (block, selected)
                    for block, selected in path)
            captured, temporary, entered, mapped = _activation(program, region.id,
                path, prefix + f'.body.segment.{ordinal}', point, thread)
            captured['activations'] = tuple(replace(row, id=body_activation) for row in captured['activations'])
            captured['segments'] = tuple(replace(row, activation=body_activation, ingress=ingress)
                                         for row in captured['segments'])
            kept = []
            for value in captured['values']:
                if value.origin == temporary:
                    if value.value in literal_ids:
                        continue
                    literal_ids.add(value.value)
                    value = replace(value, origin=body_activation)
                kept.append(value)
            captured['values'] = tuple(kept)
            append(captured, activation=ordinal == 0)
            if ordinal:
                combined['transfers'].append(ControlTransfer(previous, item['drive'].target.successor, entered[0]))
            actual_outcome = mapped[item['outcome_source']]
            association = BodyDriveExecution(driver_scopes[ordinal][2][item['drive'].operation],
                body_activation, entered[0], actual_outcome, source)
            drives.append(association)
            instance_drives.append(association)
            body_entries.append(entered[0])
            body_segments.append(captured['segments'][0].id)
            body_maps.append(mapped)
            body_visits.append(entered)
            previous = actual_outcome
        origin = BodyActivationOrigin(body_activation, creation, source)
        origins.append(origin)
        if source_kind == 'wrapper':
            create = operations[static['primary_creation'].operation]
            actuals = {use.id: use for use in create.uses}
            for slot, capture in enumerate(static['primary_creation'].captures):
                denote(caller_visits[0], actuals[capture.source].value, capture_names[slot])
                denote(body_entries[0], capture.formal, capture_names[slot])
        body_outcome = instance_drives[-1].outcome
        driver_terminal = inner_calls[-1].completion
        final = caller_ops[static['final'].id]
        body_slots, body_values = terminal_slots(body_outcome, static['body_terminal'])
        driver_slots, driver_values = terminal_slots(driver_terminal, static['drivers'][-1]['host_terminal'])
        final_slots, final_values = terminal_slots(final, static['final'])
        actual_drive = instance_drives[-1].drive
        transfer, = tuple(row for row in combined['transfers'] if row.operation == actual_drive)
        drive_operation = operations[static['drivers'][-1]['drive'].operation]
        drive_edge = drive_operation.terminator.successors[transfer.successor_index]
        landing = blocks[drive_edge.block]
        root_formal, = tuple(formal for argument, formal in zip(drive_edge.arguments, landing.arguments)
                             if type(argument) is BodyDriveResult and argument.index == 0)
        root_value, = tuple(row for row in combined['values']
                            if row.origin == transfer.target and row.value == root_formal)
        example = {'caller_activation': caller, 'caller_visits': caller_visits,
            'caller_operations': caller_ops, 'caller_path': static['caller_path'],
            'helper_scope': helper_scope, 'acquisition_call': acquisition_call,
            'source_call': acquisition_call if source_kind == 'general' else outer_calls[0],
            'wrapper_scopes': tuple(wrapper_scopes), 'driver_scopes': tuple(driver_scopes),
            'call_activations': tuple(instance_calls), 'wrapper_calls': tuple(outer_calls),
            'driver_calls': tuple(inner_calls), 'call_chain': tuple(instance_calls),
            'driver_activation': driver_scopes[-1][0], 'driver_visits': driver_scopes[-1][1],
            'driver_operations': driver_scopes[-1][2], 'driver_call': inner_calls[-1],
            'driver_root_value': root_value,
            'body_activation': body_activation, 'body_entries': tuple(body_entries),
            'body_segments': tuple(body_segments), 'body_visits': tuple(body_visits),
            'body_occurrences': tuple(body_maps), 'body_drives': tuple(instance_drives),
            'body_origin': origin, 'creation': creation,
            'acquisition': caller_ops[static['get'].id], 'advance': caller_ops[static['advance_operation']],
            'driver_terminal': driver_terminal, 'body_outcome': body_outcome, 'final': final,
            'final_definition': static['final'],
            'body_terminal_uses': body_slots, 'body_terminal_values': body_values,
            'driver_terminal_uses': driver_slots, 'driver_terminal_values': driver_values,
            'final_uses': final_slots, 'final_values': final_values,
            'body_packet_use': body_slots[0], 'body_packet_value': body_values[0],
            'driver_packet_use': driver_slots[0], 'driver_packet_value': driver_values[0],
            'host_packet_use': final_slots[0], 'host_packet_value': final_values[0],
            'conversion': None, 'extraction': None, 'implementation_frames': (),
            'body_object': None if source_kind == 'general' else ObjectID(body_name),
            'wrapper_object': None if source_kind == 'general' else ObjectID(wrapper_name)}
        if static['raise_cleanup'] is not None:
            cleanup = static['raise_cleanup']
            pending = cleanup['replacement_pending'] or cleanup['pending']
            pending_origin = next(value for value in program.values if value.id == pending.value).origin
            primary_origin = next(value for value in program.values if value.id == cleanup['pending'].value).origin
            if type(pending_origin) is not OperationResult or type(primary_origin) is not OperationResult:
                raise AssertionError('the D pending tokens require their real canonical constructors')
            driver_map = driver_scopes[-1][2]
            example.update(pending_definition=pending,
                pending_constructor=driver_map[pending_origin.operation], pending_payload_use=pending.payload,
                primary_pending_definition=cleanup['pending'],
                primary_pending_constructor=driver_map[primary_origin.operation],
                dispatch=driver_map[cleanup['dispatch'].id],
                cleanup_actions=tuple(driver_map[operation.id] for operation in cleanup['action_operations']))
        examples.append(example)
        if missing_body_use == instance:
            combined['uses'] = [row for row in combined['uses']
                if (row.operation, row.use) != (body_outcome, static['body_packet_use'].use)]

    denotations, evidence_graphs, artifact = (), {}, None
    if source_kind == 'wrapper':
        evidence = EvidenceGraph()
        for name in dict.fromkeys(objects):
            evidence.register_external(EvidenceEndpoint(EvidenceNodeKind.OBJECT, ObjectID(name)))
        artifact = external_artifact(evidence, 'memory:await-raise-wrapper-supplied-objects')
        gap = Unresolved('declared object identity; no native wrapper capture', point)
        denotations = tuple(ValueDenotation(DenotationID(identity.value), identity,
            ObjectIdentity(ObjectRef(artifact, ObjectID(name))), gap, source)
            for identity, name in assignments.items())
        evidence_graphs = {artifact.sha256: evidence}
    model = ExecutionModel(snapshot_for(program), runs=(ExecutionRun(run, source),),
        processes=(ProcessInstance(process, run, 707, source),),
        threads=(HostThreadInstance(thread, process, 808, source),),
        **{name: tuple(rows) for name, rows in combined.items()},
        call_activations=tuple(calls), body_drive_executions=tuple(drives),
        body_activation_origins=tuple(origins), denotations=denotations)
    return program, model, {'static': static, 'instances': tuple(examples),
        'implementation_instances': tuple(examples), 'source': source, 'point': point,
        'source_kind': source_kind, 'zero_cut': zero_cut, 'cleanup_mode': cleanup_mode,
        'drive_outcome': static['drive_outcome'], 'evidence_artifact': artifact,
        'evidence_graphs': evidence_graphs, 'object_assignments': dict(assignments),
        'missing_inner_call': missing_inner_call, 'missing_source_call': missing_source_call,
        'missing_body_use': missing_body_use}


__all__ = ['await_raise_source_execution']
