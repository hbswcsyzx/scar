"""R2.1 declarations retain original work/effect ports, not runtime proof."""
from dataclasses import replace

import pytest

from scar.ir.execution.common import Unresolved
from scar.ir.execution.coordinates import ExecutionRun, HostThreadInstance, OccurrencePhase, OccurrencePoint, ProcessInstance, UseRef
from scar.ir.execution.ids import (
    HandleBindingID, HostThreadInstanceID, ProcessInstanceID, QueuePrefixID,
    RunID, ValueOccurrenceID, WorkOutcomeID,
)
from scar.ir.execution.resources import EndedAt, InstanceTarget
from scar.ir.execution.validation import require_valid, validate
from scar.ir.execution.work import (
    ActualCompletionState, BorrowRelease, DirectExecution, ExternalWorkSource,
    HandleTarget, InvokeBoundaryStateEffect, WorkOutcomeKind,
)
from scar.ir.program.ids import UseID
from scar.ir.program.model import CompletionResult
from scar.ir.v2.common import Completeness
from tests.fixtures.execution_work_graphs import invoke_work_execution, ordinary_work_execution


def _valid(factory=ordinary_work_execution, **kwargs):
    program, model, values = factory(**kwargs)
    require_valid(model, program, value_graphs=values)
    report = validate(model, program, value_graphs=values)
    assert report.gaps
    assert report.source_runtime_verified is False
    assert report.transformation_authorized is False
    return program, model, values


def _replace_effect(model, effect):
    return replace(model,
        submissions=(replace(model.submissions[0], effects=(effect,)), *model.submissions[1:]),
        outcomes=(replace(model.outcomes[0], effect_frontier=(effect,)), *model.outcomes[1:]))


@pytest.mark.parametrize("queued", (False, True))
def test_ordinary_state_access_submissions_have_real_effects_and_separate_quiescence(queued):
    program, model, _ = _valid(queued=queued, two_tickets=True)
    assert len({row.id for row in model.submissions}) == 2
    assert len({row.origin.operation for row in model.submissions}) == 2
    assert all(row.effects[0].index == 0 for row in model.submissions)
    assert all(row.effect_frontier == submission.effects for row, submission in zip(model.outcomes, model.submissions))
    assert all(row.quiescence == quiet.id for row, quiet in zip(model.outcomes, model.quiescences))
    if queued:
        assert model.queue_prefixes[1].previous == model.queue_prefixes[0].id
        assert model.queue_prefixes[0].queue == model.queue_prefixes[1].queue
    else:
        assert not model.queue_prefixes
        assert all(isinstance(row.scheduling, DirectExecution) for row in model.submissions)
    assert program.operations  # The work graph is attached to a complete core graph.


@pytest.mark.parametrize("raised", (False, True))
@pytest.mark.parametrize("queued", (False, True))
def test_actual_invoke_normal_and_raise_keep_their_own_formal_and_partial_frontier(raised, queued):
    program, model, _ = _valid(invoke_work_execution, raised=raised, queued=queued)
    submission, = model.submissions
    effect, = submission.effects
    assert isinstance(effect, InvokeBoundaryStateEffect)
    assert effect.post.successor_index == int(raised)
    assert effect.post.formal == ValueOccurrenceID("1.invoke." + ("failure" if raised else "normal") + ".world")
    invoke = next(row for row in program.operations if row.id.value == "invoke.call")
    successor = invoke.terminator.successors[int(raised)]
    assert successor.arguments[1 if raised else 0] == CompletionResult(effect.post.result_index)
    outcome, = model.outcomes
    assert outcome.kind is (WorkOutcomeKind.FAILED if raised else WorkOutcomeKind.COMPLETED)
    assert outcome.effect_frontier == submission.effects
    assert outcome.frontier_coverage is Completeness.PARTIAL
    assert model.transfers[0].successor_index == int(raised)
    assert not invoke.results and not invoke.accesses


def test_cancelled_is_not_quiescent_and_does_not_release_borrow_implicitly():
    _, model, _ = _valid(kind=WorkOutcomeKind.CANCELLED, quiescent=False)
    assert not model.quiescences
    assert isinstance(model.outcomes[0].quiescence, Unresolved)
    assert isinstance(model.retentions[0].release, Unresolved)
    assert model.outcomes[0].effect_frontier  # Cancellation does not erase possible writes.


def test_repeated_static_submit_uses_distinct_tickets_and_activation_local_retention():
    _, model, _ = _valid(activations=2)
    first, second = model.submissions
    assert first.id != second.id and first.origin.operation != second.origin.operation
    operations = {row.id: row.operation for row in model.operations}
    assert operations[first.origin.operation] == operations[second.origin.operation]
    assert model.retentions[0].target != model.retentions[1].target


@pytest.mark.parametrize("retained", ("handle", "allocation", "materialization"))
def test_retention_reuses_original_handle_allocation_or_materialization_and_explicit_release(retained):
    _, model, values = _valid(retained=retained)
    retention, = model.retentions
    assert isinstance(retention.release, BorrowRelease)
    assert retention.release.quiescence == model.quiescences[0].id
    assert retention.ticket == model.submissions[0].id
    if retained == "handle":
        assert retention.target == HandleTarget(model.handles[0].id)
    else:
        assert len(values) == 1
        assert len(model.resources) == 3  # Existing OFD, executor, queue; allocation is not a new instance.
        assert model.submissions[0].materializations


