"""Strong O relationships over original canonical paths, not runtime capture."""
from dataclasses import replace

import pytest

from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.common import Unresolved
from scar.ir.execution.content import ObjectIdentity, ObjectRef
from scar.ir.execution.coordinates import CaptureIngress, OccurrencePhase, OccurrencePoint
from scar.ir.execution.ids import HostThreadInstanceID, OperationOccurrenceID, RegionActivationID, ValueOccurrenceID
from scar.ir.execution.validation import validate
from scar.ir.program.ids import OperationID, ValueID
from scar.ir.program.model import StateVersionValue
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_resumable_graphs import empty_frontier_execution, resumable_execution


def _catalogs(details):
    return {'evidence_graphs': details.get('evidence_graphs', {})}


def _index(program, model, details):
    require_valid(program)
    report = validate(model, program, **_catalogs(details))
    assert report.valid, report.issues
    return ExecutionIndex(model, program, **_catalogs(details))


def _codes(program, model, details):
    return {issue.code for issue in validate(model, program, **_catalogs(details)).issues}


def _replace_link(model, drive, **fields):
    return replace(model, body_drive_executions=tuple(replace(row, **fields) if row.drive == drive else row
                                                      for row in model.body_drive_executions))


@pytest.mark.parametrize('resume', ('value', 'packet'))
@pytest.mark.parametrize('instances', (1, 2))
@pytest.mark.parametrize('switched_thread', (False, True))
def test_fixture_is_valid_under_old_canonical_flow_without_new_relationships(resume, instances, switched_thread):
    program, model, details = resumable_execution(resume=resume, instances=instances, switched_thread=switched_thread)
    require_valid(program)
    old = replace(model, body_drive_executions=(), body_activation_origins=())
    report = validate(old, program, **_catalogs(details))
    assert report.valid, report.issues
    assert len(model.body_drive_executions) == 2 * instances
    assert len(model.body_activation_origins) == instances


@pytest.mark.parametrize('resume', ('value', 'packet'))
@pytest.mark.parametrize('switched_thread', (False, True))
def test_persistent_body_start_and_resume_keep_every_original_port_and_selected_outcome(resume, switched_thread):
    program, model, details = resumable_execution(resume=resume, switched_thread=switched_thread, extra_domain=True)
    index = _index(program, model, details)
    static = ProgramIndex(program)
    item, = details['instances']
    values = {row.id: row for row in model.values}
    uses = {(row.operation, row.use): row for row in model.uses}
    occurrences = {row.id: row for row in model.operations}
    for number, identity in enumerate(item['drives']):
        view = index.drive_execution(identity)
        assert view['drive'] == occurrences[identity]
        assert view['association'] == next(row for row in model.body_drive_executions if row.drive == identity)
        assert view['activation'].id == item['activation']
        assert view['entry'].id == item['entries'][number]
        assert view['outcome'].id == (item['suspension'] if number == 0 else item['outcome'])
        assert view['segment'].id == item['segments'][number]
        assert len(view['inputs']) == len(static.drive_input_bindings(occurrences[identity].operation))
        assert {row['role'] for row in view['inputs']} == ({'capture', 'state'} if number == 0 else {'saved', 'state', 'delivered'})
        for row in view['inputs']:
            assert row['formal'].value == row['formal_definition'].id
            assert row['formal'].origin == item['entries'][number]
            assert row['source_use'] == uses[row['source_use'].operation, row['source_use'].use]
            assert row['source_value'] == values[row['source_use'].value]
            if row['role'] == 'capture':
                assert row['source_use'].operation == item['creation']
            elif row['role'] == 'saved':
                assert row['source_use'].operation == item['suspension']
                route = index.formal_route(row['formal'].id)
                assert route.source_use == row['source_use']
            else:
                assert row['source_use'].operation == identity
            if row['role'] == 'state':
                current = index.state_at(OccurrencePoint(identity, OccurrencePhase.BEFORE))
                assert row['source_use'].value == current[row['formal_definition'].location]
        assert len(view['outputs']) == 3
        assert len(view['forwards']) == 1
        for row in view['outputs']:
            assert row['source_use'].operation == view['outcome'].id
            assert row['formal'].value == row['formal_definition'].id
        assert view['forwards'][0]['source_use'].operation == identity
        assert all(value is None for value in index.state_at(OccurrencePoint(identity, OccurrencePhase.AFTER)).values())
        transfer = next(row for row in model.transfers if row.operation == identity)
        assert all(row['formal'].origin == transfer.target for row in (*view['outputs'], *view['forwards']))
        assert view['source_runtime_verified'] is False
        assert view['value_identity_verified'] is False and view['transformation_authorized'] is False
    origin = index.body_activation_origin(item['activation'])
    assert origin['creation'].id == item['creation']
    assert origin['handle'].origin == item['factory'][1][1]
    assert len(origin['captures']) == 6
    assert set(origin['drives']) == set(item['drives'])


