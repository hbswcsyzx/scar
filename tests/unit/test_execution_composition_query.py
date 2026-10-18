"""Public composition boundary: request validation, freshness and detachment."""
from dataclasses import FrozenInstanceError, replace

import pytest

from scar.ir.execution import CompositionScope
from scar.ir.execution.ids import OperationOccurrenceID, RegionActivationID, RunID
from scar.ir.execution.inventory import InventoryResolver
from scar.ir.execution.query import ExecutionIndex
from tests.fixtures.execution_composition_scopes import composition_scope_execution
from tests.fixtures.execution_visibility_graphs import visibility_execution
from tests.fixtures.execution_work_graphs import ordinary_work_execution


@pytest.mark.parametrize('bad', (True, 0, -1, 1.0, '4096', None))
def test_invalid_budget_fails_before_external_preparation(monkeypatch, bad):
    program, model, graphs, scope, _ = composition_scope_execution()
    index = ExecutionIndex(model, program, semantic_graphs=graphs)

    def forbidden():
        pytest.fail('invalid request opened external artifacts')

    monkeypatch.setattr(index, '_content_context', forbidden)
    with pytest.raises((TypeError, ValueError)):
        index.resource_composition(scopes=(scope,), budget=bad)


@pytest.mark.parametrize('owner', (RunID('missing'), RegionActivationID('missing'),
                                  OperationOccurrenceID('missing')))
def test_unknown_owner_fails_before_external_preparation(monkeypatch, owner):
    program, model, graphs, scope, _ = composition_scope_execution()
    index = ExecutionIndex(model, program, semantic_graphs=graphs)

    def forbidden():
        pytest.fail('unknown local owner opened external artifacts')

    monkeypatch.setattr(index, '_content_context', forbidden)
    with pytest.raises(KeyError):
        index.resource_composition(scopes=(replace(scope, owner=owner),))


def test_duplicate_scopes_and_untyped_lists_fail_before_preparation(monkeypatch):
    program, model, graphs, scope, _ = composition_scope_execution()
    index = ExecutionIndex(model, program, semantic_graphs=graphs)

    def forbidden():
        pytest.fail('invalid scope opened external artifacts')

    monkeypatch.setattr(index, '_content_context', forbidden)
    with pytest.raises(ValueError, match='duplicated'):
        index.resource_composition(scopes=(scope, scope))
    with pytest.raises(TypeError, match='tuple'):
        index.resource_composition(scopes=[scope])


def test_one_preparation_and_one_final_detachment_with_real_content(monkeypatch):
    import scar.ir.execution.composition_query as composition_query
    import scar.ir.execution.production_query as production_query
    import scar.ir.execution.validity_query as validity_query

    program, model, values, payloads, details = visibility_execution()
    index = ExecutionIndex(model, program, value_graphs=values, artifact_bytes=payloads)
    replays, copies = [], []
    resolve = InventoryResolver.resolve
    detach = composition_query.deepcopy

    def counted_resolve(self, *args, **kwargs):
        replays.append(args)
        return resolve(self, *args, **kwargs)

    def counted_copy(value):
        copies.append(value)
        return detach(value)

    def forbidden(*args, **kwargs):
        pytest.fail('composition restarted a public per-read query or copied it')

    monkeypatch.setattr(InventoryResolver, 'resolve', counted_resolve)
    monkeypatch.setattr(composition_query, 'deepcopy', counted_copy)
    monkeypatch.setattr(production_query, 'production', forbidden)
    monkeypatch.setattr(validity_query, 'validity', forbidden)
    view = index.resource_composition(budget=65536)
    assert len(replays) == len(copies) == 1
    assert view['reads']['completed'] == len(model.content_reads)
    assert view['reads']['items'][0]['read'].id == details['read']
    assert view['observations']['scope_status'] == 'UNRESOLVED'
    assert view['budget']['used'] == sum(view['budget']['costs'].values())
    q_budget = view['observations']['budget']
    assert type(q_budget) is dict and q_budget['used'] <= view['budget']['used']
    assert q_budget['used'] == sum(q_budget['costs'].values())
    assert not view['transformation_authorized']


