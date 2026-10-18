"""Source-bound AND/OR support through real canonical execution fixtures."""
from copy import deepcopy
from dataclasses import replace

import pytest

from scar.ir.execution.common import Unresolved
from scar.ir.execution.content import EndpointContent, ProtocolSelector
from scar.ir.execution.ids import ContributionSupportID
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.resources import AllocationTarget
from scar.ir.execution.snapshot import external_artifact
from scar.ir.execution.validity import CompletedVisibility, OrderedVisibility, QueueDomain
from scar.ir.execution.work import MaterializationRef, WorkOutcomeKind
from scar.ir.v2.ids import MaterializationID
from scar.ir.v2.values import Materialization
from tests.fixtures.execution_visibility_graphs import visibility_execution


def _index(fixture):
    program, model, values, payloads, _ = fixture
    return ExecutionIndex(model, program, value_graphs=values, artifact_bytes=payloads)


def _query(fixture, **kwargs):
    return _index(fixture).validity(fixture[-1]['read'], **kwargs)


def _status(result):
    return result['conditional_support']['status']


def test_completed_left_and_pending_ordered_right_match_without_claiming_actual_full_production():
    fixture = visibility_execution()
    result = _query(fixture)
    assert _status(result) == 'MATCHED', result['budget_costs']
    assert result['known_fragment_coverage']['status'] == 'INCOMPLETE'
    assert result['conditional_fragment_coverage']['status'] == 'COVERED'
    portions = result['conditional_support']['portions']
    assert [portion['portion']['interval'] for portion in portions] == [(0, 4), (4, 8)]
    assert len(portions[0]['alternatives']) == len(portions[1]['alternatives']) == 1
    assert not portions[0]['alternatives'][0]['pending']
    assert portions[1]['alternatives'][0]['pending']
    left, right = result['contributions']
    assert type(left['alternatives'][0]['visibility']) is CompletedVisibility
    assert type(right['alternatives'][0]['visibility']) is OrderedVisibility
    assert left['actual'] == fixture[-1]['left'] and right['actual'] == fixture[-1]['right']
    assert result['source_reconciliation']['status'] == 'OPEN'
    assert result['source_reconciliation']['known_joins'] == 'MATCHED'
    assert result['validity_conditions']
    assert not result['source_runtime_verified'] and not result['runtime_visibility_verified']
    assert not result['transformation_authorized']


def test_two_actual_partial_results_cover_whole_only_after_each_own_support_matches():
    result = _query(visibility_execution(right_terminal=True))
    assert _status(result) == 'MATCHED'
    assert result['known_fragment_coverage']['status'] == 'COVERED'
    assert result['conditional_fragment_coverage']['status'] == 'COVERED'
    assert not any(fragment['pending'] for fragment in result['contributions'])


def test_missing_right_support_does_not_borrow_left_completed_evidence():
    result = _query(visibility_execution(missing_right_support=True))
    assert _status(result) == 'MISSING'
    assert result['conditional_fragment_coverage']['status'] == 'INCOMPLETE'
    empty, = (item for item in result['conditional_fragment_coverage']['portions'] if not item['labels'])
    assert empty['interval'] == (4, 8)
    assert len(result['source_reconciliation']['candidate_ids']) == 2


def test_missing_wait_to_consumer_start_does_not_become_ordered_visibility():
    result = _query(visibility_execution(with_wait=False))
    assert _status(result) == 'MISSING'
    assert not any(item['status'] == 'MATCHED' for fragment in result['contributions']
                   for item in fragment['alternatives'])


@pytest.mark.parametrize('kind', (WorkOutcomeKind.COMPLETED, WorkOutcomeKind.FAILED, WorkOutcomeKind.CANCELLED))
def test_known_terminal_short_result_cannot_use_requested_tail_through_order(kind):
    result = _query(visibility_execution(right_terminal=True, right_written=2, right_kind=kind))
    assert _status(result) == 'MISSING'
    assert result['known_fragment_coverage']['status'] == 'INCOMPLETE'
    assert result['conditional_fragment_coverage']['status'] == 'INCOMPLETE'
    right = next(row for row in result['contributions'] if row['write'].id.value == 'right')
    assert not right['pending']
    assert right['production']['outcome'].kind is kind
    assert right['production']['actual'].shape == (2,)
    assert any(item['interval'] == (6, 8) and not item['labels']
               for item in result['conditional_fragment_coverage']['portions'])


def test_terminal_result_cannot_be_bypassed_by_none_pending_support():
    fixture = visibility_execution(right_terminal=True, right_written=2)
    program, model, *rest = fixture
    supports = tuple(replace(row, production=None) if row.id.value == 'right' else row
                     for row in model.contribution_supports)
    with pytest.raises(ValueError, match='validity_support_terminal_actual'):
        _index((program, replace(model, contribution_supports=supports), *rest))


