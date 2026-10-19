"""General A, method-created B and the real final region share one graph."""
from dataclasses import replace

import pytest

from scar.ir.program.model import CompletionResult, ExitKind, InvokeLiteralResult, StateVersionValue, TerminatorKind
from scar.ir.program.protocol_await_records import AwaitBodyLink
from scar.ir.program.protocols import OwnedUse
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.resumption import ResumableKind
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_await_general_final_graphs import await_general_final_program


QUERY_BUDGET = 1_048_576


def _core(graph):
    return replace(graph, protocol_scopes=(), protocol_operations=(),
        protocol_call_inputs=(), protocol_result_consumers=(), protocol_bindings=())


def _query(graph, details):
    require_valid(_core(graph))
    require_valid(graph)
    return ProgramIndex(graph).protocol_obligations(details['acquisition_scope'],
        budget=QUERY_BUDGET)['connections']['families']['await']


def _consumer(report, details):
    outcome, = tuple(row for row in report['outcomes']
        if row['source'] == details['source']
        and row['advance_operation'] == details['advance_operation']
        and row['drive_outcome'] == details['drive_outcome'])
    consumer, = tuple(row for row in outcome['consumers']
        if row['actual'] == details['extract_input'] and row['requires_final_extraction'])
    return consumer


@pytest.mark.parametrize(('zero_cut', 'depth'),
    ((True, 1), (True, 2), (False, 1), (False, 2)),
    ids=('zero-depth1', 'zero-depth2', 'two-depth1', 'two-depth2'))
def test_independent_general_source_is_acquired_before_start_and_reaches_all_final_slots(zero_cut, depth):
    graph, details = await_general_final_program(zero_cut=zero_cut, depth=depth)
    report = _query(graph, details)
    assert graph.resumable_bodies[0].kind is ResumableKind.GENERATOR
    assert details['get'].callee == details['helper'].id
    assert details['get'].uses[0].value == details['A_value'].id
    assert all(row.contract.expected == details['A'] for row in details['get_rows'])
    assert details['A'] != details['B']
    assert details['helper_create'].operation == details['helper_call'].id
    assert details['helper_create'] not in details['outer_creations']
    assert details['helper_create'].body == details['body'].id
    assert details['qualification_row'].contract.expected == details['B']
    assert all(row.contract.argument_uses == () for row in details['method_call_rows'])
    blocks = {block.id: block for block in details['caller'].blocks}
    path_operations = tuple(identity for block, _selected in details['caller_path']
                            for identity in blocks[block].operations)
    assert path_operations.index(details['get'].id) < path_operations.index(details['calls'][0].id)
    assert len(details['drivers']) == (1 if zero_cut else 3)
    assert all(row['direct'] is False for row in details['drivers'])
    assert {row.operation for row in details['call_rows']} == {call.id for call in details['calls']}
    assert all(link.source == details['source'] for link in details['links'])
    if not zero_cut:
        assert sum(operation.terminator is not None and operation.terminator.kind is TerminatorKind.SUSPEND
            for operation in graph.operations) == 2

    # The same final advance packet is consumed by E; no child gets invented
    # lookup/adapter semantics.  Its own outputs cover both N/R and W/C slots.
    consumer = _consumer(report, details)
    assert consumer['final_rows'] == details['final_rows']
    implementation = consumer['implementation']
    primitive, = tuple(stage for stage in implementation['stages']
        if getattr(stage['operation'], 'id', stage['operation']) == details['primitive'].id)
    assert primitive['expanded'] is False
    assert len(primitive['inputs']) == 3
    assert primitive['inputs'][0]['must'] is True
    assert primitive['inputs'][0]['binding']['match'] is True
    for leg in primitive['legs']:
        assert leg['kind'] in (ExitKind.NORMAL, ExitKind.RAISE)
        signature, = tuple(row for row in details['primitive'].completions if row.kind is leg['kind'])
        assert len(leg['results']) == len(signature.types) == 3
        for result in leg['results']:
            witnesses = tuple(path for path in result['paths'] if path['contribution']['match'] is True)
            assert witnesses
            assert any(len(path['hops']) == depth and path['targets']
                and all(hop['binding']['match'] is True for hop in path['hops'])
                and all(target['binding']['match'] is True for target in path['targets'])
                for path in witnesses)
    expected_outputs = {InvokeLiteralResult(ControlEdgeReference(details['parent_call'].id, index),
        CompletionResult(slot)) for index, edge in enumerate(details['parent_call'].terminator.successors)
        for signature in details['parent_call'].completions if signature.kind is edge.kind
        for slot in range(len(signature.types))}
    assert {output['source'] for output in implementation['outputs']} == expected_outputs
    assert {output['kind'] for output in implementation['outputs']} == {ExitKind.NORMAL, ExitKind.RAISE}
    assert {output['slot'] for output in implementation['outputs']} == {0, 1, 2}
    assert all(terminal['match'] is True for output in implementation['outputs']
               for terminal in output['terminals'])
    assert not any(row.operation in {stage.id for stage in details['stage_operations']}
                   for row in graph.protocol_operations)
    for name in ('source_runtime_verified', 'runtime_identity_verified',
                 'value_identity_verified', 'transformation_authorized'):
        assert report[name] is False and implementation[name] is False


