"""Typed call carriers do not authorize packet construction or wrong sources.

All variants retain the original await scopes. Clearing connection attachments
below does not claim coverage of the separate legacy has-capability-false path.
"""
from dataclasses import replace

import pytest

from scar.ir.program.control import ExceptionPacketDefinition, ProtocolValueKind
from scar.ir.program.ids import OperationID, UseID, ValueID
from scar.ir.program.model import (
    Behavior, ExitKind, LiteralOrigin, Operation, OperationResult, ProtocolValue,
    ReferenceValue, Use, UseRole, value_type,
)
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_await_consumer_call_graphs import await_consumer_call_program


def _codes(graph):
    return {issue.code for issue in validate(graph)}


def _core(graph):
    return replace(graph, protocol_scopes=(), protocol_operations=(),
        protocol_call_inputs=(), protocol_result_consumers=(), protocol_bindings=())


def _no_connection_attachments(graph):
    return replace(graph, protocol_call_inputs=(), protocol_result_consumers=(),
                   protocol_bindings=())


def _insert_packet(graph, details, *, defined, effects_complete=True):
    """A distinct local producer before H, with genuine reference operands."""
    identity = OperationID('carrier.independent.packet')
    traceback = ReferenceValue(ValueID('carrier.independent.traceback'),
        details['caller'].id, LiteralOrigin(None), targets=())
    exception_use = Use(UseID('carrier.independent.exception'),
                        details['sent_value'], UseRole.REFERENCE)
    traceback_use = Use(UseID('carrier.independent.traceback.use'),
                        traceback.id, UseRole.REFERENCE)
    packet = ProtocolValue(ValueID('carrier.independent.packet.value'),
        details['caller'].id, OperationResult(identity, 0),
        ProtocolValueKind.EXCEPTION_PACKET)
    producer = Operation(identity, 'independent packet-shaped local result',
        (Behavior.CONTROL,), (exception_use, traceback_use), (packet.id,),
        effects_complete=effects_complete)
    first_call = details['helper_calls'][0]
    caller = next(region for region in graph.regions if region.id == details['caller'].id)
    caller = replace(caller, blocks=tuple(replace(block, operations=tuple(
        item for operation in block.operations
        for item in ((producer.id, operation) if operation == first_call.id else (operation,))))
        if first_call.id in block.operations else block for block in caller.blocks))
    definitions = (() if not defined else
        (ExceptionPacketDefinition(packet.id, exception_use.id, traceback_use.id),))
    return replace(graph,
        regions=tuple(caller if region.id == caller.id else region for region in graph.regions),
        operations=(*graph.operations, producer), values=(*graph.values, traceback, packet),
        exception_packets=(*graph.exception_packets, *definitions)), packet, producer


def test_known_ordinary_call_packet_is_a_carrier_without_a_local_packet_definition():
    graph, details = await_consumer_call_program()
    call = details['helper_calls'][0]
    packet = details['forwarded_values'][0]
    assert type(packet) is ProtocolValue
    assert packet.protocol is ProtocolValueKind.EXCEPTION_PACKET
    assert packet.origin == OperationResult(call.id, 0)
    assert call.results[0] == packet.id and call.terminator is None
    assert not any(row.value == packet.id for row in graph.exception_packets)
    helper = details['helper_records'][0]
    assert helper['terminal'].terminator.values[0] == helper['exit_uses'][0].use
    assert helper['region'].exits[0].kind is ExitKind.NORMAL
    assert helper['region'].exits[0].types[0] == value_type(packet)
    require_valid(_core(graph))
    require_valid(graph)


def test_a_fake_local_packet_definition_on_the_call_result_is_still_rejected():
    graph, details = await_consumer_call_program()
    require_valid(graph)
    call = details['helper_calls'][0]
    fake = ExceptionPacketDefinition(details['forwarded_values'][0].id,
        call.call_arguments[0], call.call_arguments[1])
    changed = replace(graph, exception_packets=(*graph.exception_packets, fake))
    assert 'protocol_pack_operation' in _codes(changed)


@pytest.mark.parametrize('effects_complete', (True, False),
                         ids=('primitive', 'unknown-producer'))
def test_an_unconstructed_local_packet_is_not_exempted_by_an_unrelated_known_call(effects_complete):
    graph, details = await_consumer_call_program()
    require_valid(graph)
    changed, packet, producer = _insert_packet(graph, details,
        defined=False, effects_complete=effects_complete)
    assert producer.callee is None and producer.call_arguments == ()
    assert producer.results == (packet.id,)
    assert not any(row.value == packet.id for row in changed.exception_packets)
    # Isolate the constructor check from all optional semantic declarations.
    assert _codes(_core(changed)) == {'protocol_definition_missing'}


@pytest.mark.parametrize('mismatch', ('type', 'ordinal'))
def test_the_callee_normal_result_type_and_full_ordinal_still_constrain_the_carrier(mismatch):
    graph, details = await_consumer_call_program()
    require_valid(graph)
    record = details['helper_records'][0]
    region, terminal = record['region'], record['terminal']
    normal = region.exits[0]
    extra_values = ()
    if mismatch == 'type':
        reference = ReferenceValue(ValueID('carrier.helper.reference.result'), region.id,
                                   LiteralOrigin(None), targets=())
        packet_use = record['exit_uses'][0].use
        terminal = replace(terminal, uses=tuple(replace(use,
            value=reference.id, role=UseRole.REFERENCE) if use.id == packet_use else use
            for use in terminal.uses))
        types = (value_type(reference), *normal.types[1:])
        extra_values = (reference,)
    else:
        # Keep the callee itself correctly typed while moving packet after a
        # state slot. The caller still declares packet/world/context results.
        order = (1, 0, 2)
        terminal = replace(terminal, terminator=replace(terminal.terminator,
            values=tuple(terminal.terminator.values[slot] for slot in order)))
        types = tuple(normal.types[slot] for slot in order)
    region = replace(region, exits=(replace(normal, types=types),))
    changed = replace(graph,
        regions=tuple(region if row.id == region.id else row for row in graph.regions),
        operations=tuple(terminal if row.id == terminal.id else row for row in graph.operations),
        values=(*graph.values, *extra_values))
    assert 'call_result_type' in _codes(_core(changed))


def test_old_protocol_copy_checks_reject_a_same_typed_wrong_packet_without_connection_attachments():
    graph, details = await_consumer_call_program()
    baseline = _no_connection_attachments(graph)
    require_valid(baseline)
    changed, packet, _ = _insert_packet(baseline, details, defined=True)
    call = details['helper_calls'][0]
    packet_actual = call.call_arguments[0]
    call = replace(call, uses=tuple(replace(use, value=packet.id)
        if use.id == packet_actual else use for use in call.uses))
    changed = replace(changed, operations=tuple(call if row.id == call.id else row
                                               for row in changed.operations))
    assert changed.protocol_call_inputs == changed.protocol_result_consumers == ()
    assert changed.protocol_bindings == ()
    assert changed.protocol_scopes == baseline.protocol_scopes
    assert changed.protocol_operations == baseline.protocol_operations
    assert details['root_source'] == details['final_rows'][0].contract.input.result_port
    # The new packet, H actual/result and current state ports are structurally
    # valid. Existing semantic rows still require the original advance packet.
    require_valid(_core(changed))
    assert 'protocol_copy' in _codes(changed)
