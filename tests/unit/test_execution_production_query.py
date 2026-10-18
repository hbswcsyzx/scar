"""Production inspection stays source-rooted and conditional under deletions."""
from dataclasses import replace
from copy import deepcopy

import pytest

from scar.ir.execution.content import VersionRef
from scar.ir.execution.coverage import RegionRef
from scar.ir.execution.ids import SourceBridgeID, WriteAssociationID
from scar.ir.execution.production import RawRecordRef, SourceEndpointBridge, SourceEndpointRef
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.snapshot import external_artifact
from scar.ir.execution.work import WorkOutcomeKind
from scar.ir.execution.work import MaterializationRef
from scar.ir.v2.evidence import EvidenceEndpoint, EvidenceNodeKind, EvidenceRelation
from scar.ir.v2.ids import LogicalValueID, MaterializationID, ProvenanceID, ValueVersionID
from scar.ir.v2.values import LogicalValue, Materialization, ProvenanceRecord, ProvenanceRelation, ValueVersion
from tests.fixtures.execution_production_queries import (
    native_production_query_fixture, production_query_fixture,
)


def _index(fixture):
    program, model, values, evidence, payloads, details = fixture
    return ExecutionIndex(model, program, value_graphs=values, evidence_graphs=evidence,
        semantic_graphs=details.get('semantic_graphs'), artifact_bytes=payloads)


def _query(fixture, **kwargs):
    return _index(fixture).production(fixture[-1]['read'], **kwargs)


def _codes(result):
    return {row['code'] for row in result['gaps']}


def _ids(result):
    return {row['id'] for row in result['candidates']}


def test_original_demand_and_source_candidates_are_detached_without_ready_authority():
    fixture = production_query_fixture(observed_write=True)
    result = _query(fixture)
    assert result['read'] == fixture[1].content_reads[0]
    assert result['demand']['version'] == fixture[-1]['version']
    assert {row['relation'] for row in result['candidates']} >= {'produces', 'observed_write', 'raw_record'}
    assert result['current_production'][0]['write_associations'][0]['row'] == fixture[1].writes[0]
    assert result['lineage_prerequisites'][0]['is_demand']
    assert not result['source_runtime_verified'] and not result['readiness_verified']
    assert not result['transformation_authorized'] and not result['truncated']
    result['candidates'][0]['conditions'] += ('caller edit',)
    assert 'caller edit' not in _query(fixture)['candidates'][0]['conditions']


@pytest.mark.parametrize('remove_work', (False, True))
def test_removing_produced_writes_and_even_work_cannot_shrink_raw_candidate_universe(remove_work):
    fixture = native_production_query_fixture()
    initial = _query(fixture)
    program, model, values, evidence, payloads, details = fixture
    changes = {'writes': (), 'produced': ()}
    if remove_work:
        changes.update(submissions=(), outcomes=(), retentions=(), quiescences=(), queue_prefixes=())
    deleted = (program, replace(model, **changes), values, evidence, payloads, details)
    result = _query(deleted)
    assert _ids(initial) == _ids(result) and initial['current_production']
    assert not result['current_production']
    assert 'production_write_join_missing' in _codes(result)
    assert all('missing_exact_write_join' in row['conditions'] for row in result['candidates'])


def test_source_edge_inventory_survives_deleting_all_host_associations():
    fixture = production_query_fixture()
    initial = _query(fixture)
    program, model, *rest = fixture
    result = _query((program, replace(model, writes=()), *rest))
    assert _ids(initial) == _ids(result)
    assert not result['current_production'] and 'production_write_join_missing' in _codes(result)


@pytest.mark.parametrize('kind', (WorkOutcomeKind.COMPLETED, WorkOutcomeKind.FAILED, WorkOutcomeKind.CANCELLED))
def test_native_partial_results_remain_exact_under_failure_or_cancel(kind):
    result = _query(native_production_query_fixture(kind=kind, requested=8, written=4))
    raw, = (row for row in result['candidates'] if row['relation'] == 'raw_native_result')
    produced, = raw['outcome_productions']
    assert produced['actual'].shape == (4,) and produced['requested'].shape == (8,)
    assert produced['outcome'].kind is kind and produced['rawprofile']['written_bytes'] == 4
    assert result['current_production'] and not result['readiness_verified']


def test_missing_inventory_never_becomes_an_empty_satisfied_writer_set():
    fixture = production_query_fixture(write=False)
    program, model, *rest = fixture
    result = _query((program, replace(model, source_inventories=()), *rest))
    assert not result['candidates'] and 'production_inventory_missing' in _codes(result)
    assert not result['readiness_verified']


