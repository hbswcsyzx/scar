"""Conditional stored sources compose without becoming original copies."""
from dataclasses import replace

import pytest

from scar.ir.execution.await_outcome_evidence import pair
from scar.ir.execution.body_state_history import _BodyHistory
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.snapshot import snapshot_for
from scar.ir.execution.stored_value_projection import projection
from scar.ir.execution.validation import validate as validate_execution
from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.program.model import FootprintKind
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_value_sources import (
    copied_call_sources_execution, cyclic_owner_sources_execution,
    layered_value_sources_execution, parallel_value_sources_execution,
    repeated_loop_sources_execution, shared_landing_value_sources_execution,
)


_BUDGET = 2097152
_FLAGS = ('source_runtime_verified', 'runtime_identity_verified',
          'native_identity_verified', 'value_identity_verified', 'transformation_authorized')


def _index(graph, model):
    require_valid(graph)
    report = validate_execution(model, graph)
    assert report.valid, report.issues
    return ExecutionIndex(model, graph)


def _query(index, source, target, *, budget=_BUDGET):
    return index.value_source_pair(source.id, target.id, budget=budget)


def _inventory(view, graph, model):
    assert view['read_inventory'] == graph.stored_value_reads
    assert view['write_inventory'] == graph.stored_value_writes
    assert view['operation_inventory'] == model.operations
    assert all(view[flag] is False for flag in _FLAGS)


def _stored(view):
    return tuple(row for row in view['support'] if row['rule'] == 'DECLARED_STORED_VALUE')


def _supported(view, graph, model, source, target):
    _inventory(view, graph, model)
    assert view['source_value'] == source and view['target_value'] == target
    assert view['match'] is True and view['conflict'] is False
    assert view['conditional_stored_source'] is True and _stored(view)
    assert view['budget']['truncated'] is False and view['cursor'] is None


def test_two_payload_loads_reach_original_p_without_changing_ordinary_copy_recipes():
    graph, model, details = layered_value_sources_execution()
    index = _index(graph, model)
    context = index._content_context()
    original_copies = dict(context.body_original_copy_recipes)
    for example in details['examples']:
        original = pair(context, example['source'], example['target'], ValidityBudget(_BUDGET))
        assert original['match'] is None
        view = _query(index, example['source'], example['target'])
        _supported(view, graph, model, example['source'], example['target'])
        assert len(_stored(view)) == 2
        assert {row['target'] for row in _stored(view)} == {
            value.id for value in example['loaded_values']}
        assert pair(context, example['source'], example['target'], ValidityBudget(_BUDGET))['match'] is None
    assert context.body_original_copy_recipes == original_copies
    assert not model.denotations


def test_a_loaded_owner_selects_the_slot_without_adding_produced_reference_precision():
    graph, model, details = layered_value_sources_execution(mode='owner')
    index = _index(graph, model)
    loaded_owner = details['results'][0]
    assert loaded_owner.targets is None and loaded_owner.selector.kind is FootprintKind.UNKNOWN
    assert details['reads'][-1].effects_complete is False
    for example in details['examples']:
        view = _query(index, example['source'], example['target'])
        _supported(view, graph, model, example['source'], example['target'])
        direct = index.stored_value_sources(details['read_rows'][-1].result,
            example['reads'][-1], budget=_BUDGET)
        assert direct['match'] is True
        candidate, = tuple(row for row in direct['candidates'] if row['match'] is True)
        assert candidate['address']['owner']['conditional_stored_source'] is True
        assert any(row['rule'] == 'DECLARED_STORED_VALUE'
                   for row in candidate['address']['owner']['support'])


def test_a_getter_result_retains_original_copy_and_stored_edges_in_parallel():
    graph, model, details = parallel_value_sources_execution()
    index = _index(graph, model)
    for example in details['examples']:
        context = index._content_context()
        ordinary = pair(context, example['ordinary_source'], example['target'], ValidityBudget(_BUDGET))
        assert ordinary['match'] is True
        assert pair(context, example['stored_source'], example['target'], ValidityBudget(_BUDGET))['match'] is None
        original = _query(index, example['ordinary_source'], example['target'])
        assert original['match'] is True and original['conditional_stored_source'] is False
        stored = _query(index, example['stored_source'], example['target'])
        _supported(stored, graph, model, example['stored_source'], example['target'])
        assert len(_stored(stored)) == 1
        assert stored['projections']
        assert _stored(stored)[0]['target'] == example['target'].id


