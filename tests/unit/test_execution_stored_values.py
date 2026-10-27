"""Stored payloads follow actual states, accesses, completions and call paths."""
from dataclasses import replace

import pytest

from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.snapshot import snapshot_for
from scar.ir.execution.validation import validate as validate_execution
from scar.ir.program.model import (
    CompletionResult, ExitKind, InvokeLiteralResult, OperationResult, ReferenceValue, StateVersionValue,
)
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_stored_values import (
    _actual, stored_values_calls_execution, stored_values_control_execution,
    stored_values_execution, stored_values_invoke_execution,
)


_BUDGET = 1048576
_FLAGS = ('source_runtime_verified', 'native_identity_verified',
          'runtime_identity_verified', 'value_identity_verified',
          'transformation_authorized')


def _index(graph, model):
    require_valid(graph)
    report = validate_execution(model, graph)
    assert report.valid, report.issues
    return ExecutionIndex(model, graph)


def _query(index, row, occurrence, *, budget=_BUDGET):
    return index.stored_value_sources(row.result, occurrence, budget=budget)


def _inventory(view, graph, model):
    assert view['write_inventory'] == graph.stored_value_writes
    assert view['read_inventory'] == graph.stored_value_reads
    assert view['operation_inventory'] == model.operations
    assert all(view[flag] is False for flag in _FLAGS)


def _supported(view, graph, model, payload, write):
    _inventory(view, graph, model)
    assert view['match'] is True
    assert view['source_value'] == payload
    assert view['sources'] == (payload,)
    assert view['read']['supported'] is True
    assert view['read']['before'] == view['read']['current']
    assert not view['budget']['truncated']
    supported = tuple(row for row in view['candidates'] if row['match'] is True)
    assert supported and {row['operation'].id for row in supported} == {write}
    assert all(row['source_value'] == payload and row['address']['match'] is True
               and row['interval']['preserved'] is True for row in supported)
    assert view['recipe']['source'] == payload.id
    assert view['recipe']['target'] == view['read']['result'].id
    return supported


def test_p_read_then_q_overwrite_keeps_each_reads_independent_payload_and_state():
    graph, model, details = stored_values_execution(instances=2)
    index = _index(graph, model)
    for example in details['examples']:
        for number, row in enumerate(details['read_rows']):
            view = _query(index, row, example['reads'][number])
            _supported(view, graph, model, example['payloads'][number], example['writes'][number])
            old = 1 - number
            assert not any(candidate['match'] is True
                and candidate['operation'].id == example['writes'][old]
                for candidate in view['candidates'])
        # The two source operands are original References, not state contents
        # or ordinary copies of the load's independently produced result.
        assert example['payloads'][0].id != example['payloads'][1].id
        assert all(type(next(value for value in graph.values if value.id == payload.value))
                   is not StateVersionValue for payload in example['payloads'])


@pytest.mark.parametrize('mode', ('opaque', 'alias', 'different-domain'))
def test_an_unexcluded_intervening_effect_blocks_old_value_but_q_post_reestablishes_it(mode):
    graph, model, details = stored_values_execution(mode=mode, instances=2)
    index = _index(graph, model)
    example = details['examples'][0]
    blocked = _query(index, details['read_rows'][0], example['reads'][0])
    _inventory(blocked, graph, model)
    assert blocked['match'] is None and blocked['source_value'] is None
    original = next(row for row in blocked['candidates'] if row['operation'].id == example['writes'][0])
    assert original['interval']['preserved'] is None
    barrier = details['barrier'].id
    assert any(item['occurrence'] is not None and item['definition'].id == barrier
               for item in original['interval']['operations'])
    assert original['interval']['blockers']
    current = _query(index, details['read_rows'][1], example['reads'][1])
    _supported(current, graph, model, example['payloads'][1], example['writes'][1])


@pytest.mark.parametrize('mode', ('unknown-owner', 'unknown-selector'))
def test_an_explicit_but_unresolved_address_cannot_supply_a_slot_value(mode):
    graph, model, details = stored_values_execution(mode=mode)
    index = _index(graph, model)
    example = details['examples'][0]
    view = _query(index, details['read_rows'][0], example['reads'][0])
    _inventory(view, graph, model)
    assert view['match'] is None and view['source_value'] is None
    assert not any(row['match'] is True for row in view['candidates'])
    current = _query(index, details['read_rows'][1], example['reads'][1])
    _supported(current, graph, model, example['payloads'][1], example['writes'][1])


