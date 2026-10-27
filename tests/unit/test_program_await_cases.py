"""Original two-arm inventory is independent of input/link attachments."""
from dataclasses import replace

from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid
from tests.fixtures.program_await_case_graphs import await_case_program


def _await(graph, details):
    require_valid(graph)
    return ProgramIndex(graph).protocol_obligations(details['acquisition_scope'], budget=65536)[
        'connections']['families']['await']


def test_same_iterator_in_both_arms_preserves_two_whole_case_tuples():
    graph, details = await_case_program()
    report = _await(graph, details)
    assert report['inventory']['source_count'] == 1
    jobs = report['inventory']['jobs']
    assert len(jobs) == 4
    assert {(job['advance'].slot, job['case'].guard) for job in jobs} == {
        (slot, guard) for slot in (0, 1) for guard in details['guards']}
    assert all(job['binding']['match'] is True for job in jobs)
    assert report['transformation_authorized'] is False


def test_deleting_case_attachments_keeps_original_incoming_obligations():
    graph, details = await_case_program()
    graph = replace(graph, protocol_call_inputs=tuple(replace(row, cases=row.cases[:1])
        if row.site.operation == details['call'].id else row for row in graph.protocol_call_inputs))
    report = _await(graph, details)
    assert report['inventory']['source_count'] == 1
    assert len(report['inventory']['jobs']) == 4
    assert any('await_input_case_missing' in job['gaps'] for job in report['inventory']['jobs'])


def test_deleting_the_whole_input_attachment_keeps_the_canonical_merge():
    graph, details = await_case_program()
    graph = replace(graph, protocol_call_inputs=tuple(row for row in graph.protocol_call_inputs
        if row.site.operation != details['call'].id))
    report = _await(graph, details)
    assert report['inventory']['source_count'] == 1
    jobs = report['inventory']['jobs']
    assert len(jobs) == 4
    assert all(job['case'] is None and 'await_input_case_missing' in job['gaps'] for job in jobs)
    assert {job['input_guard'] for job in jobs} == set(details['guards'])
