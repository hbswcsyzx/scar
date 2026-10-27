"""One supplied COMPLETE/reuse capture, with external B and no phase inference.

The two READ evaluations and their selected branches are capture declarations.
The COMPLETE post, exact R, and current-state call routes are checked separately;
these tests do not infer the second boolean from a prior session post.
"""
from dataclasses import replace

import pytest

from scar.ir.execution.calls import CallActivation
from scar.ir.execution.common import Unresolved
from scar.ir.execution.coordinates import (
    ExecutionSegment, OccurrencePhase, OccurrencePoint, ResumeIngress,
)
from scar.ir.execution.ids import CallActivationID, ExecutionSegmentID
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.resumables import BodyActivationOrigin, BodyDriveExecution
from scar.ir.execution.validation import validate as validate_execution
from scar.ir.program.drivers import BodyResume
from scar.ir.program.lifecycle import SessionPost
from scar.ir.program.model import (
    CompletionResult, ExitKind, InvokeLiteralResult, StateVersionValue,
    TerminatorKind,
)
from scar.ir.program.protocol_connections import RequestStateRule
from scar.ir.program.protocols import OwnedUse
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_async_pipeline_graphs import _body_path
from tests.fixtures.execution_call_graphs import _model
from tests.fixtures.program_async_pipeline_graphs import _selected_path
from tests.fixtures.program_request_admission_graphs import request_two_callers_program


_FLAGS = ('source_runtime_verified', 'runtime_identity_verified',
          'value_identity_verified', 'transformation_authorized')


def _reuse_program():
    graph, details = request_two_callers_program()
    original = details['predicate_row']
    row = replace(original, contract=replace(original.contract,
        subject=replace(original.contract.subject, rule=RequestStateRule.IS_COMPLETE)))
    branch = next(op for op in graph.operations if op.id == row.contract.branch)
    # The original INITIAL_STEP graph admits true. COMPLETE admits false;
    # retain the exact original edge arguments, actual Uses, and reject helper.
    branch = replace(branch, terminator=replace(branch.terminator,
        successors=tuple(reversed(branch.terminator.successors))))
    graph = replace(graph,
        protocol_operations=tuple(row if item == original else item
                                  for item in graph.protocol_operations),
        operations=tuple(branch if op.id == branch.id else op for op in graph.operations))
    return graph, {**details, 'predicate_row': row, 'branch_operation': branch}


def _defaults(graph):
    return {op.id: 0 for op in graph.operations
            if op.terminator is not None and op.terminator.successors}


def _reuse_execution(*, reject_raised=False):
    program, details = _reuse_program()
    operations = {op.id: op for op in program.operations}
    regions = {region.id: region for region in program.regions}
    driver = regions[details['interface'].region]
    first, second = details['callers']
    branch = details['branch_operation']
    helper = operations[details['helper']]
    defaults = _defaults(program)
    caller_choices = {**defaults, **{op.id: next(index for index, edge in
        enumerate(op.terminator.successors) if edge.kind is ExitKind.RAISE)
        for op in (first, second)}}
    caller_path = _selected_path(program, regions[program.root], caller_choices)
    first_path = _selected_path(program, driver, {**defaults, branch.id: 1})
    reject_index = next(index for index, edge in enumerate(helper.terminator.successors)
                        if edge.kind is (ExitKind.RAISE if reject_raised else ExitKind.NORMAL))
    second_path = _selected_path(program, driver,
        {**defaults, branch.id: 0, helper.id: reject_index})

    drive, = program.body_drives
    assert type(drive.target) is BodyResume
    body = regions[details['interface'].body]
    suspend = operations[drive.target.suspend]
    prefix = _body_path(program, body, body.entry, suspend.id)
    suffix = _body_path(program, body,
        suspend.terminator.successors[drive.target.successor].block,
        details['outcome'].source)
    body_path = (*prefix[:-1], (prefix[-1][0], drive.target.successor), *suffix)
    model, scopes, source = _model(program, (
        (program.root, caller_path, 'completed.reuse.caller'),
        (driver.id, first_path, 'completed.reuse.first'),
        (driver.id, second_path, 'completed.reuse.second'),
        (body.id, body_path, 'completed.reuse.external.body'),
    ))
    caller, first_scope, second_scope, body_scope = scopes
    body_activation, body_visits, body_operations = body_scope
    point = next(row.entry for row in model.activations if row.id == body_activation)
    initial_segment = next(row for row in model.segments if row.activation == body_activation)
    resumed = ExecutionSegment(ExecutionSegmentID('completed.reuse.external.body.resume'),
        body_activation, initial_segment.host_thread,
        ResumeIngress(body_operations[suspend.id], drive.target.successor, point))
    resumed_visits = set(body_visits[len(prefix):])
    model = replace(model, segments=(*model.segments, resumed),
        visits=tuple(replace(visit, segment=resumed.id)
                     if visit.id in resumed_visits else visit for visit in model.visits))
    blocks = {block.id: block for region in program.regions for block in region.blocks}
    first_terminal = blocks[first_path[-1][0]].operations[-1]
    second_terminal = blocks[second_path[-1][0]].operations[-1]
    calls = tuple(CallActivation(CallActivationID(f'completed.reuse.call.{number}'),
        caller[2][call.id], scope[0], scope[1][0], scope[2][terminal], source)
        for number, (call, scope, terminal) in enumerate((
            (first, first_scope, first_terminal), (second, second_scope, second_terminal))))
    actual_drive = BodyDriveExecution(first_scope[2][drive.operation], body_activation,
        body_visits[len(prefix)], body_operations[details['outcome'].source], source)
    model = replace(model, call_activations=calls,
        body_drive_executions=(actual_drive,),
        body_activation_origins=(BodyActivationOrigin(body_activation,
            Unresolved('B is an external already-suspended continuation; no Create is supplied', point), source),))
    return program, model, {**details, 'caller_scope': caller,
        'first_scope': first_scope, 'second_scope': second_scope, 'body_scope': body_scope,
        'calls': calls, 'actual_drive': actual_drive, 'reject_index': reject_index,
        'first_terminal': operations[first_terminal],
        'second_terminal': operations[second_terminal], 'helper_operation': helper}


