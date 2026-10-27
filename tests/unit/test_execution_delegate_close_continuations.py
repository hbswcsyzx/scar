"""Supplied close N/R occurrences through P's real C1 and two real cuts.

P retains the old packet-continuation graph. Three separate synchronous
drivers actually Start/Resume it; the primitive finally.invoke has no callee.
The receiver is an external boundary, with no invented Create/native proof.
"""
from dataclasses import replace

import pytest

from scar.ir.execution.calls import CallActivation
from scar.ir.execution.common import EvidencePoint, MissingEvidence, Unresolved
from scar.ir.execution.coordinates import (
    ControlTransfer, ExecutionRun, HostThreadInstance, InitialEntry,
    OccurrencePhase, OccurrencePoint, ProcessInstance, ResumeIngress,
)
from scar.ir.execution.ids import (
    CallActivationID, HostThreadInstanceID, ProcessInstanceID,
    RegionActivationID, RunID,
)
from scar.ir.execution.model import ExecutionModel
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.resumables import BodyActivationOrigin, BodyDriveExecution
from scar.ir.execution.snapshot import snapshot_for
from scar.ir.execution.validation import validate
from scar.ir.program.control import ProtocolValueKind
from scar.ir.program.drivers import RawRequestDefinition, RawRequestKind
from scar.ir.program.ids import BlockID, OperationID
from scar.ir.program.model import (
    CompletionResult, CompletionSignature, CompletionSuccessor, ExitKind,
    OperationResult, ProtocolValue, ReferenceValue, StateVersionValue,
    Terminator, TerminatorKind, UseRole, ValueKind, ValueType,
)
from scar.ir.program.protocols import HostTerminal
from scar.ir.program.resumption import ResumeSlotKind
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_async_pipeline_graphs import _body_path
from tests.fixtures.execution_call_graphs import _activation
from tests.fixtures.program_async_pipeline_graphs import _selected_path
from tests.fixtures.program_driver_graphs import (
    RAW, REFERENCE, PACKET, _Builder, _use as _program_use, driver_program,
)
from tests.fixtures.program_generator_close_retry_graphs import _driver_part
from tests.fixtures.program_packet_continuation_graphs import packet_continuation_program
from tests.fixtures.program_protocol_graphs import _scope


_TABLES = ('activations', 'segments', 'visits', 'operations', 'values', 'uses', 'transfers')
_PART_TABLES = ('driver_interfaces', 'final_body_gates', 'body_drives',
    'driver_lifecycles', 'body_outcome_commits', 'terminal_frame_releases',
    'protocol_scopes', 'protocol_operations', 'literal_evaluations', 'exception_packets')
_FLAGS = ('source_runtime_verified', 'runtime_identity_verified',
          'value_identity_verified', 'transformation_authorized')


