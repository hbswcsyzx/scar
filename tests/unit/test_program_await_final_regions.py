"""The real extraction interface joins child own results to caller consumers.

Only the parent interface supplies extraction semantics. A primitive's output
copy witness is independent of copying the input packet to that primitive.
"""
from dataclasses import replace

import pytest

from scar.ir.program.model import CompletionResult, ExitKind, InvokeLiteralResult
from scar.ir.program.protocols import HostTerminal, OwnedUse
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid
from tests.fixtures.program_await_final_region_graphs import await_final_region_program


def _core(graph):
    return replace(graph, protocol_scopes=(), protocol_operations=(),
        protocol_call_inputs=(), protocol_result_consumers=(), protocol_bindings=())


def _query(graph, details):
    require_valid(_core(graph))
    require_valid(graph)
    report = ProgramIndex(graph).protocol_obligations(details['acquisition_scope'],
        budget=1048576)['connections']['families']['await']
    outcomes = tuple(row for row in report['outcomes']
        if row['source'] == details['source']
        and row['advance_operation'] == details['advance_operation']
        and row['drive_outcome'] == details['drive_outcome'])
    assert len(outcomes) == 1
    consumers = tuple(row for row in outcomes[0]['consumers']
        if row['actual'] == details['extract_input']
        and row['requires_final_extraction'] is True)
    assert consumers
    return report, outcomes[0], consumers[0]


def _identity(value):
    return getattr(value, 'id', value)


def _edge(operation, kind):
    matches = tuple(ControlEdgeReference(operation.id, number)
        for number, edge in enumerate(operation.terminator.successors) if edge.kind is kind)
    assert len(matches) == 1
    return matches[0]


def _result(operation, kind, slot):
    return InvokeLiteralResult(_edge(operation, kind), CompletionResult(slot))


def _frame_keys(details):
    path, result = (details['parent_call'].id,), []
    for record in details['stage_records']:
        result.append(path)
        path = (*path, record['operation'].id)
    return tuple(result)


def _leaf(implementation, details):
    frame = _frame_keys(details)[-1]
    matches = tuple(stage for stage in implementation['stages']
        if stage['key'] == (frame, details['primitive'].id))
    assert len(matches) == 1
    stage = matches[0]
    assert stage['frame'] == frame
    assert _identity(stage['operation']) == details['primitive'].id
    assert stage['expanded'] is False
    expected = details['stage_records'][-1]['arguments']
    assert len(stage['inputs']) == len(expected) == 3
    for ordinal, (item, actual) in enumerate(zip(stage['inputs'], expected)):
        assert item['ordinal'] == ordinal and item['actual'] == actual
    packet = stage['inputs'][0]
    assert packet['may'] is True and packet['must'] is True
    assert packet['binding']['match'] is True
    return stage


def _leg(stage, kind):
    matches = tuple(leg for leg in stage['legs'] if leg['kind'] is kind)
    assert len(matches) == 1
    return matches[0]


def _output(implementation, source):
    matches = tuple(output for output in implementation['outputs'] if output['source'] == source)
    assert len(matches) == 1
    return matches[0]


def _caller_target(graph, details, kind, slot):
    parent = details['parent_call']
    edge = parent.terminator.successors[_edge(parent, kind).successor_index]
    blocks = {block.id: block for region in graph.regions for block in region.blocks}
    terminal = next(operation for operation in graph.operations
                    if operation.id == blocks[edge.block].operations[-1])
    return (HostTerminal(terminal.id) if slot == 0 else
            OwnedUse(terminal.id, terminal.terminator.values[slot]))


def _positive_path(path, source, kind, slot, graph, details):
    assert path['binding']['match'] is True
    assert path['interface_result'] == _result(details['parent_call'], kind, slot)
    assert len(path['hops']) == details['depth']
    frames = _frame_keys(details)
    for hop, number in zip(path['hops'], reversed(range(details['depth']))):
        record = details['stage_records'][number]
        parent = (details['parent_call'] if number == 0
                  else details['stage_records'][number - 1]['operation'])
        assert hop['frame'] == frames[number]
        assert _identity(hop['call']) == parent.id
        assert hop['source'] == source
        assert hop['terminal'] == record['terminal_uses'][kind][slot]
        assert hop['kind'] is kind and hop['slot'] == slot
        result = _result(parent, kind, slot)
        assert hop['caller_result'] == result
        edge = parent.terminator.successors[result.edge.successor_index]
        position, = tuple(position for position, argument in enumerate(edge.arguments)
                          if type(argument) is CompletionResult and argument.index == slot)
        assert hop['landing_position'] == position
        assert hop['binding']['match'] is True
        source = result
    expected_target = _caller_target(graph, details, kind, slot)
    matches = tuple(target for target in path['targets'] if target['target'] == expected_target)
    assert matches and all(target['binding']['match'] is True for target in matches)