def test_two_reads_sharing_a_landing_use_the_exact_selected_call_incoming():
    graph, model, details = shared_landing_value_sources_execution(arm=1)
    index = _index(graph, model)
    assert len(graph.stored_value_reads) == 2
    assert model.transfers[0].successor_index == 1
    receipt = projection(index._content_context(), details['own_target'], ValidityBudget(_BUDGET))
    assert receipt['binding']['match'] is True
    assert receipt['declaration'] == details['selected_row']
    assert receipt['operation'].id == details['operation']
    assert receipt['sources_report']['read']['declaration'] == details['selected_row']
    assert projection(index._content_context(), details['target'], ValidityBudget(_BUDGET)) is None
    view = _query(index, details['source'], details['target'])
    _supported(view, graph, model, details['source'], details['target'])
    assert _stored(view)[0]['target'] == details['own_target'].id
    assert any(row['rule'] != 'DECLARED_STORED_VALUE' and row['target'] == details['target'].id
               for row in view['support'])


@pytest.mark.parametrize('raised', (False, True), ids=('normal-forward', 'raise-forward'))
def test_same_landing_forwarded_reference_is_never_projected_as_the_getters_own_result(raised):
    graph, model, details = parallel_value_sources_execution(raised=raised)
    index = _index(graph, model)
    for example in details['examples']:
        assert projection(index._content_context(), example['forwarded'], ValidityBudget(_BUDGET)) is None
        view = _query(index, example['stored_source'], example['forwarded'])
        _inventory(view, graph, model)
        assert view['match'] is None and view['conditional_stored_source'] is False
        if raised:
            assert example['target'] is None


def test_a_real_call_result_and_parent_consumer_keep_the_child_load_source():
    graph, model, details = copied_call_sources_execution(instances=2)
    index = _index(graph, model)
    for example in details['examples']:
        view = _query(index, example['source'], example['target'])
        _supported(view, graph, model, example['source'], example['target'])
        assert len(_stored(view)) == 1
        assert any(row['rule'] != 'DECLARED_STORED_VALUE' for row in view['support'])
        selected = tuple(row for row in view['projections'] if row['recipe'] is not None)
        assert any(row['operation'].id == example['read'] for row in selected)


@pytest.mark.parametrize('missing', ('association', 'state'))
def test_missing_this_call_evidence_cannot_borrow_a_complete_peer(missing):
    graph, model, details = copied_call_sources_execution(instances=2, missing=missing)
    index = _index(graph, model)
    first, second = details['examples']
    view = _query(index, first['source'], first['target'])
    _inventory(view, graph, model)
    assert view['match'] is None and view['gaps']
    _supported(_query(index, second['source'], second['target']),
               graph, model, second['source'], second['target'])


def test_repeated_static_loads_follow_the_current_visit_not_the_last_dictionary_entry():
    graph, model, details = repeated_loop_sources_execution()
    index = _index(graph, model)
    assert len(details['targets']) == 2 and details['targets'][0].id != details['targets'][1].id
    for source, target in zip(details['payloads'], details['targets'], strict=True):
        view = _query(index, source, target)
        _supported(view, graph, model, source, target)
        assert _stored(view)[0]['target'] == target.id
    earlier = _query(index, details['payloads'][0], details['targets'][1])
    _inventory(earlier, graph, model)
    assert earlier['match'] is None


@pytest.mark.parametrize('missing', ('payload', 'inner-state', 'read-declaration'))
def test_a_missing_inner_layer_keeps_raw_inventory_and_does_not_use_the_other_instance(missing):
    graph, model, details = layered_value_sources_execution(instances=2)
    first, second = details['examples']
    if missing == 'read-declaration':
        changed_graph = replace(graph, stored_value_reads=graph.stored_value_reads[1:])
        changed = replace(model, snapshot=snapshot_for(changed_graph))
    else:
        changed_graph = graph
        occurrence, use = ((first['writes'][0], details['write_rows'][0].payload)
            if missing == 'payload' else (first['reads'][0], details['reads'][0].accesses[0].before))
        changed = replace(model, uses=tuple(row for row in model.uses
            if (row.operation, row.use) != (occurrence, use)))
    index = _index(changed_graph, changed)
    view = _query(index, first['source'], first['target'])
    _inventory(view, changed_graph, changed)
    assert view['operation_inventory'] == model.operations
    assert view['match'] is None and view['gaps']
    peer = _query(index, second['source'], second['target'])
    if missing == 'read-declaration':
        assert peer['match'] is None
    else:
        _supported(peer, changed_graph, changed, second['source'], second['target'])


