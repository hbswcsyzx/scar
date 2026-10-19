"""Continuous async protocol obligations, independently of supplied post rows."""
from dataclasses import replace

from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.program.protocol_async import async_connections
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_async_pipeline_graphs import (
    async_pipeline_program, await_handoff_program, missing_session_update_program,
    shared_async_update_program,
)


def _without_protocol(graph):
    return replace(graph, protocol_scopes=(), protocol_operations=(), protocol_bindings=(),
                   protocol_call_inputs=(), protocol_result_consumers=())


def test_await_host_return_must_consume_its_exact_body_export():
    graph, details = await_handoff_program(wrong=True)
    require_valid(_without_protocol(graph))
    terminal = details['host_terminal']
    assert next(use.value for use in terminal.uses if use.id == details['host_payload_use']) == details['interface'].receiver
    assert details['original_handoff_value'] != details['interface'].receiver
    report = validate(graph)
    assert 'protocol_copy' in {issue.code for issue in report}


def test_removing_whole_session_update_keeps_the_original_await_obligation():
    original, details = await_handoff_program()
    graph, _ = missing_session_update_program()
    require_valid(_without_protocol(graph))
    assert graph.operations == original.operations
    assert graph.values == original.values
    assert graph.body_outcome_commits == original.body_outcome_commits
    assert not graph.session_updates
    index = ProgramIndex(graph)
    report = async_connections(ConnectionContext(graph, index=index, budget=ValidityBudget(4096)))
    obligations = tuple(row for row in report['obligations'] if row.get('source') == details['outcome'])
    assert obligations, 'the original AWAIT source still requires a session consumer'
    assert any(row['status'] == 'MISSING' for row in obligations)
    assert any(row['code'] in ('async_session_outcome_missing', 'async_session_update_missing',
                               'async_session_consumer_missing') for row in report['gaps'])
    assert report['source_runtime_verified'] is False
    assert report['transformation_authorized'] is False


def _view(graph, *, budget=131072):
    require_valid(graph)
    return async_connections(ConnectionContext(graph, index=ProgramIndex(graph), budget=ValidityBudget(budget)))


def test_main_pipeline_has_one_body_request_and_three_real_latest_state_calls():
    from scar.ir.program.model import ExitKind, StateVersionValue
    from scar.ir.program.protocols import OwnedUse
    from scar.ir.program.resumption import SuspensionFlavor

    graph, details = async_pipeline_program()
    require_valid(_without_protocol(graph))
    require_valid(graph)
    index = ProgramIndex(graph)
    values = {value.id: value for value in graph.values}
    blocks = {block.id: block for region in graph.regions for block in region.blocks}
    assert len(graph.resumable_bodies) == len(graph.resumable_creates) == len(graph.async_request_creates) == 1
    assert len(details['calls']) == len(graph.body_drives) == 3
    assert [details['body'][key].terminator.flavor for key in ('await1', 'await2', 'async_yield')] == [
        SuspensionFlavor.AWAIT, SuspensionFlavor.AWAIT, SuspensionFlavor.ASYNC_YIELD]
    prior_states = None
    for number, stage in enumerate(details['drivers']):
        call, interface = stage['caller_call'], stage['interface']
        arguments = {formal: index.use_site(use).use for formal, use in
                     zip(stage['entry_formals'], call.invoke_arguments)}
        receiver = arguments[interface.receiver]
        assert index.source_binding(details['request']['request_result'], OwnedUse(call.id, receiver.id))['match'] is True
        state_actuals = {values[formal].location: use.value for formal, use in arguments.items()
                         if isinstance(values[formal], StateVersionValue)}
        if prior_states is not None:
            assert state_actuals == prior_states
        normal = next((edge for edge in call.terminator.successors if edge.kind is ExitKind.NORMAL), None)
        if normal is not None:
            prior_states = {values[formal].location: formal for formal in blocks[normal.block].arguments
                            if isinstance(values[formal], StateVersionValue)}
        assert {row.kind for row in call.completions} == {exit_.kind for exit_ in stage['driver_region'].exits}
    third = details['drivers'][2]
    assert {row.kind for row in third['caller_call'].completions} == {ExitKind.RAISE}
    assert third['host_terminal'].terminator.kind.value == 'RAISE'
    assert not graph.terminal_frame_releases