def _driver(body, number, source, previous=None, *, packet=False):
    core = replace(body, protocol_scopes=(), protocol_operations=(),
        protocol_bindings=(), protocol_call_inputs=(), protocol_result_consumers=())
    if previous is not None:
        core = replace(core, operations=tuple(sorted(core.operations, key=lambda row: row.id != previous)))
    graph = driver_program(body_graph=core, target='start' if previous is None else 'value')
    region = next(row for row in graph.regions if row.id == graph.driver_interfaces[0].region)
    operations = {row.id: row for row in graph.operations}
    if packet:
        # The original first cut has successor 0, not the builder's generic
        # target='packet' successor 1. Retain its DELEGATE_PACKET slot exactly.
        gate = graph.final_body_gates[0]
        position, = gate.delivery_arguments
        entry = next(row for row in region.blocks if row.id == region.entry)
        ingress_id = operations[gate.operation].terminator.successors[0].block
        ingress = next(row for row in region.blocks if row.id == ingress_id)
        payloads = {entry.arguments[position], ingress.arguments[position]}
        graph = replace(graph, values=tuple(
            ProtocolValue(row.id, row.region, row.origin, ProtocolValueKind.EXCEPTION_PACKET)
            if row.id in payloads else row for row in graph.values),
            operations=tuple(replace(row, uses=tuple(
                replace(use, role=UseRole.PROTOCOL) if use.value in payloads else use
                for use in row.uses)) for row in graph.operations))
        operations = {row.id: row for row in graph.operations}
    actual_kinds = {ExitKind.NORMAL if operations[identity].terminator.kind is TerminatorKind.RETURN
        else ExitKind.RAISE for block in region.blocks for identity in block.operations
        if operations[identity].terminator is not None
        and operations[identity].terminator.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE)}
    region = replace(region, exits=tuple(row for row in region.exits if row.kind in actual_kinds))
    graph = replace(graph, regions=tuple(region if row.id == region.id else row for row in graph.regions))
    part, _ = _driver_part(graph, f'delegate.close.driver.{number}')
    # The old extractor also carries body-level side tables. Keep those on P
    # once; a driver part owns only rows for its renamed region/operations.
    owned_operations = {row.id for row in part['operations']}
    owned_values = {row.id for row in part['values']}
    for name in ('driver_interfaces', 'driver_lifecycles'):
        part[name] = tuple(row for row in part[name] if row.region == part['region'].id)
    for name in ('final_body_gates', 'body_drives', 'body_outcome_commits', 'terminal_frame_releases'):
        part[name] = tuple(row for row in part[name] if row.operation in owned_operations)
    part['literal_evaluations'] = tuple(row for row in part['literal_evaluations']
        if (row.site.operation if type(row.site) is OperationResult else row.site.edge.operation)
        in owned_operations)
    part['exception_packets'] = tuple(row for row in part['exception_packets'] if row.value in owned_values)
    assert not part['protocol_scopes'] and not part['protocol_operations']
    assert all(row.region == part['region'].id for row in part['control_scopes'])
    drive = part['body_drives'][0]
    drive_operation = next(row for row in part['operations'] if row.id == drive.operation)
    selected = next(index for index, edge in enumerate(drive_operation.terminator.successors)
                    if edge.source == source)
    choices = {part['final_body_gates'][0].operation: 0, drive.operation: selected}
    shell = replace(graph, regions=(part['region'],), operations=part['operations'])
    path = _selected_path(shell, part['region'], choices)
    terminal_id = next(block.operations[-1] for block in part['region'].blocks if block.id == path[-1][0])
    return dict(part, drive=drive, source=source, path=path,
        terminal=next(row for row in part['operations'] if row.id == terminal_id))


