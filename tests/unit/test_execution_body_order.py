"""Body host bridges preserve partial endpoints and joint occurrence causality."""
from dataclasses import replace

import pytest

from scar.ir.execution.coordinates import OccurrencePhase, OccurrencePoint, UnresolvedHostThread
from scar.ir.execution.host_order import host_cycle_errors, host_path
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.execution.validation import refresh_external_context
from scar.ir.program.ids import OperationID
from scar.ir.program.validation import validate as validate_program
from tests.fixtures.execution_body_order_graphs import mixed_body_call_cycle_execution
from tests.fixtures.execution_resumable_graphs import resumable_execution


def _point(identity, phase=OccurrencePhase.BEFORE, index=None):
    return OccurrencePoint(identity, phase, index)


def _index(program, model, details):
    return ExecutionIndex(model, program, evidence_graphs=details['evidence_graphs'])


def _steps(ctx, rule):
    return tuple(step for steps in ctx.host_call_adjacency.values() for step in steps if step.rule == rule)


@pytest.mark.parametrize('resume', ('value', 'packet'))
def test_start_resume_bridges_follow_the_exact_segment_and_actual_outcome_edge(resume):
    program, model, details = resumable_execution(resume=resume)
    ctx = _index(program, model, details)._ctx
    instance, = details['instances']
    assert ctx.host_cycle_preparation['status'] == 'DECLARED_ACYCLIC'
    assert len(_steps(ctx, 'resumable-body-entry')) == 2
    assert len(_steps(ctx, 'resumable-body-completion')) == 2
    for drive in instance['drives']:
        view = ctx.resolved_body_drives[drive]
        start, first = _point(drive), _point(view['entry_first'].id)
        completed = _point(view['outcome'].id, OccurrencePhase.AFTER)
        returned = _point(drive, OccurrencePhase.EDGE, view['transfer'].successor_index)
        budget = ValidityBudget(1024)
        entry = host_path(ctx, start, first, budget=budget)
        outcome = host_path(ctx, completed, returned, budget=budget)
        assert entry and entry[-1].rule == 'resumable-body-entry'
        assert outcome and outcome[-1].rule == 'resumable-body-completion'
        assert entry[-1].support[0] is view['association']
        assert host_path(ctx, first, start, budget=budget) is None
        assert host_path(ctx, completed, _point(drive, OccurrencePhase.AFTER), budget=budget) is None
        assert not budget.truncated and sum(budget.costs.values()) == budget.used
    left = _point(instance['suspension'], OccurrencePhase.AFTER)
    right = _point(ctx.resolved_body_drives[instance['drives'][1]]['entry_first'].id)
    assert host_path(ctx, left, right, budget=ValidityBudget(2048))


def test_missing_entry_keeps_conditional_completion_support_and_no_entry_bridge():
    program, model, details = resumable_execution()
    first, second = model.body_drive_executions
    changed = replace(first, entry=details['gap'])
    ctx = _index(program, replace(model, body_drive_executions=(changed, second)), details)._ctx
    entries = _steps(ctx, 'resumable-body-entry')
    assert not any(step.support[0].drive == first.drive for step in entries)
    completion = next(step for step in _steps(ctx, 'resumable-body-completion')
                      if step.support[0].drive == first.drive)
    assert completion.source == _point(first.outcome, OccurrencePhase.AFTER)
    assert {gap.code for gap in completion.support[1:]} >= {'body_entry_unobserved', 'body_path_unobserved'}


def test_missing_outcome_keeps_known_entry_without_selecting_an_unpaired_terminal():
    program, model, details = resumable_execution()
    first, second = model.body_drive_executions
    ctx = _index(program, replace(model, body_drive_executions=(replace(first, outcome=details['gap']), second)), details)._ctx
    assert any(step.support[0].drive == first.drive for step in _steps(ctx, 'resumable-body-entry'))
    assert not any(step.support[0].drive == first.drive for step in _steps(ctx, 'resumable-body-completion'))


def test_missing_actual_drive_transfer_cannot_invent_a_completion_edge():
    program, model, details = resumable_execution()
    first, = (row for row in model.body_drive_executions if row.drive == details['instances'][0]['drives'][0])
    changed = replace(model, transfers=tuple(row for row in model.transfers if row.operation != first.drive))
    ctx = _index(program, changed, details)._ctx
    assert any(step.support[0].drive == first.drive for step in _steps(ctx, 'resumable-body-entry'))
    assert not any(step.support[0].drive == first.drive for step in _steps(ctx, 'resumable-body-completion'))
    assert host_path(ctx, _point(first.outcome, OccurrencePhase.AFTER),
                     _point(first.drive, OccurrencePhase.EDGE, 0), budget=ValidityBudget(64)) is None


