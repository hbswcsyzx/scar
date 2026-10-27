"""Numerical versions, external freshness and body query ownership."""
from dataclasses import replace

import pytest

from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validation import validate
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_body_values import saved_data_execution
from tests.fixtures.execution_resumable_graphs import resumable_execution


@pytest.mark.parametrize('changed', (False, True))
def test_actual_saved_data_binding_keeps_declared_versions_separate_from_numerical_equality(changed):
    program, model, details = saved_data_execution(changed_version=changed)
    require_valid(program)
    catalogs = {name: details[name] for name in ('evidence_graphs', 'value_graphs')}
    report = validate(model, program, **catalogs)
    assert report.valid, report.issues
    index = ExecutionIndex(model, program, **catalogs)
    view = index.drive_execution(details['instances'][0]['drives'][1])
    source, target = details['saved_data']
    binding, = (row for row in view['inputs'] if row['formal'].id == target.id)
    assert binding['role'] == 'saved'
    assert binding['source_value'] == source and binding['formal'] == target
    compatibility = binding['compatibility']
    assert compatibility['status'] == ('UNPROVED' if changed else 'DECLARED_SAME_VERSION')
    assert any(row.code == 'body_data_correspondence_unproved' for row in view['gaps']) is changed
    assert compatibility['value_identity_verified'] is compatibility['transformation_authorized'] is False


def test_query_rechecks_mutable_external_value_artifact_instead_of_using_old_denotations():
    program, model, details = saved_data_execution()
    catalogs = {name: details[name] for name in ('evidence_graphs', 'value_graphs')}
    index = ExecutionIndex(model, program, **catalogs)
    identity = details['instances'][0]['drives'][1]
    before = index.drive_execution(identity)
    graph, = details['value_graphs'].values()
    graph.versions.clear()
    with pytest.raises(ValueError, match='snapshot|artifact|version'):
        index.drive_execution(identity)
    assert before['inputs'][-1]['compatibility']['status'] == 'DECLARED_SAME_VERSION'
    assert index.report.valid


def test_body_origin_with_no_captured_drive_or_origin_is_a_missing_query_not_a_crash():
    program, model, details = resumable_execution()
    # Keep the complete core capture, only remove association metadata. The
    # public query must retain the activation's explicit missing origin.
    changed = replace(model, body_activation_origins=(), body_drive_executions=())
    index = ExecutionIndex(changed, program, evidence_graphs=details['evidence_graphs'])
    view = index.body_activation_origin(details['instances'][0]['activation'])
    assert view['status'] == 'MISSING' and view['creation'] is None
    assert any(row.code == 'body_origin_missing' for row in view['gaps'])
    assert view['transformation_authorized'] is False