def _driven_program():
    body, old = packet_continuation_program(two_cuts=True, complete_transitions=True)
    parent = body.regions[0]
    cuts = (OperationID('finally.suspend'), old['second_suspend'])
    sources = (*cuts, old['host'].id)
    parts = tuple(_driver(body, number, source,
        None if number == 0 else cuts[number - 1], packet=number == 1)
        for number, source in enumerate(sources))
    locations = tuple(row.id for row in body.locations)
    state_types = tuple(ValueType(ValueKind.STATE, location=identity) for identity in locations)
    host = _Builder('delegate.close.host', locations)
    entry_name = 'delegate.close.host.entry'
    entry = host.formals(entry_name, (REFERENCE, PACKET, REFERENCE, *state_types))
    receiver, injection, sent = entry[:3]
    current_name, current_arguments, current_states = entry_name, entry, entry[3:]
    calls, raws, selected_calls = [], [], {}
    for number, part in enumerate(parts):
        name = f'delegate.close.host.call.{number}'
        raw_operands = (_program_use(name + '.sent', sent),) if number == 2 else ()
        raw = host.value(name + '.raw.value', OperationResult(OperationID(name + '.raw'), 0), RAW)
        pack = host.add(name + '.raw', raw_operands, results=(raw,), effects_complete=True)
        raws.append(RawRequestDefinition(raw,
            (RawRequestKind.NEXT, RawRequestKind.CLOSE, RawRequestKind.SEND)[number],
            tuple(use.id for use in raw_operands)))
        actuals = (_program_use(name + '.receiver', receiver), _program_use(name + '.scheduler', raw, protocol=True),
            *((_program_use(name + '.packet', injection, protocol=True),) if number == 1 else
              (_program_use(name + '.value', sent),) if number == 2 else ()),
            *(_program_use(name + f'.state.{index}', value, state=True)
              for index, value in enumerate(current_states)))
        forward = _program_use(name + '.normal.receiver', receiver)
        edges, normal = [], None
        for port in part['region'].exits:
            landing_name = name + ('.normal' if port.kind is ExitKind.NORMAL else '.failure')
            arguments = host.formals(landing_name,
                (REFERENCE, *port.types) if port.kind is ExitKind.NORMAL else port.types)
            edges.append(CompletionSuccessor(port.kind, BlockID(landing_name),
                (forward.id, *(CompletionResult(index) for index in range(len(port.types))))
                if port.kind is ExitKind.NORMAL else
                tuple(CompletionResult(index) for index in range(len(port.types)))))
            if port.kind is ExitKind.NORMAL:
                normal = landing_name, arguments
            else:
                host.block(landing_name, arguments,
                    (host.terminal(landing_name + '.exit', arguments, fail=True),))
        call = host.add(name, (*actuals, *((forward,) if normal is not None else ())),
            effects_complete=True, callee=part['region'].id,
            invoke_arguments=tuple(use.id for use in actuals),
            completions=tuple(CompletionSignature(port.kind, port.types) for port in part['region'].exits),
            terminator=Terminator(TerminatorKind.INVOKE, tuple(edges)))
        host.block(current_name, current_arguments, (pack, call))
        calls.append(call)
        selected_kind = ExitKind.NORMAL if number < 2 else ExitKind.RAISE
        selected_calls[call.id] = next(index for index, edge in enumerate(edges) if edge.kind is selected_kind)
        if normal is not None:
            current_name, current_arguments = normal
            receiver, current_states = current_arguments[0], current_arguments[2:]
    if normal is not None:
        host.block(current_name, current_arguments,
            (host.terminal(current_name + '.exit', current_arguments[1:]),))
    host_region = host.finish(entry_name)
    if normal is None:
        host_region = replace(host_region,
            exits=tuple(row for row in host_region.exits if row.kind is ExitKind.RAISE))
    additions = {name: (*getattr(body, name), *(row for part in parts for row in part[name]))
                 for name in _PART_TABLES}
    program = replace(body, root=host_region.id,
        regions=(host_region, replace(parent, parent=host_region.id),
            *(replace(part['region'], parent=host_region.id) for part in parts)),
        operations=(*body.operations, *host.operations, *(row for part in parts for row in part['operations'])),
        values=(*body.values, *host.values, *(row for part in parts for row in part['values'])),
        control_scopes=(*body.control_scopes, _scope(host_region.id, host_region.blocks),
            *(row for part in parts for row in part['control_scopes'])),
        raw_driver_requests=(*body.raw_driver_requests, *raws), **additions)
    return program, dict(old, parent=parent, host_region=host_region,
        host_path=_selected_path(program, host_region, selected_calls),
        drivers=parts, calls=tuple(calls), cuts=cuts, sources=sources)