def test_returned_graphs_and_nested_ledgers_cannot_change_index_or_next_query():
    program, model, graphs, scope, _ = composition_scope_execution()
    index = ExecutionIndex(model, program, semantic_graphs=graphs)
    first = index.resource_composition(scopes=(scope,))
    count = len(program.operations)
    assert first['inventory']['program'] is not program
    with pytest.raises(FrozenInstanceError):
        first['inventory']['program'].operations = ()
    first['inventory']['execution_counts'].clear()
    first['budget']['costs'].clear()
    first['observations']['scopes'][0]['expected_outputs'] = ()
    second = index.resource_composition(scopes=(scope,))
    assert len(program.operations) == len(second['inventory']['program'].operations) == count
    assert second['inventory']['execution_counts']['operations'] == len(model.operations)
    assert second['observations']['scopes'][0]['expected_outputs']
    assert second['budget']['costs']


def test_requested_contract_mutation_is_rechecked_without_changing_old_report():
    program, model, graphs, scope, _ = composition_scope_execution()
    index = ExecutionIndex(model, program, semantic_graphs=graphs)
    old = index.report
    index.resource_composition(scopes=(scope,))
    next(iter(graphs.values())).contracts.clear()
    with pytest.raises(ValueError, match='external_graph_invalid|external_snapshot'):
        index.resource_composition(scopes=(scope,))
    assert index.report == old


def test_source_evidence_inventory_does_not_require_a_content_read():
    program, model, values, payloads, _ = visibility_execution()
    model = replace(model, content_reads=(), contribution_supports=())
    index = ExecutionIndex(model, program, value_graphs=values, artifact_bytes=payloads)
    view = index.resource_composition(budget=65536)
    assert view['reads']['total'] == 0
    source_views = [source for binding in view['sources']['items'] for source in binding['sources']]
    assert source_views
    assert any(source['evidence']['edges'] for source in source_views)
    for source in source_views:
        evidence = source['evidence']
        assert evidence['edge_count'] == len(evidence['edges'])
        assert evidence['pending_edges'] == 0
    assert not view['sources']['capture_complete']


def _cost_before(view, stop):
    used = 0
    for kind, cost in view['budget']['costs'].items():
        if kind == stop:
            return used
        used += cost
    raise AssertionError(f'expected phase did not run: {stop}')


def test_source_edge_prefix_truncation_preserves_original_count_and_cursor():
    program, model, values, payloads, _ = visibility_execution()
    model = replace(model, content_reads=(), contribution_supports=())
    index = ExecutionIndex(model, program, value_graphs=values, artifact_bytes=payloads)
    complete = index.resource_composition(budget=65536)
    limit = _cost_before(complete, 'composition_source_edge') + 1
    partial = index.resource_composition(budget=limit)
    assert partial['status'] == partial['sources']['status'] == 'TRUNCATED'
    assert partial['sources']['cursor']['edge_ordinal'] == 1
    source = partial['sources']['items'][0]['sources'][0]
    assert len(source['evidence']['edges']) == 1
    assert source['evidence']['pending_edges'] == source['evidence']['edge_count'] - 1 > 0
    assert partial['inventory']['execution'] == model
    assert partial['budget']['used'] == limit


def test_visited_work_with_unvisited_relations_is_still_truncated():
    program, model, values = ordinary_work_execution(retained='materialization')
    index = ExecutionIndex(model, program, value_graphs=values)
    complete = index.resource_composition()
    limit = _cost_before(complete, 'composition_work_relation')
    partial = index.resource_composition(budget=limit)
    lifecycle = partial['lifecycle']
    assert lifecycle['pending_work'] == 0
    assert lifecycle['status'] == 'TRUNCATED'
    assert lifecycle['cursor']['relation'] == 'outcomes'
    assert lifecycle['work'][0]['pending']['outcomes'] == len(model.outcomes)
    assert partial['budget']['used'] == limit
