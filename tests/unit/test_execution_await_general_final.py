"""Exact general source/helper/B/child occurrences through the final consumer."""
from dataclasses import replace

import pytest

from scar.ir.execution.common import Unresolved
from scar.ir.execution.coordinates import InitialEntry, ResumeIngress
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validation import validate
from scar.ir.program.model import ExitKind, StateVersionValue
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_await_general_final_graphs import await_general_final_execution


QUERY_BUDGET = 1_048_576


def _index(program, model):
    require_valid(program)
    report = validate(model, program)
    assert report.valid, report.issues
    return ExecutionIndex(model, program)


def _report(program, model, details, *, budget=QUERY_BUDGET):
    return _index(program, model).await_body_links(details['static']['acquisition_scope'], budget=budget)


def _implementation(report, details, example):
    outcome, = tuple(row for row in report['outcomes']
        if row['definition']['drive_outcome'] == details['drive_outcome']
        and row['definition']['advance_operation'] == details['static']['advance_operation'])
    occurrence, = tuple(row for row in outcome['occurrences']
        if row['advance'].id == example['advance'] and row['drive'].id == example['body_drives'][-1].drive)
    consumer, = tuple(row for row in occurrence['consumers']
        if row['definition']['actual'] == details['static']['extract_input']
        and row['definition']['requires_final_extraction'])
    return consumer['implementation']


def _paths(implementation):
    return tuple(path for stage in implementation['stages'] for leg in stage['legs']
        for result in leg['results'] for path in result['paths']
        if path['selected'] is True and path['contribution']['match'] is True)


def _job_occurrence(report, example, item, ordinal):
    job, = tuple(job for job in report['jobs']
        if job['advance'].operation == item['caller_call'].id
        and job['advance'].slot == item['selected_call_edge'])
    occurrence, = tuple(row for row in job['occurrences']
        if row['advance'].id == example['call_activations'][ordinal].caller)
    return occurrence


def _call_id(call):
    return call['association'].id


@pytest.mark.parametrize(('zero_cut', 'depth', 'child_raised'),
    ((True, 1, False), (True, 2, True), (False, 1, True), (False, 2, False)),
    ids=('zero-depth1-normal', 'zero-depth2-raise', 'two-depth1-raise', 'two-depth2-normal'))
def test_general_acquisition_before_start_owns_the_persistent_body_and_real_final_chain(
        zero_cut, depth, child_raised):
    program, model, details = await_general_final_execution(zero_cut=zero_cut,
        depth=depth, child_raised=child_raised, instances=2)
    index = _index(program, model)
    # This remains an ordinary legal captured graph without the new O links.
    old = validate(replace(model, body_drive_executions=(), body_activation_origins=()), program)
    assert old.valid, old.issues
    report = index.await_body_links(details['static']['acquisition_scope'], budget=QUERY_BUDGET)
    assert not report['budget']['truncated']
    static = details['static']
    segments = {row.id: row for row in model.segments}
    uses = {(row.operation, row.use): row for row in model.uses}
    actual_values = {row.id: row for row in model.values}
    definitions = {row.id: row for row in program.values}
    kind = ExitKind.RAISE if child_raised else ExitKind.NORMAL

    for example in details['instances']:
        assert example['body_origin'].creation == example['helper_operations'][static['helper_create'].operation]
        assert example['body_origin'].creation != example['decoy_creation']
        assert example['acquisition_call'].caller == example['acquisition']
        assert example['acquisition_call'].activation == example['helper_activation']
        assert example['acquisition_call'].completion == example['helper_operations'][static['helper_return'].id]
        assert len(example['body_segments']) == (1 if zero_cut else 3)
        assert isinstance(segments[example['body_segments'][0]].ingress, InitialEntry)
        origin = index.body_activation_origin(example['body_activation'], budget=QUERY_BUDGET)
        assert origin['creation'].id == example['creation']
        assert origin['creation'].operation == static['helper_create'].operation

        for ordinal, item in enumerate(static['drivers']):
            occurrence = _job_occurrence(report, example, item, ordinal)
            assert occurrence['advance_selected'] is True
            assert tuple(row['occurrence'].id for row in occurrence['matched_sources']) == (example['acquisition'],)
            route, = occurrence['routes']
            assert tuple(row['association'] for row in route['call_chain']) == (example['call_activations'][ordinal],)
            view = route['drive']
            assert view['association'] == example['body_drives'][ordinal]
            assert view['activation'].id == example['body_activation']
            assert view['entry'].id == example['body_entries'][ordinal]
            assert view['outcome'].id == example['body_drives'][ordinal].outcome
            assert view['segment'].id == example['body_segments'][ordinal]
            assert view['instance']['creation_handle'] is not None
            if ordinal:
                ingress = segments[example['body_segments'][ordinal]].ingress
                assert isinstance(ingress, ResumeIngress)
                assert ingress.suspension == example['body_drives'][ordinal - 1].outcome
                assert ingress.successor_index == item['drive'].target.successor
                assert any(row.operation == ingress.suspension and row.target == example['body_entries'][ordinal]
                           for row in model.transfers)
            # Inputs and state slots refer to their own actual/current ports,
            # never the sibling activation or an earlier post-state by name.
            assert view['inputs'] and view['outputs']
            for binding in (*view['inputs'], *view['outputs']):
                if isinstance(binding['formal_definition'], StateVersionValue):
                    formal = binding['formal']
                    assert formal is not None
                    assert definitions[formal.value].location == binding['formal_definition'].location

        implementation = _implementation(report, details, example)
        expected_calls = (example['implementation_root_call'], *example['implementation_nested_calls'])
        assert len(implementation['frames']) == depth
        assert tuple(_call_id(frame['call']) for frame in implementation['frames']) == tuple(
            call.id for call in expected_calls)
        for frame, original in zip(implementation['frames'], example['implementation_frames']):
            assert frame['completion'].id == original['completion']
        paths = _paths(implementation)
        assert paths
        assert any(len(path['hops']) == depth
            and {_call_id(hop['call']) for hop in path['hops']} == {call.id for call in expected_calls}
            and all(hop['binding']['match'] is True and hop['post_binding']['match'] is True
                    for hop in path['hops'])
            and any(target['operation'].id == example['final'] and target['binding']['match'] is True
                    for target in path['targets']) for path in paths)
        leaf = example['implementation_frames'][-1]
        payload = leaf['definition']['terminal_payloads'][kind]
        payload_use = uses[(leaf['completion'], payload.use)]
        assert actual_values[payload_use.value].origin in leaf['visits']
        active_outputs = tuple(output for output in implementation['outputs'] if output['selected'] is True)
        assert len(active_outputs) == 3
        assert all(terminal['match'] is True for output in active_outputs for terminal in output['terminals']
                   if terminal['selected'] is True)
        for name in ('source_runtime_verified', 'runtime_identity_verified',
                     'value_identity_verified', 'transformation_authorized'):
            assert report[name] is False and implementation[name] is False