def _capture(*, close_raised=False, instances=2):
    program, static = _driven_program()
    source = MissingEvidence('supplied close/C1 occurrences; no source/native/runtime proof')
    run, process = RunID('delegate.close.run'), ProcessInstanceID('delegate.close.process')
    thread = HostThreadInstanceID('delegate.close.thread')
    point = EvidencePoint(run, process, source)
    rows = {name: [] for name in _TABLES}
    calls, drives, origins, examples = [], [], [], []
    operations = {row.id: row for row in program.operations}
    blocks = {block.id: block for region in program.regions for block in region.blocks}
    close = operations[static['helper']]
    assert close.callee is None
    selected = next(index for index, edge in enumerate(close.terminator.successors)
        if edge.kind is (ExitKind.RAISE if close_raised else ExitKind.NORMAL))
    first_resume = operations[static['cuts'][0]].terminator.successors[0]
    second_resume = operations[static['cuts'][1]].terminator.successors[0]
    prefix = _body_path(program, static['parent'], first_resume.block, close.id)
    middle = (*prefix[:-1], (prefix[-1][0], selected),
        *_body_path(program, static['parent'], close.terminator.successors[selected].block, static['cuts'][1]))
    paths = (_body_path(program, static['parent'], static['parent'].entry, static['cuts'][0]),
        middle, _body_path(program, static['parent'], second_resume.block, static['host'].id))

    def append(captured, *, activation=True):
        for name in _TABLES:
            if name != 'activations' or activation:
                rows[name].extend(captured[name])

    for number in range(instances):
        label = f'delegate.close.instance.{number}'
        captured, host_activation, host_visits, host_operations = _activation(program,
            static['host_region'].id, static['host_path'], label + '.host', point, thread)
        append(captured)
        scopes, links = [], []
        for ordinal, part in enumerate(static['drivers']):
            captured, activation, visits, mapped = _activation(program, part['region'].id,
                part['path'], label + f'.driver.{ordinal}', point, thread)
            append(captured)
            link = CallActivation(CallActivationID(label + f'.call.{ordinal}'),
                host_operations[static['calls'][ordinal].id], activation, visits[0],
                mapped[part['terminal'].id], source)
            calls.append(link)
            links.append(link)
            scopes.append((activation, visits, mapped))
        parent_activation = RegionActivationID(label + '.P')
        previous, literals = None, set()
        entries, segments, visits_by_segment, mapped_by_segment, actual_drives = [], [], [], [], []
        for ordinal, path in enumerate(paths):
            captured, temporary, visits, mapped = _activation(program, static['parent'].id,
                path, label + f'.P.segment.{ordinal}', point, thread)
            ingress = InitialEntry(point) if ordinal == 0 else ResumeIngress(previous, 0, point)
            captured['activations'] = tuple(replace(row, id=parent_activation) for row in captured['activations'])
            captured['segments'] = tuple(replace(row, activation=parent_activation, ingress=ingress)
                                         for row in captured['segments'])
            captured_values = []
            for value in captured['values']:
                if value.origin == temporary:
                    if value.value in literals:
                        continue
                    literals.add(value.value)
                    value = replace(value, origin=parent_activation)
                captured_values.append(value)
            captured['values'] = tuple(captured_values)
            append(captured, activation=ordinal == 0)
            if ordinal:
                rows['transfers'].append(ControlTransfer(previous, 0, visits[0]))
            actual = BodyDriveExecution(scopes[ordinal][2][static['drivers'][ordinal]['drive'].operation],
                parent_activation, visits[0], mapped[static['sources'][ordinal]], source)
            drives.append(actual)
            actual_drives.append(actual)
            entries.append(visits[0])
            segments.append(captured['segments'][0].id)
            visits_by_segment.append(visits)
            mapped_by_segment.append(mapped)
            previous = actual.outcome
        origins.append(BodyActivationOrigin(parent_activation,
            Unresolved('P is supplied through an external receiver boundary, not a Create', point), source))
        anchor = mapped_by_segment[1][close.id]
        close_transfer, = tuple(row for row in rows['transfers'] if row.operation == anchor)
        selected_edge = close.terminator.successors[selected]
        packet_position = next(index for index, argument in enumerate(selected_edge.arguments)
            if type(argument) is CompletionResult and argument.index == 0)
        own, = tuple(row for row in rows['values'] if row.origin == close_transfer.target
            and row.value == blocks[selected_edge.block].arguments[packet_position])
        injected, = tuple(row for row in rows['values']
            if row.origin == entries[1] and row.value == static['injected'])
        examples.append({'parent_activation': parent_activation, 'parent_segments': tuple(segments),
            'parent_entries': tuple(entries), 'parent_visits': tuple(visits_by_segment),
            'parent_operations': tuple(mapped_by_segment), 'parent_drives': tuple(actual_drives),
            'driver_scopes': tuple(scopes), 'driver_calls': tuple(links),
            'host_activation': host_activation, 'host_visits': host_visits, 'host_operations': host_operations,
            'anchor': anchor, 'selected_close': selected, 'close_transfer': close_transfer,
            'own_value': own.id, 'injected_value': injected.id,
            'source_value': own.id if close_raised else injected.id,
            'parent_final': mapped_by_segment[2][static['host'].id]})
    model = ExecutionModel(snapshot_for(program), runs=(ExecutionRun(run, source),),
        processes=(ProcessInstance(process, run, 31, source),),
        threads=(HostThreadInstance(thread, process, 32, source),),
        **{name: tuple(items) for name, items in rows.items()},
        call_activations=tuple(calls), body_drive_executions=tuple(drives),
        body_activation_origins=tuple(origins))
    return program, model, dict(static=static, instances=tuple(examples), close_raised=close_raised)


