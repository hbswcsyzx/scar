"""Independent port contradictions remain visible across intermediate copies."""
from dataclasses import replace
import pytest

from scar.ir.execution.content import ObjectIdentity, ObjectRef
from scar.ir.execution.ids import RegionActivationID
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validation import validate
from tests.fixtures.execution_resumable_graphs import resumable_execution


@pytest.mark.parametrize('table,code', (
    ('body_drive_executions', 'body_duplicate_drive'),
    ('body_activation_origins', 'body_duplicate_origin'),
))
def test_body_relationship_tables_reject_duplicate_natural_keys_without_inventing_ids(table, code):
    program, model, details = resumable_execution()
    rows = getattr(model, table)
    changed = replace(model, **{table: (*rows, rows[0])})
    report = validate(changed, program, evidence_graphs=details['evidence_graphs'])
    assert code in {row.code for row in report.issues}


def test_known_intermediate_reference_conflict_cannot_hide_behind_equal_create_and_owner_endpoints():
    program, model, details = resumable_execution()
    item, = details['instances']
    entry = next(row for row in model.visits if row.id == item['start'][1][0])
    block = next(row for region in program.regions for row in region.blocks if row.id == entry.block)
    middle = next(row for row in model.values if row.origin == entry.id and row.value == block.arguments[0])
    changed = replace(model, denotations=tuple(replace(row,
        identity=ObjectIdentity(ObjectRef(details['object_artifact'], item['wrong_object'])))
        if row.value == middle.id else row for row in model.denotations))
    # Both endpoint identities still name the body, but their intervening
    # original CALL/CFG copies now contradict this known scoped object.
    bare = replace(changed, body_drive_executions=(), body_activation_origins=())
    assert validate(bare, program, evidence_graphs=details['evidence_graphs']).valid
    report = validate(changed, program, evidence_graphs=details['evidence_graphs'])
    assert 'body_reference_conflict' in {row.code for row in report.issues}, report


def test_missing_activation_does_not_suppress_known_wrong_kind_outcome():
    program, model, details = resumable_execution()
    item, = details['instances']
    ordinary = next(row for row in model.operations if row.visit == item['entries'][0]
                    and row.id != item['suspension'])
    first, *others = model.body_drive_executions
    changed = replace(model, body_drive_executions=(replace(first,
        activation=RegionActivationID('absent.body'), outcome=ordinary.id), *others))
    report = validate(changed, program, evidence_graphs=details['evidence_graphs'])
    assert {'body_activation', 'body_outcome_kind'} <= {row.code for row in report.issues}


def test_captured_body_without_any_driver_or_origin_still_has_missing_origin_inventory():
    program, model, details = resumable_execution()
    drive_ids = {row.drive for row in model.body_drive_executions}
    changed = replace(model, body_drive_executions=(), body_activation_origins=(),
        operations=tuple(row for row in model.operations if row.id not in drive_ids),
        uses=tuple(row for row in model.uses if row.operation not in drive_ids),
        transfers=tuple(row for row in model.transfers if row.operation not in drive_ids))
    index = ExecutionIndex(changed, program, evidence_graphs=details['evidence_graphs'])
    view = index.body_activation_origin(details['instances'][0]['activation'])
    assert view['status'] == 'MISSING' and view['drives'] == ()
    assert any(row.code == 'body_origin_missing' for row in view['gaps'])
    assert view['preparation_work']['canonical']['captured_drives'] == 0
    assert view['transformation_authorized'] is False


def test_canonical_copy_source_rejects_swapped_creators_even_without_any_object_denotations():
    program, model, details = resumable_execution(instances=2)
    left, right = model.body_activation_origins
    changed = replace(model, denotations=(), body_activation_origins=(
        replace(left, creation=right.creation), replace(right, creation=left.creation)))
    bare = replace(changed, body_drive_executions=(), body_activation_origins=())
    assert validate(bare, program).valid
    report = validate(changed, program)
    assert 'body_instance_source' in {row.code for row in report.issues}, report


def test_known_contrary_create_source_is_not_hidden_by_an_absent_origin_association():
    program, model, details = resumable_execution(instances=2)
    left, right = model.body_activation_origins
    # The actual owner still comes from Create-left, which now has no origin
    # association anywhere. The supplied body claims Create-right instead.
    changed = replace(model, denotations=(), body_activation_origins=(
        replace(left, creation=right.creation),))
    bare = replace(changed, body_drive_executions=(), body_activation_origins=())
    assert validate(bare, program).valid
    report = validate(changed, program)
    assert 'body_instance_source' in {row.code for row in report.issues}, report


def test_distinct_drives_cannot_claim_one_exact_entry_outcome_or_segment():
    program, model, details = resumable_execution(instances=2)
    first, resume, other, last = model.body_drive_executions
    changed = replace(model, body_drive_executions=(first, resume,
        replace(other, activation=first.activation, entry=first.entry, outcome=first.outcome), last))
    report = validate(changed, program, evidence_graphs=details['evidence_graphs'])
    assert {'body_entry_reused', 'body_outcome_reused', 'body_segment_reused'} <= {row.code for row in report.issues}


def test_persistent_owner_conflict_is_rejected_even_with_external_origin_and_a_new_thread():
    program, model, details = resumable_execution(switched_thread=True, known_creation=False)
    item, = details['instances']
    segments = {row.id: row for row in model.segments}
    visits = {row.id: row for row in model.visits}
    values = {row.id: row for row in model.values}
    def is_resume_owner(row):
        value = values[row.value]
        return (value.origin in visits and segments[visits[value.origin].segment].activation == item['resume'][0]
                and row.identity.object.object == item['owner_object'])
    changed = replace(model, denotations=tuple(replace(row,
        identity=ObjectIdentity(ObjectRef(details['object_artifact'], item['wrong_object'])))
        if is_resume_owner(row) else row for row in model.denotations))
    bare = replace(changed, body_drive_executions=(), body_activation_origins=())
    assert validate(bare, program, evidence_graphs=details['evidence_graphs']).valid
    report = validate(changed, program, evidence_graphs=details['evidence_graphs'])
    assert any(row.code == 'body_reference_conflict' and row.path.endswith(':persistent-instance')
               for row in report.issues), report


def test_public_copy_support_retains_intermediate_call_recipe_and_truncation_never_reports_checked_cycle():
    from scar.ir.execution.calls import CallActivation
    program, model, details = resumable_execution()
    index = ExecutionIndex(model, program, evidence_graphs=details['evidence_graphs'])
    item, = details['instances']
    view = index.drive_execution(item['drives'][0])
    entry = next(row for row in model.visits if row.id == item['start'][1][0])
    block = next(row for region in program.regions for row in region.blocks if row.id == entry.block)
    middle = next(row for row in model.values if row.origin == entry.id and row.value == block.arguments[0])
    edge, = (row for row in view['copy_support'] if row['target'] == middle.id)
    assert edge['rule'] == 'ORIGINAL_CALL_INPUT'
    assert any(type(row) is CallActivation and row in model.call_activations for row in edge['support'])
    assert edge['compatibility']['value_identity_verified'] is False
    partial = index.drive_execution(item['drives'][0], budget=1)
    assert partial['input_count'] == view['input_count']
    assert partial['host_order']['status'] == 'NOT_CHECKED'
    assert partial['cursor'] is not None and partial['budget']['used'] == 1
