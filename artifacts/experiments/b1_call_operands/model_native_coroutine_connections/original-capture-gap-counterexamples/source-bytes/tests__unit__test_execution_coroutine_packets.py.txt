"""Native Suspended THROW/CLOSE keep current own packets and actual ports."""
from dataclasses import replace

import pytest

from scar.ir.execution.coordinates import OccurrencePhase, OccurrencePoint, ResumeIngress
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validation import validate as execution_validate
from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.program.drivers import RawRequestKind
from scar.ir.program.model import CompletionResult, ExitKind, StateVersionValue, TerminatorKind
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.protocol_continuations import continuation_connections
from scar.ir.program.protocols import OutcomeAdapter, OutcomeAdapterRule, OwnedUse, ProtocolProfile
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.resumption import ResumableKind, ResumeSlotKind, SuspensionFlavor, SuspendTerminator
from scar.ir.program.validation import require_valid, validate as program_validate
from tests.fixtures.execution_coroutine_packets_graphs import (
    coroutine_suspended_packet_execution, coroutine_suspended_packet_program,
)


def _core(program):
    return replace(program, protocol_scopes=(), protocol_operations=(), protocol_call_inputs=(),
                   protocol_result_consumers=(), protocol_bindings=())


def _use(model, occurrence, identity):
    rows = tuple(row for row in model.uses if row.operation == occurrence and row.use == identity)
    assert len(rows) == 1
    return rows[0]


def _value(model, identity):
    return next(row for row in model.values if row.id == identity)


def _copied_from(view, target, source):
    copies = {row['target']: row['source'] for row in view['copy_support']}
    cursor, seen = target, set()
    while cursor != source and cursor not in seen and cursor in copies:
        seen.add(cursor)
        cursor = copies[cursor]
    assert cursor == source


def _own(program, model, occurrence, port):
    canonical = next(row for row in program.operations if row.id == port.edge.operation)
    transfer, = tuple(row for row in model.transfers if row.operation == occurrence)
    assert transfer.successor_index == port.edge.successor_index
    edge = canonical.terminator.successors[transfer.successor_index]
    block = next(block for region in program.regions for block in region.blocks if block.id == edge.block)
    formal, = tuple(formal for actual, formal in zip(edge.arguments, block.arguments)
                    if type(actual) is CompletionResult and actual.index == port.result.index)
    value, = tuple(row for row in model.values if row.origin == transfer.target and row.value == formal)
    return value


def _resume_obligation(program, details):
    index = ProgramIndex(program)
    report = continuation_connections(ConnectionContext(program, index=index, budget=ValidityBudget(262144)))
    drive = details['drivers'][-1]['drive']
    rows = tuple(row for row in report['obligations'] if row['site'].operation == drive.operation)
    assert len(rows) == 1
    return {**rows[0], 'gaps': report['gaps']}


def _assert_current_states(index, program, model, operation):
    definition = next(row for row in program.operations if row.id == operation.operation)
    state = index.state_at(OccurrencePoint(operation.id, OccurrencePhase.BEFORE))
    assert state is not None
    values = {row.id: row for row in program.values}
    actuals = tuple(use for use in definition.uses if type(values[use.value]) is StateVersionValue)
    assert {values[use.value].location for use in actuals} == {row.id for row in program.locations}
    for use in actuals:
        value = _value(model, _use(model, operation.id, use.id).value)
        assert state[values[use.value].location] == value.id