def test_same_code_two_created_instances_have_distinct_activation_capture_and_owner_sources():
    program, model, details = resumable_execution(instances=2)
    index = _index(program, model, details)
    first, second = details['instances']
    assert first['activation'] != second['activation']
    assert first['creation'] != second['creation']
    assert len({row.region for row in model.activations if row.id in {first['activation'], second['activation']}}) == 1
    assert index.body_activation_origin(first['activation'])['handle'].id != index.body_activation_origin(second['activation'])['handle'].id
    wrong = _replace_link(model, second['drives'][0], entry=first['entries'][0])
    assert 'body_entry_activation' in _codes(program, wrong, details)
    wrong = _replace_link(model, second['drives'][1], entry=details['gap'], outcome=first['outcome'])
    assert 'body_outcome_activation' in _codes(program, wrong, details)


@pytest.mark.parametrize('unobserved', ('entry', 'outcome'))
def test_unknown_one_endpoint_does_not_hide_the_other_known_thread_conflict(unobserved):
    program, model, details = resumable_execution(switched_thread=True)
    _index(program, model, details)
    item, = details['instances']
    first_thread = model.threads[0].id
    wrong = replace(model, segments=tuple(replace(row, host_thread=first_thread)
        if row.id == item['segments'][1] else row for row in model.segments))
    wrong = _replace_link(wrong, item['drives'][1], **{unobserved: details['gap']})
    assert 'body_thread' in _codes(program, wrong, details)


def test_unknown_entry_still_rejects_two_captured_outcomes_in_the_selected_segment():
    program, model, details = resumable_execution()
    _index(program, model, details)
    item, = details['instances']
    changed = replace(model,
        visits=tuple(replace(row, segment=item['segments'][0]) if row.id == item['entries'][1] else row
                     for row in model.visits),
        segments=tuple(row for row in model.segments if row.id != item['segments'][1]),
        transfers=tuple(row for row in model.transfers if row.operation != item['suspension']),
        body_drive_executions=tuple(replace(row, entry=details['gap']) for row in model.body_drive_executions
                                   if row.drive == item['drives'][0]))
    old = replace(changed, body_drive_executions=(), body_activation_origins=())
    assert validate(old, program, **_catalogs(details)).valid
    assert 'body_multiple_outcome' in _codes(program, changed, details)


def test_one_successful_create_cannot_claim_two_distinct_persistent_activations():
    program, model, details = resumable_execution(instances=2)
    _index(program, model, details)
    first, second = details['instances']
    wrong = replace(model, body_activation_origins=tuple(replace(row, creation=first['creation'])
        if row.activation == second['activation'] else row for row in model.body_activation_origins))
    assert 'body_creation_reused' in _codes(program, wrong, details)


def test_start_cannot_reuse_a_known_resume_entry_or_segment():
    program, model, details = resumable_execution()
    _index(program, model, details)
    item, = details['instances']
    wrong = _replace_link(model, item['drives'][0], entry=item['entries'][1], outcome=details['gap'])
    assert {'body_start_ingress', 'body_entry_block'} <= _codes(program, wrong, details)


def test_capture_ingress_does_not_become_verified_initial_entry():
    program, model, details = resumable_execution()
    _index(program, model, details)
    item, = details['instances']
    changed = replace(model, segments=tuple(replace(row, ingress=CaptureIngress(details['point'], 'prefix not captured'))
        if row.id == item['segments'][0] else row for row in model.segments))
    view = _index(program, changed, details).drive_execution(item['drives'][0])
    assert view['entry'].id == item['entries'][0]
    assert 'body_entry_ingress_unproved' in {gap.code for gap in view['gaps']}
    assert view['source_runtime_verified'] is False


def test_known_old_suspend_from_another_activation_is_not_a_resume_generation():
    program, model, details = resumable_execution(instances=2)
    _index(program, model, details)
    first, second = details['instances']
    wrong = replace(model, segments=tuple(replace(row, ingress=replace(row.ingress, suspension=first['suspension']))
        if row.id == second['segments'][1] else row for row in model.segments))
    assert 'transfer_resume' in _codes(program, wrong, details)


def test_missing_temporal_transfer_keeps_saved_sources_and_the_exact_missing_ingress_gap():
    program, model, details = resumable_execution()
    _index(program, model, details)
    item, = details['instances']
    missing = replace(model, transfers=tuple(row for row in model.transfers if row.operation != item['suspension']))
    view = _index(program, missing, details).drive_execution(item['drives'][1])
    saved = [row for row in view['inputs'] if row['role'] == 'saved']
    assert saved and all(row['source_use'].operation == item['suspension'] for row in saved)
    assert 'body_resume_transfer_unobserved' in {gap.code for gap in view['gaps']}
    assert all(_index(program, missing, details).formal_route(row['formal'].id).transfer is None for row in saved)


