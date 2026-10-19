"""Two original request sources, one body, and exact rejection/current slots."""
from dataclasses import replace

import pytest

from scar.ir.execution.coordinates import InitialEntry, OccurrencePhase, OccurrencePoint, ResumeIngress
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validation import validate as execution_validate
from scar.ir.program.model import AccessMode, Behavior, CompletionResult, ExitKind, FootprintKind, OperationResult, StateVersionValue, TerminatorKind
from scar.ir.program.protocol_connections import AsyncSessionOutcome
from scar.ir.program.protocols import OutcomeAdapter, OutcomeAdapterRule, OwnedUse
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.lifecycle import LifecyclePostBinding, SessionPost
from scar.ir.program.resumption import ResumableKind, SuspendTerminator, SuspensionFlavor
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_async_competition_graphs import async_competition_execution


_BUDGET = 524288
_FLAGS = ('source_runtime_verified', 'runtime_identity_verified',
          'value_identity_verified', 'transformation_authorized')


def _index(program, model):
    require_valid(program)
    report = execution_validate(model, program)
    assert report.valid, report.issues
    return ExecutionIndex(model, program)


def _use(model, operation, identity):
    rows = tuple(row for row in model.uses if (row.operation, row.use) == (operation, identity))
    assert len(rows) == 1
    return rows[0]


def _own(program, model, operation, port):
    canonical = next(row for row in program.operations if row.id == port.edge.operation)
    transfer, = tuple(row for row in model.transfers if row.operation == operation)
    assert transfer.successor_index == port.edge.successor_index
    edge = canonical.terminator.successors[transfer.successor_index]
    block = next(block for region in program.regions for block in region.blocks if block.id == edge.block)
    formal, = tuple(formal for actual, formal in zip(edge.arguments, block.arguments)
                    if type(actual) is CompletionResult and actual.index == port.result.index)
    result, = tuple(row for row in model.values if row.origin == transfer.target and row.value == formal)
    return result


def _current(index, program, model, occurrence):
    actual = next(row for row in model.operations if row.id == occurrence)
    definition = next(row for row in program.operations if row.id == actual.operation)
    definitions = {row.id: row for row in program.values}
    current = index.state_at(OccurrencePoint(occurrence, OccurrencePhase.BEFORE))
    state_uses = tuple(use for use in definition.uses if type(definitions[use.value]) is StateVersionValue)
    assert {definitions[use.value].location for use in state_uses} == {row.id for row in program.locations}
    for use in state_uses:
        assert current[definitions[use.value].location] == _use(model, occurrence, use.id).value
    return current