def test_two_legal_reference_keys_stay_unclassified_instead_of_becoming_builtin_data_keys():
    graph, model, details = stored_values_execution(mode='reference-key')
    index = _index(graph, model)
    first, second = details['reference_keys']
    assert type(first) is type(second) is ReferenceValue and first.id != second.id
    assert first.origin.value is second.origin.value is None
    example = details['examples'][0]
    view = _query(index, details['read_rows'][0], example['reads'][0])
    _inventory(view, graph, model)
    assert view['match'] is None and view['source_value'] is None
    assert view['read']['supported'] is False
    assert not any(row['match'] is True for row in view['candidates'])


@pytest.mark.parametrize('removed', ('write', 'read'))
def test_deleting_optional_value_semantics_does_not_erase_original_access_or_result_inventory(removed):
    graph, model, details = stored_values_execution()
    if removed == 'write':
        changed_graph = replace(graph, stored_value_writes=graph.stored_value_writes[1:])
    else:
        changed_graph = replace(graph, stored_value_reads=graph.stored_value_reads[1:])
    changed = replace(model, snapshot=snapshot_for(changed_graph))
    index = _index(changed_graph, changed)
    example = details['examples'][0]
    view = _query(index, details['read_rows'][0], example['reads'][0])
    _inventory(view, changed_graph, changed)
    assert view['operation_inventory'] == model.operations
    assert view['match'] is None and view['source_value'] is None
    assert view['gaps']
    assert any(op.id == details['reads'][0].id for op in changed_graph.operations)
    assert details['read_rows'][0].result in tuple(
        value.origin for value in changed_graph.values)
    _supported(_query(index, details['read_rows'][1], example['reads'][1]),
               changed_graph, changed, example['payloads'][1], example['writes'][1])


@pytest.mark.parametrize('missing', ('payload', 'write-state', 'read-state'))
def test_missing_exact_operand_preserves_all_sources_without_borrowing_another_instance(missing):
    graph, model, details = stored_values_execution(instances=2)
    first, second = details['examples']
    if missing == 'payload':
        occurrence, use = first['writes'][0], details['write_rows'][0].payload
    elif missing == 'write-state':
        occurrence, use = first['writes'][0], details['writes'][0].accesses[0].before
    else:
        occurrence, use = first['reads'][0], details['reads'][0].accesses[0].before
    changed = replace(model, uses=tuple(row for row in model.uses
                                      if (row.operation, row.use) != (occurrence, use)))
    index = _index(graph, changed)
    view = _query(index, details['read_rows'][0], first['reads'][0])
    _inventory(view, graph, changed)
    assert view['match'] is None and view['source_value'] is None
    assert view['gaps'] or any(row['gaps'] for row in view['candidates'])
    _supported(_query(index, details['read_rows'][0], second['reads'][0]),
               graph, changed, second['payloads'][0], second['writes'][0])


@pytest.mark.parametrize('limit', (1, 16))
def test_shared_budget_keeps_all_raw_inventories_and_cannot_grant_a_checked_prefix(limit):
    graph, model, details = stored_values_execution(instances=2)
    index = _index(graph, model)
    example = details['examples'][0]
    view = _query(index, details['read_rows'][1], example['reads'][1], budget=limit)
    _inventory(view, graph, model)
    assert view['match'] is None and view['source_value'] is None and view['recipe'] is None
    assert view['budget']['truncated'] is True and view['budget']['used'] <= limit
    assert view['cursor']
    assert not any(row['match'] is True for row in view['candidates'])


@pytest.mark.parametrize('arm', (0, 1))
def test_original_branch_incoming_selects_the_matching_payload_owner_and_current_state(arm):
    graph, model, details = stored_values_control_execution(route='branch', arm=arm)
    index = _index(graph, model)
    occurrence, = details['reads']
    write, = details['selected_writes']
    payload, = details['payloads']
    assert model.transfers[0].successor_index == arm
    assert len(graph.stored_value_writes) == 2
    view = _query(index, details['read_row'], occurrence)
    _supported(view, graph, model, payload, write)
    assert len(view['candidates']) == 1


