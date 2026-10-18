"""Original MatRef queries share geometry without granting content/ready proof."""
from dataclasses import replace

import pytest

from scar.ir.execution.coverage import CoverageStatus
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.snapshot import external_artifact
from scar.ir.execution.work import MaterializationRef
from scar.ir.v2.ids import LogicalValueID, MaterializationID, StorageAllocationID, StorageRegionID, ValueVersionID
from scar.ir.v2.values import LogicalValue, Materialization, StorageAllocation, StorageRegion, ValueGraph, ValueVersion
from tests.fixtures.execution_resource_graphs import resource_execution_program


def _fixture():
    program, model = resource_execution_program(activations=1)
    graph = ValueGraph()
    logical = LogicalValueID('query.bytes')
    graph.add_logical_value(LogicalValue(logical, 'bytes'))
    for revision in (0, 1):
        graph.add_version(ValueVersion(ValueVersionID(logical, revision)))
    allocation = StorageAllocationID('query.bytes')
    graph.add_allocation(StorageAllocation(allocation, 'cpu', 8))
    for name, offset, shape, strides in (
        ('required', 0, (8,), (1,)), ('left', 0, (4,), (1,)),
        ('right', 4, (4,), (1,)), ('even', 0, (4,), (2,)),
        ('odd', 1, (4,), (2,)), ('empty', 0, (0,), (0,))):
        region = StorageRegionID(name)
        graph.add_region(StorageRegion(region, allocation, offset, shape, strides, 'uint8', 'cpu'))
        graph.add_materialization(Materialization(MaterializationID(name), ValueVersionID(logical, 0),
            'bytes', 'cpu', region))
    graph.add_materialization(Materialization(MaterializationID('new-version'), ValueVersionID(logical, 1),
        'bytes', 'cpu', StorageRegionID('required')))
    graph.add_materialization(Materialization(MaterializationID('endpoint'), ValueVersionID(logical, 0),
        'protocol-bytes', 'cpu', None))
    artifact = external_artifact(graph, uri='unavailable:query-does-not-open-artifact')
    refs = {name.value: MaterializationRef(artifact, name) for name in graph.materializations}
    return program, model, graph, refs, {artifact.sha256: graph}


def test_public_matref_query_uses_union_and_preserves_strided_holes():
    program, model, _, refs, catalog = _fixture()
    index = ExecutionIndex(model, program, value_graphs=catalog)
    assert index.materialization_coverage(refs['required'], (refs['left'], refs['right']))['status'] == 'COVERED'
    holes = index.materialization_coverage(refs['required'], (refs['even'],))
    assert holes['status'] == 'INCOMPLETE'
    assert holes['geometry'].missing_intervals == ((1, 2), (3, 4), (5, 6), (7, 8))
    assert index.materialization_coverage(refs['required'], (refs['even'], refs['odd']))['status'] == 'COVERED'


def test_unknown_offered_endpoint_cannot_be_erased_to_assert_missing_bytes():
    program, model, _, refs, catalog = _fixture()
    index = ExecutionIndex(model, program, value_graphs=catalog)
    result = index.materialization_coverage(refs['required'], (refs['left'], refs['endpoint']))
    assert result['status'] == 'UNRESOLVED'
    assert refs['endpoint'] in result['unmapped']
    assert result['geometry'].status is CoverageStatus.UNRESOLVED
    assert result['geometry'].missing_intervals is None
    assert any(gap.code == 'materialization_region_unresolved' for gap in result['gaps'])
    # Geometry of a sufficient known subset is monotone, but gives no ready fact.
    covered = index.materialization_coverage(refs['required'], (refs['required'], refs['endpoint']))
    assert covered['status'] == 'COVERED' and covered['unmapped']
    assert not covered['source_runtime_verified'] and not covered['transformation_authorized']


def test_region_none_required_is_not_storage_even_when_offers_or_payload_are_empty():
    program, model, _, refs, catalog = _fixture()
    index = ExecutionIndex(model, program, value_graphs=catalog)
    assert index.materialization_coverage(refs['endpoint'], ())['status'] == 'UNRESOLVED'
    empty = index.materialization_coverage(refs['empty'], ())
    assert empty['status'] == 'COVERED' and empty['geometry'].covered_intervals == ()
    assert 'ready' not in empty and 'free' not in empty


def test_geometry_can_match_different_versions_without_proving_content_equivalence():
    program, model, _, refs, catalog = _fixture()
    result = ExecutionIndex(model, program, value_graphs=catalog).materialization_coverage(
        refs['required'], (refs['new-version'],))
    assert result['status'] == 'COVERED'
    before, after = (row['materialization'].value_version for row in result['resolved'])
    assert before != after
    assert not result['source_runtime_verified'] and not result['transformation_authorized']
    assert not {'ready', 'free', 'equal_content', 'same_version'}.intersection(result)


def test_public_query_revalidates_mutable_catalog_on_every_call():
    program, model, graph, refs, catalog = _fixture()
    index = ExecutionIndex(model, program, value_graphs=catalog)
    assert index.materialization_coverage(refs['required'], (refs['required'],))['status'] == 'COVERED'
    graph.logical_values[next(iter(graph.logical_values))].description = 'changed after first query'
    with pytest.raises(ValueError, match='hash|snapshot|match'):
        index.materialization_coverage(refs['required'], (refs['required'],))


def test_returned_original_materialization_records_are_detached():
    program, model, graph, refs, catalog = _fixture()
    index = ExecutionIndex(model, program, value_graphs=catalog)
    result = index.materialization_coverage(refs['required'], (refs['required'],))
    result['resolved'][0]['materialization'].representation = 'forged'
    assert graph.materializations[refs['required'].materialization].representation == 'bytes'
    assert index.materialization_coverage(refs['required'], (refs['required'],))['resolved'][0]['materialization'].representation == 'bytes'


def test_missing_graph_remains_unresolved_without_opening_artifact_uri():
    program, model, _, refs, _ = _fixture()
    result = ExecutionIndex(model, program).materialization_coverage(refs['required'], (refs['left'],))
    assert result['status'] == 'UNRESOLVED' and result['geometry'] is None
    assert any(gap.code == 'external_graph_unavailable' for gap in result['gaps'])


@pytest.mark.parametrize('wrong', ['missing-materialization', 'snapshot-size', 'wrong-family'])
def test_known_bad_matref_or_supplied_snapshot_is_rejected(wrong):
    program, model, _, refs, catalog = _fixture()
    required = refs['required']
    if wrong == 'missing-materialization':
        required = replace(required, materialization=MaterializationID('absent'))
    elif wrong == 'snapshot-size':
        required = replace(required, artifact=replace(required.artifact, size_bytes=required.artifact.size_bytes + 1))
    else:
        from scar.ir.v2.evidence import EvidenceGraph
        catalog = {required.artifact.sha256: EvidenceGraph()}
    with pytest.raises(ValueError):
        ExecutionIndex(model, program, value_graphs=catalog).materialization_coverage(required, ())


def test_query_budget_is_shared_with_materialization_resolution_and_truncates():
    program, model, _, refs, catalog = _fixture()
    index = ExecutionIndex(model, program, value_graphs=catalog)
    result = index.materialization_coverage(refs['required'], (refs['left'], refs['right']), budget=1)
    assert result['status'] == 'UNRESOLVED' and result['budget_used'] <= 1
    assert any(gap.code == 'geometry_budget_exhausted' for gap in result['gaps'])
    with pytest.raises(ValueError):
        index.materialization_coverage(refs['required'], (), budget=True)
    with pytest.raises(TypeError):
        index.materialization_coverage(refs['required'], [refs['required']])
