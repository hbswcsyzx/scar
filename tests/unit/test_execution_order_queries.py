"""Query bounds and isolation over original queue/event associations."""
from dataclasses import replace

import pytest

from scar.ir.execution.ids import QueuePrefixID, WorkTicketID
from scar.ir.execution.order import PrefixEnd, WorkEnd, WorkStart
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.snapshot import snapshot_for
from tests.fixtures.execution_order_graphs import event_order_execution


def test_order_query_budget_does_not_turn_truncated_search_into_independence():
    program, model = event_order_execution()
    index = ExecutionIndex(model, program)
    query = index.work_order(WorkTicketID('p1'), WorkTicketID('c'), budget=1)
    assert query['status'] == 'UNRESOLVED'
    assert query['truncated'] and query['examined_edges'] == 1
    assert not query['path']
    assert index.work_order(WorkTicketID('p1'), WorkTicketID('c'))['status'] == 'CONDITIONAL'


@pytest.mark.parametrize('budget', [True, False, 0, -1, 1.5, '4', None])
def test_order_query_budget_requires_exact_positive_integer(budget):
    program, model = event_order_execution()
    with pytest.raises(ValueError, match='positive integer'):
        ExecutionIndex(model, program).work_order(WorkTicketID('p1'), WorkTicketID('c'), budget=budget)


def test_order_query_cannot_accept_host_point_or_wrong_typed_resource_boundary():
    program, model = event_order_execution()
    index = ExecutionIndex(model, program)
    with pytest.raises(TypeError, match='exact typed'):
        index.order_path(model.event_records[0].observed_at, WorkStart(WorkTicketID('c')))
    with pytest.raises(KeyError):
        index.order_path(WorkEnd(WorkTicketID('absent')), WorkStart(WorkTicketID('c')))
    forged = WorkEnd(WorkTicketID('p1'))
    object.__setattr__(forged, 'ticket', QueuePrefixID('p1'))
    with pytest.raises(TypeError):
        index.order_path(forged, WorkStart(WorkTicketID('c')))


def test_same_endpoint_does_not_supply_strict_order_path():
    program, model = event_order_execution()
    query = ExecutionIndex(model, program).order_path(WorkEnd(WorkTicketID('p1')), WorkEnd(WorkTicketID('p1')))
    assert query['status'] == 'UNRESOLVED' and not query['path']


def test_query_returns_detached_original_rows_and_keeps_authority_false():
    program, model = event_order_execution()
    index = ExecutionIndex(model, program)
    first = index.work_order(WorkTicketID('p1'), WorkTicketID('c'))
    assert first['status'] == 'CONDITIONAL'
    assert not first['source_runtime_verified']
    assert not first['runtime_order_verified']
    assert not first['transformation_authorized']
    assert 'ready' not in first and 'free' not in first
    assert first['gaps']
    original = first['path'][0].support[0]
    object.__setattr__(original, 'work', WorkTicketID('forged'))
    second = index.work_order(WorkTicketID('p1'), WorkTicketID('c'))
    assert second['path'][0].support[0].work == WorkTicketID('p1')
    assert model.queue_prefixes[0].work == WorkTicketID('p1')


def test_fifo_profile_cannot_escape_its_exact_prefix_cutoff():
    program, model = event_order_execution(same_queue=True)
    profiles = tuple(replace(profile, through=QueuePrefixID('r1'))
                     if profile.queue.value == 'order.qa' else profile
                     for profile in model.queue_order_profiles)
    bounded = replace(model, queue_order_profiles=profiles)
    index = ExecutionIndex(bounded, program)
    assert index.work_order(WorkTicketID('p1'), WorkTicketID('r1'))['status'] == 'CONDITIONAL'
    assert index.work_order(WorkTicketID('p1'), WorkTicketID('c'))['status'] == 'UNRESOLVED'
    # Prefix completion still includes its members; it is not a start endpoint.
    assert index.order_path(WorkEnd(WorkTicketID('p1')), PrefixEnd(QueuePrefixID('r2')))['status'] == 'CONDITIONAL'


def test_requirement_only_event_use_joins_exact_realization_or_retains_missing_owner_gap():
    program, model = event_order_execution()
    event_definition = program.resource_locations[-1].resource
    assert event_definition.value == 'order.event'
    uses = tuple(replace(use, definition=None) if use.definition == event_definition else use
                 for use in program.resource_uses)
    program = replace(program, resource_uses=uses)
    model = replace(model, snapshot=snapshot_for(program))
    assert ExecutionIndex(model, program).work_order(WorkTicketID('p1'), WorkTicketID('c'))['status'] == 'CONDITIONAL'
    model = replace(model, realizations=tuple(row for row in model.realizations if row.definition != event_definition))
    index = ExecutionIndex(model, program)
    assert any(gap.code == 'order_event_location_unresolved' for gap in index.report.gaps)
    assert index.work_order(WorkTicketID('p1'), WorkTicketID('c'))['status'] == 'UNRESOLVED'