def test_main_public_query_keeps_await_handoffs_separate_from_item_completion():
    from scar.ir.program.lifecycle import SessionPost
    graph, details = async_pipeline_program()
    require_valid(graph)
    public = ProgramIndex(graph).protocol_obligations(budget=131072)
    report = public['connections']['families']['async']
    assert not public['budget']['truncated']
    expected = {stage['outcome']: stage for stage in details['drivers']}
    sources = {row['source']: row for row in report['session_consumers']}
    assert set(sources) == set(expected)
    for outcome, stage in expected.items():
        source = sources[outcome]
        assert source['expected_post'] is stage['update'].post
        assert source['expected_post'] is (SessionPost.COMPLETE if stage is details['drivers'][2] else SessionPost.HOLD)
        assert source['known_inventory_complete']
        assert source['targets']
        assert all(target['update'] == stage['update'] for target in source['targets'])
        assert all(target['source_binding']['match'] is True for target in source['targets'])
    handoffs = {row['source']: row for row in report['handoffs']}
    assert set(handoffs) == {stage['outcome'] for stage in details['drivers'][:2]}
    assert all(row['consumers'] and all(item['match'] is True for item in row['consumers']) for row in handoffs.values())
    assert public['source_runtime_verified'] is False and public['transformation_authorized'] is False
    assert public['protocol_implementation_complete'] is False


def test_real_helper_normal_post_and_raise_partial_states_stay_distinct():
    from scar.ir.program.lifecycle import SessionPost
    from scar.ir.program.model import CompletionResult, ExitKind, StateVersionValue
    graph, details = async_pipeline_program(helper_stage=1)
    require_valid(_without_protocol(graph))
    require_valid(graph)
    index = ProgramIndex(graph)
    stage = details['drivers'][1]
    helper = index.operations[stage['update'].operation]
    normal = next(number for number, edge in enumerate(helper.terminator.successors) if edge.kind is ExitKind.NORMAL)
    raised = next(number for number, edge in enumerate(helper.terminator.successors) if edge.kind is ExitKind.RAISE)
    assert {row.post for row in index.lifecycle_edge(helper.id, normal).session.posts} == {SessionPost.HOLD}
    assert not index.lifecycle_edge(helper.id, raised).session.posts
    for edge in helper.terminator.successors:
        assert all(type(argument) is CompletionResult for argument in edge.arguments)
        block = next(block for region in graph.regions for block in region.blocks if block.id == edge.block)
        states = {index.values[formal].location for formal in block.arguments
                  if isinstance(index.values[formal], StateVersionValue)}
        assert states == {location.id for location in graph.locations}


def test_shared_hold_post_preserves_both_selected_sources_and_exact_incoming_choices():
    graph, details = shared_async_update_program()
    require_valid(_without_protocol(graph))
    report = _view(graph)
    sources = {row['source']: row for row in report['session_consumers']}
    assert set(sources) == set(details['outcomes'])
    for number, outcome in enumerate(details['outcomes']):
        row = sources[outcome]
        assert row['targets'] and row['known_inventory_complete']
        for target in row['targets']:
            assert target['update'] == details['update']
            assert details['selected_drive_edges'][number] in target['choices']
            assert details['incoming_edges'][number] in target['choices']
            assert details['incoming_edges'][1 - number] not in target['choices']
            assert target['source_binding']['match'] is True
    assert all(item['match'] is True for row in report['handoffs'] for item in row['consumers'])


def test_shared_post_missing_one_binding_does_not_remove_its_source():
    graph, details = shared_async_update_program(omit_binding=1)
    report = _view(graph)
    sources = {row['source']: row for row in report['session_consumers']}
    assert set(sources) == set(details['outcomes'])
    missing = sources[details['outcomes'][1]]
    assert missing['status'] == 'MISSING'
    assert missing['targets'] and all(target['binding'] is None for target in missing['targets'])


def test_wrong_body_on_one_shared_incoming_is_a_known_source_conflict():
    graph, _ = shared_async_update_program(wrong_body_arm=1)
    require_valid(_without_protocol(graph))
    assert 'async_session_body' in {issue.code for issue in validate(graph)}


def test_budget_one_keeps_every_original_shared_source_and_cursor():
    graph, details = shared_async_update_program()
    report = _view(graph, budget=1)
    sources = report['session_consumers']
    assert {row['source'] for row in sources} == set(details['outcomes'])
    assert all(not row['known_inventory_complete'] for row in sources)
    assert report['cursor'] is not None
    assert all(row['status'] in ('NOT_CHECKED', 'PARTIAL') for row in sources)
