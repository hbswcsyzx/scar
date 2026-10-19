"""Current async item and adapter output are two independent source edges.

The old candidate is the preceding AWAIT handoff, not an earlier ASYNC_YIELD.
It is forwarded through the third call's existing SEND/delivery ports. The
independent old packet is constructed before that call's actual body Drive.
Neither candidate changes the three body frontiers or any state operand.
"""
from dataclasses import replace

from scar.ir.program.control import ExceptionPacketDefinition, ProtocolValueKind
from scar.ir.program.ids import OperationID, UseID, ValueID
from scar.ir.program.model import (
    Behavior, CompletionResult, ExitKind, InvokeLiteralResult, Operation,
    OperationResult, ProtocolValue, ReferenceValue, StateVersionValue, Use,
    UseRole,
)
from scar.ir.program.protocols import DriveResult, OutcomeAdapter, OutcomeAdapterRule, OwnedUse
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_async_pipeline_graphs import async_pipeline_program


def _without_protocol(program):
    return replace(program, protocol_scopes=(), protocol_operations=(),
        protocol_bindings=(), protocol_call_inputs=(), protocol_result_consumers=())


def _current_item_program(*, wrong=None):
    """Retain the original pipeline and add two legal, older candidates.

    ``wrong`` selects only the adapter input or the final whole-packet Use.
    All constructor N/R signatures, result ordinals and current state Uses
    remain the original ones. This helper also serves the new execution unit.
    """
    if wrong not in (None, 'item', 'packet'):
        raise ValueError('wrong must select one of the two original source edges')
    program, static = async_pipeline_program()
    operations = {row.id: row for row in program.operations}
    values = {row.id: row for row in program.values}
    blocks = {block.id: block for region in program.regions for block in region.blocks}
    previous, third = static['drivers'][1:]
    previous_call = previous['caller_call']
    previous_normal = next(index for index, edge in enumerate(previous_call.terminator.successors)
        if edge.kind is ExitKind.NORMAL)
    previous_edge = previous_call.terminator.successors[previous_normal]
    previous_slot = next(index for index, argument in enumerate(previous_edge.arguments)
        if type(argument) is CompletionResult and argument.index == 0)
    old_reference = blocks[previous_edge.block].arguments[previous_slot]
    assert isinstance(values[old_reference], ReferenceValue)
    old_result = InvokeLiteralResult(ControlEdgeReference(previous_call.id, previous_normal),
                                    CompletionResult(0))

    call = third['caller_call']
    entry_formals = third['entry_formals']
    delivery_formal, = tuple(formal for formal in entry_formals
        if isinstance(values[formal], ReferenceValue)
        and formal not in (entry_formals[0], third['interface'].receiver))
    actuals = dict(zip(entry_formals, call.invoke_arguments, strict=True))
    scheduler_use = next(use for use in call.uses
        if use.id == actuals[third['interface'].scheduler_request])
    raw, = tuple(row for row in program.raw_driver_requests if row.value == scheduler_use.value)
    raw_operand, = raw.operands
    scheduler_pack = operations[values[raw.value].origin.operation]
    scheduler_pack = replace(scheduler_pack, uses=tuple(
        replace(use, value=old_reference) if use.id == raw_operand else use
        for use in scheduler_pack.uses))
    call = replace(call, uses=tuple(
        replace(use, value=old_reference) if use.id == actuals[delivery_formal] else use
        for use in call.uses))
    operations[scheduler_pack.id] = scheduler_pack
    operations[call.id] = call

    adapters = tuple(row for row in program.protocol_operations
        if type(row.contract) is OutcomeAdapter
        and row.contract.rule is OutcomeAdapterRule.ASYNCGEN_YIELD_TO_REQUEST_ITEM
        and row.contract.input == DriveResult(third['outcome'], 0))
    adapter_id, = {row.operation for row in adapters}
    adapter = operations[adapter_id]
    normal_adapter, = tuple(row for row in adapters
        if adapter.terminator.successors[row.contract.output.edge.successor_index].kind
        is ExitKind.NORMAL)
    host = operations[third['host_terminal'].id]
    host_payload, = tuple(use for use in host.uses
        if use.id in host.terminator.values
        and not isinstance(values[use.value], StateVersionValue))
    current_packet, = tuple(row for row in program.exception_packets
        if row.value == host_payload.value)
    packet_origin = values[current_packet.value].origin
    packet_operation = operations[packet_origin.operation]
    traceback = next(use.value for use in packet_operation.uses
                     if use.id == current_packet.traceback)

    old_packet_id = OperationID('async.current.old.packet')
    old_packet = ProtocolValue(ValueID('async.current.old.packet.value'),
        third['driver_region'].id, OperationResult(old_packet_id, 0),
        ProtocolValueKind.EXCEPTION_PACKET)
    old_packet_uses = (
        Use(UseID('async.current.old.packet.exception'), delivery_formal, UseRole.REFERENCE),
        Use(UseID('async.current.old.packet.traceback'), traceback, UseRole.REFERENCE),
    )
    old_pack = Operation(old_packet_id, 'independent packet of the older handoff',
        (Behavior.CONTROL,), old_packet_uses, (old_packet.id,), effects_complete=True)
    old_definition = ExceptionPacketDefinition(old_packet.id,
        old_packet_uses[0].id, old_packet_uses[1].id)
    if wrong == 'item':
        adapter = replace(adapter, uses=tuple(
            replace(use, value=delivery_formal)
            if use.id == normal_adapter.contract.input_use else use
            for use in adapter.uses))
        operations[adapter.id] = adapter
    if wrong == 'packet':
        host = replace(host, uses=tuple(
            replace(use, value=old_packet.id) if use.id == host_payload.id else use
            for use in host.uses))
        operations[host.id] = host
    driver = next(region for region in program.regions if region.id == third['driver_region'].id)
    driver = replace(driver, blocks=tuple(
        replace(block, operations=(old_pack.id, *block.operations))
        if block.id == driver.entry else block for block in driver.blocks))
    program = replace(program,
        regions=tuple(driver if region.id == driver.id else region for region in program.regions),
        operations=tuple(operations[row.id] for row in program.operations) + (old_pack,),
        values=(*program.values, old_packet),
        exception_packets=(*program.exception_packets, old_definition))
    changed_third = dict(third, caller_call=call, driver_region=driver, host_terminal=host)
    static = dict(static, calls=(*static['calls'][:2], call),
        drivers=(*static['drivers'][:2], changed_third))
    current = {
        'old_result': old_result, 'old_reference': old_reference,
        'old_delivery': OwnedUse(call.id, actuals[delivery_formal]),
        'delivery_formal': delivery_formal,
        'old_pack': old_pack, 'old_packet': old_definition,
        'item': DriveResult(third['outcome'], 0),
        'adapter': adapter, 'adapter_row': normal_adapter,
        'adapter_input': OwnedUse(adapter.id, normal_adapter.contract.input_use),
        'adapter_output': normal_adapter.contract.output,
        'packet_operation': packet_operation, 'packet': current_packet,
        'packet_component': OwnedUse(packet_operation.id, current_packet.exception),
        'packet_result': packet_origin,
        'host': host, 'host_payload': OwnedUse(host.id, host_payload.id),
    }
    return program, dict(static, current_item=current)


