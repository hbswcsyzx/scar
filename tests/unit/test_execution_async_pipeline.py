"""One continuous body activation across three async request/drive sessions."""
from dataclasses import replace

from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.snapshot import snapshot_for
from scar.ir.execution.validation import validate
from scar.ir.execution.common import Unresolved
from scar.ir.execution.coordinates import ResumeIngress
from scar.ir.program.lifecycle import SessionPost
from scar.ir.program.protocol_connections import AsyncSessionOutcome
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_async_pipeline_graphs import async_pipeline_execution


def _index(program, model):
    require_valid(program)
    report = validate(model, program)
    assert report.valid, report.issues
    return ExecutionIndex(model, program)


def test_one_body_activation_has_three_exact_await_and_async_yield_occurrences():
    program, model, details = async_pipeline_execution()
    index = _index(program, model)

    assert len(model.body_drive_executions) == 3
    assert len(model.call_activations) == 3
    assert len(model.body_activation_origins) == 1
    assert {row.activation for row in model.body_drive_executions} == {details['body_activation']}
    assert len(set(details['body_segments'])) == 3
    origin, = model.body_activation_origins
    assert origin.activation == details['body_activation']
    assert origin.creation == details['body_creation_occurrence']

    expected_posts = (SessionPost.HOLD, SessionPost.HOLD, SessionPost.COMPLETE)
    static_drivers = details['static']['drivers']
    for number, drive in enumerate(details['body_drive_occurrences']):
        view = index.drive_execution(drive)
        session = view['session']
        static = static_drivers[number]
        actual = next(row for row in model.body_drive_executions if row.drive == drive)
        assert view['drive'].id == drive
        assert actual.activation == details['body_activation']
        assert actual.entry == details['body_entries'][number]
        assert actual.outcome == details['body_outcomes'][number]
        assert session['drive'] == view['drive']
        assert session['source'] == static['outcome']
        assert session['expected_post'] is expected_posts[number]
        assert session['request']['value'] is not None
        assert session['body']['use'] is not None
        assert session['body']['value'] is not None
        assert session['target_count'] == 1
        target, = session['targets']
        assert target['update'] == static['update']
        assert target['occurrence'].id == details['session_update_occurrences'][number]
        assert target['binding'] is not None
        assert target['binding'].source == static['outcome']
        assert target['post_established'] is True
        assert target['request']['target_value'] is not None
        assert target['body']['target_value'] is not None
        assert target['state_inputs'] and target['state_outputs']
        assert all(value is not None for value in target['state_outputs'].values())

        # The host endpoint is the actual completion linked to this exact
        # caller operation, including the third stage's real RAISE result.
        caller = details['caller_operations'][static['caller_call'].id]
        link = next(row for row in model.call_activations if row.caller == caller)
        host, = session['hosts']
        assert host['operation'].id == link.completion
        assert host['definition'] == static['host_terminal']
        if number == 2:
            assert static['host_terminal'].terminator.kind.value == 'RAISE'
            assert host['adapter'] is not None
            assert host['bindings']
        assert session['source_runtime_verified'] is False
        assert session['runtime_identity_verified'] is False
        assert session['value_identity_verified'] is False
        assert session['transformation_authorized'] is False
        assert session['status'] in ('DECLARED', 'PARTIAL')


def test_session_post_is_established_only_on_the_actual_helper_normal_edge():
    # Exercise the same original helper on both real exits.  A declaration of
    # NORMAL_COMPLETION cannot make the selected RAISE edge establish a post.
    for helper_raised in (False, True):
        program, model, details = async_pipeline_execution(
            helper_stage=0, helper_raised=helper_raised)
        index = _index(program, model)
        drive = details['body_drive_occurrences'][0]
        session = index.drive_execution(drive)['session']
        target, = session['targets']
        static = details['static']['drivers'][0]
        assert session['source'] == static['outcome']
        assert target['update'] == static['update']
        assert target['occurrence'].id == details['session_update_occurrences'][0]
        assert target['binding'] is not None
        assert target['binding'].source == static['outcome']
        assert target['selected_successor'] is not None
        helper = next(row for row in program.operations if row.id == static['update'].operation)
        selected = helper.terminator.successors[target['selected_successor'].successor_index]
        assert selected.kind.value == ('RAISE' if helper_raised else 'NORMAL')
        assert target['post_established'] is (not helper_raised)

        caller = details['caller_operations'][static['caller_call'].id]
        link = next(row for row in model.call_activations if row.caller == caller)
        host, = session['hosts']
        assert host['operation'].id == link.completion
        assert host['definition'] == static['host_terminal']