def _r2_complete(index, program, model, details, number):
    """The selected busy rejection first publishes R2's own COMPLETE post."""
    static, example = details['static'], details['instances'][number]
    occupancy = static['occupancy']
    update, operation = occupancy['completion_update'], occupancy['completion_operation']
    assert update in program.session_updates
    assert update.operation == operation.id
    assert update.binding is LifecyclePostBinding.AFTER_OPERATION
    assert update.post is SessionPost.COMPLETE
    assert operation.effects_complete is True and operation.terminator is None
    assert set(operation.behaviors) == {Behavior.CONTROL, Behavior.READ, Behavior.WRITE}
    assert {access.location for access in operation.accesses} == set(occupancy['interface'].lifecycle)
    assert all(access.footprint.kind is FootprintKind.WHOLE for access in operation.accesses)
    assert any(access.mode is AccessMode.READ_WRITE for access in operation.accesses)
    assert not any(type(row) is AsyncSessionOutcome and row.update == operation.id
                   for row in program.protocol_bindings)
    # R2's source is its independent Create; no R1 or future Drive supplies
    # this post. COMPLETE(R2, B) makes no assertion about B being unoccupied.
    expected = static['requests'][1]['result']
    assert expected != static['requests'][0]['result']
    program_index = ProgramIndex(program)
    assert program_index.source_binding(expected,
        OwnedUse(operation.id, update.request), budget=_BUDGET)['match'] is True
    publication = program_index.session_publication(operation.id)
    assert publication.update == update and publication.normal_successor is None
    fact, = tuple(fact for fact in publication.point.session.for_pair(
        publication.request.use.value, publication.body.use.value) if fact.post is SessionPost.COMPLETE)
    assert fact.sources == {operation.id} and fact.support == publication.support
    assert {value.location for value in fact.support} == set(occupancy['interface'].lifecycle)
    occurrence = example['driver_scopes'][1][2][operation.id]
    actual = next(row for row in model.operations if row.id == occurrence)
    helper_actual = next(row for row in model.operations if row.id == example['reject'])
    assert actual.visit == helper_actual.visit
    visit = next(row for row in model.visits if row.id == actual.visit)
    block = next(block for region in program.regions for block in region.blocks if block.id == visit.block)
    assert block.operations.index(operation.id) + 1 == block.operations.index(occupancy['reject'].id)
    request = _use(model, occurrence, update.request)
    request_route = index.formal_route(request.value)
    assert request_route.transfer.operation == example['driver_scopes'][1][2][occupancy['branch'].id]
    assert request_route.transfer.successor_index == 0
    assert request_route.source_use is not None
    assert _use(model, occurrence, update.body).value == _use(
        model, example['occupancy_read'], occupancy['body_use'].use).value
    before = index.state_at(OccurrencePoint(occurrence, OccurrencePhase.BEFORE))
    after = index.state_at(OccurrencePoint(occurrence, OccurrencePhase.AFTER))
    written = set()
    for access in operation.accesses:
        assert _use(model, occurrence, access.before).value == before[access.location]
        if access.mode is AccessMode.READ_WRITE:
            value, = tuple(row for row in model.values if row.origin == occurrence and row.value == access.after)
            assert after[access.location] == value.id != before[access.location]
            written.add(access.location)
        else:
            assert after[access.location] == before[access.location]
    assert all(before[location] == after[location] for location in before if location not in written)
    for support in publication.support:
        value, = tuple(row for row in model.values if row.value == support.id and row.id == after[support.location])
        assert value.id == after[support.location]
    assert _current(index, program, model, example['reject']) == after
    # Both declared completion edges retain their own full state slots. The
    # actual selected edge supplies the host's current states, never stale L.
    for row in occupancy['reject_rows']:
        edge = occupancy['reject'].terminator.successors[row.contract.result.edge.successor_index]
        landing = next(block for region in program.regions for block in region.blocks if block.id == edge.block)
        arguments = tuple((argument, formal) for argument, formal in zip(edge.arguments, landing.arguments)
                          if type(argument) is CompletionResult)
        assert tuple(argument.index for argument, _ in arguments) == tuple(range(1 + len(program.locations)))
        terminal = next(op for op in occupancy['terminals'] if op.id in landing.operations)
        assert tuple(use.value for use_id in terminal.terminator.values
                     for use in terminal.uses if use.id == use_id) == tuple(formal for _, formal in arguments)
    selected = occupancy['reject_rows'][int(static['reject_raised'])]
    current = _current(index, program, model, example['reject_terminal'])
    values = {row.id: row for row in program.values}
    terminal = occupancy['selected_terminal']
    for slot, use_id in enumerate(terminal.terminator.values[1:], 1):
        use = next(use for use in terminal.uses if use.id == use_id)
        own = _own(program, model, example['reject'],
            replace(selected.contract.result, result=CompletionResult(slot)))
        assert _use(model, example['reject_terminal'], use.id).value == own.id
        assert current[values[use.value].location] == own.id
    return occurrence