@pytest.mark.parametrize('kind', (RawRequestKind.THROW, RawRequestKind.CLOSE), ids=('throw', 'close'))
@pytest.mark.parametrize('normalization_raised', (False, True), ids=('own-normal', 'own-raise'))
def test_native_suspended_packets_follow_their_exact_normalizer_and_body_ports(kind, normalization_raised):
    program, model, details = coroutine_suspended_packet_execution(kind,
        normalization_raised=normalization_raised, instances=2)
    require_valid(program)
    validation = execution_validate(model, program)
    assert validation.valid, validation.issues
    index = ExecutionIndex(model, program)
    static, packet = details['static'], details['static']['packet']
    definitions = {row.id: row for row in program.operations}
    body, = program.resumable_bodies
    assert body.kind is ResumableKind.COROUTINE
    suspends = tuple(row for row in program.operations if type(row.terminator) is SuspendTerminator)
    assert len(suspends) == 2
    assert all(row.terminator.flavor is SuspensionFlavor.AWAIT for row in suspends)
    assert all(row.profile is ProtocolProfile.COROUTINE_BODY_V1 for row in program.protocol_scopes)
    final = static['drivers'][-1]
    second = definitions[static['second_suspend']]
    assert final['drive'].target.suspend == second.id and final['drive'].target.successor == 1
    ingress = second.terminator.successors[1]
    assert ingress.inputs[final['drive'].resume_inputs[0].slot].kind is ResumeSlotKind.THROWN_PACKET
    first = next(row for row in suspends if row.id != second.id)
    assert ingress.block != first.terminator.successors[1].block
    assert tuple(row.contract.result for row in packet['rows']) == (packet['normal_result'], packet['raise_result'])
    binding = ProgramIndex(program).source_binding(packet['normal_source'],
        OwnedUse(final['drive'].operation, final['drive'].resume_inputs[0].source), budget=262144)
    assert binding['match'] is True
    obligation = _resume_obligation(program, static)
    assert obligation['status'] == 'DECLARED' and obligation['binding']['match'] is True
    if kind is RawRequestKind.CLOSE:
        close_rows = tuple(row for row in program.protocol_operations if type(row.contract) is OutcomeAdapter)
        assert len(close_rows) == 1 and close_rows[0].contract.rule is OutcomeAdapterRule.CLOSE_RETURN_VALUE
    else:
        assert not any(type(row.contract) is OutcomeAdapter for row in program.protocol_operations)

    expected_drives = 2 if normalization_raised else 3
    assert len({example['creation'] for example in details['instances']}) == 2
    assert len({example['body_activation'] for example in details['instances']}) == 2
    for example in details['instances']:
        assert len(example['body_segments']) == expected_drives
        assert len(example['body_drives']) == expected_drives
        assert example['active_driver_ordinals'] == tuple(range(expected_drives))
        assert {row.activation for row in example['body_drives']} == {example['body_activation']}
        origin = index.body_activation_origin(example['body_activation'], budget=262144)
        assert origin['association'] == example['body_origin']
        assert origin['association'].creation == example['creation']
        for ordinal, association in enumerate(example['body_drives']):
            view = index.drive_execution(association.drive, budget=262144)
            assert view['association'] == association
            assert view['entry'].id == example['body_entries'][ordinal]
            assert view['instance']['creation_handle'] is not None
            _copied_from(view, view['instance']['value'].id, view['instance']['creation_handle'].id)
            assert not any(gap.code == 'body_instance_copy_unproved' for gap in view['gaps'])
            assert len(view['outputs']) == 3
            assert all(row['source_value'] is not None and row['formal'] is not None
                       for row in (*view['inputs'], *view['outputs']))
            for key in ('source_runtime_verified', 'runtime_identity_verified', 'value_identity_verified',
                        'transformation_authorized'):
                assert view[key] is False
        driver_operations = example['driver_scopes'][2][2]
        normalizer = driver_operations[packet['normalizer']]
        own_port = packet['raise_result'] if normalization_raised else packet['normal_result']
        own = _own(program, model, normalizer, own_port)
        route = index.formal_route(own.id)
        assert route.transfer.operation == normalizer
        assert route.argument == CompletionResult(0)
        for association in example['call_activations']:
            call = index.call_activation(association.id)
            assert call['association'] == association
            assert len(call['outputs']) == 3
            assert all(row['callee_use'] is not None and row['caller_formal'] is not None
                       for row in call['outputs'])
        host = next(row for row in model.operations if row.id == driver_operations[final['host_terminal'].id])
        _assert_current_states(index, program, model, host)
        caller_terminal = example['caller_operations'][static['caller_terminal'].id]
        terminal = next(row for row in model.operations if row.id == caller_terminal)
        _assert_current_states(index, program, model, terminal)
        host_payload = _value(model, _use(model, host.id, final['host_terminal'].terminator.values[0]).value)
        if normalization_raised:
            assert own == host_payload
            assert final['drive'].operation not in driver_operations
            assert host.operation == packet['normalizer_failure']
            assert definitions[host.operation].terminator.kind is TerminatorKind.RAISE
            assert packet['guard']['predicate'] not in driver_operations
        else:
            association = example['body_drives'][2]
            view = index.drive_execution(association.drive, budget=262144)
            delivered, = tuple(row for row in view['inputs'] if row['role'] == 'delivered')
            assert delivered['binding'].source.use.id == final['drive'].resume_inputs[0].source
            _copied_from(view, delivered['formal'].id, own.id)
            segment = next(row for row in model.segments if row.id == example['body_segments'][2])
            assert type(segment.ingress) is ResumeIngress
            assert segment.ingress.suspension == example['body_drives'][1].outcome
            assert segment.ingress.successor_index == 1
            outcome = definitions[static['body_terminal'].id]
            assert outcome.id == static['drivers'][2]['outcome_source']
            expected = TerminatorKind.RAISE if kind is RawRequestKind.THROW else TerminatorKind.RETURN
            assert outcome.terminator.kind is expected
            assert definitions[host.operation].terminator.kind is expected
            if kind is RawRequestKind.THROW:
                output, = tuple(row for row in view['outputs']
                    if row['binding'].actual.use.id == outcome.terminator.values[0])
                assert output['source_value'].id == delivered['formal'].id
            else:
                assert definitions[outcome.id].uses[0].value != delivered['formal'].value
        last_call = index.call_activation(example['call_activations'][2].id)
        payload_output, = tuple(row for row in last_call['outputs'] if row['callee_use'].use == final['host_terminal'].terminator.values[0])
        assert payload_output['callee_use'].value == host_payload.id
        terminal_payload = _use(model, terminal.id, static['caller_terminal'].terminator.values[0])
        assert terminal_payload.value == payload_output['caller_formal'].id


def test_same_typed_independent_packet_cannot_replace_current_normalizer_own_packet():
    program, details = coroutine_suspended_packet_program(RawRequestKind.THROW, wrong_packet=True)
    core = _core(program)
    require_valid(core)
    final = details['drivers'][-1]['drive']
    binding = ProgramIndex(core).source_binding(details['packet']['normal_source'].result_port,
        OwnedUse(final.operation, final.resume_inputs[0].source), budget=262144)
    assert binding['match'] is False
    report = program_validate(program)
    assert report
    assert any(issue.code == 'protocol_copy' and issue.path == str(final.operation) for issue in report)


def test_removed_packet_source_keeps_the_original_thrown_packet_obligation():
    program, details = coroutine_suspended_packet_program(RawRequestKind.CLOSE, attach_source=False)
    require_valid(program)
    obligation = _resume_obligation(program, details)
    assert obligation['kind'] is ResumeSlotKind.THROWN_PACKET
    assert obligation['status'] == 'MISSING'
    assert any(gap['code'] == 'continuation_resume_source_missing' for gap in obligation['gaps'])