def _index(program, model):
    require_valid(program)
    report = validate_execution(model, program)
    assert report.valid, report.issues
    return ExecutionIndex(model, program)


def _source_and_states(program, index, details):
    static = ProgramIndex(program)
    create = next(row for row in program.async_request_creates
                  if row.operation == details['request_create'])
    operation = next(op for op in program.operations if op.id == create.operation)
    normal = next(index for index, edge in enumerate(operation.terminator.successors)
                  if edge.kind is ExitKind.NORMAL)
    source = InvokeLiteralResult(ControlEdgeReference(create.operation, normal),
                                 CompletionResult(create.request_result.index))
    entry = next(block for region in program.regions
                 if region.id == details['interface'].region for block in region.blocks
                 if block.id == region.entry)
    receiver_ordinal = entry.arguments.index(details['interface'].receiver)
    calls = tuple(index.call_activation(row.id) for row in details['calls'])
    receiver_values = []
    for call, view in zip(details['callers'], calls):
        actual = OwnedUse(call.id, call.invoke_arguments[receiver_ordinal])
        assert static.source_binding(source, actual)['match'] is True
        receiver_values.append(view['inputs'][receiver_ordinal]['actual_value'])
        assert view['association'].caller == details['caller_scope'][2][call.id]
    assert receiver_values[0] == receiver_values[1]
    assert receiver_values[0] is not None
    # The first own completion feeds every latest caller state. The caught
    # context install supplies only its actual replacement context version.
    first_states = {row['caller_formal_definition'].location: row['caller_formal']
        for row in calls[0]['outputs'] if type(row['caller_formal_definition']) is StateVersionValue}
    handler = details['completion_handler']
    handler_occurrence = details['caller_scope'][2][handler.id]
    handler_states = index.state_at(OccurrencePoint(handler_occurrence, OccurrencePhase.AFTER))
    current = index.state_at(OccurrencePoint(details['calls'][1].caller, OccurrencePhase.BEFORE))
    assert current == handler_states
    assert set(current) == set(first_states)
    context = program.resumable_bodies[0].context_location
    for route in calls[1]['inputs']:
        definition = route['formal_definition']
        if type(definition) is not StateVersionValue:
            continue
        assert route['actual_value'].id == current[definition.location]
        if definition.location != context:
            assert route['actual_value'] == first_states[definition.location]
        else:
            assert route['actual_value'].origin == handler_occurrence
            assert route['actual_value'] != first_states[context]
    return calls


