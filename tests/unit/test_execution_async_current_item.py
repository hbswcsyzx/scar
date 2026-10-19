"""Actual current item/adapter/packet Uses over the original three Drives.

Static wrong-source programs are rejected at ProgramIndex, before execution's
resumable preparation, and belong to the companion program tests. Pointing a
UseOccurrence at a different canonical Value would instead be use_definition.
These missing-capture cases retain the full valid program and omit only one
current Use; the older candidate and its independent packet stay captured.
"""
from dataclasses import replace

import pytest

from scar.ir.execution.coordinates import InitialEntry, ResumeIngress
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.snapshot import snapshot_for
from scar.ir.execution.validation import validate
from scar.ir.program.lifecycle import SessionPost
from scar.ir.program.model import CompletionResult, ExitKind, StateVersionValue
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_async_pipeline_graphs import async_pipeline_execution, _caller_path
from tests.fixtures.execution_await_outcome_graphs import _rebuild
from tests.unit.test_program_async_current_item import _current_item_program


def _current_item_execution():
    """Rebuild only the changed caller and final synchronous driver capture."""
    _, model, original = async_pipeline_execution()
    program, static = _current_item_program()
    point = next(row.entry for row in model.activations if row.id == original['root_activation'])
    model, caller_visits, caller_operations = _rebuild(program, model,
        original['root_activation'], static['caller'], _caller_path(program, static), point)
    final = static['drivers'][2]
    model, driver_visits, driver_operations = _rebuild(program, model,
        original['driver_activations'][2], final['driver_region'], final['path'], point)
    model = replace(model, snapshot=snapshot_for(program))
    return program, model, dict(original, static=static,
        root_path=caller_visits, caller_operations=caller_operations,
        current_driver_visits=driver_visits, current_driver_operations=driver_operations)


def _index(program, model):
    require_valid(program)
    report = validate(model, program)
    assert report.valid, report.issues
    return ExecutionIndex(model, program)


def _use(model, operation, identity):
    return next(row for row in model.uses if (row.operation, row.use) == (operation, identity))


def _value(model, identity):
    return next(row for row in model.values if row.id == identity)


def _definition(model, origin, identity):
    return next(row for row in model.values if row.origin == origin and row.value == identity)


def _transfer(model, occurrence):
    return next(row for row in model.transfers if row.operation == occurrence)


def _sessions(index, program, model, details):
    """Keep B/R, the real three cuts, each CallActivation and current post."""
    assert len(model.body_drive_executions) == len(model.call_activations) == 3
    origin, = model.body_activation_origins
    assert origin.activation == details['body_activation']
    assert origin.creation == details['body_creation_occurrence']
    segments = {row.id: row for row in model.segments}
    assert len(set(details['body_segments'])) == 3
    for number, identity in enumerate(details['body_segments']):
        segment = segments[identity]
        assert segment.activation == details['body_activation']
        if number == 0:
            assert type(segment.ingress) is InitialEntry
        else:
            assert type(segment.ingress) is ResumeIngress
            assert segment.ingress.suspension == details['body_outcomes'][number - 1]
            selected = details['static']['drivers'][number]['drive'].target.successor
            assert segment.ingress.successor_index == selected
            transfer = _transfer(model, segment.ingress.suspension)
            assert transfer.successor_index == selected
            assert transfer.target == details['body_entries'][number]

    result = []
    for number, drive in enumerate(details['body_drive_occurrences']):
        static = details['static']['drivers'][number]
        actual = next(row for row in model.body_drive_executions if row.drive == drive)
        assert actual.activation == details['body_activation']
        assert actual.entry == details['body_entries'][number]
        assert actual.outcome == details['body_outcomes'][number]
        view = index.drive_execution(drive, budget=131072)
        session = view['session']
        assert not view['budget']['truncated']
        assert session['source'] == static['outcome']
        assert session['expected_post'] is (SessionPost.COMPLETE if number == 2 else SessionPost.HOLD)
        assert session['target_count'] == session['host_count'] == 1
        target, = session['targets']
        assert target['update'] == static['update']
        assert target['occurrence'].id == details['session_update_occurrences'][number]
        assert target['binding'].source == static['outcome']
        assert target['post_established'] is True
        assert target['state_bindings']
        for binding in target['state_bindings']:
            assert binding['use'] is not None and binding['value'] is not None
            assert binding['current'] == binding['value'].id
        assert target['state_outputs'] and all(value is not None
            for value in target['state_outputs'].values())
        link, = tuple(row for row in model.call_activations
            if row.caller == details['caller_operations'][static['caller_call'].id])
        assert link.activation == details['driver_activations'][number]
        host, = session['hosts']
        assert host['operation'].id == link.completion
        assert host['definition'] == static['host_terminal']
        for flag in ('source_runtime_verified', 'runtime_identity_verified',
                     'value_identity_verified', 'transformation_authorized'):
            assert session[flag] is False
        result.append((view, session, host, link))
    return tuple(result)