@pytest.mark.parametrize('obstruction', ('overwrite', 'opaque'))
def test_a_later_establishment_or_opaque_effect_cannot_reuse_an_earlier_successful_prefix(obstruction):
    graph, model, details = layered_value_sources_execution(
        overwrite=obstruction == 'overwrite', opaque=obstruction == 'opaque')
    index = _index(graph, model)
    first = details['examples'][0]
    view = _query(index, first['source'], first['target'])
    _inventory(view, graph, model)
    assert view['match'] is None
    if obstruction == 'overwrite':
        current = first['payloads'][-1]
        _supported(_query(index, current, first['target']), graph, model, current, first['target'])
    else:
        assert details['barrier'] is not None


def test_tiny_budget_preserves_endpoints_and_all_declared_read_write_and_actual_operation_keys():
    graph, model, details = layered_value_sources_execution()
    index = _index(graph, model)
    example = details['examples'][0]
    view = _query(index, example['source'], example['target'], budget=1)
    _inventory(view, graph, model)
    assert view['source_value'] == example['source'] and view['target_value'] == example['target']
    assert view['match'] is None and view['conditional_stored_source'] is False
    assert view['budget']['truncated'] is True and view['budget']['used'] <= 1
    assert view['cursor']


def test_a_projection_cache_hit_cannot_restore_success_after_the_shared_budget_truncates():
    graph, model, details = layered_value_sources_execution()
    index = _index(graph, model)
    context, shared = index._content_context(), ValidityBudget(_BUDGET)
    target = details['examples'][0]['target']
    first = projection(context, target, shared)
    assert first['binding']['match'] is True
    assert not shared.spend('test_cut_after_complete_projection', shared.remaining + 1)
    second = projection(context, target, shared)
    assert second['binding']['match'] is None and second['recipe'] is None
    assert second['target_value'] == target and second['cursor']


def test_an_active_unseeded_owner_cycle_is_unknown_and_does_not_poison_a_later_real_store():
    graph, model, details = cyclic_owner_sources_execution()
    index = _index(graph, model)
    context, shared = index._content_context(), ValidityBudget(_BUDGET)
    unseeded = projection(context, details['unseeded'], shared)
    assert unseeded['binding']['match'] is None and unseeded['recipe'] is None
    assert getattr(shared, '_stored_projection_cycle_generation', 0) > 0
    assert shared.truncated is False
    seeded = projection(context, details['seeded'], shared)
    assert seeded['binding']['match'] is True
    assert seeded['recipe']['source'] == details['source'].id
    assert not context.issues


def test_a_real_nested_owner_chain_stops_at_the_explicit_analysis_depth_boundary(monkeypatch):
    from scar.ir.execution import stored_value_projection
    graph, model, details = layered_value_sources_execution(mode='owner-chain', length=8, instances=1)
    index = _index(graph, model)
    # Bound the actual recursive owner proof; payload-only chains are iterative.
    monkeypatch.setattr(stored_value_projection, '_DEPTH_LIMIT', 4)
    example = details['examples'][0]
    view = _query(index, example['source'], example['target'])
    _inventory(view, graph, model)
    assert view['match'] is None and view['conditional_stored_source'] is False
    assert view['budget']['truncated'] is True and view['cursor']
    assert len(view['read_inventory']) == len(view['write_inventory']) == 8


def test_the_existing_body_consumer_uses_a_separate_stored_binding_without_proving_f19():
    graph, model, details = layered_value_sources_execution()
    index = _index(graph, model)
    example = details['examples'][0]
    context, shared = index._content_context(), ValidityBudget(_BUDGET)
    view = _BodyHistory(context, shared).body_pair(None, example['source'], example['target'])
    assert view['match'] is True
    assert view['ordinary_binding']['match'] is None
    assert view['stored_source_binding']['match'] is True
    assert view['binding_kind'] == 'CONDITIONAL_STORED_VALUE_SOURCE'
    assert all(view[flag] is False for flag in _FLAGS)


def test_public_results_are_detached_and_removed_semantics_do_not_reuse_a_previous_query_cache():
    graph, model, details = layered_value_sources_execution()
    index = _index(graph, model)
    example = details['examples'][0]
    first = _query(index, example['source'], example['target'])
    assert first['match'] is True
    first['support'][0]['rule'] = 'caller forgery'
    first['budget']['costs']['caller forgery'] = 999
    again = _query(index, example['source'], example['target'])
    _supported(again, graph, model, example['source'], example['target'])
    assert 'caller forgery' not in {row['rule'] for row in again['support']}
    assert 'caller forgery' not in again['budget']['costs']
    changed_graph = replace(graph, stored_value_reads=graph.stored_value_reads[1:])
    changed = replace(model, snapshot=snapshot_for(changed_graph))
    missing = _query(_index(changed_graph, changed), example['source'], example['target'])
    _inventory(missing, changed_graph, changed)
    assert missing['match'] is None