def _complete(index, program, model, details, number):
    static, example = details['static'], details['instances'][number]
    _r2_complete(index, program, model, details, number)
    assert len(example['call_activations']) == 4
    assert example['active_driver_ordinals'] == (0, 2, 3)
    assert len(example['body_drives']) == len(example['body_segments']) == 3
    assert {row.activation for row in example['body_drives']} == {example['body_activation']}
    assert len(set(example['request_creations'])) == 2
    assert index.body_activation_origin(example['body_activation'], budget=_BUDGET)['association'] == example['body_origin']
    assert example['body_origin'].creation == example['creation']
    second_scope = example['driver_scopes'][1]
    assert static['drivers'][1]['drive'].operation not in second_scope[2]
    assert not any(row.drive in set(second_scope[2].values()) for row in model.body_drive_executions)
    body, = program.resumable_bodies
    assert body.kind is ResumableKind.ASYNC_GENERATOR
    suspends = tuple(row for row in program.operations if type(row.terminator) is SuspendTerminator)
    assert sum(row.terminator.flavor is SuspensionFlavor.AWAIT for row in suspends) == 2
    assert sum(row.terminator.flavor is SuspensionFlavor.ASYNC_YIELD for row in suspends) == 1

    program_index = ProgramIndex(program)
    for ordinal, association in enumerate(example['call_activations']):
        driver = static['drivers'][ordinal]
        view = index.call_activation(association.id)
        assert view['association'] == association
        assert view['caller'].id == example['caller_operations'][driver['caller_call'].id]
        assert view['activation'].id == example['driver_scopes'][ordinal][0]
        assert view['completion'].id == example['driver_scopes'][ordinal][2][driver['host_terminal'].id]
        assert len(view['outputs']) == 1 + len(program.locations)
        assert all(row['callee_use'] is not None and row['caller_formal'] is not None for row in view['outputs'])
        assert {row['ordinal'] for row in view['outputs']} == set(range(1 + len(program.locations)))
        for row in view['outputs']:
            assert row['edge_argument'] == CompletionResult(row['ordinal'])
        receiver = next(row for row in view['inputs'] if row['formal_definition'].id == driver['interface'].receiver)
        expected = static['requests'][1 if ordinal == 1 else 0]['result']
        binding = program_index.source_binding(expected,
            OwnedUse(driver['caller_call'].id, receiver['actual'].use), budget=_BUDGET)
        assert binding['match'] is True
        assert receiver['actual_value'] is not None
        _current(index, program, model, association.caller)
        _current(index, program, model, association.completion)
        assert all(view[key] is False for key in _FLAGS)
    for body_ordinal, driver_ordinal in enumerate((0, 2, 3)):
        association = example['body_drives'][body_ordinal]
        view = index.drive_execution(association.drive, budget=_BUDGET)
        assert view['association'] == association
        assert association.entry == example['body_entries'][body_ordinal]
        assert view['entry_bridge'] is True and view['path_complete'] is True
        assert view['session']['expected_post'] is (SessionPost.COMPLETE if body_ordinal == 2 else SessionPost.HOLD)
        target, = view['session']['targets']
        assert target['update'] == static['drivers'][driver_ordinal]['update']
        assert target['post_established'] is True
        assert target['state_bindings']
        assert all(row['use'] is not None and row['value'] is not None
                   and row['current'] == row['value'].id for row in target['state_bindings'])
        assert all(row['source_value'] is not None and row['formal'] is not None
                   for row in (*view['inputs'], *view['outputs']))
        segment = next(row for row in model.segments if row.id == example['body_segments'][body_ordinal])
        if body_ordinal == 0:
            assert type(segment.ingress) is InitialEntry
        else:
            assert type(segment.ingress) is ResumeIngress
            assert segment.ingress.suspension == example['body_drives'][body_ordinal - 1].outcome
            transfer, = tuple(row for row in model.transfers if row.operation == segment.ingress.suspension)
            assert transfer.target == association.entry
            assert transfer.successor_index == static['drivers'][driver_ordinal]['drive'].target.successor

    occupancy = static['occupancy']
    reject = occupancy['reject']
    selected = occupancy['reject_rows'][int(static['reject_raised'])]
    own = _own(program, model, example['reject'], selected.contract.result)
    packet = _use(model, example['reject_terminal'], occupancy['selected_terminal'].terminator.values[0])
    assert packet.value == own.id
    parent = index.call_activation(example['call_activations'][1].id)
    assert parent['completion'].id == example['reject_terminal']
    assert occupancy['selected_terminal'].terminator.kind is TerminatorKind.RAISE
    assert reject.terminator.successors[int(static['reject_raised'])].kind is (
        ExitKind.RAISE if static['reject_raised'] else ExitKind.NORMAL)
    outgoing, = tuple(row for row in model.transfers if row.operation == example['call_activations'][1].caller)
    parent_edge = static['drivers'][1]['caller_call'].terminator.successors[outgoing.successor_index]
    assert parent_edge.kind is ExitKind.RAISE
    payload, = tuple(row for row in parent['outputs'] if row['ordinal'] == 0)
    assert payload['callee_use'] == packet
    caught = _use(model, example['catch'], static['catch'].uses[0].id)
    assert caught.value == payload['caller_formal'].id
    before = index.state_at(OccurrencePoint(example['catch'], OccurrencePhase.BEFORE))
    after = index.state_at(OccurrencePoint(example['catch'], OccurrencePhase.AFTER))
    context = body.context_location
    assert before[context] != after[context]
    assert all(before[location] == after[location] for location in before if location != context)
    continued = index.state_at(OccurrencePoint(example['call_activations'][2].caller, OccurrencePhase.BEFORE))
    assert continued == after
    if static['getter'] is not None:
        link = example['extra_call_activations']['r2.association']
        getter = index.call_activation(link.id)
        assert getter['caller'].id == example['association']
        assert getter['activation'].region == static['getter']['region'].id
        assert len(getter['outputs']) == 2 + len(program.locations)
        assert all(row['callee_use'] is not None and row['caller_formal'] is not None for row in getter['outputs'])
        assert tuple(row['edge_argument'] for row in getter['outputs']) == tuple(
            CompletionResult(slot) for slot in range(2 + len(program.locations)))
        read_body = _use(model, example['occupancy_read'], occupancy['body_use'].use)
        route = index.formal_route(read_body.value)
        assert route.transfer.operation == example['driver_scopes'][1][2][occupancy['initial_branch'].id]
        assert route.source_use.value == getter['outputs'][0]['caller_formal'].id
        _current(index, program, model,
                 example['extra_scopes']['r2.association'][2][static['getter']['read'].id])

    # The final item belongs to R1's actual ASYNC_YIELD and its selected
    # constructor. The rejection packet from R2 is never used as that item.
    final_driver = static['drivers'][3]
    adapters = tuple(row for row in program.protocol_operations
        if type(row.contract) is OutcomeAdapter
        and row.contract.rule is OutcomeAdapterRule.ASYNCGEN_YIELD_TO_REQUEST_ITEM
        and row.operation in example['driver_scopes'][3][2])
    normal_row, = tuple(row for row in adapters if next(op for op in program.operations
        if op.id == row.operation).terminator.successors[row.slot].kind is ExitKind.NORMAL)
    constructor_occurrence = example['driver_scopes'][3][2][normal_row.operation]
    own_exception = _own(program, model, constructor_occurrence, normal_row.contract.output)
    actual_item = _use(model, constructor_occurrence, normal_row.contract.input_use)
    last_drive = index.drive_execution(example['body_drives'][2].drive, budget=_BUDGET)
    payload_binding, = tuple(row for row in last_drive['outputs']
        if row['binding'].actual.use.id == next(op for op in program.operations
            if op.id == final_driver['outcome'].source).terminator.exported)
    assert actual_item.value == payload_binding['formal'].id
    host = final_driver['host_terminal']
    host_payload = next(use.value for use in host.uses if use.id == host.terminator.values[0])
    packet_definition, = tuple(row for row in program.exception_packets if row.value == host_payload)
    packet_value = next(row for row in program.values if row.id == packet_definition.value)
    assert type(packet_value.origin) is OperationResult
    packet_occurrence = example['driver_scopes'][3][2][packet_value.origin.operation]
    assert _use(model, packet_occurrence, packet_definition.exception).value == own_exception.id
    actual_packet, = tuple(row for row in model.values
        if row.origin == packet_occurrence and row.value == packet_value.id)
    last_call = index.call_activation(example['call_activations'][3].id)
    last_output, = tuple(row for row in last_call['outputs'] if row['ordinal'] == 0)
    assert last_output['callee_use'].value == actual_packet.id
    assert _use(model, example['final'], static['final'].terminator.values[0]).value == last_output['caller_formal'].id
    _current(index, program, model, example['final'])
    return example


