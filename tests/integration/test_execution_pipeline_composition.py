"""Public composition over canonical declarations, without native proof claims.

Each input model is validated before its public query. These are bounded
cross-component tests, not an automatically recovered whole IO pipeline.
"""
from dataclasses import fields, replace

import pytest

from scar.ir.execution.common import Unresolved
from scar.ir.execution.composition import CompositionScope
from scar.ir.execution.coordinates import OccurrencePhase, OccurrencePoint
from scar.ir.execution.ids import TargetLifetimeEventID, ValueOccurrenceID
from scar.ir.execution.observations import OutputValue
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.resources import EndedAt
from scar.ir.execution.validity import (
    CompletedVisibility, LifetimeEventKind, OrderedVisibility, TargetLifetimeEvent,
)
from scar.ir.execution.validation import require_valid
from scar.ir.execution.work import BorrowRelease, HandleTarget, WorkOutcomeKind
from scar.ir.program.model import ExitKind
from scar.ir.program.providers import ProviderFactReference
from tests.fixtures.execution_call_graphs import shared_calls_execution
from tests.fixtures.execution_observation_graphs import observation_execution
from tests.fixtures.execution_produced_graphs import byte_prefix_execution
from tests.fixtures.execution_visibility_graphs import visibility_execution
from tests.fixtures.execution_work_graphs import invoke_work_execution, ordinary_work_execution


def _index(program, model, **catalogs):
    # A test must not obtain the expected view by bypassing the canonical graph.
    require_valid(model, program, **catalogs)
    return ExecutionIndex(model, program, **catalogs)


def _without_authority(view):
    assert not view['scope_inventory_complete']
    assert not view['source_runtime_verified']
    assert not view['runtime_visibility_verified']
    assert not view['transformation_authorized']


def test_public_composition_keeps_completed_actual_left_and_pending_ordered_right_separate():
    program, model, values, payloads, details = visibility_execution()
    index = _index(program, model, value_graphs=values, artifact_bytes=payloads)
    view = index.resource_composition(budget=16384)
    read, = view['reads']['items']
    assert read['status'] == 'INSPECTED' and read['read'].id == details['read']
    validity = read['validity']
    assert validity['known_fragment_coverage']['status'] == 'INCOMPLETE'
    assert validity['conditional_fragment_coverage']['status'] == 'COVERED'
    assert validity['conditional_support']['status'] == 'MATCHED'
    left, right = validity['contributions']
    assert left['actual'] == details['left'] and right['actual'] == details['right']
    assert type(left['alternatives'][0]['visibility']) is CompletedVisibility
    assert type(right['alternatives'][0]['visibility']) is OrderedVisibility
    assert not left['pending'] and right['pending']
    assert validity['source_reconciliation']['status'] == 'OPEN'
    assert validity['validity_conditions']
    assert view['inventory']['execution_counts']['content_reads'] == 1
    assert len(view['production']['outcome_productions']) == 1
    assert view['lifecycle']['total_work'] == len(model.submissions)
    assert not view['budget']['truncated']
    _without_authority(view)


def test_public_composition_retains_actual_four_byte_prefix_of_eight_byte_request():
    program, model, values, payloads = byte_prefix_execution(requested=8, written=4)
    index = _index(program, model, value_graphs=values, artifact_bytes=payloads)
    view = index.resource_composition()
    produced, = view['production']['outcome_productions']
    assert produced['actual'].shape == (4,) and produced['requested'].shape == (8,)
    assert produced['row'] == model.produced[0]
    assert produced['outcome'].kind is WorkOutcomeKind.COMPLETED
    assert produced['placement_match'] is True
    assert produced['conditions']
    assert view['reads']['items'] == ()  # Result observation is not a fabricated read.
    assert len(view['inventory']['execution'].produced) == 1
    assert view['sources']['items'][0]['format_replayed'] is True
    assert 'ready' not in view and 'free' not in view
    _without_authority(view)


def test_host_raise_can_still_have_pending_work_and_unreleased_borrow_in_public_composition():
    program, model, values = invoke_work_execution(raised=True)
    unknown = Unresolved('work terminal/quiescence/release were not captured', model.activations[0].entry)
    model = replace(model, outcomes=(), quiescences=(),
                    retentions=tuple(replace(row, release=unknown) for row in model.retentions))
    index = _index(program, model, value_graphs=values)
    view = index.resource_composition()
    work, = view['lifecycle']['work']
    assert work['submission'] == model.submissions[0]
    assert work['actual_host_successor'].kind is ExitKind.RAISE
    assert work['actual_host_transfer'].successor_index == 1
    assert work['outcomes'] == work['quiescences'] == ()
    assert type(work['retentions'][0].release) is Unresolved
    host = next(row for row in view['routes']['operations']
                if row['occurrence'].id == work['submission'].origin.operation)
    assert host['after'] and all(value is None for value in host['after'].values())
    actual = next(row for row in view['routes']['transfers']
                  if row['transfer'] == work['actual_host_transfer'])
    assert actual['state'] and all(value is not None for value in actual['state'].values())
    assert view['inventory']['execution_counts']['submissions'] == 1
    assert view['inventory']['execution_counts']['outcomes'] == 0
    _without_authority(view)