def test_missing_async_session_attachment_keeps_the_original_update_target():
    program, model, details = async_pipeline_execution()
    selected = details['static']['drivers'][1]
    update, source = selected['update'], selected['outcome']
    changed = replace(program, protocol_bindings=tuple(
        row for row in program.protocol_bindings
        if not (type(row) is AsyncSessionOutcome and row.update == update.operation
                and row.source == source)))
    changed_model = replace(model, snapshot=snapshot_for(changed))
    index = _index(changed, changed_model)

    session = index.drive_execution(details['body_drive_occurrences'][1])['session']
    assert session['source'] == source
    assert session['target_count'] == 1
    target, = session['targets']
    assert target['update'] == update
    assert target['occurrence'].id == details['session_update_occurrences'][1]
    assert target['binding'] is None
    assert any(gap.code == 'body_session_source_binding_missing' for gap in session['gaps'])
    assert session['status'] == 'PARTIAL'


def test_missing_session_update_keeps_the_actual_body_result_as_missing_work():
    program, model, details = async_pipeline_execution()
    selected = details['static']['drivers'][0]
    changed = replace(program, session_updates=tuple(
        row for row in program.session_updates if row != selected['update']),
        protocol_bindings=tuple(row for row in program.protocol_bindings
            if not (type(row) is AsyncSessionOutcome
                    and row.update == selected['update'].operation
                    and row.source == selected['outcome'])))
    changed_model = replace(model, snapshot=snapshot_for(changed))
    index = _index(changed, changed_model)

    session = index.drive_execution(details['body_drive_occurrences'][0])['session']
    assert session['source'] == selected['outcome']
    assert session['expected_post'] is SessionPost.HOLD
    assert session['targets'] == ()
    assert session['target_count'] == 0
    assert any(gap.code == 'body_session_update_missing' for gap in session['gaps'])
    assert session['status'] == 'MISSING'


def test_missing_current_state_use_does_not_establish_the_session_post():
    program, model, details = async_pipeline_execution()
    static = details['static']['drivers'][0]
    occurrence = details['session_update_occurrences'][0]
    operation = next(row for row in program.operations if row.id == static['update'].operation)
    state_site = next(access.before for access in operation.accesses)
    changed_model = replace(model, uses=tuple(
        row for row in model.uses if (row.operation, row.use) != (occurrence, state_site)))
    index = _index(program, changed_model)

    session = index.drive_execution(details['body_drive_occurrences'][0])['session']
    target, = session['targets']
    assert target['update'] == static['update']
    assert target['occurrence'].id == occurrence
    assert target['post_established'] is False
    assert any(gap.code == 'body_session_input_state_missing' for gap in session['gaps'])
    assert session['status'] == 'PARTIAL'


def test_missing_request_or_body_use_keeps_the_exact_session_target_unresolved():
    program, model, details = async_pipeline_execution()
    static = details['static']['drivers'][0]
    occurrence = details['session_update_occurrences'][0]
    for role in ('request', 'body'):
        use = getattr(static['update'], role)
        changed_model = replace(model, uses=tuple(
            row for row in model.uses if (row.operation, row.use) != (occurrence, use)))
        index = _index(program, changed_model)
        session = index.drive_execution(details['body_drive_occurrences'][0])['session']
        target, = session['targets']
        assert target['update'] == static['update']
        assert target['occurrence'].id == occurrence
        assert target[role]['target_value'] is None
        assert target[role]['compatibility'] is not True
        assert session['status'] == 'PARTIAL'


