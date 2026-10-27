"""Host call order retains exact occurrence boundaries and a shared budget."""
from dataclasses import replace

import pytest

from scar.ir.execution.common import EvidencePoint, Unresolved
from scar.ir.execution.coordinates import (
    ExecutionRun, HostThreadInstance, InitialEntry, OccurrencePhase, OccurrencePoint,
    ProcessInstance, UnresolvedHostThread,
)
from scar.ir.execution.ids import HostThreadInstanceID, ProcessInstanceID, RunID
from scar.ir.execution.host_order import host_path
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.execution.validity_order import point_order
from scar.ir.execution.validation import refresh_external_context
from scar.ir.execution.order import WorkEnd
from tests.fixtures.execution_call_graphs import invoke_call_execution, shared_calls_execution
from tests.fixtures.execution_call_order_graphs import nested_call_order_execution
from tests.fixtures.execution_work_graphs import ordinary_work_execution


def _point(operation, phase=OccurrencePhase.BEFORE, index=None):
    return OccurrencePoint(operation, phase, index)


def test_sibling_calls_are_ordered_via_exact_child_return_and_parent_original_cfg():
    program, model, _ = shared_calls_execution()
    ctx = ExecutionIndex(model, program)._ctx
    first, second = model.call_activations
    left = _point(first.completion, OccurrencePhase.AFTER)
    right = _point(next(row.id for row in model.operations if row.visit == second.entry))
    budget = ValidityBudget(256)
    view = point_order(ctx, left, right, budget=budget)
    assert view['status'] == 'CONDITIONAL' and not view['truncated']
    assert [step['rule'] for step in view['path']] == [
        'synchronous-call-completion', 'actual-host-path', 'synchronous-call-entry']
    assert view['path'][0]['support'] == (first,)
    assert view['path'][-1]['support'] == (second,)
    assert ctx.point_precedes(left, right) is True
    assert ctx.point_precedes(right, left) is None
    assert point_order(ctx, right, left, budget=budget)['status'] == 'CONTRADICTED'
    assert budget.used <= 256 and sum(budget.costs.values()) == budget.used


@pytest.mark.parametrize('raised', (False, True))
def test_actual_invoke_return_or_raise_only_bridges_to_its_taken_edge(raised):
    program, model, _ = invoke_call_execution(raised=raised)
    ctx = ExecutionIndex(model, program)._ctx
    row, = model.call_activations
    completion = _point(row.completion, OccurrencePhase.AFTER)
    index = 1 if raised else 0
    view = point_order(ctx, completion, _point(row.caller, OccurrencePhase.EDGE, index),
                       budget=ValidityBudget(128))
    assert view['status'] == 'CONDITIONAL'
    assert view['path'][0]['rule'] == 'synchronous-call-completion'
    assert view['path'][0]['target'].successor_index == index
    assert ctx.point_precedes(completion, _point(row.caller, OccurrencePhase.AFTER)) is None
    assert ctx.point_precedes(completion, _point(row.caller, OccurrencePhase.EDGE, 1-index)) is None


def test_missing_caller_transfer_does_not_guess_a_normal_completion_edge():
    program, model, _ = invoke_call_execution(raised=True, caller_transfer=False)
    ctx = ExecutionIndex(model, program)._ctx
    row, = model.call_activations
    start = _point(row.completion, OccurrencePhase.AFTER)
    view = point_order(ctx, start, _point(row.caller, OccurrencePhase.EDGE, 0), budget=ValidityBudget(128))
    assert view['status'] == 'UNRESOLVED'
    assert not any(step.rule == 'synchronous-call-completion'
                   for steps in ctx.host_call_adjacency.values() for step in steps)


def test_missing_entry_keeps_completion_bridge_without_inventing_entry():
    program, model, _ = shared_calls_execution()
    first, second = model.call_activations
    child = next(row for row in model.activations if row.id == first.activation)
    changed = replace(first, entry=Unresolved('entry not paired', child.entry))
    ctx = ExecutionIndex(replace(model, call_activations=(changed, second)), program)._ctx
    first_op = next(row.id for row in model.operations if row.visit == first.entry)
    assert ctx.point_precedes(_point(first.caller), _point(first_op)) is None
    assert ctx.point_precedes(_point(first.completion, OccurrencePhase.AFTER),
                              _point(first.caller, OccurrencePhase.AFTER)) is True