@pytest.mark.parametrize('reject_raised', (False, True), ids=('reject-own-normal', 'reject-own-raise'))
def test_two_requests_reject_only_r2_then_resume_the_original_body_and_r1(reject_raised):
    program, model, details = async_competition_execution(reject_raised=reject_raised, local_probe=True)
    index = _index(program, model)
    assert len(program.resumable_creates) == 1 and len(program.async_request_creates) == 2
    assert len(model.body_activation_origins) == 2 and len(model.body_drive_executions) == 6
    assert len({row['creation'] for row in details['instances']}) == 2
    assert len({creation for row in details['instances'] for creation in row['request_creations']}) == 4
    for number in range(2):
        example = _complete(index, program, model, details, number)
        source = OccurrencePoint(example['source_hold'], OccurrencePhase.AFTER)
        read = OccurrencePoint(example['local_read'], OccurrencePhase.BEFORE)
        local = index.state_preservation(source, read, locations=details['static']['domains'], budget=_BUDGET)
        assert local['reached'] is True and local['preserved'] is True
        assert not local['blockers']


def test_opaque_handoff_and_association_keep_the_main_occupancy_interval_unproved():
    program, model, details = async_competition_execution(known_association=False)
    index = _index(program, model)
    example = _complete(index, program, model, details, 0)
    assert not example['extra_call_activations']
    interval = index.state_preservation(OccurrencePoint(example['source_hold'], OccurrencePhase.AFTER),
        OccurrencePoint(example['occupancy_read'], OccurrencePhase.BEFORE),
        locations=details['static']['domains'], budget=_BUDGET)
    assert interval['preserved'] is None and interval['blockers']
    handoff = example['driver_scopes'][0][2][details['static']['drivers'][0]['host_terminal'].id]
    assert any(row['operation'] == handoff and row['code'] == 'state_preservation_effects_incomplete'
               for row in interval['blockers'])
    assert any(row['operation'] == example['association'] and row['code'] == 'state_preservation_primitive_invoke'
               for row in interval['blockers'])