def test_deleting_known_outcome_does_not_turn_independent_source_short_result_into_future_whole_write():
    fixture = visibility_execution(right_terminal=True, right_written=2)
    before = _query(fixture)
    program, model, *rest = fixture
    deleted = replace(model,
        outcomes=tuple(row for row in model.outcomes if row.id.value != 'right'),
        produced=tuple(row for row in model.produced if row.id.value != 'right'),
        contribution_supports=tuple(replace(row, production=None) if row.id.value == 'right' else row
                                    for row in model.contribution_supports))
    result = _query((program, deleted, *rest))
    assert _status(result) == 'MISSING'
    assert result['conditional_fragment_coverage']['status'] != 'COVERED'
    assert result['source_reconciliation']['candidate_ids'] == before['source_reconciliation']['candidate_ids']
    right = next(row for row in result['contributions'] if row['write'].id.value == 'right')
    assert not right['pending'] and right['source_result']['blocked']
    assert any('source' in condition and 'result' in condition for condition in right['conditions'])


def test_wrong_actual_consumer_queue_is_a_structural_domain_error():
    fixture = visibility_execution()
    program, model, *rest = fixture
    left = model.contribution_supports[0]
    queue = next(row for row in model.resources if row.id.value == 'order.qa')
    wrong = replace(left, visibility=replace(left.visibility, domain=QueueDomain(queue.id)))
    with pytest.raises(ValueError, match='validity_queue_domain'):
        _index((program, replace(model, contribution_supports=(wrong, *model.contribution_supports[1:])), *rest))


def test_missing_alternative_does_not_poison_matching_alternative_on_exact_same_fragment():
    fixture = visibility_execution()
    program, model, *rest = fixture
    left = model.contribution_supports[0]
    missing = replace(left, id=ContributionSupportID('left.unsupported'),
        visibility=replace(left.visibility, basis=Unresolved('no exact establishing basis', model.activations[0].entry)))
    result = _query((program, replace(model, contribution_supports=(missing, *model.contribution_supports)), *rest))
    assert _status(result) == 'MATCHED'
    left_fragment = next(row for row in result['contributions'] if row['write'].id.value == 'left')
    assert {row['status'] for row in left_fragment['alternatives']} == {'MATCHED', 'MISSING'}


def test_unused_other_version_candidate_does_not_poison_valid_covering_combination():
    result = _query(visibility_execution(old_version=True))
    assert _status(result) == 'MATCHED'
    old = next(row for row in result['contributions'] if row['write'].id.value == 'old')
    assert not old['content_match']
    assert old['label'] not in {label for portion in result['conditional_fragment_coverage']['portions']
                               for label in portion['labels']}
    assert len(result['source_reconciliation']['candidate_ids']) == 3
    source = next(row for row in result['source_universe']['candidates']
                  if any(write['row'].id.value == 'old' for write in row['write_associations']))
    assert any(type(item.get('original')) is dict and item['original'].get('id') == source['id']
        for fragment in result['contributions'] if fragment['content_match']
        for kind in ('invalidators', 'potential_invalidators', 'exclusions')
        for item in fragment['stability'][kind])


def test_actual_alias_overwrite_of_needed_fragment_blocks_its_otherwise_matching_support():
    result = _query(visibility_execution(right_terminal=True, right_alias=True))
    assert result['known_fragment_coverage']['status'] == 'COVERED'
    assert _status(result) == 'CONTRADICTED'
    assert result['invalidators']
    left = next(row for row in result['contributions'] if row['write'].id.value == 'left')
    assert any(item['status'] == 'MATCHED' for item in left['alternatives'])
    assert left['stability']['status'] == 'CONTRADICTED'
    assert left['status'] == 'CONTRADICTED'


def test_repaired_left_with_historical_blocked_left_does_not_turn_missing_right_into_contradiction():
    fixture = visibility_execution(right_terminal=True, right_alias=True)
    program, model, values, payloads, details = fixture
    wanted = next(row.placement.materialization for row in model.writes if row.id.value == 'left')
    # P1's earlier wanted left is clobbered by r1's fresh wanted left, which
    # has its own exact actual result and wait-to-C support. Nothing
    # establishes the demand's right half. Preserve both independent sources.
    model = replace(model,
        writes=tuple(replace(row, placement=replace(row.placement, materialization=wanted))
                     if row.id.value == 'right' else row for row in model.writes),
        content_reads=(replace(model.content_reads[0], placement=replace(
            model.content_reads[0].placement, selector=details['whole'])),))
    # The default bounded query may report TRUNCATED on two complete overlapping
    # protection scans. Give this status-regression enough budget to finish;
    # keep the product default and every existing default-budget case unchanged.
    result = _query((program, model, values, payloads, details), budget=8192)
    assert not result['truncated'] and result['budget_used'] <= 8192
    assert _status(result) == 'MISSING', result['budget_costs']
    assert result['conditional_fragment_coverage']['status'] == 'INCOMPLETE'
    assert result['conditional_support']['blocked_portions'] == ()
    fragments = {row['write'].id.value: row for row in result['contributions']}
    assert fragments['left']['status'] == 'CONTRADICTED'
    assert fragments['right']['status'] == 'MATCHED'
    assert any(portion['interval'] == (4, 8) and not portion['labels']
               for portion in result['conditional_fragment_coverage']['portions'])
    assert len(result['source_reconciliation']['candidate_ids']) == 2