def _positive_structure(graph, consumer, details):
    implementation = consumer['implementation']
    assert implementation is not None
    assert _identity(implementation['operation']) == details['parent_call'].id
    assert _identity(implementation['callee']) == details['parent_call'].callee
    assert implementation['entry_frame'] == (details['parent_call'].id,)
    assert set(_frame_keys(details)).issubset({frame['key'] for frame in implementation['frames']})
    stage = _leaf(implementation, details)
    expected_outputs = set()
    for kind in (ExitKind.NORMAL, ExitKind.RAISE):
        leg = _leg(stage, kind)
        assert leg['edge'] == _edge(details['primitive'], kind)
        assert leg['own_result'] == _result(details['primitive'], kind, 0)
        signature = next(row for row in details['primitive'].completions if row.kind is kind)
        assert len(leg['results']) == len(signature.types) == 3
        assert {result['slot'] for result in leg['results']} == set(range(3))
        for result in leg['results']:
            slot = result['slot']
            source = _result(details['primitive'], kind, slot)
            assert result['source'] == source
            paths = tuple(path for path in result['paths'] if path['binding']['match'] is True)
            assert paths
            for path in paths:
                _positive_path(path, source, kind, slot, graph, details)
            interface = _result(details['parent_call'], kind, slot)
            expected_outputs.add(interface)
            output = _output(implementation, interface)
            assert output['kind'] is kind and output['slot'] == slot
            assert output['edge'] == interface.edge
            expected_terminal = details['stage_records'][0]['terminal_uses'][kind][slot]
            assert {terminal['terminal'] for terminal in output['terminals']} == {expected_terminal}
            for terminal in output['terminals']:
                assert terminal['match'] is True
                # Only a nonexpanded frontier contribution covers the output.
                assert any(witness['binding']['match'] is True
                    and witness['hops'][0]['source'] == source
                    for witness in terminal['witnesses'])
    assert {output['source'] for output in implementation['outputs']} == expected_outputs
    assert implementation['inventory']['enumerated_outputs'] == len(expected_outputs)
    # The primitive frontier remains conditional; copy witnesses grant no
    # native semantics, purity, value identity or transformation authority.
    assert implementation['status'] == 'PARTIAL'
    return implementation


@pytest.mark.parametrize(('zero_cut', 'depth'), ((True, 1), (True, 2), (False, 1), (False, 2)),
                         ids=('zero-one-region', 'zero-two-regions',
                              'two-cut-one-region', 'two-cut-two-regions'))
def test_real_child_extractor_own_results_return_through_each_exact_parent_slot(zero_cut, depth):
    graph, details = await_final_region_program(zero_cut=zero_cut, depth=depth)
    report, _, consumer = _query(graph, details)
    assert consumer['final_rows'] == details['final_rows']
    _positive_structure(graph, consumer, details)
    assert all(row.operation == details['parent_call'].id for row in details['final_rows'])
    assert not any(row.operation in {operation.id for operation in details['stage_operations']}
                   for row in graph.protocol_operations)
    for name in ('source_runtime_verified', 'runtime_identity_verified',
                 'value_identity_verified', 'transformation_authorized'):
        assert report[name] is False


def test_deleting_parent_final_adapter_keeps_regions_stages_outputs_and_real_consumers():
    complete, details = await_final_region_program(zero_cut=False, depth=2)
    missing, removed = await_final_region_program(zero_cut=False, depth=2, final_adapters=False)
    assert complete.operations == missing.operations and complete.values == missing.values
    assert complete.regions == missing.regions
    _, before_outcome, before = _query(complete, details)
    _, after_outcome, after = _query(missing, removed)
    assert before_outcome['key'] == after_outcome['key']
    assert tuple(row['actual'] for row in before_outcome['consumers']) == tuple(
        row['actual'] for row in after_outcome['consumers'])
    assert after['final_rows'] == ()
    assert 'await_final_adapter_missing' in after['gaps']
    first = _positive_structure(complete, before, details)
    second = _positive_structure(missing, after, removed)
    assert tuple(frame['key'] for frame in first['frames']) == tuple(
        frame['key'] for frame in second['frames'])
    assert tuple(stage['key'] for stage in first['stages']) == tuple(
        stage['key'] for stage in second['stages'])
    assert tuple(output['source'] for output in first['outputs']) == tuple(
        output['source'] for output in second['outputs'])


def test_rethrowing_old_packet_keeps_false_candidate_without_fabricating_output_coverage():
    graph, details = await_final_region_program(depth=2, wrong_child_exit=True)
    _, _, consumer = _query(graph, details)
    implementation = consumer['implementation']
    stage = _leaf(implementation, details)
    leg = _leg(stage, ExitKind.RAISE)
    result, = tuple(row for row in leg['results'] if row['slot'] == 0)
    own = details['stage_records'][-1]['own_results'][ExitKind.RAISE]
    assert result['source'] == own
    terminal = details['stage_records'][-1]['terminal_payloads'][ExitKind.RAISE]
    assert any(hop['source'] == own and hop['terminal'] == terminal
        and hop['binding']['match'] is False
        for path in result['paths'] for hop in path['hops'])
    output = _output(implementation, _result(details['parent_call'], ExitKind.RAISE, 0))
    assert output['status'] == 'PARTIAL'
    assert all(row['match'] is not True for row in output['terminals'])
    assert not any(witness['binding']['match'] is True for row in output['terminals']
                   for witness in row['witnesses'])
    assert implementation['status'] == 'PARTIAL'
    normal = _output(implementation, _result(details['parent_call'], ExitKind.NORMAL, 0))
    assert normal['terminals'] and all(row['match'] is True for row in normal['terminals'])