def _index(program, model):
    require_valid(program)
    report = validate(model, program)
    assert report.valid, report.issues
    return ExecutionIndex(model, program)


def _use(model, operation, identity):
    return next(row for row in model.uses if (row.operation, row.use) == (operation, identity))


def _value(model, identity):
    return next(row for row in model.values if row.id == identity)


def _query(index, example, *, cross_resume=True):
    return index.completion_continuations(example['source_value'], example['anchor'],
        cross_resume=cross_resume, budget=1_048_576)


def _assert_final(report, model, static, example):
    receipt, = tuple(row for row in report['terminals'] if row['terminal'] == HostTerminal(static['host'].id))
    actual_use = _use(model, example['parent_final'], static['host_packet'].use)
    assert receipt['actual'] == static['host_packet']
    assert receipt['operation'].id == example['parent_final']
    assert receipt['use'] == actual_use
    assert receipt['value'] == _value(model, actual_use.value)
    assert receipt['binding']['match'] is True
    assert receipt['root_binding']['match'] is True
    assert receipt['root_preserved'] is True
    assert receipt['crossed_suspend'] is True
    assert tuple(row.id for row in report['segments']) == example['parent_segments'][1:]
    assert report['drives'] == example['parent_drives'][1:]
    future = ControlTransfer(example['parent_drives'][1].outcome, 0, example['parent_entries'][2])
    assert future in report['transfers']
    assert all(row in model.transfers for row in report['transfers'])
    assert report['status'] == 'DECLARED'
    assert report['known_inventory_complete'] is True
    assert not report['budget']['truncated']
    assert all(report[name] is False for name in _FLAGS)