def test_uninterpreted_endpoint_actual_to_mat_join_cannot_borrow_byte_geometry_for_known_or_conditional_cover():
    fixture = visibility_execution()
    program, model, values, payloads, details = fixture
    left = next(row for row in model.writes if row.id.value == 'left')
    graph = deepcopy(values[details['artifact'].sha256])
    mat = graph.materializations[left.placement.materialization.materialization]
    endpoint_mat = MaterializationID('visibility.endpoint')
    # A genuine unbacked endpoint materialization has the same scoped logical
    # version, but no interpreted relation from its selector to these bytes.
    # A storage Mat cannot simply be relabeled as endpoint-backed content.
    graph.add_materialization(Materialization(endpoint_mat, mat.value_version, 'opaque endpoint', 'cpu'))
    artifact = external_artifact(graph)
    target = AllocationTarget(artifact, graph.regions[details['left'].region].allocation)
    endpoint = EndpointContent(MaterializationRef(artifact, endpoint_mat), target,
                               ProtocolSelector(model.submissions[0].protocol))
    region = lambda ref: replace(ref, artifact=artifact)
    read = model.content_reads[0]
    model = replace(model,
        writes=tuple(replace(row, placement=endpoint if row.id == left.id else replace(row.placement,
            materialization=replace(row.placement.materialization, artifact=artifact),
            selector=region(row.placement.selector))) for row in model.writes),
        produced=tuple(replace(row, actual=region(row.actual)) for row in model.produced),
        content_reads=(replace(read, placement=replace(read.placement,
            materialization=replace(read.placement.materialization, artifact=artifact),
            selector=region(details['left']))),))
    result = _query((program, model, {artifact.sha256: graph}, payloads, details))
    fragment = next(row for row in result['contributions'] if row['write'].id == left.id)
    assert fragment['content_match'] and fragment['production']['actual'].shape == (4,)
    assert fragment['actual'] == region(details['left'])  # exactly the read's byte selector
    assert fragment['placement_match'] is None and fragment['status'] == 'MISSING'
    assert any('actual-to-write' in condition for condition in fragment['conditions'])
    assert _status(result) == 'MISSING'
    assert result['known_fragment_coverage']['status'] != 'COVERED'
    assert result['conditional_fragment_coverage']['status'] != 'COVERED'
    assert all(fragment['label'] not in portion['labels']
               for portion in result['conditional_fragment_coverage']['portions'])


@pytest.mark.parametrize('remove_work', (False, True))
def test_removing_right_associations_keeps_original_source_obligation_instead_of_empty_and(remove_work):
    fixture = visibility_execution()
    original = _query(fixture)
    program, model, *rest = fixture
    deleted = replace(model, writes=tuple(row for row in model.writes if row.id.value != 'right'),
        contribution_supports=tuple(row for row in model.contribution_supports if row.id.value != 'right'))
    if remove_work:
        ticket = next(row.writer.ticket for row in model.writes if row.id.value == 'right')
        prefix = next(row.id for row in model.queue_prefixes if row.work == ticket)
        deleted = replace(deleted,
            submissions=tuple(row for row in deleted.submissions if row.id != ticket),
            queue_prefixes=tuple(replace(row, previous=Unresolved('deleted predecessor work; queue prefix is partial',
                                                                 model.activations[0].entry))
                                 if row.previous == prefix else row
                                 for row in deleted.queue_prefixes if row.id != prefix),
            event_records=tuple(row for row in deleted.event_records if row.marker != ticket),
            queue_waits=())
    result = _query((program, deleted, *rest))
    assert result['source_reconciliation']['candidate_ids'] == original['source_reconciliation']['candidate_ids']
    assert result['source_reconciliation']['known_joins'] == 'MISSING'
    assert _status(result) == 'MISSING'


def test_one_shared_budget_caps_source_geometry_order_and_threat_scans():
    result = _query(visibility_execution(), budget=128)
    assert result['truncated'] and _status(result) == 'TRUNCATED'
    assert result['budget_used'] <= 128
    assert sum(result['budget_costs'].values()) == result['budget_used']
    assert result['budget_costs']['production_query'] > 0
    assert result['gaps']


def test_query_rechecks_external_catalog_and_returns_detached_original_facts():
    fixture = visibility_execution()
    index = _index(fixture)
    first = index.validity(fixture[-1]['read'])
    first['contributions'][0]['production']['actual'].shape = (0,)
    assert _status(index.validity(fixture[-1]['read'])) == 'MATCHED'
    graph = fixture[2][fixture[-1]['artifact'].sha256]
    graph.regions[fixture[-1]['left'].region].shape = (0,)
    with pytest.raises(ValueError, match='external_'):
        index.validity(fixture[-1]['read'])