def test_actual_other_resume_case_and_body_source_cannot_fill_the_requested_driver_route():
    program, model, details = resumable_execution(resume='value')
    _index(program, model, details)
    _, packet, packet_details = resumable_execution(resume='packet')
    item, = details['instances']
    other, = packet_details['instances']
    body_visits = set(item['entries'])
    body_ops = {row.id for row in model.operations if row.visit in body_visits}
    packet_ops = {row.id for row in packet.operations if row.visit in body_visits}
    keep_values = {row.id for row in model.values if row.origin not in body_ops | body_visits}
    body_values = {row.id for row in packet.values if row.origin in packet_ops | body_visits}
    changed = replace(model,
        visits=tuple(row for row in model.visits if row.id not in body_visits)
               + tuple(row for row in packet.visits if row.id in body_visits),
        segments=tuple(row for row in model.segments if row.id not in item['segments'])
                 + tuple(row for row in packet.segments if row.id in item['segments']),
        operations=tuple(row for row in model.operations if row.id not in body_ops)
                   + tuple(row for row in packet.operations if row.id in packet_ops),
        values=tuple(row for row in model.values if row.id in keep_values)
               + tuple(row for row in packet.values if row.id in body_values),
        uses=tuple(row for row in model.uses if row.operation not in body_ops)
             + tuple(row for row in packet.uses if row.operation in packet_ops),
        transfers=tuple(row for row in model.transfers if row.operation not in body_ops)
                  + tuple(row for row in packet.transfers if row.operation in packet_ops),
        denotations=tuple(row for row in model.denotations if row.value in keep_values)
                    + tuple(row for row in packet.denotations if row.value in body_values))
    changed = _replace_link(changed, item['drives'][1], outcome=other['outcome'])
    assert validate(replace(changed, body_drive_executions=(), body_activation_origins=()),
                    program, **_catalogs(details)).valid
    assert {'body_resume_source', 'body_drive_source'} <= _codes(program, changed, details)


@pytest.mark.parametrize('role', ('owner', 'capture', 'saved', 'delivered', 'output'))
def test_known_scoped_object_conflicts_are_rejected_for_each_real_binding(role):
    program, model, details = resumable_execution(known_creation=role != 'owner')
    index = _index(program, model, details)
    item, = details['instances']
    first, second = (index.drive_execution(identity) for identity in item['drives'])
    if role == 'owner':
        identity = second['instance']['value'].id
    elif role == 'output':
        identity = next(row['formal'].id for row in second['outputs']
                        if not isinstance(row['formal_definition'], StateVersionValue))
    else:
        view = first if role == 'capture' else second
        identity = next(row['formal'].id for row in view['inputs'] if row['role'] == role
                        and not isinstance(row['formal_definition'], StateVersionValue)
                        and any(denotation.value == row['formal'].id for denotation in model.denotations))
    wrong = replace(model, denotations=tuple(replace(row, identity=ObjectIdentity(ObjectRef(
        details['object_artifact'], item['wrong_object']))) if row.value == identity else row for row in model.denotations))
    report = validate(wrong, program, **_catalogs(details))
    assert not report.valid
    assert 'body_reference_conflict' in {issue.code for issue in report.issues}, report.issues


def test_missing_creation_capture_use_keeps_original_formal_obligation_without_self_binding():
    program, model, details = resumable_execution()
    index = _index(program, model, details)
    item, = details['instances']
    before = index.drive_execution(item['drives'][0])
    selected = next(row for row in before['inputs'] if row['role'] == 'capture')
    absent = selected['source_use']
    model = replace(model, uses=tuple(row for row in model.uses if row != absent))
    after = _index(program, model, details).drive_execution(item['drives'][0])
    assert len(after['inputs']) == len(before['inputs'])
    row = next(row for row in after['inputs'] if row['formal_definition'] == selected['formal_definition'])
    assert row['formal'] is not None and row['source_use'] is None and row['source_value'] is None
    assert 'body_input_use_unobserved' in {gap.code for gap in after['gaps']}