def test_another_root_reference_cannot_supply_the_independent_A_contract():
    graph, details = await_general_final_program(zero_cut=False, depth=2)
    require_valid(graph)
    get = details['get']
    wrong = replace(get, uses=tuple(replace(use, value=details['sent_value'])
        if use.id == get.invoke_arguments[0] else use for use in get.uses))
    changed = replace(graph, operations=tuple(wrong if row.id == get.id else row
                                             for row in graph.operations))
    require_valid(_core(changed))
    report = ProgramIndex(_core(changed)).source_binding(details['A'],
        OwnedUse(get.id, get.invoke_arguments[0]), budget=QUERY_BUDGET)
    assert report['match'] is False
    assert 'protocol_await_source' in {issue.code for issue in validate(changed)}


def test_old_preacquisition_world_cannot_be_used_as_the_first_driver_current_state():
    graph, details = await_general_final_program(zero_cut=False)
    require_valid(graph)
    values = {row.id: row for row in graph.values}
    get_states = tuple(use for use in details['get'].uses
        if use.id in details['get'].invoke_arguments and isinstance(values[use.value], StateVersionValue))
    first = details['calls'][0]
    first_state = next(use for use in first.uses if use.id in first.invoke_arguments
        and isinstance(values[use.value], StateVersionValue)
        and values[use.value].location == values[get_states[0].value].location)
    wrong = replace(first, uses=tuple(replace(use, value=get_states[0].value)
        if use.id == first_state.id else use for use in first.uses))
    changed = replace(graph, operations=tuple(wrong if row.id == first.id else row for row in graph.operations))
    assert 'stale_state' in {issue.code for issue in validate(_core(changed))}


def test_deleting_all_body_links_keeps_every_original_advance_and_final_output_inventory():
    graph, details = await_general_final_program(zero_cut=False, depth=2)
    before = _query(graph, details)
    changed = replace(graph, protocol_bindings=tuple(row for row in graph.protocol_bindings
                                                   if not isinstance(row, AwaitBodyLink)))
    after = _query(changed, details)
    key = lambda job: (job['source'], job['advance'], job.get('drive'))
    original = tuple(job for job in before['inventory']['jobs'] if job['scope'] == details['acquisition_scope'])
    missing = tuple(job for job in after['inventory']['jobs'] if job['scope'] == details['acquisition_scope'])
    assert tuple(map(key, original)) == tuple(map(key, missing))
    assert len(missing) == len(details['call_rows'])
    assert all(not row['links'] and 'await_body_link_missing' in row['gaps'] for row in missing)
    first = _consumer(before, details)['implementation']
    second = _consumer(after, details)['implementation']
    assert tuple(row['source'] for row in first['outputs']) == tuple(row['source'] for row in second['outputs'])


__all__ = []
