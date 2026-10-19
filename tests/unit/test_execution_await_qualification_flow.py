"""Actual acceptance is checked separately from complete static CFG shape."""
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validation import validate
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_await_qualification_graphs import (
    accepted_without_later_drive_execution, qualified_general_execution,
)


def _view(program, model, details):
    report = ExecutionIndex(model, program).await_body_links(
        details['acquisition_scope'], budget=262144)
    matches = tuple(row for row in report['qualifications']
        if row['record'] == details['qualification_row']
        and row['occurrence'].id == details['qualification_occurrence'])
    assert len(matches) == 1
    return report, matches[0]


def test_captured_rejection_of_known_bad_candidate_keeps_real_packet_and_no_drive():
    program, model, details = qualified_general_execution(accepted=False)
    require_valid(program)
    validation = validate(model, program)
    assert validation.valid, validation.issues
    assert model.body_drive_executions == ()
    assert details['call_activation'].completion == details['helper_operations'][details['failure_terminal'].id]
    report, qualification = _view(program, model, details)
    assert qualification['acceptance_selected'] is False
    assert qualification['feasibility']['acceptance'] is False
    assert not any(issue.code == 'await_qualification_acceptance' for issue in report['issues'])
    assert qualification['source_runtime_verified'] is False
    assert qualification['runtime_identity_verified'] is False
    assert report['value_identity_verified'] is False
    assert report['transformation_authorized'] is False


def test_captured_acceptance_of_known_bad_candidate_is_a_protocol_contradiction():
    program, model, details = qualified_general_execution(accepted=True)
    require_valid(program)
    report, qualification = _view(program, model, details)
    assert qualification['acceptance_selected'] is True
    assert qualification['feasibility']['acceptance'] is False
    assert 'await_qualification_acceptance' in {issue.code for issue in report['issues']}
    assert report['status'] == 'CONTRADICTED'
    assert qualification['source_runtime_verified'] is False
    assert qualification['runtime_identity_verified'] is False
    assert report['value_identity_verified'] is False
    assert report['transformation_authorized'] is False


def test_bad_acceptance_is_checked_without_any_later_advance_or_body_capture():
    program, model, details = accepted_without_later_drive_execution()
    require_valid(program)
    validation = validate(model, program)
    assert validation.valid, validation.issues
    assert details['omitted_advance'] not in {row.id for row in model.operations}
    assert model.body_drive_executions == () and model.body_activation_origins == ()
    assert model.call_activations == (details['acquisition_call'],)
    assert details['qualification_occurrence'] in {row.id for row in model.operations}
    report, qualification = _view(program, model, details)
    assert qualification['acceptance_selected'] is True
    assert qualification['feasibility']['acceptance'] is False
    assert 'await_qualification_acceptance' in {issue.code for issue in report['issues']}
    assert report['status'] == 'CONTRADICTED'
    assert qualification['runtime_identity_verified'] is False
    assert report['source_runtime_verified'] is False
    assert report['transformation_authorized'] is False