def test_deleting_associations_or_both_endpoints_never_deletes_original_input_frontier_denominator():
    program, model, details = resumable_execution()
    index = _index(program, model, details)
    item, = details['instances']
    before = index.drive_execution(item['drives'][1])
    missing = replace(model, body_drive_executions=())
    after = _index(program, missing, details).drive_execution(item['drives'][1])
    assert after['association'] is None
    assert len(after['inputs']) == len(before['inputs'])
    assert after['outcome_candidates'] == before['outcome_candidates']
    assert 'body_drive_execution_missing' in {gap.code for gap in after['gaps']}
    unknown = _replace_link(model, item['drives'][1], entry=details['gap'], outcome=details['gap'])
    view = _index(program, unknown, details).drive_execution(item['drives'][1])
    assert len(view['inputs']) == len(before['inputs'])
    assert {'body_entry_unobserved', 'body_outcome_unobserved'} <= {gap.code for gap in view['gaps']}


def test_missing_actual_drive_transfer_keeps_body_output_uses_without_fake_landing():
    program, model, details = resumable_execution()
    _index(program, model, details)
    item, = details['instances']
    drive = item['drives'][1]
    transfer = next(row for row in model.transfers if row.operation == drive)
    visit = transfer.target
    removed = {row.id for row in model.operations if row.visit == visit}
    call = next(row for row in model.call_activations if row.id.value.endswith('.resume'))
    model = replace(model, visits=tuple(row for row in model.visits if row.id != visit),
        operations=tuple(row for row in model.operations if row.id not in removed),
        uses=tuple(row for row in model.uses if row.operation not in removed),
        values=tuple(row for row in model.values if row.origin != visit and row.origin not in removed),
        denotations=tuple(row for row in model.denotations if row.value in {
            value.id for value in model.values if value.origin != visit and value.origin not in removed}),
        transfers=tuple(row for row in model.transfers if row != transfer),
        call_activations=tuple(replace(row, completion=details['gap']) if row == call else row for row in model.call_activations))
    view = _index(program, model, details).drive_execution(drive)
    assert len(view['outputs']) == 3
    assert all(row['source_use'] is not None and row['formal'] is None for row in view['outputs'])
    assert 'body_drive_transfer_unobserved' in {gap.code for gap in view['gaps']}


def test_old_state_incarnation_cannot_replace_the_new_resume_formal():
    program, model, details = resumable_execution()
    _index(program, model, details)
    item, = details['instances']
    source = next(row for row in model.uses if row.operation == item['outcome'] and row.use.value == 'resume.return.world')
    old = next(row.id for row in model.values if row.origin == item['entries'][0] and row.value == ValueID('resume.world.0'))
    wrong = replace(model, uses=tuple(replace(row, value=old) if row == source else row for row in model.uses))
    assert {'use_definition', 'stale_incarnation', 'stale_state'} & _codes(program, wrong, details)


def test_empty_frontier_keeps_a_finite_prefix_without_fabricating_completion():
    program, model, details = empty_frontier_execution()
    index = _index(program, model, details)
    view = index.drive_execution(details['drive'])
    assert view['entry'].id == details['entry']
    assert view['outcome'] is None and not view['outputs'] and not view['outcome_candidates']
    assert view['transfer'] is None
    assert 'body_outcome_unobserved' in {gap.code for gap in view['gaps']}
    assert view['source_runtime_verified'] is False and view['transformation_authorized'] is False


def test_public_views_are_detached_and_strict_ids_budget_preserve_unchecked_work():
    program, model, details = resumable_execution()
    index = _index(program, model, details)
    item, = details['instances']
    drive = item['drives'][0]
    view = index.drive_execution(drive)
    object.__setattr__(view['drive'], 'operation', OperationID('not.the.original'))
    view['inputs'] = ()
    original = index.drive_execution(drive)
    assert original['drive'].operation == OperationID('driver.drive') and original['inputs']
    small = index.drive_execution(drive, budget=1)
    assert small['budget']['used'] <= 1 and small['budget']['truncated'] is True
    assert small['cursor'] is not None
    assert small['outcome_candidates'] == original['outcome_candidates']
    assert small['association'] == original['association']
    for field, count in (('inputs', 'input_count'), ('outputs', 'output_count'), ('forwards', 'forward_count')):
        assert small[count] == len(small[field]) == len(original[field])
        assert all(row['compatibility'] is None for row in small[field] if row['check_status'] == 'NOT_CHECKED')
    assert any(row['check_status'] == 'NOT_CHECKED' for row in (*small['inputs'], *small['outputs']))
    for bad in (True, 0, -1):
        with pytest.raises((TypeError, ValueError)):
            index.drive_execution(drive, budget=bad)
    with pytest.raises(TypeError):
        index.drive_execution(drive.value)
    with pytest.raises(ValueError, match='captured canonical BodyDrive'):
        index.drive_execution(OperationOccurrenceID('missing'))
    with pytest.raises(TypeError):
        index.body_activation_origin(item['activation'].value)
    with pytest.raises(ValueError, match='resumable body activation'):
        index.body_activation_origin(RegionActivationID('missing'))