def test_missing_index_leaves_a_pending_source_even_without_graph_projection():
    fixture = production_query_fixture(write=False)
    fixture[4].pop(fixture[1].source_inventories[0].index.sha256)
    result = _query(fixture)
    assert result['pending_sources'] and 'production_inventory_pending' in _codes(result)
    assert not result['readiness_verified']


def test_same_bundle_identity_is_used_but_cross_scope_bridge_remains_conditional():
    fixture = production_query_fixture(write=False)
    program, model, values, evidence, payloads, details = fixture
    edge = details['produce_edges'][0]
    endpoint = SourceEndpointRef(details['source_ref'], edge.target)
    bridge = SourceEndpointBridge(SourceBridgeID('explicit'), endpoint, details['version'], model.runs[0].source)
    result = _query((program, replace(model, source_bridges=(bridge,)), values, evidence, payloads, details))
    candidate, = (row for row in result['candidates'] if row['relation'] == 'produces')
    assert candidate['endpoints'][0]['resolved']['values_artifact'] == details['source'].values_artifact
    assert candidate['endpoints'][0]['bridges'][0]['row'] == bridge
    assert 'lineage_prerequisite' in candidate['relevance']
    assert 'endpoint_bridge_runtime_unverified' in candidate['conditions']
    assert not result['current_production'] and not result['readiness_verified']


def test_multiple_bridges_are_all_preserved_instead_of_choosing_the_first():
    fixture = production_query_fixture(write=False)
    program, model, values, evidence, payloads, details = fixture
    endpoint = SourceEndpointRef(details['source_ref'], details['produce_edges'][0].target)
    bridges = tuple(SourceEndpointBridge(SourceBridgeID('bridge.' + str(i)), endpoint, target, model.runs[0].source)
                    for i, target in enumerate((details['version'], details['other_version'])))
    result = _query((program, replace(model, source_bridges=bridges), values, evidence, payloads, details))
    candidate, = (row for row in result['candidates'] if row['relation'] == 'produces')
    assert len(candidate['endpoints'][0]['bridges']) == 2
    assert 'production_bridge_ambiguous' in _codes(result)


def test_overlapping_allocation_is_a_possible_invalidator_even_for_another_version():
    fixture = production_query_fixture(write=False)
    program, model, values, evidence, payloads, details = fixture
    endpoint = SourceEndpointRef(details['source_ref'], details['produce_edges'][0].target)
    # Region correspondence gives a spatial route without asserting a version.
    bridge = SourceEndpointBridge(SourceBridgeID('region.alias'), endpoint,
        model.content_reads[0].placement.selector, model.runs[0].source)
    result = _query((program, replace(model, source_bridges=(bridge,)), values, evidence, payloads, details))
    candidate, = (row for row in result['candidates'] if row['relation'] == 'produces')
    assert candidate['id'] in result['possible_invalidators']
    assert 'lineage_prerequisite' not in candidate['relevance']
    assert not result['current_production']


def test_unsupported_alias_event_is_retained_raw_not_invented_as_an_eeg_relation():
    result = _query(production_query_fixture(raw_kind='opaque_alias', write=False, native=True))
    raw, = (row for row in result['candidates'] if row['relation'] == 'raw_native_result')
    assert raw['original'].payload['kind'] == 'opaque_alias'
    assert not any(row['relation'] in ('aliases', 'overwrites') for row in result['candidates'])
    assert 'raw_effect_or_selector_mapping_unresolved' in raw['conditions']


def test_same_raw_stage_production_and_placement_group_duplicate_facts_only():
    fixture = production_query_fixture(observed_write=True)
    program, model, values, evidence, payloads, details = fixture
    raw = details['source'].raw_records[0]
    stage = RawRecordRef(details['source_ref'], raw.line, raw.sha256)
    edge = details['produce_edges'][0]
    from scar.ir.execution.production import SourceEdgeRef
    first = replace(model.writes[0], stage=stage, evidence=(SourceEdgeRef(details['source_ref'], edge.edge_id),))
    second = replace(first, id=WriteAssociationID('same.physical.stage'))
    result = _query((program, replace(model, writes=(first, second)), values, evidence, payloads, details))
    group, = result['current_production']
    assert len(group['write_associations']) == 2
    assert len(group['candidates']) == 2  # exact raw stage and exact declared source edge
    assert not result['readiness_verified']


def test_distinct_observed_result_stages_cannot_merge_on_same_host_or_placement():
    fixture = production_query_fixture(outputs=2)
    program, model, values, evidence, payloads, details = fixture
    from scar.ir.execution.production import SourceEdgeRef
    second = replace(model.writes[0], id=WriteAssociationID('second.stage'),
        stage=SourceEdgeRef(details['source_ref'], details['produce_edges'][1].edge_id))
    result = _query((program, replace(model, writes=(*model.writes, second)), values, evidence, payloads, details))
    assert len(result['current_production']) == 2
    assert 'production_duplicate_stage_unresolved' in _codes(result)


