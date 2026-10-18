"""A captured contrary branch cannot be repaired with a disconnected frontier."""
from dataclasses import replace

import pytest

from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validation import validate
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_body_prefix_graphs import body_prefix_execution


def _original_core_valid(program, model):
    require_valid(program)
    old = replace(model, body_drive_executions=(), body_activation_origins=())
    report = validate(old, program)
    assert report.valid, report.issues


@pytest.mark.parametrize('selected', ('A', 'B'))
def test_complete_original_a_or_b_branch_has_the_correct_first_outcome_and_actual_drive_source(selected):
    program, model, details = body_prefix_execution(selected=selected)
    _original_core_valid(program, model)
    report = validate(model, program)
    assert report.valid, report.issues
    view = ExecutionIndex(model, program).drive_execution(details['drive'])
    assert view['entry'].id == details['entry']
    assert view['outcome'].id == details['outcome']
    assert view['path_complete'] is True
    assert view['outcome'].operation == details['selected_source']
    assert len(view['outcome_candidates']) == 2
    assert {site.operation for site in view['outcome_candidates']} == set(details['static_sources'])
    transfer = next(row for row in model.transfers if row.operation == details['branch'])
    assert transfer.successor_index == int(selected == 'B')
    assert view['source_runtime_verified'] is False and view['transformation_authorized'] is False


def test_actual_choose_a_cannot_claim_disconnected_b_even_when_a_terminal_occurrence_is_missing():
    program, model, details = body_prefix_execution(selected='B', mode='ghost_b')
    _original_core_valid(program, model)
    assert details['omitted'] not in {row.id for row in model.operations}
    transfer = next(row for row in model.transfers if row.operation == details['branch'])
    assert transfer.successor_index == 0
    outcome = next(row for row in model.operations if row.id == details['outcome'])
    assert outcome.visit not in {row.target for row in model.transfers}
    assert details['selected_source'] in details['static_sources']
    report = validate(model, program)
    assert 'body_outcome_path' in {issue.code for issue in report.issues}, report.issues
    # The observed B is a valid source of this Drive. The contradiction comes
    # from the actual A prefix, not shape/FK, multiple-outcome or source errors.
    assert not {'body_drive_source', 'body_multiple_outcome', 'body_outcome_frontier'} & {
        issue.code for issue in report.issues}


def test_missing_branch_transfer_with_a_legal_b_suffix_is_a_gap_and_keeps_b_output():
    program, model, details = body_prefix_execution(selected='B', mode='missing_transfer')
    _original_core_valid(program, model)
    assert not any(row.operation == details['branch'] for row in model.transfers)
    report = validate(model, program)
    assert report.valid, report.issues
    view = ExecutionIndex(model, program).drive_execution(details['drive'])
    assert view['outcome'].id == details['outcome'] and view['path_complete'] is False
    assert 'body_path_unobserved' in {gap.code for gap in view['gaps']}
    assert view['outputs'] and all(row['source_use'] is not None for row in view['outputs'])
    assert view['source_runtime_verified'] is False and view['transformation_authorized'] is False