def test_call_path_consumes_existing_budget_and_cannot_use_a_fresh_hidden_allowance():
    program, model, _ = shared_calls_execution()
    ctx = ExecutionIndex(model, program)._ctx
    first, second = model.call_activations
    left = _point(first.completion, OccurrencePhase.AFTER)
    right = _point(second.completion, OccurrencePhase.AFTER)
    budget = ValidityBudget(3)
    assert budget.spend('earlier_stage')
    view = point_order(ctx, left, right, budget=budget)
    assert view['status'] == 'UNRESOLVED' and view['truncated']
    assert budget.used == 3 and budget.remaining == 0
    assert sum(budget.costs.values()) == 3
    assert host_path(ctx, left, right, budget=budget) is None


@pytest.mark.parametrize('recursive', (False, True))
def test_nested_or_recursive_distinct_activations_compose_both_directions_of_each_call(recursive):
    program, model, details = nested_call_order_execution(recursive=recursive)
    ctx = ExecutionIndex(model, program)._ctx
    assert len(set(details['activations'])) == 3
    first = next(row.id for row in model.operations if row.visit == details['entries'][-1])
    entry_path = point_order(ctx, _point(details['calls'][0]), _point(first), budget=ValidityBudget(256))
    assert entry_path['status'] == 'CONDITIONAL'
    assert sum(step['rule'] == 'synchronous-call-entry' for step in entry_path['path']) == 2
    returned = point_order(ctx, _point(details['returns'][-1], OccurrencePhase.AFTER),
        _point(details['calls'][0], OccurrencePhase.AFTER), budget=ValidityBudget(256))
    assert returned['status'] == 'CONDITIONAL'
    assert sum(step['rule'] == 'synchronous-call-completion' for step in returned['path']) == 2
    assert len({step['support'][0].id for step in returned['path'] if step['support']}) == 2
    assert not any('work' in step['rule'] for step in returned['path'])


def test_missing_first_canonical_entry_operation_cannot_use_a_later_captured_operation_as_entry():
    program, model, _ = shared_calls_execution()
    first = model.call_activations[0]
    missing = next(row for row in model.operations if row.visit == first.entry)
    removed = {row.id for row in model.values if row.origin == missing.id}
    changed = replace(model, operations=tuple(row for row in model.operations if row.id != missing.id),
        values=tuple(row for row in model.values if row.id not in removed),
        uses=tuple(row for row in model.uses if row.operation != missing.id and row.value not in removed))
    ctx = ExecutionIndex(changed, program)._ctx
    later = next(row.id for row in changed.operations if row.visit == first.entry)
    assert ctx.point_precedes(_point(first.caller), _point(later)) is None
    assert not any(step.rule == 'synchronous-call-entry' and step.support == (first,)
                   for steps in ctx.host_call_adjacency.values() for step in steps)
    assert any(gap.code == 'operation_unobserved' for gap in ctx.gaps)


def test_missing_completion_does_not_select_an_unpaired_terminal_from_the_same_child():
    program, model, _ = shared_calls_execution()
    first, second = model.call_activations
    child = next(row for row in model.activations if row.id == first.activation)
    changed = replace(first, completion=Unresolved('not paired to its actual completion', child.entry))
    ctx = ExecutionIndex(replace(model, call_activations=(changed, second)), program)._ctx
    assert first.completion in ctx.occurrences
    assert ctx.point_precedes(_point(first.completion, OccurrencePhase.AFTER),
                              _point(first.caller, OccurrencePhase.AFTER)) is None


