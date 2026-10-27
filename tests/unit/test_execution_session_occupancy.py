"""Current session occupancy requires a post, exact body and preserved interval."""
from dataclasses import replace

import pytest

from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validation import validate
from scar.ir.program.lifecycle import SessionPost
from scar.ir.program.protocol_connections import SessionOccupancyCondition
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_async_competition_graphs import async_competition_execution


_BUDGET = 1_048_576


def _index(graph, model):
    require_valid(graph)
    report = validate(model, graph)
    assert report.valid, report.issues
    return ExecutionIndex(model, graph)


def _source(view, example):
    candidate, = tuple(row for row in view['candidates'] if row['source'].id == example['source_hold'])
    return candidate


def _flags(view):
    for key in ('source_runtime_verified', 'runtime_identity_verified',
                'value_identity_verified', 'transformation_authorized'):
        assert view[key] is False


@pytest.mark.parametrize('reject_raised', (False, True), ids=('reject-own-normal', 'reject-own-raise'))
def test_current_occupancy_keeps_provenance_separate_from_whole_call_preservation(reject_raised):
    graph, model, details = async_competition_execution(reject_raised=reject_raised)
    index = _index(graph, model)
    for example in details['instances']:
        view = index.session_occupancy_history(example['occupancy_read'], budget=_BUDGET)
        candidate = _source(view, example)
        assert type(view['predicate'].contract.subject) is SessionOccupancyCondition
        assert view['source_inventory'] == graph.session_updates
        assert view['association_inventory'] == graph.request_association_reads
        assert view['request_create_inventory'] == graph.async_request_creates
        assert candidate['update'].post is SessionPost.HOLD
        assert candidate['post_established'] is True
        assert candidate['subject_binding']['match'] is True
        assert candidate['subject_binding']['conditional_projection'] is True
        assert candidate['subject_binding']['ordinary_binding']['match'] is None
        assert candidate['preservation']['preserved'] is None
        assert candidate['preservation']['blockers']
        assert candidate['expected_bool'] is view['expected_bool'] is None
        assert view['observed_branch'] is True
        assert all(row['expected_bool'] is None for row in view['candidates']
                   if row['update'].post is not SessionPost.HOLD)
        _flags(view)


@pytest.mark.parametrize('reject_raised', (False, True), ids=('future-reject-normal', 'future-reject-raise'))
def test_local_hold_to_actual_occupancy_read_has_a_complete_current_interval(reject_raised):
    graph, model, details = async_competition_execution(reject_raised=reject_raised, local_probe=True)
    index = _index(graph, model)
    for example in details['instances']:
        view = index.session_occupancy_history(example['local_read'], budget=_BUDGET)
        candidate = _source(view, example)
        assert candidate['post_established'] is True
        assert candidate['subject_binding']['match'] is True
        assert candidate['preservation']['preserved'] is True
        assert candidate['preservation']['blockers'] == ()
        assert candidate['expected_bool'] is view['expected_bool'] is True
        assert view['observed_branch'] is True and view['consistent'] is True
        # A supported occupied read in R1 does not mean that R1 must reject.
        # It occurs after its own HOLD, before its real awaitable host return.
        assert len(example['body_drives']) == 3
        assert len(example['body_segments']) == 3
        _flags(view)


@pytest.mark.parametrize('missing', ('source-state', 'read-state', 'body-use'))
def test_missing_this_instances_original_input_cannot_borrow_a_complete_sibling(missing):
    graph, model, details = async_competition_execution(local_probe=True)
    first, second = details['instances']
    occurrences = {row.id: row for row in model.operations}
    operations = {row.id: row for row in graph.operations}
    read = operations[occurrences[first['local_read']].operation]
    if missing == 'source-state':
        source = operations[occurrences[first['source_hold']].operation]
        omitted = first['source_hold'], source.accesses[0].before
    elif missing == 'read-state':
        omitted = first['local_read'], read.accesses[0].before
    else:
        predicate, = tuple(row for row in graph.protocol_operations
            if row.operation == read.id
            and type(getattr(row.contract, 'subject', None)) is SessionOccupancyCondition)
        omitted = first['local_read'], predicate.contract.subject.body_use
    model = replace(model, uses=tuple(row for row in model.uses if (row.operation, row.use) != omitted))
    index = _index(graph, model)
    view = index.session_occupancy_history(first['local_read'], budget=_BUDGET)
    assert view['expected_bool'] is None
    assert view['source_inventory'] == graph.session_updates
    assert index.session_occupancy_history(second['local_read'], budget=_BUDGET)['expected_bool'] is True
    _flags(view)


def test_budget_one_retains_every_original_post_association_and_read_domain():
    graph, model, details = async_competition_execution(local_probe=True)
    index = _index(graph, model)
    first = details['instances'][0]
    complete = index.session_occupancy_history(first['local_read'], budget=_BUDGET)
    view = index.session_occupancy_history(first['local_read'], budget=1)
    assert view['source_inventory'] == graph.session_updates
    assert view['association_inventory'] == graph.request_association_reads
    assert view['request_create_inventory'] == graph.async_request_creates
    assert view['locations'] == complete['locations']
    assert tuple((row['update'], row['source']) for row in view['candidates']) == tuple(
        (row['update'], row['source']) for row in complete['candidates'])
    assert view['budget']['truncated'] is True and view['cursor']
    assert view['expected_bool'] is None
    assert all(row['expected_bool'] is None for row in view['candidates'])
    _flags(view)


def test_own_normal_result_slots_cannot_be_scanned_after_shared_budget_is_exhausted():
    from scar.ir.execution.session_occupancy_history import _Projections
    from scar.ir.execution.validity_budget import ValidityBudget
    graph, model, details = async_competition_execution()
    index = _index(graph, model)
    first = details['instances'][0]
    ctx = index._content_context()
    occurrence = ctx.occurrences[first['association']]
    marker, = tuple(row for row in graph.request_association_reads if row.operation == occurrence.operation)
    shared = ValidityBudget(1)
    assert shared.spend('prior_work', 1)
    projection = _Projections(ctx, shared)
    assert projection.own_normal(occurrence, marker.body_result) is None
    assert shared.truncated is True
