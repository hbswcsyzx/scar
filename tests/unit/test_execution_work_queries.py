from dataclasses import replace

import pytest

from scar.ir.execution.common import Unresolved
from scar.ir.execution.coordinates import AccessRef, OccurrencePhase, OccurrencePoint, UseRef
from scar.ir.execution.ids import WorkOutcomeID
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validation import require_valid, validate
from scar.ir.execution.work import BorrowRelease, ExternalWorkSource, WithinOperation, WorkOutcomeKind
from scar.ir.program.ids import UseID
from scar.ir.program.model import ExitKind
from tests.fixtures.execution_work_graphs import invoke_work_execution, ordinary_work_execution


@pytest.mark.parametrize('raised', [False, True])
def test_invoke_queries_retain_actual_host_outcome_and_original_state_input_and_landing(raised):
    program, model, values = invoke_work_execution(raised=raised)
    index = ExecutionIndex(model, program, value_graphs=values)
    result = index.work(model.submissions[0].id)
    assert result['host_completion'] is (ExitKind.RAISE if raised else ExitKind.NORMAL)
    effect, = result['effects']
    assert effect['input'].use == UseID('invoke.call.world')
    assert effect['post'].id == model.submissions[0].effects[0].post.formal
    assert effect['actual_transfer'].successor_index == int(raised)
    assert result['outcomes'][0].effect_frontier
    assert not result['source_runtime_verified'] and not result['transformation_authorized']
    assert 'ready' not in result and 'free' not in result


def test_host_raise_can_have_pending_work_without_any_terminal_or_quiescence_observation():
    program, model, values = invoke_work_execution(raised=True, quiescent=False)
    model = replace(model, outcomes=())
    result = ExecutionIndex(model, program, value_graphs=values).work(model.submissions[0].id)
    assert result['host_completion'] is ExitKind.RAISE
    assert result['submission'].origin.operation == model.submissions[0].origin.operation
    assert result['outcomes'] == result['quiescences'] == ()
    assert isinstance(result['retentions'][0].release, Unresolved)


def test_multiple_terminal_observations_are_retained_and_result_is_detached():
    program, model, values = ordinary_work_execution()
    second = replace(model.outcomes[0], id=WorkOutcomeID('same-terminal-again'))
    model = replace(model, outcomes=(*model.outcomes, second))
    index = ExecutionIndex(model, program, value_graphs=values)
    result = index.work(model.submissions[0].id)
    assert len(result['outcomes']) == 2
    assert result['host_completion'] is None
    object.__setattr__(result['submission'].origin, 'operation', None)
    assert index.work(model.submissions[0].id)['submission'].origin.operation is not None


def test_ordinary_effect_query_derives_original_access_before_use_and_after_definition():
    program, model, values = ordinary_work_execution()
    submission = model.submissions[0]
    effect = ExecutionIndex(model, program, value_graphs=values).canonical_effect(submission.effects[0])
    original = next(row for row in program.operations if row.id == effect['operation'].operation)
    assert effect['access'] == original.accesses[0]
    assert effect['before'].use == original.accesses[0].before
    assert effect['after'].value == original.accesses[0].after
    assert effect['after'].origin == submission.origin.operation


def test_unresolved_invoke_post_and_external_work_remain_unresolved_in_query():
    program, model, values = invoke_work_execution(quiescent=False)
    unknown = Unresolved('post not captured', model.activations[0].entry)
    effect = replace(model.submissions[0].effects[0], post=unknown)
    submission = replace(model.submissions[0], origin=ExternalWorkSource(model.activations[0].entry,
        model.submissions[0].source), effects=(effect,))
    model = replace(model, submissions=(submission,), outcomes=())
    result = ExecutionIndex(model, program, value_graphs=values).work(submission.id)
    assert result['host_completion'] is None
    assert result['effects'][0]['post'] == unknown