def test_unresolved_external_source_and_actual_completion_post_keep_specific_gaps():
    program, model, values = _valid(invoke_work_execution)
    submission = model.submissions[0]
    unknown = Unresolved("completion association not captured", model.activations[0].entry)
    effect = replace(submission.effects[0], post=unknown)
    changed = _replace_effect(model, effect)
    external = ExternalWorkSource(model.activations[0].entry, submission.source)
    changed = replace(changed, submissions=(replace(changed.submissions[0], origin=external,
        scheduling=unknown, executor=unknown, retention=unknown),), retentions=())
    report = validate(changed, program, value_graphs=values)
    assert not report.issues
    assert report.gaps and not report.source_runtime_verified


@pytest.mark.parametrize("raised", (False, True))
@pytest.mark.parametrize("which", ("successor", "result", "formal", "location", "input", "invocation"))
def test_invoke_effect_cannot_change_actual_successor_result_formal_location_or_input(raised, which):
    program, model, values = _valid(invoke_work_execution, raised=raised)
    effect = model.submissions[0].effects[0]
    if which == "successor":
        changed = replace(effect, post=replace(effect.post, successor_index=1 - effect.post.successor_index))
    elif which == "result":
        changed = replace(effect, post=replace(effect.post, result_index=1))
    elif which == "formal":
        changed = replace(effect, post=replace(effect.post, formal=ValueOccurrenceID("0.invoke.world")))
    elif which == "location":
        label = "failure" if raised else "normal"
        changed = replace(effect, post=replace(effect.post,
            formal=ValueOccurrenceID("1.invoke." + label + ".context")))
    elif which == "input":
        changed = replace(effect, state_input=UseRef(effect.invocation, UseID("invoke.call.normal.context")))
    else:
        changed = replace(effect, invocation=model.operations[0].id)
    assert validate(_replace_effect(model, changed), program, value_graphs=values).issues


@pytest.mark.parametrize("which", ("access-index", "executor-role", "queue-role", "prefix-ticket", "prefix-cycle", "dependency-cycle", "outcome-ticket", "frontier-ticket", "quiescence-ticket", "release-before-quiescence", "stale-retention-state"))
def test_work_connections_cannot_be_replaced_by_another_existing_port_or_ticket(which):
    program, model, values = _valid(queued=True, two_tickets=True)
    first, second = model.submissions
    if which == "access-index":
        changed = _replace_effect(model, replace(first.effects[0], index=1))
    elif which == "executor-role":
        changed = replace(model, submissions=(replace(first, executor=model.accesses[0].id), second))
    elif which == "queue-role":
        changed = replace(model, submissions=(replace(first,
            scheduling=replace(first.scheduling, queue_access=first.executor)), second))
    elif which == "prefix-ticket":
        changed = replace(model, submissions=(replace(first,
            scheduling=replace(first.scheduling, prefix=second.scheduling.prefix)), second))
    elif which == "prefix-cycle":
        a, b = model.queue_prefixes
        changed = replace(model, queue_prefixes=(replace(a, previous=b.id), b))
    elif which == "dependency-cycle":
        changed = replace(model, submissions=(replace(first, dependencies=(second.id,)),
                                              replace(second, dependencies=(first.id,))))
    elif which == "outcome-ticket":
        changed = replace(model, outcomes=(replace(model.outcomes[0], ticket=second.id), model.outcomes[1]))
    elif which == "frontier-ticket":
        changed = replace(model, outcomes=(replace(model.outcomes[0], effect_frontier=second.effects), model.outcomes[1]))
    elif which == "quiescence-ticket":
        changed = replace(model, quiescences=(replace(model.quiescences[0], ticket=second.id), model.quiescences[1]))
    elif which == "release-before-quiescence":
        row = model.retentions[0]
        early = OccurrencePoint(first.origin.operation, OccurrencePhase.BEFORE)
        changed = replace(model, retentions=(replace(row, release=replace(row.release, point=early)), model.retentions[1]))
    else:
        changed = replace(model, retentions=(replace(model.retentions[0],
            support=(ValueOccurrenceID("activation.0.resource.initial"),)), model.retentions[1]))
    assert validate(changed, program, value_graphs=values).issues, which


def test_direct_executor_cannot_use_a_thread_from_another_known_run():
    program, model, values = _valid()
    source = model.runs[0].source
    run = ExecutionRun(RunID("other-run"), source)
    process = ProcessInstance(ProcessInstanceID("other-process"), run.id, None, source)
    thread = HostThreadInstance(HostThreadInstanceID("other-thread"), process.id, None, source)
    submission = replace(model.submissions[0], scheduling=DirectExecution(thread.id, source))
    changed = replace(model, runs=(*model.runs, run), processes=(*model.processes, process),
        threads=(*model.threads, thread), submissions=(submission,))
    assert validate(changed, program, value_graphs=values).issues


def test_known_conflicting_terminal_observations_do_not_override_earlier_outcome():
    program, model, values = _valid()
    duplicate = replace(model.outcomes[0], id=WorkOutcomeID("contradiction"), kind=WorkOutcomeKind.CANCELLED)
    assert validate(replace(model, outcomes=(*model.outcomes, duplicate)), program, value_graphs=values).issues


def test_retention_cannot_begin_using_an_already_ended_handle_lifetime():
    program, model, values = _valid(retained="handle")
    original = model.handles[0]
    ended = replace(original, id=HandleBindingID("already-ended"),
        end=EndedAt(original.start, original.source))
    changed = replace(model, handles=(*model.handles, ended),
        retentions=(replace(model.retentions[0], target=HandleTarget(ended.id)),))
    # The alternate historical binding has no ResourceAccess users. Its known
    # end is legal R1 history; the new work borrow must fail independently.
    history_only = replace(changed, submissions=(), outcomes=(), quiescences=(), retentions=(), queue_prefixes=())
    require_valid(history_only, program, value_graphs=values)
    assert validate(changed, program, value_graphs=values).issues