@pytest.mark.parametrize('missing', ('association', 'completion'))
def test_missing_first_acquisition_join_or_completion_cannot_borrow_the_other_instance(missing):
    program, model, details = await_general_final_execution(zero_cut=False, depth=1,
        missing_acquisition_call=0 if missing == 'association' else None,
        missing_helper_return=0 if missing == 'completion' else None)
    first, sibling = details['instances']
    if missing == 'completion':
        assert type(first['acquisition_call'].completion) is Unresolved
    report = _report(program, model, details)
    assert report['status'] == 'PARTIAL'
    for ordinal, item in enumerate(details['static']['drivers']):
        partial = _job_occurrence(report, first, item, ordinal)
        assert partial['gaps']
        assert 'await_general_body_source_occurrence_unproved' in {
            getattr(gap, 'code', gap) for gap in partial['gaps']}
        assert all(row['occurrence'].id != sibling['acquisition'] for row in partial['matched_sources'])
        complete = _job_occurrence(report, sibling, item, ordinal)
        assert tuple(row['occurrence'].id for row in complete['matched_sources']) == (sibling['acquisition'],)
        assert not any(getattr(gap, 'code', gap) == 'await_general_body_source_occurrence_unproved'
                       for gap in complete['gaps'])


@pytest.mark.parametrize('missing', ('child_call', 'terminal_use'))
def test_missing_exact_nested_final_capture_keeps_the_other_general_instance(missing):
    program, model, details = await_general_final_execution(zero_cut=False, depth=2,
        child_raised=True, missing_child_call=(0, 0) if missing == 'child_call' else None,
        missing_child_use=(0, 1) if missing == 'terminal_use' else None)
    report = _report(program, model, details)
    first, sibling = details['instances']
    partial = _implementation(report, details, first)
    assert len(partial['frames']) == 2
    assert partial['status'] == 'PARTIAL' and partial['gaps']
    if missing == 'child_call':
        assert partial['frames'][0]['call'] is not None and partial['frames'][1]['call'] is None
    else:
        assert partial['frames'][1]['completion'] is not None
        assert any('region_return_use_unobserved' in path['gaps'] for stage in partial['stages']
            for leg in stage['legs'] for result in leg['results'] for path in result['paths'])
    assert _paths(_implementation(report, details, sibling))


def test_same_code_outer_create_cannot_claim_the_method_created_persistent_body():
    program, model, details = await_general_final_execution(zero_cut=False, depth=2)
    _index(program, model)
    first, sibling = details['instances']
    assert details['static']['outer_creations'][0].body == details['static']['helper_create'].body
    wrong = replace(model, body_activation_origins=tuple(replace(row, creation=first['decoy_creation'])
        if row.activation == first['body_activation'] else row for row in model.body_activation_origins))
    report = validate(wrong, program)
    assert 'body_instance_source' in {issue.code for issue in report.issues}
    assert next(row for row in wrong.body_activation_origins
                if row.activation == sibling['body_activation']) == sibling['body_origin']


def test_tiny_budget_retains_canonical_source_and_marks_unchecked_actual_chain():
    program, model, details = await_general_final_execution(zero_cut=False, depth=2)
    report = _report(program, model, details, budget=1)
    assert report['inventory']['source_count'] == 1  # the queried acquisition scope, not its child Q scope
    assert report['budget']['used'] <= 1 and report['budget']['truncated'] is True
    assert report['status'] == 'PARTIAL' and report['cursor'] is not None
    assert report['job_count'] >= 1
    assert any(job['source_operation'] == details['static']['get'].id for job in report['jobs'])
    for job in report['jobs']:
        for occurrence in job['occurrences']:
            if occurrence['status'] == 'NOT_CHECKED':
                assert occurrence['matched_sources'] == () and occurrence['bindings'] == ()
    assert len(model.body_drive_executions) == 6 and len(model.body_activation_origins) == 2
    assert report['transformation_authorized'] is False


__all__ = []