def test_repeated_loop_visits_select_each_visits_store_and_do_not_reuse_a_static_operation_key():
    graph, model, details = stored_values_control_execution(route='loop', iterations=2)
    index = _index(graph, model)
    assert len(details['reads']) == len(details['selected_writes']) == 2
    assert len(set(details['reads'])) == 2
    assert len({row.operation for row in model.operations if row.id in details['reads']}) == 1
    assert details['payloads'][0].id != details['payloads'][1].id
    for read, write, payload in zip(details['reads'], details['selected_writes'], details['payloads'], strict=True):
        view = _query(index, details['read_row'], read)
        _supported(view, graph, model, payload, write)
        assert len(view['candidates']) == 2
        assert all(row['match'] is not True for row in view['candidates'] if row['operation'].id != write)


@pytest.mark.parametrize('raised', (False, True), ids=('own-normal', 'own-raise'))
def test_invoke_post_uses_its_exact_selected_completion_and_reordered_state_slots(raised):
    graph, model, details = stored_values_invoke_execution(raised=raised)
    index = _index(graph, model)
    view = _query(index, details['read_row'], details['read_occurrence'])
    supported = _supported(view, graph, model, details['payload'], details['write_occurrence'])
    candidate, = supported
    assert candidate['write'].completion == details['selected_edge']
    assert candidate['binding']['completion'].successor_index == details['selected_edge'].successor_index
    selected = details['invoke'].terminator.successors[details['selected_edge'].successor_index]
    block = next(block for region in graph.regions for block in region.blocks if block.id == selected.block)
    expected = {location.id for location in graph.locations}
    values = {value.id: value for value in graph.values}
    actual = {values[formal].location for formal, argument in zip(block.arguments, selected.arguments, strict=True)
              if type(argument) is CompletionResult and type(values[formal]) is StateVersionValue}
    assert actual == expected
    assert any(type(argument) is not CompletionResult for argument in selected.arguments)
    assert all(row['match'] is not True for row in view['candidates']
               if row['write'].completion != details['selected_edge'])


def test_an_undeclared_raise_post_cannot_borrow_the_declared_normal_establishment():
    graph, model, details = stored_values_invoke_execution(raised=True, declare_raise=False)
    index = _index(graph, model)
    view = _query(index, details['read_row'], details['read_occurrence'])
    _inventory(view, graph, model)
    assert view['match'] is None and view['source_value'] is None
    candidate, = view['candidates']
    assert candidate['binding']['selected'] is False
    assert candidate['match'] is None


@pytest.mark.parametrize('raised', (False, True), ids=('load-normal', 'load-raise'))
def test_two_actual_activations_of_one_callee_keep_the_real_source_and_own_read_completion(raised):
    graph, model, details = stored_values_calls_execution(raised=raised, instances=2)
    index = _index(graph, model)
    assert len({call.callee for call in details['calls']}) == 1
    assert len(model.call_activations) == 4
    assert type(details['read_row'].result) is InvokeLiteralResult
    for example in details['examples']:
        view = _query(index, details['read_row'], example['read'])
        _inventory(view, graph, model)
        if raised:
            assert view['match'] is None and view['source_value'] is None
            assert view['read']['selected'] is False and view['read']['result'] is None
        else:
            supported = _supported(view, graph, model, example['payload'], example['write'])
            interval = supported[0]['interval']
            assert {row['association'].id for row in interval['calls']} == {
                row.id for row in example['links']}
            assert interval['effect_expansion_inventory'] == graph.call_effect_expansions


@pytest.mark.parametrize('missing', ('association', 'state'))
def test_cross_call_missing_evidence_is_local_and_never_borrows_the_other_child_activation(missing):
    graph, model, details = stored_values_calls_execution(instances=2, missing=missing)
    index = _index(graph, model)
    first, second = details['examples']
    view = _query(index, details['read_row'], first['read'])
    _inventory(view, graph, model)
    assert view['match'] is None and view['source_value'] is None
    _supported(_query(index, details['read_row'], second['read']),
               graph, model, second['payload'], second['write'])


def test_public_receipts_are_detached_from_the_next_query_and_original_producers():
    graph, model, details = stored_values_execution(instances=2)
    index = _index(graph, model)
    example = details['examples'][0]
    first = _query(index, details['read_rows'][1], example['reads'][1])
    first['read']['before'] = None
    first['candidates'][0]['match'] = True
    first['budget']['costs']['caller-forgery'] = 999
    next_view = _query(index, details['read_rows'][1], example['reads'][1])
    _supported(next_view, graph, model, example['payloads'][1], example['writes'][1])
    assert 'caller-forgery' not in next_view['budget']['costs']
    assert type(details['read_rows'][1].result) is OperationResult