@pytest.mark.parametrize('close_raised', (False, True), ids=('normal-injection', 'raise-own-packet'))
def test_selected_close_packet_crosses_its_actual_parent_c1_and_future_resume(close_raised):
    program, model, details = _capture(close_raised=close_raised)
    index = _index(program, model)
    static = details['static']
    values = {row.id: row for row in program.values}
    operations = {row.id: row for row in program.operations}
    blocks = {block.id: block for region in program.regions for block in region.blocks}
    assert operations[static['helper']].callee is None
    assert len(model.call_activations) == 6
    assert {row.caller for row in model.call_activations}.isdisjoint(
        example['anchor'] for example in details['instances'])
    assert len({example['parent_activation'] for example in details['instances']}) == 2
    for example in details['instances']:
        assert len(example['parent_segments']) == len(example['parent_drives']) == 3
        assert {row.activation for row in example['parent_drives']} == {example['parent_activation']}
        source = _value(model, example['source_value'])
        own = _value(model, example['own_value'])
        assert isinstance(values[source.value], ProtocolValue)
        assert values[source.value].protocol is ProtocolValueKind.EXCEPTION_PACKET
        if close_raised:
            assert source == own
            assert source.id != example['injected_value']
        else:
            assert source.id == example['injected_value']
            assert isinstance(values[own.value], ReferenceValue)
            assert source.id != own.id
        for ordinal, drive in enumerate(example['parent_drives']):
            view = index.drive_execution(drive.drive, budget=1_048_576)
            assert view['association'] == drive
            assert view['entry'].id == example['parent_entries'][ordinal]
            assert view['outcome'].id == drive.outcome
            link = example['driver_calls'][ordinal]
            assert link.activation == example['driver_scopes'][ordinal][0]
            assert link.completion == example['driver_scopes'][ordinal][2][static['drivers'][ordinal]['terminal'].id]
            if ordinal:
                target = static['drivers'][ordinal]['drive'].target
                signature = operations[target.suspend].terminator.successors[target.successor]
                assert target.suspend == static['cuts'][ordinal - 1]
                assert signature.inputs[1].kind is (
                    ResumeSlotKind.DELEGATE_PACKET if ordinal == 1 else ResumeSlotKind.SENT_VALUE)

        close = operations[static['helper']]
        selected = close.terminator.successors[example['selected_close']]
        landing = blocks[selected.block]
        current = index.state_at(OccurrencePoint(example['anchor'], OccurrencePhase.EDGE,
                                                 example['selected_close']))
        for argument, formal in zip(selected.arguments, landing.arguments, strict=True):
            if type(argument) is CompletionResult and isinstance(values[formal], StateVersionValue):
                actual, = tuple(row for row in model.values
                    if row.origin == example['close_transfer'].target and row.value == formal)
                assert argument.index in (1, 2)
                assert current[values[formal].location] == actual.id
        replacement = example['parent_operations'][2][static['replacement']]
        before = index.occurrence(replacement)['before']
        for use in operations[static['replacement']].uses:
            definition = values[use.value]
            if isinstance(definition, StateVersionValue):
                assert _use(model, replacement, use.id).value == before[definition.location]
        final_before = index.occurrence(example['parent_final'])['before']
        for use in static['host'].uses:
            definition = values[use.value]
            if isinstance(definition, StateVersionValue):
                assert _use(model, example['parent_final'], use.id).value == final_before[definition.location]

        # P's actual packet/state output slots feed D2, then that exact call's
        # RAISE landing and root host terminal, without extending P's cursor.
        final_view = index.drive_execution(example['parent_drives'][2].drive, budget=1_048_576)
        link = example['driver_calls'][2]
        terminal = static['drivers'][2]['terminal']
        outputs = final_view['outputs']
        assert len(outputs) == len(static['host'].terminator.values)
        for output, source_use in zip(outputs, static['host'].terminator.values, strict=True):
            assert output['source_use'] == _use(model, example['parent_final'], source_use)
            consumer, = tuple(use for use in terminal.uses if use.value == output['formal'].value)
            assert _use(model, link.completion, consumer.id).value == output['formal'].id
        call_view = index.call_activation(link.id)
        host_transfer = call_view['outputs'][0]['caller_transfer']
        host_block = blocks[next(row.block for row in model.visits if row.id == host_transfer.target)]
        host_terminal = operations[host_block.operations[-1]]
        host_occurrence = example['host_operations'][host_terminal.id]
        for ordinal, output in enumerate(call_view['outputs']):
            assert output['ordinal'] == ordinal
            assert output['edge_argument'] == CompletionResult(ordinal)
            assert output['callee_exit'].id == link.completion
            consumer, = tuple(use for use in host_terminal.uses if use.value == output['caller_formal'].value)
            assert _use(model, host_occurrence, consumer.id).value == output['caller_formal'].id

        stopped = _query(index, example, cross_resume=False)
        assert not stopped['terminals']
        assert tuple(row.id for row in stopped['segments']) == example['parent_segments'][1:2]
        assert any(row['kind'] == 'SUSPENSION' and row['operation'].id == example['parent_drives'][1].outcome
                   for row in stopped['boundaries'])
        _assert_final(_query(index, example), model, static, example)


