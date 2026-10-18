"""Dynamic call links are checked against the original CFG and exit ports."""
from dataclasses import replace

import pytest

from scar.ir.execution.common import EvidencePoint, MissingEvidence, Unresolved
from scar.ir.execution.validation import validate
from scar.ir.program.model import TerminatorKind
from tests.fixtures.execution_call_graphs import invoke_call_execution, shared_calls_execution


def _codes(report):
    return {issue.code for issue in report.issues}


def test_two_dynamic_calls_to_one_static_body_are_distinct_valid_activations():
    program, model, details = shared_calls_execution()
    report = validate(model, program)
    assert report.valid, report.issues
    assert len(model.call_activations) == 2
    assert len(set(details['callers'])) == len(set(details['children'])) == 2
    assert all(row.activation in details['children'] for row in model.call_activations)
    assert any(gap.code == 'call_source_runtime_unverified' for gap in report.gaps)
    assert report.transformation_authorized is False


@pytest.mark.parametrize('raised', (False, True))
def test_invoke_link_requires_the_actual_taken_completion_successor(raised):
    program, model, details = invoke_call_execution(raised=raised)
    report = validate(model, program)
    assert report.valid, report.issues
    transfer, = (row for row in model.transfers if row.operation == details['caller'])
    operation = next(row for row in program.operations if row.id ==
                     next(row.operation for row in model.operations if row.id == details['caller']))
    successor = operation.terminator.successors[transfer.successor_index]
    assert successor.block == details['taken_target']
    completion = next(row for row in model.operations if row.id == details['completions'][0])
    expected = TerminatorKind.RAISE if raised else TerminatorKind.RETURN
    assert operation.terminator.kind is TerminatorKind.INVOKE
    assert completion.operation in {item.id for item in program.operations}
    child_operation = next(row for row in program.operations if row.id == completion.operation)
    assert child_operation.terminator.kind is expected
    assert not any(issue.code == 'call_transfer_kind' for issue in report.issues)


def test_child_completion_without_caller_transfer_is_a_gap_not_a_guessed_normal_edge():
    program, model, details = invoke_call_execution(raised=True, caller_transfer=False)
    report = validate(model, program)
    assert report.valid, report.issues
    assert not any(row.operation == details['caller'] for row in model.transfers)
    assert any(gap.code == 'call_transfer_unobserved' for gap in report.gaps)
    assert any(row.id == details['completions'][0] for row in model.operations)


def test_child_completion_disconnected_from_its_initial_entry_keeps_a_path_gap():
    program, model, details = invoke_call_execution(raised=False)
    child = details['child']
    child_visits = {row.id for row in model.visits if row.segment in {
        segment.id for segment in model.segments if segment.activation == child}}
    cut = next(row for row in model.transfers
               if row.operation != details['caller'] and row.target in child_visits)
    changed = replace(model, transfers=tuple(row for row in model.transfers if row != cut))
    report = validate(changed, program)
    assert report.valid, report.issues
    assert any(gap.code == 'call_path_unobserved' for gap in report.gaps)


def test_entry_must_be_the_callee_initial_visit_not_the_parent_or_a_resume_landing():
    program, model, details = invoke_call_execution(raised=False)
    row, = model.call_activations
    changed = replace(model, call_activations=(replace(row, entry=details['caller_entry']),))
    report = validate(changed, program)
    assert {'call_entry_activation', 'call_entry_block'} & _codes(report)


def test_known_process_conflict_on_unresolved_endpoint_is_rejected():
    program, model, details = invoke_call_execution(raised=False, caller_transfer=False)
    row, = model.call_activations
    run = model.runs[0].id
    source = MissingEvidence('second process scope for a negative endpoint')
    process_type = type(model.processes[0])
    process_id_type = type(model.processes[0].id)
    process = process_id_type('calls.second-process')
    other_process = process_type(process, run, 22, source)
    bad_point = EvidencePoint(run, process, source)
    changed_row = replace(row, entry=Unresolved('entry omitted in another known process', bad_point))
    changed = replace(model, processes=(*model.processes, other_process),
                      call_activations=(changed_row,))
    report = validate(changed, program)
    assert 'call_unresolved_process' in _codes(report)


def test_no_association_remains_valid_but_records_that_static_callee_capture_is_missing():
    program, model, details = shared_calls_execution()
    changed = replace(model, call_activations=())
    report = validate(changed, program)
    assert report.valid, report.issues
    caller_ids = set(details['callers'])
    assert sum(gap.code == 'call_activation_missing' and gap.path in {str(i) for i in caller_ids}
               for gap in report.gaps) == len(caller_ids)


def test_unknown_unresolved_endpoint_scope_remains_a_gap_and_not_a_synthetic_effect():
    program, model, _details = invoke_call_execution(raised=False, caller_transfer=False)
    row, = model.call_activations
    point = model.activations[1].entry
    changed = replace(model, call_activations=(replace(
        row, completion=Unresolved('completion capture omitted', point)),))
    report = validate(changed, program)
    assert report.valid, report.issues
    assert any(gap.code == 'call_completion_unobserved' for gap in report.gaps)
    assert any(gap.code == 'unresolved' for gap in report.gaps)
    assert not any(issue.code == 'call_completion_raise' for issue in report.issues)