def test_actual_current_async_item_reaches_its_own_adapter_packet_and_caller_slots():
    program, model, details = _current_item_execution()
    index = _index(program, model)
    (_, session, host, link) = _sessions(index, program, model, details)[2]
    current = details['static']['current_item']
    sites = details['current_driver_operations']
    blocks = {block.id: block for region in program.regions for block in region.blocks}
    values = {row.id: row for row in program.values}
    body_operation = next(row for row in program.operations
        if row.id == details['static']['body']['async_yield'].id)
    exported = _value(model, _use(model, details['body_outcomes'][2],
        body_operation.terminator.exported).value)
    adapter_occurrence = sites[current['adapter'].id]
    current_input = _value(model, _use(model, adapter_occurrence,
        current['adapter_input'].use).value)
    first, second = host['bindings']
    assert first['source_value'] == exported
    assert first['target_value'] == current_input
    assert first['copy_status'] == 'DECLARED_ORIGINAL_COPY'
    assert host['adapter']['occurrence'].id == adapter_occurrence
    assert host['adapter']['input'] == current_input

    normal = _transfer(model, adapter_occurrence)
    output_port = current['adapter_output']
    assert normal.successor_index == output_port.edge.successor_index
    normal_edge = current['adapter'].terminator.successors[normal.successor_index]
    assert normal_edge.kind is ExitKind.NORMAL
    slot = next(index for index, argument in enumerate(normal_edge.arguments)
        if type(argument) is CompletionResult and argument.index == output_port.result.index)
    produced = _definition(model, normal.target, blocks[normal_edge.block].arguments[slot])
    component_use = _use(model, sites[current['packet_operation'].id], current['packet'].exception)
    assert component_use.value == produced.id
    assert host['adapter']['output'] == produced
    assert second['source_value'] == second['target_value'] == produced
    assert second['copy_status'] == 'DECLARED_ORIGINAL_COPY'
    packet = _definition(model, sites[current['packet_operation'].id], current['packet'].value)
    assert host['target_value'] == packet
    assert _use(model, link.completion, current['host_payload'].use).value == packet.id

    # The preceding AWAIT value has its own exact caller result and delivery
    # route, but is not this current export's original copy source.
    previous_call = details['static']['drivers'][1]['caller_call']
    previous_link, = tuple(row for row in model.call_activations
        if row.caller == details['caller_operations'][previous_call.id])
    previous_output = index.call_activation(previous_link.id)['outputs'][0]
    old_actual = _use(model, details['caller_operations'][current['old_delivery'].operation],
                      current['old_delivery'].use)
    assert previous_output['caller_formal'].id == old_actual.value
    delivery, = tuple(row for row in index.call_activation(link.id)['inputs']
        if row['formal_definition'].id == current['delivery_formal'])
    assert delivery['actual_value'].id == old_actual.value
    old_component = _use(model, sites[current['old_pack'].id], current['old_packet'].exception)
    assert old_component.value == delivery['formal'].id
    assert old_component.value != current_input.id
    old_packet = _definition(model, sites[current['old_pack'].id], current['old_packet'].value)
    assert old_packet.id != packet.id
    assert host['target_value'] != old_packet

    # Every payload/state ordinal travels through this driver's real RAISE
    # completion to the original caller terminal, with no state substitution.
    caller_transfer = _transfer(model, link.caller)
    call = details['static']['drivers'][2]['caller_call']
    caller_edge = call.terminator.successors[caller_transfer.successor_index]
    assert caller_edge.kind is ExitKind.RAISE
    caller_block = blocks[caller_edge.block]
    caller_terminal = next(row for row in program.operations
        if row.id == caller_block.operations[-1])
    caller_terminal_occurrence = details['caller_operations'][caller_terminal.id]
    outputs = index.call_activation(link.id)['outputs']
    assert len(outputs) == len(current['host'].terminator.values)
    for ordinal, (output, use_id) in enumerate(zip(outputs,
            current['host'].terminator.values, strict=True)):
        assert output['ordinal'] == ordinal
        assert output['callee_exit'].id == link.completion
        assert output['callee_use'] == _use(model, link.completion, use_id)
        assert output['edge_argument'] == CompletionResult(ordinal)
        assert output['caller_transfer'] == caller_transfer
        caller_formal = output['caller_formal']
        assert caller_formal.origin == caller_transfer.target
        consumer, = tuple(use for use in caller_terminal.uses if use.value == caller_formal.value)
        assert _use(model, caller_terminal_occurrence, consumer.id).value == caller_formal.id
        definition = values[output['callee_use_definition'].value]
        if isinstance(definition, StateVersionValue):
            assert values[caller_formal.value].location == definition.location
            assert _value(model, output['callee_use'].value).origin == normal.target
    assert session['targets'][0]['post_established'] is True