def _missing_capture(program, model, static, example, missing):
    """Omit one occurrence fact, never a canonical source or sibling fact."""
    if missing == 'resume-transfer':
        target = static['drivers'][2]['drive'].target
        omitted = ControlTransfer(example['parent_drives'][1].outcome,
            target.successor, example['parent_entries'][2])
        assert omitted in model.transfers
        changed = replace(model, transfers=tuple(row for row in model.transfers if row != omitted))
        assert len(changed.transfers) + 1 == len(model.transfers)
    else:
        if missing == 'pending-use':
            definitions = {row.id: row for row in program.values}
            pending, = tuple(row for row in program.pending_completions
                if type(definitions[row.value].origin) is OperationResult
                and definitions[row.value].origin.operation == static['pending_pack'])
            assert pending.payload is not None
            operation = example['parent_operations'][1][definitions[pending.value].origin.operation]
            use = pending.payload
        elif missing == 'terminal-use':
            operation, use = example['parent_final'], static['host_packet'].use
        else:
            raise ValueError('missing must select one of the three occurrence facts')
        omitted = _use(model, operation, use)
        changed = replace(model, uses=tuple(row for row in model.uses if row != omitted))
        assert len(changed.uses) + 1 == len(model.uses)
    assert changed.snapshot == model.snapshot
    return changed, omitted


@pytest.mark.parametrize('close_raised', (False, True), ids=('normal-injection', 'raise-own-packet'))
@pytest.mark.parametrize('missing', ('pending-use', 'resume-transfer', 'terminal-use'))
def test_missing_close_parent_occurrence_cannot_borrow_the_complete_sibling(close_raised, missing):
    program, model, details = _capture(close_raised=close_raised)
    static = details['static']
    absent, sibling = details['instances']
    changed, omitted = _missing_capture(program, model, static, absent, missing)
    index = _index(program, changed)
    report = _query(index, absent)
    assert report['source'].id == absent['source_value']
    assert report['anchor'].id == absent['anchor']
    assert report['status'] == 'PARTIAL'
    assert report['known_inventory_complete'] is False
    assert report['cursor'] is None and not report['budget']['truncated']
    assert all(segment.activation == absent['parent_activation'] for segment in report['segments'])
    assert all(row['operation'].id != sibling['parent_final'] for row in report['terminals'])
    if missing == 'pending-use':
        assert 'pending_payload_use_unobserved' in report['gaps']
        assert 'completion_actual_projection_unproved' in report['gaps']
        assert any(row['kind'] == 'UNPROVED_PROJECTION' for row in report['boundaries'])
        projection, = report['projections']
        assert projection['constructor'].id == omitted.operation
        assert projection['payload_use'] is None and projection['payload_value'] is None
        assert projection['binding']['match'] is None
        assert not report['terminals']
    elif missing == 'resume-transfer':
        assert 'completion_actual_transfer_missing' in report['gaps']
        assert any(row['kind'] == 'MISSING_TRANSFER' and row['operation'].id == omitted.operation
                   for row in report['boundaries'])
        assert tuple(segment.id for segment in report['segments']) == absent['parent_segments'][1:2]
        assert report['drives'] == absent['parent_drives'][1:2]
        assert not report['terminals']
        assert 'resume_transfer_unobserved' in {gap.code for gap in index.report.gaps}
    else:
        assert 'await_outcome_value_unobserved' in report['gaps']
        receipt, = report['terminals']
        assert receipt['terminal'] == HostTerminal(static['host'].id)
        assert receipt['operation'].id == absent['parent_final']
        assert receipt['actual'] == static['host_packet']
        assert receipt['use'] is None and receipt['value'] is None
        assert receipt['binding']['match'] is None
        assert receipt['root_binding']['match'] is None
        assert receipt['status'] == 'PARTIAL'
        assert tuple(segment.id for segment in report['segments']) == absent['parent_segments'][1:]
    assert all(report[name] is False for name in _FLAGS)
    _assert_final(_query(index, sibling), changed, static, sibling)


