"""The same body survives direct and await calls; declarations give no authority."""
from dataclasses import replace

import pytest

from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validation import validate
from scar.ir.program.model import ExitKind, TerminatorKind
from scar.ir.program.resumption import SuspendTerminator
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_await_resume_graphs import await_resume_execution


def _index(program, model):
    require_valid(program)
    report = validate(model, program)
    assert report.valid, report.issues
    return ExecutionIndex(model, program)


@pytest.mark.parametrize('zero_cut', (True, False), ids=('zero-cut', 'two-cut'))
def test_real_first_and_final_outcomes_keep_one_body_and_the_exact_extraction(zero_cut):
    program, model, details = await_resume_execution(zero_cut=zero_cut)
    index = _index(program, model)
    example, = details['instances']
    expected = 1 if zero_cut else 3
    assert len(example['body_drives']) == expected
    assert len(example['body_segments']) == expected
    assert {row.activation for row in example['body_drives']} == {example['body_activation']}
    for ordinal, association in enumerate(example['body_drives']):
        view = index.drive_execution(association.drive, budget=65536)
        assert view['association'] == association
        assert view['activation'].id == example['body_activation']
        assert view['entry'].id == example['body_entries'][ordinal]
        assert view['instance']['creation_handle'] is not None
        assert all(view[key] is False for key in ('source_runtime_verified', 'runtime_identity_verified',
                                                 'value_identity_verified', 'transformation_authorized'))
    operations = {op.id: op for op in program.operations}
    for ordinal, item in enumerate(details['static']['drivers']):
        outcome = operations[item['outcome_source']]
        assert outcome.terminator.kind is (TerminatorKind.RETURN if ordinal == expected - 1 else TerminatorKind.SUSPEND)
    assert sum(type(op.terminator) is SuspendTerminator for op in program.operations) == (0 if zero_cut else 2)
    assert details['static']['drivers'][-1]['host_terminal'].terminator.kind is TerminatorKind.RAISE
    assert example['extraction'] in {row.id for row in model.operations}
    assert example['final'] in {row.id for row in model.operations}

    report = index.await_body_links(details['static']['acquisition_scope'], budget=262144)
    selected = [occurrence for job in report['jobs'] for occurrence in job['occurrences']
                if occurrence.get('advance_selected') is True]
    expected_calls = {call.caller for call, item in zip(example['call_activations'], details['static']['drivers'])
                      if not item['direct']}
    assert {row['advance'].id for row in selected} == expected_calls
    assert all(row['matched_sources'] for row in selected)
    assert all(route['drive_occurrence'].id in {row.drive for row in example['body_drives']}
               for occurrence in selected for route in occurrence['routes'])
    assert all(report[key] is False for key in ('source_runtime_verified', 'runtime_identity_verified',
                                               'value_identity_verified', 'transformation_authorized'))


def test_two_same_code_creates_do_not_select_the_other_body_origin():
    program, model, details = await_resume_execution()
    _index(program, model)
    example, = details['instances']
    assert example['creation'] != example['decoy_creation']
    assert len({row.body for row in program.resumable_creates}) == 1
    wrong = replace(model, body_activation_origins=(
        replace(example['body_origin'], creation=example['decoy_creation']),))
    report = validate(wrong, program)
    assert not report.valid
    assert 'body_instance_source' in {issue.code for issue in report.issues}


def test_old_cut_cannot_be_used_as_the_second_resume_ingress():
    program, model, details = await_resume_execution()
    _index(program, model)
    example, = details['instances']
    first = example['body_drives'][0].outcome
    target = example['body_segments'][2]
    wrong = replace(model, segments=tuple(replace(segment,
        ingress=replace(segment.ingress, suspension=first)) if segment.id == target else segment
        for segment in model.segments))
    report = validate(wrong, program)
    assert not report.valid
    assert 'transfer_resume' in {issue.code for issue in report.issues}


def test_same_body_does_not_allow_another_drive_entry_and_outcome():
    program, model, details = await_resume_execution()
    _index(program, model)
    example, = details['instances']
    first, second, final = example['body_drives']
    wrong = replace(model, body_drive_executions=(first, second,
        replace(final, entry=second.entry, outcome=second.outcome)))
    report = validate(wrong, program)
    assert not report.valid
    assert {'body_entry_block', 'body_outcome_source', 'body_segment_reused', 'body_entry_reused'} & {
        issue.code for issue in report.issues}


def test_missing_exact_caller_pair_keeps_the_captured_body_and_missing_route():
    program, model, details = await_resume_execution()
    example, = details['instances']
    missing = example['call_activations'][1]
    model = replace(model, call_activations=tuple(row for row in model.call_activations if row != missing))
    report = _index(program, model).await_body_links(details['static']['acquisition_scope'], budget=262144)
    rows = [occurrence for job in report['jobs'] for occurrence in job['occurrences']
            if occurrence['advance'].id == missing.caller and occurrence.get('advance_selected') is True]
    assert rows
    assert all(not row['routes'] for row in rows)
    assert any(getattr(gap, 'code', None) == 'await_drive_call_chain_missing' for row in rows for gap in row['gaps'])
    assert report['status'] == 'PARTIAL'


def test_repeated_root_evaluation_never_borrows_a_sibling_body_activation():
    program, model, details = await_resume_execution(instances=2)
    report = _index(program, model).await_body_links(details['static']['acquisition_scope'], budget=524288)
    owner = {call.caller: example for example in details['instances'] for call in example['call_activations']}
    assert len({item['creation'] for item in details['instances']}) == 2
    assert len({item['body_activation'] for item in details['instances']}) == 2
    for job in report['jobs']:
        for occurrence in job['occurrences']:
            if occurrence.get('advance_selected') is not True:
                continue
            example = owner[occurrence['advance'].id]
            assert occurrence['matched_sources']
            assert {source['occurrence'].id for source in occurrence['matched_sources']} == {example['acquisition']}
            assert all(route['drive']['activation'].id == example['body_activation'] for route in occurrence['routes'])


def test_budget_one_keeps_sources_jobs_and_original_unexamined_occurrences():
    program, model, details = await_resume_execution()
    index = _index(program, model)
    report = index.await_body_links(details['static']['acquisition_scope'], budget=1)
    assert report['inventory']['source_count'] >= 1
    assert report['job_count'] >= 1
    assert report['budget']['used'] <= 1
    assert report['budget']['truncated'] is True
    assert report['cursor'] is not None
    assert report['status'] == 'PARTIAL'
    assert report['source_runtime_verified'] is False