@pytest.mark.parametrize('missing', ('adapter_input', 'packet_component', 'host_payload'))
def test_missing_current_item_edge_cannot_borrow_the_still_captured_old_packet(missing):
    program, model, details = _current_item_execution()
    current = details['static']['current_item']
    sites = details['current_driver_operations']
    ports = {'adapter_input': current['adapter_input'],
             'packet_component': current['packet_component'],
             'host_payload': current['host_payload']}
    port = ports[missing]
    occurrence = sites[port.operation]
    changed = replace(model, uses=tuple(row for row in model.uses
        if (row.operation, row.use) != (occurrence, port.use)))
    assert len(changed.uses) + 1 == len(model.uses)
    index = _index(program, changed)
    (_, session, host, link) = _sessions(index, program, changed, details)[2]
    assert host['operation'].id == link.completion
    assert host['adapter']['occurrence'].id == sites[current['adapter'].id]
    assert host['adapter']['output'] is not None
    assert _definition(changed, sites[current['old_pack'].id], current['old_packet'].value)
    assert _use(changed, sites[current['old_pack'].id], current['old_packet'].exception)
    codes = {gap.code for gap in session['gaps']}
    if missing == 'adapter_input':
        assert host['adapter']['input'] is None
        assert host['bindings'][0]['target_value'] is None
        assert host['bindings'][0]['copy_status'] == 'UNPROVED'
        assert 'body_session_copy_unproved' in codes
    elif missing == 'packet_component':
        assert host['target_value'].value == current['packet'].value
        assert len(host['bindings']) == 1
        assert host['bindings'][0]['copy_status'] == 'DECLARED_ORIGINAL_COPY'
        assert 'body_session_packet_route_unproved' in codes
    else:
        assert host['target_value'] is None
        assert host['bindings'][0]['copy_status'] == 'DECLARED_ORIGINAL_COPY'
        assert 'body_session_adapter_result_missing' in codes
    assert session['status'] == 'PARTIAL'
    assert session['targets'][0]['post_established'] is True