def test_unknown_threads_leave_call_order_unresolved_without_discarding_the_record():
    program, model, _ = shared_calls_execution()
    first = model.call_activations[0]
    child = next(row for row in model.activations if row.id == first.activation)
    changed = replace(model, segments=tuple(replace(row,
        host_thread=UnresolvedHostThread('thread not observed', child.entry))
        if row.activation == child.id else row for row in model.segments))
    ctx = ExecutionIndex(changed, program)._ctx
    assert first.id in ctx.resolved_call_activations
    view = point_order(ctx, _point(first.completion, OccurrencePhase.AFTER),
        _point(first.caller, OccurrencePhase.AFTER), budget=ValidityBudget(128))
    assert view['status'] == 'UNRESOLVED'
    assert any(gap.code == 'call_thread_unresolved' for gap in ctx.gaps)


def test_known_thread_conflict_is_rejected_before_preparing_host_bridges():
    program, model, _ = shared_calls_execution()
    first = model.call_activations[0]
    other = HostThreadInstance(HostThreadInstanceID('host.other'), model.processes[0].id, 23,
                               model.runs[0].source)
    changed = replace(model, threads=(*model.threads, other), segments=tuple(
        replace(row, host_thread=other.id) if row.activation == first.activation else row
        for row in model.segments))
    with pytest.raises(ValueError, match='call_thread'):
        ExecutionIndex(changed, program)


def test_unlinked_cross_run_child_cannot_acquire_order_from_same_static_region():
    program, model, _ = shared_calls_execution()
    first, second = model.call_activations
    source = model.runs[0].source
    run = ExecutionRun(RunID('host.other'), source)
    process = ProcessInstance(ProcessInstanceID('host.other'), run.id, 12, source)
    thread = HostThreadInstance(HostThreadInstanceID('host.other'), process.id, 13, source)
    point = EvidencePoint(run.id, process.id, source)
    changed = replace(model, runs=(*model.runs, run), processes=(*model.processes, process),
        threads=(*model.threads, thread), call_activations=(second,),
        activations=tuple(replace(row, process=process.id, entry=point)
                          if row.id == first.activation else row for row in model.activations),
        segments=tuple(replace(row, host_thread=thread.id, ingress=InitialEntry(point))
                       if row.activation == first.activation else row for row in model.segments))
    ctx = ExecutionIndex(changed, program)._ctx
    assert ctx.point_precedes(_point(first.completion), _point(second.caller)) is None
    assert point_order(ctx, _point(first.completion), _point(second.caller),
                       budget=ValidityBudget(128))['status'] == 'CONTRADICTED'


def test_same_activation_local_semantics_and_fresh_external_context_do_not_change():
    program, model, _ = invoke_call_execution()
    ctx = ExecutionIndex(model, program)._ctx
    link, = model.call_activations
    caller = _point(link.caller)
    after = _point(link.caller, OccurrencePhase.AFTER)
    assert ctx.point_precedes(caller, after) is True
    assert ctx.point_precedes(after, caller) is False
    parent_return = next(row.id for row in model.operations
                         if ctx.activation_of(row.id) == ctx.activation_of(link.caller)
                         and row.id != link.caller)
    assert ctx.point_precedes(_point(parent_return), caller) is None
    fresh = refresh_external_context(ctx)
    assert fresh.host_call_adjacency == ctx.host_call_adjacency
    assert fresh.host_call_adjacency is not ctx.host_call_adjacency
    assert fresh.host_visit_chains[0] is not ctx.host_visit_chains[0]
    assert fresh.point_precedes(_point(link.completion, OccurrencePhase.AFTER),
                                _point(link.caller, OccurrencePhase.EDGE, 0)) is True


def test_host_operation_return_does_not_establish_resource_work_end():
    program, model, values = ordinary_work_execution()
    ctx = ExecutionIndex(model, program, value_graphs=values)._ctx
    work = model.submissions[0]
    returned = _point(model.operations[-1].id, OccurrencePhase.AFTER)
    view = point_order(ctx, WorkEnd(work.id), returned, budget=ValidityBudget(128))
    assert view['status'] == 'UNRESOLVED'
    assert host_path(ctx, WorkEnd(work.id), returned, budget=ValidityBudget(128)) is None