@pytest.mark.parametrize('reject_raised', (False, True), ids=('reject-own-normal', 'reject-own-raise'))
def test_completed_request_reuses_exact_r_and_latest_states_then_rejects_without_a_second_drive(reject_raised):
    program, model, details = _reuse_execution(reject_raised=reject_raised)
    index = _index(program, model)
    assert len(program.async_request_creates) == 1
    assert program.resumable_creates == ()
    assert len(model.call_activations) == 2
    assert len(model.body_drive_executions) == 1
    assert details['actual_drive'].drive in details['first_scope'][2].values()
    assert program.body_drives[0].operation not in details['second_scope'][2]
    calls = _source_and_states(program, index, details)

    # Distinct occurrences of one original READ choose false then true.
    branch = details['branch_operation']
    transfers = {row.operation: row for row in model.transfers}
    uses = {(row.operation, row.use): row for row in model.uses}
    values = {row.id: row for row in model.values}
    booleans = []
    for number, scope in enumerate((details['first_scope'], details['second_scope'])):
        predicate = scope[2][details['predicate']]
        actual_branch = scope[2][branch.id]
        assert transfers[actual_branch].successor_index == (1 if number == 0 else 0)
        condition = values[uses[actual_branch, branch.terminator.condition].value]
        assert condition.origin == predicate
        booleans.append(condition.id)
    assert booleans[0] != booleans[1]
    drive = index.drive_execution(details['actual_drive'].drive, budget=65536)
    assert drive['association'] == details['actual_drive']
    session = drive['session']
    assert session['expected_post'] is SessionPost.COMPLETE
    target, = session['targets']
    assert target['post_established'] is True
    assert target['update'].post is SessionPost.COMPLETE
    assert target['state_inputs'] and target['state_outputs']
    assert target['occurrence'].id in details['first_scope'][2].values()
    assert target['occurrence'].id not in details['second_scope'][2].values()

    helper = details['helper_operation']
    anchor = details['second_scope'][2][helper.id]
    transfer = transfers[anchor]
    assert transfer.successor_index == details['reject_index']
    selected = helper.terminator.successors[transfer.successor_index]
    assert selected.kind is (ExitKind.RAISE if reject_raised else ExitKind.NORMAL)
    assert {row.kind for row in helper.completions} == {ExitKind.NORMAL, ExitKind.RAISE}
    assert len(calls[1]['outputs']) == len(details['second_terminal'].terminator.values)
    assert len(calls[1]['outputs']) == 1 + len(program.locations)
    for slot, output in enumerate(calls[1]['outputs']):
        assert output['edge_argument'] == CompletionResult(slot)
        assert output['callee_exit'].id == details['calls'][1].completion
        assert output['callee_use'].operation == details['calls'][1].completion
        assert output['caller_formal'] is not None
        assert output['caller_transfer'].operation == details['calls'][1].caller
    assert details['second_terminal'].terminator.kind is TerminatorKind.RAISE
    payload, = tuple(output for output in calls[1]['outputs'] if output['ordinal'] == 0)
    route = index.formal_route(payload['callee_use'].value)
    assert route.transfer.operation == anchor
    assert route.transfer.successor_index == details['reject_index']
    assert route.argument == CompletionResult(0)
    packet = values[payload['callee_use'].value]
    continuation = index.completion_continuations(packet.id, anchor, budget=32768)
    terminal, = continuation['terminals']
    assert terminal['operation'].id == details['calls'][1].completion
    assert terminal['root_binding']['match'] is True
    assert terminal['binding']['match'] is True
    assert terminal['use'] == payload['callee_use']
    assert terminal['value'] == packet
    for view in (*calls, drive, continuation):
        assert all(view[flag] is False for flag in _FLAGS)


def test_missing_second_call_capture_retains_both_original_calls_without_borrowing_the_first():
    program, model, details = _reuse_execution()
    second = details['calls'][1]
    changed = replace(model, call_activations=(details['calls'][0],))
    index = _index(program, changed)
    listings = tuple(index.call_entries(details['caller_scope'][2][call.id])
                     for call in details['callers'])
    assert listings[0]['status'] == 'DECLARED'
    assert listings[1]['status'] == 'MISSING'
    assert listings[1]['caller'].id == second.caller
    assert listings[1]['operation'] == details['callers'][1]
    assert listings[1]['callee'] == listings[0]['callee']
    assert listings[1]['entries'] == ()
    assert any(gap.code == 'call_activation_missing' for gap in listings[1]['gaps'])
    assert len(changed.body_drive_executions) == 1
    first = index.drive_execution(details['actual_drive'].drive, budget=65536)
    assert first['session']['expected_post'] is SessionPost.COMPLETE
    assert first['session']['targets'][0]['post_established'] is True
    public = ProgramIndex(program).protocol_obligations(budget=65536)
    admissions = public['connections']['families']['async']['request_admissions']
    assert len(admissions) == len(program.final_body_gates) == 1
    assert admissions[0]['predicate_count'] == 1
    assert details['predicate_row'].contract.subject.rule is RequestStateRule.IS_COMPLETE
    assert all(listings[1][flag] is False for flag in _FLAGS)
