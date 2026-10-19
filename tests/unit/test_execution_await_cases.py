"""Identical data from two arms does not select an unexecuted CFG guard."""
from dataclasses import replace

import pytest

from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.snapshot import snapshot_for
from scar.ir.execution.validation import validate
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_await_case_graphs import await_case_execution


@pytest.mark.parametrize('selected', (0, 1))
def test_actual_incoming_selects_one_case_even_when_both_carry_the_same_body(selected):
    program, model, details = await_case_execution(selected=selected)
    require_valid(program)
    validation = validate(model, program)
    assert validation.valid, validation.issues
    report = ExecutionIndex(model, program).await_body_links(details['acquisition_scope'], budget=65536)
    assert report['inventory']['source_count'] == 1
    assert report['job_count'] == 4
    assert report['issues'] == ()
    active = []
    for job in report['jobs']:
        occurrence, = job['occurrences']
        if occurrence['status'] != 'NOT_APPLICABLE':
            active.append((job, occurrence))
    assert len(active) == 1
    job, occurrence = active[0]
    assert job['case'].guard == details['guards'][selected]
    assert job['advance'].slot == 0
    assert occurrence['matched_sources']
    assert len(occurrence['routes']) == 1
    assert report['transformation_authorized'] is False


@pytest.mark.parametrize('selected', (0, 1))
def test_deleted_case_does_not_erase_a_captured_incoming_leg(selected):
    program, model, details = await_case_execution(selected=selected)
    program = replace(program, protocol_call_inputs=tuple(replace(row, cases=row.cases[:1])
        if row.site.operation == details['call'].id else row for row in program.protocol_call_inputs))
    model = replace(model, snapshot=snapshot_for(program))
    validation = validate(model, program)
    assert validation.valid, validation.issues
    report = ExecutionIndex(model, program).await_body_links(details['acquisition_scope'], budget=65536)
    assert report['inventory']['source_count'] == 1
    assert report['job_count'] == 4
    missing = [job for job in report['jobs'] if job.get('input_case_missing')]
    assert len(missing) == 2
    assert all(job['case'] is None and 'await_input_case_missing' in job['gaps'] for job in missing)
    assert all(job['input_guard'] == details['guards'][1] for job in missing)
    assert report['status'] == 'PARTIAL'
    assert report['transformation_authorized'] is False