def test_request_and_body_uses_cannot_be_swapped_by_same_typed_value_occurrence():
    program, model, details = async_pipeline_execution()
    static = details['static']['drivers'][0]
    occurrence = details['session_update_occurrences'][0]
    index = _index(program, model)
    target, = index.drive_execution(details['body_drive_occurrences'][0])['session']['targets']
    wrong_body_value = target['request']['target_value']
    assert wrong_body_value is not None
    changed_model = replace(model, uses=tuple(
        replace(row, value=wrong_body_value.id)
        if (row.operation, row.use) == (occurrence, static['update'].body) else row
        for row in model.uses))
    report = validate(changed_model, program)
    assert not report.valid
    assert 'use_definition' in {issue.code for issue in report.issues}


def test_resume_cannot_borrow_another_static_suspend_occurrence():
    program, model, details = async_pipeline_execution()
    resumed_segment = details['body_segments'][2]
    wrong_source = details['body_outcomes'][0]
    changed = replace(model, segments=tuple(
        replace(row, ingress=replace(row.ingress, suspension=wrong_source))
        if row.id == resumed_segment and type(row.ingress) is ResumeIngress else row
        for row in model.segments))
    report = validate(changed, program)
    assert not report.valid
    assert 'transfer_resume' in {issue.code for issue in report.issues}


def _omit_update_suffix(program, model, details, ordinal):
    """Keep the static update obligation while omitting its captured suffix."""
    target = details['session_update_occurrences'][ordinal]
    occurrence = next(row for row in model.operations if row.id == target)
    segment = next(row for row in model.segments
                   if row.id == next(visit for visit in model.visits if visit.id == occurrence.visit).segment)
    segment_visits = [row for row in model.visits if row.segment == segment.id]
    visit_position = next(i for i, row in enumerate(segment_visits) if row.id == occurrence.visit)
    block = next(row for region in program.regions for row in region.blocks
                 if row.id == next(row for row in model.visits if row.id == occurrence.visit).block)
    operation_position = block.operations.index(occurrence.operation)
    omitted_visits = {row.id for row in segment_visits[visit_position + 1:]}
    omitted_operations = {
        row.id for row in model.operations
        if row.visit in omitted_visits or row.visit == occurrence.visit and
        block.operations.index(row.operation) >= operation_position
    }
    omitted_values = {
        row.id for row in model.values
        if row.origin in omitted_operations or row.origin in omitted_visits
    }
    point = model.segments[0].ingress.source
    changed = replace(model,
        visits=tuple(row for row in model.visits if row.id not in omitted_visits),
        operations=tuple(row for row in model.operations if row.id not in omitted_operations),
        values=tuple(row for row in model.values if row.id not in omitted_values),
        uses=tuple(row for row in model.uses if row.operation not in omitted_operations),
        transfers=tuple(row for row in model.transfers
                        if row.operation not in omitted_operations and row.target not in omitted_visits),
        call_activations=tuple(replace(row, completion=Unresolved('captured suffix omitted', point))
            if row.caller == details['caller_operations'][details['static']['drivers'][ordinal]['caller_call'].id]
            else row for row in model.call_activations))
    return changed


def test_missing_actual_update_occurrence_keeps_the_original_target_and_gap():
    program, model, details = async_pipeline_execution()
    changed_model = _omit_update_suffix(program, model, details, 0)
    index = _index(program, changed_model)

    session = index.drive_execution(details['body_drive_occurrences'][0])['session']
    assert session['target_count'] == 1
    target, = session['targets']
    assert target['update'] == details['static']['drivers'][0]['update']
    assert target['occurrence'] is None
    assert target['post_established'] is False
    assert any(gap.code == 'body_session_update_occurrence_missing' for gap in session['gaps'])
    assert session['status'] == 'PARTIAL'


def test_tiny_budget_preserves_session_target_denominator_and_unchecked_cursor():
    program, model, details = async_pipeline_execution()
    index = _index(program, model)

    session = index.drive_execution(details['body_drive_occurrences'][0], budget=1)['session']
    assert session['target_count'] == 1
    target, = session['targets']
    assert target['update'] == details['static']['drivers'][0]['update']
    assert target['check_status'] == 'NOT_CHECKED'
    assert target['post_established'] is False
    assert target['request']['compatibility'] is None
    assert target['body']['compatibility'] is None
    assert session['cursor'] is not None
    assert session['status'] == 'PARTIAL'