def test_old_candidates_do_not_replace_the_three_drive_current_item_chain():
    from scar.ir.program.lifecycle import SessionPost

    program, details = _current_item_program()
    require_valid(_without_protocol(program))
    require_valid(program)
    current = details['current_item']
    index = ProgramIndex(program)
    assert index.source_binding(current['old_result'], current['old_delivery'])['match'] is True
    assert index.source_binding(current['item'], current['adapter_input'])['match'] is True
    assert index.source_binding(current['adapter_output'], current['packet_component'])['match'] is True
    assert index.source_binding(current['packet_result'], current['host_payload'])['match'] is True
    assert index.source_binding(current['adapter_output'],
        OwnedUse(current['old_pack'].id, current['old_packet'].exception))['match'] is False
    assert len(program.body_drives) == 3
    assert [row['update'].post for row in details['drivers']] == [
        SessionPost.HOLD, SessionPost.HOLD, SessionPost.COMPLETE]
    public = index.protocol_obligations(budget=131072)
    sessions = public['connections']['families']['async']['session_consumers']
    assert {row['source'] for row in sessions} == {row['outcome'] for row in details['drivers']}
    assert all(row['targets'] and row['known_inventory_complete'] for row in sessions)
    assert public['source_runtime_verified'] is False
    assert public['transformation_authorized'] is False


def test_old_same_type_handoff_cannot_supply_this_async_yield_adapter_input():
    program, details = _current_item_program(wrong='item')
    require_valid(_without_protocol(program))
    current = details['current_item']
    core = ProgramIndex(_without_protocol(program))
    assert core.source_binding(current['old_result'], current['old_delivery'])['match'] is True
    assert core.source_binding(current['item'], current['adapter_input'])['match'] is False
    assert core.source_binding(current['adapter_output'], current['packet_component'])['match'] is True
    assert core.source_binding(current['packet_result'], current['host_payload'])['match'] is True
    assert 'protocol_copy' in {issue.code for issue in validate(program)}


def test_old_typed_packet_cannot_replace_this_item_adapters_own_host_packet():
    program, details = _current_item_program(wrong='packet')
    require_valid(_without_protocol(program))
    current = details['current_item']
    core = ProgramIndex(_without_protocol(program))
    assert core.source_binding(current['item'], current['adapter_input'])['match'] is True
    assert core.source_binding(current['adapter_output'], current['packet_component'])['match'] is True
    assert core.source_binding(current['packet_result'], current['host_payload'])['match'] is False
    assert core.source_binding(OperationResult(current['old_pack'].id, 0),
        current['host_payload'])['match'] is True
    assert 'protocol_copy' in {issue.code for issue in validate(program)}