def test_other_version_same_scoped_allocation_is_not_a_current_production_group():
    fixture = production_query_fixture()
    program, model, values, evidence, payloads, details = fixture
    original_artifact = details['version'].artifact
    graph = deepcopy(values[original_artifact.sha256])
    mat = graph.materializations[details['materialization'].materialization]
    other_mat = MaterializationID('other.version.mat')
    graph.add_materialization(Materialization(other_mat, details['other_version'].version,
                                             mat.representation, mat.device, mat.region))
    artifact = external_artifact(graph)
    read = replace(model.content_reads[0], placement=replace(model.content_reads[0].placement,
        materialization=replace(model.content_reads[0].placement.materialization, artifact=artifact),
        selector=replace(model.content_reads[0].placement.selector, artifact=artifact)))
    denotation = replace(model.denotations[0], identity=replace(model.denotations[0].identity,
        version=VersionRef(artifact, details['version'].version)))
    write = replace(model.writes[0], placement=replace(read.placement,
        materialization=MaterializationRef(artifact, other_mat)))
    result = _query((program, replace(model, content_reads=(read,), denotations=(denotation,), writes=(write,)),
        {artifact.sha256: graph}, evidence, payloads, details))
    assert not result['current_production']
    assert result['possible_invalidators']
    source, = (row for row in result['candidates'] if row['relation'] == 'produces')
    assert source['write_associations'] and not source['current_write_associations']


def test_lineage_parents_are_prerequisites_not_current_materialization_and_writers():
    fixture = production_query_fixture(write=False)
    program, model, values, evidence, payloads, details = fixture
    graph = values[details['version'].artifact.sha256]
    logical = LogicalValueID('parent.logical')
    parent = ValueVersionID(logical, 0)
    graph.add_logical_value(LogicalValue(logical, 'bytes'))
    graph.add_version(ValueVersion(parent))
    provenance_id = ProvenanceID('parent.transform')
    row = graph.versions[details['version'].version]
    row.parent_versions = (parent,)
    row.provenance_id = provenance_id
    graph.add_provenance(ProvenanceRecord(provenance_id, ProvenanceRelation.TRANSFORM,
        (parent,), (row.id,)))
    artifact = external_artifact(graph)
    read = replace(model.content_reads[0], placement=replace(model.content_reads[0].placement,
        materialization=replace(model.content_reads[0].placement.materialization, artifact=artifact),
        selector=replace(model.content_reads[0].placement.selector, artifact=artifact)))
    denotation = replace(model.denotations[0], identity=replace(model.denotations[0].identity,
        version=VersionRef(artifact, row.id)))
    result = _query((program, replace(model, content_reads=(read,), denotations=(denotation,)),
        {artifact.sha256: graph}, evidence, payloads, details))
    assert {row['version'].version for row in result['lineage_prerequisites']} == {row.id, parent}
    assert not result['current_production']


def test_public_query_rechecks_changed_source_graph_and_detaches_returned_nodes():
    fixture = production_query_fixture()
    details = fixture[-1]
    source = details['source']
    fixture[2][source.values_artifact.sha256] = source.bundle.values
    index = _index(fixture)
    result = index.production(details['read'])
    original = next(row for row in result['candidates'] if row['relation'] == 'produces')['endpoints'][0]['resolved']
    original['source'].bundle.values.versions.clear()
    assert index.production(details['read'])['candidates']
    source.bundle.values.versions.clear()
    with pytest.raises(ValueError, match='external_'):
        index.production(details['read'])


@pytest.mark.parametrize('budget', (1, 5, 17))
def test_budget_caps_all_traversal_and_keeps_truncation_explicit(budget):
    fixture = production_query_fixture(outputs=8)
    result = _query(fixture, budget=budget)
    assert result['budget_used'] <= budget and sum(result['budget_costs'].values()) == result['budget_used']
    assert result['truncated'] and 'production_budget' in _codes(result)
    assert not result['readiness_verified']


@pytest.mark.parametrize('budget,error', ((True, TypeError), (0, ValueError), (-1, ValueError), ('4', TypeError)))
def test_budget_contract_rejects_boolean_or_invalid_limits(budget, error):
    with pytest.raises(error):
        _query(production_query_fixture(write=False), budget=budget)


def test_observation_root_uses_its_original_consumer_run_without_fake_work_ticket():
    result = _query(production_query_fixture(observation=True, write=False))
    assert result['demand']['run'] is not None and result['candidates']
    assert not result['current_production'] and not result['readiness_verified']
