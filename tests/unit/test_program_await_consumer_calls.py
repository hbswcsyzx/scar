"""Await forwarding callees keep their own original consumers and port slots."""
from dataclasses import replace

import pytest

from scar.ir.program.model import ExitKind, InvokeLiteralResult, OperationResult
from scar.ir.program.protocols import OwnedUse
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid
from tests.fixtures.program_await_consumer_call_graphs import await_consumer_call_program


def _core(graph):
    return replace(graph, protocol_scopes=(), protocol_operations=(),
        protocol_call_inputs=(), protocol_result_consumers=(), protocol_bindings=())


def _index(graph):
    require_valid(_core(graph))
    require_valid(graph)
    return ProgramIndex(graph)


def _await(index, details):
    return index.protocol_obligations(details['acquisition_scope'],
        budget=1048576)['connections']['families']['await']


def _outcome(report, details):
    matches = tuple(row for row in report['outcomes']
        if row['drive_outcome'] == details['drive_outcome']
        and row['advance_operation'] == details['advance_operation']
        and row['source'] == details['source'])
    assert len(matches) == 1
    return matches[0]


def _consumer(row, actual):
    matches = tuple(consumer for consumer in row['consumers']
        if consumer['actual'] == actual and consumer['requires_final_extraction'] is True)
    assert matches
    return matches[0]


def _identity(value):
    return getattr(value, 'id', value)


def _frames(report, details):
    assert report['source'] == details['root_source']
    frames = {frame['key']: frame for frame in report['frames']}
    assert () in frames and frames[()]['inputs'] == ()
    assert _identity(frames[()]['region']) == details['caller'].id
    parent_key = ()
    for call, record in zip(details['helper_calls'], details['helper_records']):
        key = (*parent_key, call.id)
        assert key in frames
        parent, child = frames[parent_key], frames[key]
        matching = tuple(item for item in parent['calls'] if _identity(item['operation']) == call.id)
        assert len(matching) == 1
        boundary = matching[0]
        assert boundary['child_frame'] == key
        assert _identity(boundary['callee']) == record['region'].id
        assert _identity(child['parent_call']) == call.id
        assert _identity(child['region']) == record['region'].id
        assert child['inputs'] == boundary['arguments']
        assert len(child['inputs']) == len(call.call_arguments) == 3
        for ordinal, item in enumerate(child['inputs']):
            assert item['ordinal'] == ordinal
            assert item['actual'] == OwnedUse(call.id, call.call_arguments[ordinal])
            assert item['formal'] == record['formals'][ordinal].origin
        packet = child['inputs'][0]
        assert packet['may'] is True and packet['must'] is True
        assert packet['binding']['match'] is True
        assert set(child['may_seeds']) == {record['formals'][0].id}
        assert set(child['must_seeds']) == {record['formals'][0].id}
        actual = record['exit_uses'][0]
        consumers = tuple(item for item in child['consumers'] if item['actual'] == actual)
        assert len(consumers) == 1
        consumer = consumers[0]
        assert consumer['key'] == (key, actual)
        assert consumer['role'] == 'EXIT'
        assert consumer['kind'] is ExitKind.NORMAL and consumer['slot'] == 0
        assert consumer['may'] is True and consumer['must'] is True
        assert consumer['binding']['match'] is True
        # The interface inventory preserves state slots as well as payload.
        assert {item['slot'] for item in child['returns']} == set(range(3))
        assert len(child['returns']) == 3
        for slot, actual in enumerate(record['exit_uses']):
            returned = tuple(item for item in child['returns'] if item['actual'] == actual)
            assert len(returned) == 1
            item = returned[0]
            assert item['kind'] is ExitKind.NORMAL and item['slot'] == slot
            assert item['caller_result'] == OperationResult(call.id, slot)
            if slot == 0:
                assert item['may'] is True and item['must'] is True
                assert item['binding']['match'] is True
        parent_key = key
    for name in ('source_runtime_verified', 'runtime_identity_verified',
                 'value_identity_verified', 'transformation_authorized'):
        assert report[name] is False
    return frames