@pytest.mark.parametrize('close_raised', (False, True), ids=('normal-own-none', 'raise-old-injection'))
def test_close_wrong_source_does_not_gain_the_current_packet_delivery(close_raised):
    program, model, details = _capture(close_raised=close_raised)
    index = _index(program, model)
    static = details['static']
    example, sibling = details['instances']
    _assert_final(_query(index, example), model, static, example)
    wrong = example['injected_value'] if close_raised else example['own_value']
    assert wrong != example['source_value']
    report = index.completion_continuations(wrong, example['anchor'],
        cross_resume=True, budget=1_048_576)
    assert report['source'].id == wrong
    assert report['anchor'].id == example['anchor']
    receipt, = report['terminals']
    assert receipt['terminal'] == HostTerminal(static['host'].id)
    assert receipt['operation'].id == example['parent_final']
    assert receipt['use'] == _use(model, example['parent_final'], static['host_packet'].use)
    assert receipt['binding']['match'] is True
    assert receipt['current_source'].id != wrong
    assert report['projections'][0]['payload_value'] == receipt['current_source']
    if close_raised:
        # A visible injection is not this RAISE edge's own fullslot-0 packet.
        assert receipt['root_binding']['match'] is None
        assert 'completion_source_anchor_association_unproved' in receipt['root_binding']['gaps']
        assert 'completion_source_anchor_association_unproved' in report['gaps']
    else:
        # None is a real own NORMAL Reference result. Its original kind cannot
        # turn it into the independently injected packet consumed by C1.
        assert receipt['root_binding']['match'] is False
        assert receipt['root_binding']['compatibility']['status'] == 'CONFLICT'
        assert 'await_original_copy_unproved' in receipt['root_binding']['gaps']
    assert report['status'] == 'PARTIAL'
    assert report['known_inventory_complete'] is False
    assert all(report[name] is False for name in _FLAGS)
    _assert_final(_query(index, sibling), model, static, sibling)


def test_unresolved_normal_packet_forward_keeps_source_permission_unproved():
    program, model, details = _capture(close_raised=False)
    static = details['static']
    absent, sibling = details['instances']
    values = {row.id: row for row in program.values}
    close = next(row for row in program.operations if row.id == static['helper'])
    uses = {row.id: row for row in close.uses}
    edge = close.terminator.successors[absent['selected_close']]
    assert edge.kind is ExitKind.NORMAL
    forward, = tuple(argument for argument in edge.arguments
        if type(argument) is not CompletionResult
        and isinstance(values[uses[argument].value], ProtocolValue)
        and values[uses[argument].value].protocol is ProtocolValueKind.EXCEPTION_PACKET)
    original = _use(model, absent['anchor'], forward)
    assert original.value == absent['injected_value']
    point = next(row.entry for row in model.activations if row.id == absent['parent_activation'])
    unresolved = replace(original,
        value=Unresolved('the selected NORMAL packet-forward operand is not observed', point))
    changed = replace(model, uses=tuple(unresolved if row == original else row for row in model.uses))
    assert changed.snapshot == model.snapshot
    assert len(changed.uses) == len(model.uses)
    index = _index(program, changed)
    assert 'use_unresolved' in {gap.code for gap in index.report.gaps}
    report = _query(index, absent)
    assert report['status'] == 'PARTIAL'
    assert report['known_inventory_complete'] is False
    assert report['source'].id == absent['injected_value']
    assert 'completion_source_anchor_association_unproved' in report['gaps']
    receipt, = report['terminals']
    assert receipt['operation'].id == absent['parent_final']
    assert receipt['binding']['match'] is True
    assert receipt['root_binding']['match'] is None
    assert 'completion_source_anchor_association_unproved' in receipt['root_binding']['gaps']
    assert all(segment.activation == absent['parent_activation'] for segment in report['segments'])
    assert all(report[name] is False for name in _FLAGS)
    _assert_final(_query(index, sibling), changed, static, sibling)