@pytest.mark.parametrize('missing', ('getter-call', 'reject-payload', 'resume-transfer'))
def test_missing_this_instances_edge_cannot_borrow_the_complete_request_sibling(missing):
    program, model, details = async_competition_execution(
        missing_getter_call=0 if missing == 'getter-call' else None,
        missing_reject_payload=0 if missing == 'reject-payload' else None,
        missing_resume_transfer=0 if missing == 'resume-transfer' else None)
    index = _index(program, model)
    example = details['instances'][0]
    _r2_complete(index, program, model, details, 0)
    if missing == 'getter-call':
        view = index.call_entries(example['association'])
        assert view['status'] == 'MISSING' and not view['entries']
        assert any(gap.code == 'call_activation_missing' for gap in view['gaps'])
    elif missing == 'reject-payload':
        view = index.call_activation(example['call_activations'][1].id)
        assert view['outputs'][0]['callee_use'] is None
        assert view['outputs'][0]['caller_formal'] is not None
        assert any(gap.code == 'call_exit_use_unobserved' for gap in view['gaps'])
    else:
        view = index.drive_execution(example['body_drives'][1].drive, budget=_BUDGET)
        assert view['association'] == example['body_drives'][1]
        assert view['entry_bridge'] is False and view['status'] == 'PARTIAL'
        assert any(gap.code == 'body_resume_transfer_unobserved' for gap in view['gaps'])
    _complete(index, program, model, details, 1)


def test_budget_one_retains_original_resume_input_output_and_forward_slots():
    program, model, details = async_competition_execution()
    index = _index(program, model)
    for number in range(2):
        _r2_complete(index, program, model, details, number)
    drive = details['instances'][0]['body_drives'][1].drive
    full = index.drive_execution(drive, budget=_BUDGET)
    limited = index.drive_execution(drive, budget=1)
    for field, count in (('inputs', 'input_count'), ('outputs', 'output_count'), ('forwards', 'forward_count')):
        assert limited[count] == full[count] == len(limited[field])
    assert limited['association'] == full['association']
    assert limited['status'] == 'PARTIAL'
    assert limited['budget']['used'] <= 1 and limited['budget']['truncated'] is True
    assert limited['cursor'] is not None
    assert all(limited[key] is False for key in _FLAGS)
