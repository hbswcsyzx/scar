"""Byte labels preserve exact contributions without creating value proofs."""
import pytest

from scar.ir.execution.coverage import (
    RegionRef, _ValueCatalog, _labeled_storage_coverage, labeled_storage_coverage,
)
from scar.ir.execution.snapshot import external_artifact
from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.v2.ids import StorageAllocationID, StorageRegionID
from scar.ir.v2.values import StorageAllocation, StorageRegion, ValueGraph


def _fixture(*rows, nbytes=32):
    graph = ValueGraph()
    allocation = StorageAllocationID('labels.alloc')
    graph.add_allocation(StorageAllocation(allocation, 'cpu', nbytes))
    for name, offset, shape, strides in rows:
        graph.add_region(StorageRegion(StorageRegionID(name), allocation, offset,
                                       shape, strides, 'uint8', 'cpu'))
    artifact = external_artifact(graph)
    refs = {name: RegionRef(artifact, StorageRegionID(name)) for name, *_ in rows}
    return graph, artifact, refs


def _call(fixture, offers, **kwargs):
    graph, artifact, refs = fixture
    return labeled_storage_coverage(refs['required'], tuple((label, refs[name]) for label, name in offers),
                                    value_graphs={artifact.sha256: graph}, **kwargs)


def test_disjoint_halves_keep_their_own_labels_instead_of_cross_pairing_support():
    fixture = _fixture(('required', 0, (8,), (1,)), ('left', 0, (4,), (1,)), ('right', 4, (4,), (1,)))
    result = _call(fixture, (('A-completed', 'left'), ('B-ordered', 'right')))
    assert result['status'] == 'COVERED'
    assert [(item['interval'], item['labels']) for item in result['portions']] == [
        ((0, 4), ('A-completed',)), ((4, 8), ('B-ordered',))]
    assert not result['source_runtime_verified'] and not result['transformation_authorized']


def test_overlap_adds_or_labels_only_where_both_original_selectors_apply():
    fixture = _fixture(('required', 0, (8,), (1,)), ('first', 0, (6,), (1,)), ('second', 4, (4,), (1,)))
    result = _call(fixture, (('A', 'first'), ('B', 'second')))
    assert [(item['interval'], item['labels']) for item in result['portions']] == [
        ((0, 4), ('A',)), ((4, 6), ('A', 'B')), ((6, 8), ('B',))]


def test_stride_holes_remain_uncovered_and_required_holes_are_not_invented():
    fixture = _fixture(('required', 0, (7,), (1,)), ('even', 0, (4,), (2,)))
    result = _call(fixture, (('A', 'even'),))
    assert result['status'] == 'INCOMPLETE'
    assert {item['interval'] for item in result['portions'] if not item['labels']} == {(1, 2), (3, 4), (5, 6)}
    fixture = _fixture(('required', 0, (4,), (2,)), ('all', 0, (7,), (1,)))
    assert [item['interval'] for item in _call(fixture, (('A', 'all'),))['portions']] == [(0, 1), (2, 3), (4, 5), (6, 7)]


def test_exact_huge_strided_ref_remains_symbolic_not_empty_or_enumerated(monkeypatch):
    fixture = _fixture(('required', 0, (10**100,), (2,)), nbytes=2 * 10**100)
    monkeypatch.setattr('scar.ir.execution.coverage._byte_intervals',
                        lambda *args, **kwargs: pytest.fail('exact symbolic witness must not enumerate'))
    result = _call(fixture, (('A', 'required'),), budget=512)
    assert result['status'] == 'COVERED' and result['symbolic_whole'] == ('A',)
    assert result['portions'] == ({'selector': fixture[-1]['required'], 'interval': None,
                                  'labels': ('A',), 'symbolic': True},)


def test_empty_zero_stride_is_covered_without_any_phantom_labeled_bytes():
    fixture = _fixture(('required', 10**20, (0,), (0,)), nbytes=0)
    result = _call(fixture, ())
    assert result['status'] == 'COVERED' and result['portions'] == ()


def test_preused_query_budget_is_shared_across_geometry_and_label_sweep():
    fixture = _fixture(('required', 0, (8,), (1,)), ('left', 0, (4,), (1,)), ('right', 4, (4,), (1,)))
    graph, artifact, refs = fixture
    budget = ValidityBudget(128)
    budget.spend('source_query', 100)
    result = _labeled_storage_coverage(refs['required'], (('A', refs['left']), ('B', refs['right'])),
        catalog=_ValueCatalog({artifact.sha256: graph}), budget=budget)
    assert budget.truncated and result['status'] == 'UNRESOLVED'
    assert result['budget_used'] <= 28 and budget.used <= 128
    assert budget.costs['source_query'] == 100


def test_bare_allocation_id_in_another_artifact_cannot_supply_a_label():
    fixture = _fixture(('required', 0, (8,), (1,)))
    other = _fixture(('offered', 0, (8,), (1,)))
    graph, artifact, refs = fixture
    result = labeled_storage_coverage(refs['required'], (('other-scope', other[-1]['offered']),),
        value_graphs={artifact.sha256: graph, other[1].sha256: other[0]})
    assert result['status'] == 'UNRESOLVED'
    assert not any(item['labels'] for item in result['portions'])


def test_duplicate_label_cannot_silently_merge_two_different_fragment_selectors():
    fixture = _fixture(('required', 0, (8,), (1,)), ('left', 0, (4,), (1,)), ('right', 4, (4,), (1,)))
    with pytest.raises(ValueError, match='unique'):
        _call(fixture, (('same', 'left'), ('same', 'right')))