def test_terminal_quiescence_borrow_release_handle_end_and_retirement_remain_distinct_records():
    program, model, values = ordinary_work_execution(retained='handle')
    retained, = model.retentions
    assert type(retained.target) is HandleTarget
    handle = next(row for row in model.handles if row.id == retained.target.binding)
    endpoint = OccurrencePoint(model.operations[-1].id, OccurrencePhase.AFTER)
    ended = replace(handle, end=EndedAt(endpoint, model.runs[0].source))
    unknown = Unresolved('declared target retirement has no native correspondence', model.activations[0].entry)
    retired = TargetLifetimeEvent(TargetLifetimeEventID('pipeline.retired'), handle.target,
        LifetimeEventKind.RETIRED, endpoint, unknown, None,
        ProviderFactReference(model.snapshot.artifact, '#declared-retirement'), model.runs[0].source)
    model = replace(model, handles=tuple(ended if row.id == ended.id else row for row in model.handles),
                    target_lifetime_events=(retired,))
    index = _index(program, model, value_graphs=values)
    view = index.resource_composition()
    work, = view['lifecycle']['work']
    outcome, = work['outcomes']
    quiet, = work['quiescences']
    borrow, = work['retentions']
    assert outcome.id == model.outcomes[0].id and outcome.quiescence == quiet.id
    assert type(borrow.release) is BorrowRelease and borrow.release.quiescence == quiet.id
    assert borrow.target.binding == ended.id
    assert next(row for row in view['lifecycle']['handles'] if row.id == ended.id).end == ended.end
    assert view['lifecycle']['target_lifetime_events'] == (retired,)
    assert type(borrow.release) is not type(ended.end)
    assert 'free' not in view['lifecycle'] and 'persisted' not in view['lifecycle']
    _without_authority(view)


def test_public_composition_keeps_two_calls_original_routes_and_detaches_once_at_boundary():
    program, model, _ = shared_calls_execution()
    index = _index(program, model)
    view = index.resource_composition()
    calls = view['routes']['calls']
    assert len(calls) == 2
    assert calls[0]['activation'].id != calls[1]['activation'].id
    for call, association in zip(calls, model.call_activations, strict=True):
        assert call['association'] == association and call['status'] == 'DECLARED'
        assert call['caller'].id == association.caller
        assert call['inputs'] and call['outputs']
        assert call['inputs'][0]['actual_definition'].id != call['outputs'][0]['callee_use_definition'].id
    observed = view['routes']['operations'][0]
    original_label = observed['definition'].label
    object.__setattr__(observed['definition'], 'label', 'mutated detached public result')
    assert index.resource_composition()['routes']['operations'][0]['definition'].label == original_label
    assert program.operations[0].label == original_label
    _without_authority(view)


def test_budget_one_keeps_entire_canonical_and_execution_inventory_and_exact_pending_cursors():
    program, model, values, payloads, _ = visibility_execution()
    index = _index(program, model, value_graphs=values, artifact_bytes=payloads)
    view = index.resource_composition(budget=1)
    assert view['status'] == 'TRUNCATED' and view['budget']['used'] == 1
    inventory = view['inventory']
    assert inventory['program'] == program and inventory['execution'] == model
    assert inventory['execution_counts'] == {field.name: len(getattr(model, field.name))
        for field in fields(model) if field.name != 'snapshot'}
    assert inventory['canonical_counts']['operations'] == len(program.operations)
    assert view['routes']['pending']['operations'] == len(model.operations)
    assert view['routes']['cursor'] is not None
    assert view['reads']['pending'] == len(model.content_reads)
    assert view['reads']['cursor'] is not None
    assert view['lifecycle']['pending_work'] == len(model.submissions)
    assert view['sources']['pending'] == len(model.source_inventories)
    assert view['gaps']
    _without_authority(view)


@pytest.mark.parametrize('kind', ('scalar', 'reference'))
def test_scalar_and_reference_observation_roots_do_not_create_content_reads_or_materializations(kind):
    program, model, semantics = observation_execution(output=True)
    identity = ValueOccurrenceID('activation.0.resource.fd' if kind == 'scalar'
                                 else 'activation.0.resource.handle')
    model = replace(model, observation_roots=(replace(model.observation_roots[0], actual=OutputValue(identity)),))
    scope = CompositionScope(model.observation_requirements[0].contract,
                             model.runs[0].id, model.runs[0].source)
    index = _index(program, model, semantic_graphs=semantics)
    view = index.resource_composition(scopes=(scope,))
    assert view['requested_scopes'] == (scope,)
    assert view['observations']['roots'] == model.observation_roots
    assert view['observations']['requirements'] == model.observation_requirements
    assert view['observations']['obligations']
    assert view['reads']['items'] == () and view['inventory']['execution_counts']['content_reads'] == 0
    assert view['lifecycle']['work'] == () and view['inventory']['execution_counts']['submissions'] == 0
    assert view['production']['writes'] == () and view['production']['outcome_productions'] == ()
    actual = next(row for row in view['routes']['values'] if row['value'].id == identity)
    assert actual['definition'].id.value == ('resource.fd' if kind == 'scalar' else 'resource.handle')
    assert view['inventory']['execution'].denotations == ()
    assert any('protocol' in gap.code or 'unverified' in gap.code for gap in view['gaps'])
    _without_authority(view)