def test_missing_first_canonical_operation_does_not_promote_a_later_capture_to_entry():
    program, model, details = resumable_execution()
    first, second = model.body_drive_executions
    initial = next(row for row in model.operations if row.visit == first.entry and row.operation == OperationID('resume.initial'))
    removed = {row.id for row in model.values if row.origin == initial.id}
    changed = replace(model, operations=tuple(row for row in model.operations if row.id != initial.id),
        values=tuple(row for row in model.values if row.id not in removed),
        uses=tuple(row for row in model.uses if row.operation != initial.id and row.value not in removed))
    ctx = _index(program, changed, details)._ctx
    assert not any(step.support[0].drive == first.drive for step in _steps(ctx, 'resumable-body-entry'))
    assert any(step.support[0].drive == first.drive for step in _steps(ctx, 'resumable-body-completion'))


def test_unknown_selected_thread_suppresses_only_its_body_bridges():
    program, model, details = resumable_execution()
    instance, = details['instances']
    changed = replace(model, segments=tuple(replace(row,
        host_thread=UnresolvedHostThread('selected thread not captured', details['point']))
        if row.id == instance['segments'][0] else row for row in model.segments))
    ctx = _index(program, changed, details)._ctx
    for rule in ('resumable-body-entry', 'resumable-body-completion'):
        assert not any(step.support[0].drive == instance['drives'][0] for step in _steps(ctx, rule))
        assert any(step.support[0].drive == instance['drives'][1] for step in _steps(ctx, rule))
    assert any(gap.code == 'body_thread_unresolved' for gap in ctx.gaps)


def test_different_historical_drive_threads_are_legal_and_current_mismatch_is_rejected():
    program, model, details = resumable_execution(switched_thread=True)
    ctx = _index(program, model, details)._ctx
    assert len(_steps(ctx, 'resumable-body-entry')) == 2
    assert len(_steps(ctx, 'resumable-body-completion')) == 2
    instance, = details['instances']
    old_thread = next(row.host_thread for row in model.segments if row.id == instance['segments'][0])
    wrong = replace(model, segments=tuple(replace(row, host_thread=old_thread)
                    if row.id == instance['segments'][1] else row for row in model.segments))
    with pytest.raises(ValueError, match='body_thread'):
        _index(program, wrong, details)


def test_refresh_detaches_prepared_host_containers_and_preserves_original_bridge_records():
    program, model, details = resumable_execution()
    ctx = _index(program, model, details)._ctx
    fresh = refresh_external_context(ctx)
    assert fresh.host_call_adjacency == ctx.host_call_adjacency
    assert fresh.host_call_adjacency is not ctx.host_call_adjacency
    assert fresh.host_cycle_preparation is not ctx.host_cycle_preparation
    assert fresh.host_visit_chains[0] is not ctx.host_visit_chains[0]


def test_joint_cycle_scan_consumes_only_the_supplied_remaining_budget_and_reports_partial():
    program, model, details = resumable_execution()
    ctx = _index(program, model, details)._ctx
    budget = ValidityBudget(2)
    assert budget.spend('prior_stage')
    assert host_cycle_errors(ctx, budget=budget) is None
    assert budget.used == 2 and budget.truncated
    assert ctx.host_cycle_preparation['status'] == 'PARTIAL'
    assert any(gap.code == 'host_cycle_unresolved' for gap in ctx.gaps)


def test_actual_call_and_body_bridges_can_cycle_even_when_call_activation_dag_is_acyclic():
    program, model, details = mixed_body_call_cycle_execution()
    assert not validate_program(program)
    # Removing O declarations removes the body bridges; all original static and
    # dynamic call/state/temporal ports remain intact and no CALL cycle exists.
    unpaired = replace(model, body_drive_executions=())
    assert _index(program, unpaired, details)._ctx.host_cycle_preparation['status'] == 'DECLARED_ACYCLIC'
    with pytest.raises(ValueError, match='host_occurrence_cycle'):
        _index(program, model, details)