def test_persistent_queue_prefix_query_is_bounded_without_order_authority():
    program, model, values = ordinary_work_execution(queued=True, two_tickets=True)
    index = ExecutionIndex(model, program, value_graphs=values)
    result = index.queue_prefix(model.queue_prefixes[1].id)
    assert len(result['prefixes']) == 2 and not result['truncated']
    assert not result['runtime_order_verified']
    truncated = index.queue_prefix(model.queue_prefixes[1].id, budget=1)
    assert truncated['truncated'] and len(truncated['prefixes']) == 1
    with pytest.raises(ValueError, match='positive integer'):
        index.queue_prefix(model.queue_prefixes[1].id, budget=True)


@pytest.mark.parametrize('which', ['outcome', 'quiescence', 'queue-prefix'])
def test_work_observations_cannot_precede_the_enclosing_submission_call(which):
    program, model, values = ordinary_work_execution(queued=True)
    before = OccurrencePoint(model.submissions[0].origin.operation, OccurrencePhase.BEFORE)
    if which == 'outcome':
        model = replace(model, outcomes=(replace(model.outcomes[0], observed_at=before),))
    elif which == 'quiescence':
        model = replace(model, quiescences=(replace(model.quiescences[0], observed_at=before),))
    else:
        model = replace(model, queue_prefixes=(replace(model.queue_prefixes[0], observed_at=before),))
    assert 'work_observation_before_submission' in {row.code for row in validate(model, program, value_graphs=values).issues}


def test_internal_retention_may_name_actual_post_but_cannot_claim_an_exact_host_point():
    program, model, values = ordinary_work_execution()
    index = ExecutionIndex(model, program, value_graphs=values)
    effect = index.canonical_effect(model.submissions[0].effects[0])
    retention = replace(model.retentions[0], support=(effect['after'].id,))
    model = replace(model, retentions=(retention,))
    report = require_valid(model, program, value_graphs=values)
    assert 'work_retention_internal_start' in {row.code for row in report.gaps}


@pytest.mark.parametrize('basis_kind', ['data-use', 'queue-access'])
def test_known_direct_retention_basis_must_match_held_handle_type_and_target(basis_kind):
    program, model, values = ordinary_work_execution(retained='handle')
    require_valid(model, program, value_graphs=values)
    work = model.submissions[0]
    if basis_kind == 'data-use':
        basis = UseRef(work.origin.operation, UseID('resource.use.0.fd'))
    else:
        basis = next(row.id for row in model.accesses if row.operation == work.origin.operation
                     and row.id.value.startswith('work.queue.'))
    model = replace(model, retentions=(replace(model.retentions[0], basis=basis),))
    assert validate(model, program, value_graphs=values).issues


def test_empty_queue_boundary_must_match_queue_identity_run_even_without_a_work_ticket():
    from scar.ir.execution.common import EvidencePoint
    from scar.ir.execution.coordinates import ExecutionRun, ProcessInstance
    from scar.ir.execution.ids import ProcessInstanceID, QueuePrefixID, RunID
    from scar.ir.execution.work import QueueStart
    program, model, values = ordinary_work_execution(queued=True)
    source = model.runs[0].source
    run = ExecutionRun(RunID('unrelated-run'), source)
    process = ProcessInstance(ProcessInstanceID('unrelated-process'), run.id, None, source)
    point = EvidencePoint(run.id, process.id, source)
    empty = replace(model.queue_prefixes[0], id=QueuePrefixID('foreign-empty-start'),
                    previous=QueueStart(source), work=None, observed_at=point)
    first = replace(model.queue_prefixes[0], previous=empty.id)
    model = replace(model, runs=(*model.runs, run), processes=(*model.processes, process), queue_prefixes=(empty, first))
    assert 'work_prefix_scope' in {row.code for row in validate(model, program, value_graphs=values).issues}


def test_another_activation_may_observe_work_but_missing_host_order_remains_a_specific_gap():
    program, model, values = ordinary_work_execution(activations=2)
    observer = next(row.id for row in model.operations if row.id.value.startswith('activation.1.')
                    and row.operation.value == 'resource.return')
    outcome = replace(model.outcomes[0], observed_at=OccurrencePoint(observer, OccurrencePhase.BEFORE))
    model = replace(model, outcomes=(outcome, *model.outcomes[1:]))
    report = require_valid(model, program, value_graphs=values)
    assert 'work_observation_order_unresolved' in {row.code for row in report.gaps}
    assert not report.source_runtime_verified