def _extractor(row, details, *, final_adapters=True):
    consumer = _consumer(row, details['extract_input'])
    assert consumer['binding']['match'] is True
    assert consumer['final_rows'] == (details['final_rows'] if final_adapters else ())
    expected = details['extraction_targets']
    assert {leg['edge'] for leg in consumer['legs']} == set(expected)
    for leg in consumer['legs']:
        assert type(leg['own_result']) is InvokeLiteralResult
        assert leg['own_result'].edge == leg['edge']
        assert leg['own_result'].result.index == 0
        assert expected[leg['edge']] in leg['targets']
        assert leg['bindings'] and all(item['match'] is True for item in leg['bindings'])
    return consumer


@pytest.mark.parametrize('zero_cut', (True, False), ids=('zero-cut', 'two-cut'))
def test_await_forwarding_call_keeps_its_child_use_and_real_extractor(zero_cut):
    graph, details = await_consumer_call_program(zero_cut=zero_cut)
    report = _await(_index(graph), details)
    row = _outcome(report, details)
    helper = _consumer(row, details['helper_inputs'][0][0])
    assert helper['binding']['match'] is True
    assert helper['final_rows'] == ()  # H does not acquire extractor semantics.
    _frames(helper['consumer_graph'], details)
    extraction = _extractor(row, details)
    _frames(extraction['consumer_graph'], details)
    assert details['extract'].id == details['original_extract'].id
    assert details['extract'].terminator == details['original_extract'].terminator
    assert details['extract'].completions == details['original_extract'].completions
    assert details['extract'].uses[0].value == details['forwarded_values'][0].id


def test_two_nested_forwarders_keep_both_call_frames_and_all_return_slots():
    graph, details = await_consumer_call_program(depth=2)
    row = _outcome(_await(_index(graph), details), details)
    graph_report = _consumer(row, details['helper_inputs'][0][0])['consumer_graph']
    frames = _frames(graph_report, details)
    key = tuple(call.id for call in details['helper_calls'])
    assert key in frames and len(key) == 2
    assert frames[key]['key'] != frames[key[:1]]['key']
    _extractor(row, details)


def test_public_copy_consumer_query_reuses_the_exact_advance_raise_source():
    graph, details = await_consumer_call_program()
    index = _index(graph)
    report = index.copy_consumers(details['root_source'], budget=1048576)
    frames = _frames(report, details)
    actual = details['helper_inputs'][0][0]
    assert any(item['actual'] == actual and item['role'] == 'CALL_ARGUMENT'
               and item['binding']['match'] is True for item in frames[()]['consumers'])
    assert any(item['actual'] == details['extract_input'] and item['binding']['match'] is True
               for item in frames[()]['consumers'])


def test_deleting_final_rows_keeps_helper_inventory_and_original_final_consumers():
    complete, details = await_consumer_call_program()
    missing, removed = await_consumer_call_program(final_adapters=False)
    assert complete.operations == missing.operations and complete.values == missing.values
    assert complete.regions == missing.regions
    before = _outcome(_await(_index(complete), details), details)
    after = _outcome(_await(_index(missing), removed), removed)
    assert before['key'] == after['key']
    assert tuple(item['actual'] for item in before['consumers']) == tuple(
        item['actual'] for item in after['consumers'])
    before_graph = _consumer(before, details['helper_inputs'][0][0])['consumer_graph']
    after_graph = _consumer(after, removed['helper_inputs'][0][0])['consumer_graph']
    before_frames, after_frames = _frames(before_graph, details), _frames(after_graph, removed)
    assert tuple(before_frames) == tuple(after_frames)
    assert {key: tuple(item['key'] for item in frame['consumers'])
            for key, frame in before_frames.items()} == {
        key: tuple(item['key'] for item in frame['consumers'])
        for key, frame in after_frames.items()}
    extractor = _extractor(after, removed, final_adapters=False)
    assert 'await_final_adapter_missing' in extractor['gaps']
    assert extractor['status'] in ('PARTIAL', 'MISSING')
