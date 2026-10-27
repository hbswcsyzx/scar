"""The acquisition's RAISE and its caller's current completion are distinct."""
from dataclasses import replace

import pytest

from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.program.control import ProtocolValueKind, ProtocolValueType
from scar.ir.program.model import (
    CompletionResult, ExitKind, InvokeLiteralResult, OperationResult,
    StateVersionValue, TerminatorKind, ValueKind,
)
from scar.ir.program.protocols import HostTerminal, OwnedUse
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_await_failure_cleanup_graphs import await_failure_cleanup_program


BUDGET = 1_048_576
STAGES = {
    'lookup_raise': 'LOOKUP', 'method_call_raise': 'METHOD_CALL',
    'qualification_reject': 'QUALIFICATION_REJECT',
    'wrapper_constructor_raise': 'WRAPPER_CONSTRUCTION_RAISE',
}


def _core(graph):
    return replace(graph, protocol_scopes=(), protocol_operations=(),
        protocol_call_inputs=(), protocol_result_consumers=(), protocol_bindings=())


def _index(graph):
    require_valid(_core(graph))
    require_valid(graph)
    return ProgramIndex(graph)


def _report(index, details, *, budget=BUDGET):
    return index.protocol_obligations(details['failure_cleanup']['source_ref'].scope,
        budget=budget)['connections']['families']['await']


def _path(report, details, *, own=False):
    definition = details['failure_cleanup']
    stage = ('WRAPPER_CONSTRUCTION_RAISE' if definition['stage'] == 'wrapper_constructor_raise'
        else 'ACQUISITION_RAISE') if own else STAGES[definition['stage']]
    path, = tuple(row for row in report['failure_paths']
        if row['scope'] == definition['source_ref'].scope
        and row['source_operation'] == definition['source_operation'].id
        and getattr(row['stage'], 'value', row['stage']) == stage)
    assert path['source_result'] == definition['source_result']
    assert path['source_edge'] == definition['source_edge']
    assert path['source_edge'] == path['source_result'].edge
    return path


def _source(graph, definition):
    source = next(row for row in graph.operations if row.id == definition['source_operation'].id)
    result = definition['source_result']
    assert type(result) is InvokeLiteralResult
    edge = source.terminator.successors[result.edge.successor_index]
    assert edge.kind is ExitKind.RAISE and result.result == CompletionResult(0)
    signature, = tuple(row for row in source.completions if row.kind is ExitKind.RAISE)
    assert type(signature.types[0]) is ProtocolValueType
    assert signature.types[0].kind is ProtocolValueKind.EXCEPTION_PACKET
    assert edge.arguments[0] == definition['forwarded_use'].use
    assert edge.arguments[1] == CompletionResult(0)
    assert definition['forwarded_use'].use not in source.invoke_arguments
    assert definition['root_packet'].origin.index == 1


def _helper(graph, path, definition):
    if definition['helper_terminal'] is None:
        assert path['terminals'] == ()
        return
    terminal, = tuple(row for row in path['terminals']
        if row['terminal'] == HostTerminal(definition['helper_terminal'].id))
    assert terminal['packet'] == definition['helper_stage_packet_use']
    assert terminal['binding']['match'] is True
    signature, = tuple(row for row in definition['source_operation'].completions
                       if row.kind is ExitKind.RAISE)
    values = {value.id: value for value in graph.values}
    operation = definition['helper_terminal']
    actuals = {values[use.value].location: OwnedUse(operation.id, use.id)
        for use in operation.uses if use.id in operation.terminator.values
        and isinstance(values[use.value], StateVersionValue)}
    expected = {(slot, actuals[type_.location], InvokeLiteralResult(
        definition['source_edge'], CompletionResult(slot)))
        for slot, type_ in enumerate(signature.types) if type_.kind is ValueKind.STATE}
    assert {(row['slot'], row['source'], row['target']) for row in terminal['states']} == expected
    assert expected and all(row['binding']['match'] is True for row in terminal['states'])
    if definition['stage'] == 'qualification_reject':
        assert terminal['stage_source'] is None and terminal['stage_binding'] is None
        assert terminal['control_anchor'] == definition['reject_edge']
        origins = terminal['stage_origins']
        assert origins['recipes']
        packet = definition['packet_definition']
        assert {row['leaf'].id for row in origins['recipes']} == {packet.value}
        assert all(row['leaf'].origin == OperationResult(definition['packet_constructor'].id, 0)
                   for row in origins['recipes'])
        constructor = definition['packet_constructor']
        assert definition['packet_exception_use'] == OwnedUse(constructor.id, packet.exception)
        assert definition['packet_traceback_use'] == OwnedUse(constructor.id, packet.traceback)
    else:
        assert terminal['stage_source'] == definition['stage_source']
        assert terminal['stage_binding']['match'] is True


def _current_states(graph, receipt):
    operation = next(row for row in graph.operations if row.id == receipt['terminal'].operation)
    values = {value.id: value for value in graph.values}
    owned = {use.id: use for use in operation.uses}
    expected = {(ordinal, OwnedUse(operation.id, identity), values[owned[identity].value],
                 values[owned[identity].value].location)
        for ordinal, identity in enumerate(operation.terminator.values)
        if isinstance(values[owned[identity].value], StateVersionValue)}
    assert expected
    assert {(row['ordinal'], row['actual'], row['value'], row['location'])
            for row in receipt['state_uses']} == expected


def _flags(view):
    names = tuple(name for name in view
        if name.endswith('_verified') or name == 'transformation_authorized')
    assert names and all(view[name] is False for name in names)


def _caller(index, graph, path, definition):
    continuation_row, = tuple(row for row in path['caller_continuations']
        if row['packet']['source'] == definition['source_result'])
    continuation = continuation_row['continuation']
    assert continuation['source'] == definition['source_result']
    assert continuation['frontier_only'] is False
    assert definition['source_edge'] in continuation_row['choices']
    assert continuation['actions'] and continuation['projections']
    assert not continuation['suspensions']
    receipts = tuple(row for row in path['caller_terminals']
        if row['actual'] in definition['payload_uses'])
    assert {row['actual'] for row in receipts} == set(definition['payload_uses'])
    assert {row['terminal'] for row in receipts} == {
        HostTerminal(operation.id) for operation in definition['terminals']}
    assert index.source_binding(definition['source_result'], definition['source_consumer'],
        guard=definition['choices'], budget=BUDGET)['match'] is True
    for receipt in receipts:
        assert receipt['actual'] != definition['source_consumer']
        assert receipt['root_source'] == definition['source_result']
        assert receipt['current_source'] == definition['current_source']
        assert receipt['binding']['match'] is True
        assert receipt['root_binding']['match'] is (definition['mode'] == 'preserve')
        assert receipt['requires_final_extraction'] is False
        assert receipt['crossed_suspend'] is False
        assert index.source_binding(receipt['current_source'], receipt['actual'],
            guard=receipt['choices'], budget=BUDGET)['match'] is True
        _current_states(graph, receipt)
    _flags(continuation)
    return receipts


@pytest.mark.parametrize('mode', ('preserve', 'replace_raise', 'replace_return'))
def test_qualification_reject_packet_reaches_get_raise_then_the_callers_current_completion(mode):
    graph, details = await_failure_cleanup_program(stage='qualification_reject', mode=mode)
    index = _index(graph)
    report = _report(index, details)
    definition = details['failure_cleanup']
    _source(graph, definition)
    selected = _path(report, details)
    _helper(graph, selected, definition)
    receipts = _caller(index, graph, selected, definition)
    own = _path(report, details, own=True)
    assert own['terminals'] == ()
    _caller(index, graph, own, definition)
    kind = TerminatorKind.RETURN if mode == 'replace_return' else TerminatorKind.RAISE
    assert all(operation.terminator.kind is kind for operation in definition['terminals'])
    assert all(row['role'] == ('reference' if mode == 'replace_return' else 'packet') for row in receipts)
    assert not report['issues']
    _flags(report)


@pytest.mark.parametrize(('stage', 'mode'), (
    ('lookup_raise', 'preserve'), ('lookup_raise', 'replace_raise'),
    ('method_call_raise', 'preserve'), ('method_call_raise', 'replace_return'),
    ('wrapper_constructor_raise', 'preserve'), ('wrapper_constructor_raise', 'replace_return'),
), ids=('lookup-preserve', 'lookup-new-raise', 'call-preserve', 'call-new-return',
        'constructor-preserve', 'constructor-new-return'))
def test_each_other_failure_origin_keeps_its_own_raise_and_current_caller_completion(stage, mode):
    graph, details = await_failure_cleanup_program(stage=stage, mode=mode)
    index = _index(graph)
    report = _report(index, details)
    definition = details['failure_cleanup']
    _source(graph, definition)
    selected = _path(report, details)
    _helper(graph, selected, definition)
    _caller(index, graph, selected, definition)
    own = _path(report, details, own=True)
    assert own['terminals'] == ()
    _caller(index, graph, own, definition)
    assert all(operation.terminator.kind is (
        TerminatorKind.RETURN if mode == 'replace_return' else TerminatorKind.RAISE)
        for operation in definition['terminals'])
    assert not report['issues']
    _flags(report)


def test_wrong_current_terminal_packet_is_not_an_authorized_finally_replacement():
    graph, details = await_failure_cleanup_program(mode='wrong_terminal')
    core = _core(graph)
    require_valid(core)
    definition = details['failure_cleanup']
    report = ProgramIndex(core).completion_continuations(definition['source_result'],
        choices=definition['choices'], cross_resume=False, budget=BUDGET)
    receipts = tuple(row for row in report['terminals']
        if row['actual'] in definition['payload_uses'])
    assert {row['actual'] for row in receipts} == set(definition['payload_uses'])
    assert report['status'] == 'CONTRADICTED'
    assert not report['overrides']
    for receipt in receipts:
        assert receipt['root_source'] == receipt['current_source'] == definition['source_result']
        assert receipt['binding']['match'] is False
        assert receipt['root_binding']['match'] is False
    # Core legality above is independent of the deliberately false protocol
    # connection. Full validation must retain that known contradiction.
    assert validate(graph)
    _flags(report)


def test_caller_opaque_boundary_does_not_turn_an_unfinished_failure_into_no_consumer():
    graph, details = await_failure_cleanup_program(mode='opaque')
    report = _report(_index(graph), details)
    definition = details['failure_cleanup']
    own = _path(report, details, own=True)
    assert own['terminals'] == ()
    row, = own['caller_continuations']
    continuation = row['continuation']
    assert continuation['status'] == 'PARTIAL'
    assert continuation['known_inventory_complete'] is False
    assert any(boundary['operation'].id == definition['opaque'].id
        and boundary['kind'] == 'OPAQUE_OPERATION' for boundary in continuation['boundaries'])
    assert 'packet_continuation_intervening_effects_unresolved' in continuation['gaps']
    assert not any(receipt['binding']['match'] is True for receipt in own['caller_terminals'])
    assert own['status'] == 'PARTIAL'
    _flags(report)


def test_removing_get_raise_row_and_receipt_preserves_original_failure_keys_and_owned_input():
    graph, details = await_failure_cleanup_program(mode='replace_return')
    original = _report(_index(graph), details)
    definition = details['failure_cleanup']
    changed = replace(graph,
        protocol_operations=tuple(row for row in graph.protocol_operations if row != definition['source_row']),
        protocol_result_consumers=tuple(row for row in graph.protocol_result_consumers
                                        if row.site != definition['source_ref']))
    index = _index(changed)
    report = _report(index, details)
    assert {row['key'] for row in report['failure_paths']} == {
        row['key'] for row in original['failure_paths']}
    own = _path(report, details, own=True)
    assert own['terminals'] == ()
    assert 'await_failure_source_row_missing' in own['gaps']
    assert own['status'] == 'PARTIAL'
    assert index.source_binding(definition['source_result'], definition['source_consumer'],
        guard=definition['choices'], budget=BUDGET)['match'] is True
    _caller(index, changed, own, definition)
    _flags(report)


def test_budget_one_keeps_every_original_failure_key_and_its_unchecked_source_port():
    graph, details = await_failure_cleanup_program()
    index = _index(graph)
    complete = _report(index, details)
    limited = _report(index, details, budget=1)
    assert {row['key'] for row in limited['failure_paths']} == {
        row['key'] for row in complete['failure_paths']}
    for row in limited['failure_paths']:
        assert row['source_result'] == details['failure_cleanup']['source_result']
        assert row['source_edge'] == details['failure_cleanup']['source_edge']
        assert row['status'] == 'NOT_CHECKED'
        assert row['terminals'] == ()
    inventory = limited['failure_path_inventory']
    assert inventory['enumerated_count'] == len(limited['failure_paths'])
    assert inventory['checked_count'] == 0
    assert inventory['known_inventory_complete'] is False
    assert inventory['jobs_total'] is None and inventory['pending_count'] is None
    assert inventory['cursor'] is not None or limited['cursor'] is not None
    _flags(limited)


def test_own_failure_rejects_a_source_receipt_naming_the_independent_current_packet():
    graph, details = await_failure_cleanup_program(
        stage='wrapper_constructor_raise', mode='replace_raise')
    index = _index(graph)
    definition = details['failure_cleanup']
    own = _path(_report(index, details), details, own=True)
    assert own['terminals'] == ()  # No helper loop can carry this obligation.
    wrong = definition['consumer_payload_use']
    assert wrong != definition['source_consumer']
    operation = next(row for row in graph.operations if row.id == wrong.operation)
    use = next(row for row in operation.uses if row.id == wrong.use)
    value = next(row for row in graph.values if row.id == use.value)
    assert type(value) is type(definition['root_packet'])
    assert value.protocol is definition['root_packet'].protocol
    assert index.source_binding(definition['source_result'], wrong,
        guard=definition['choices'], budget=BUDGET)['match'] is False
    original, = tuple(row for row in graph.protocol_result_consumers
                     if row.site == definition['source_ref'])
    corrupted = replace(original, targets=(wrong,))
    changed = replace(graph, protocol_result_consumers=tuple(
        corrupted if row is original else row for row in graph.protocol_result_consumers))
    require_valid(_core(changed))
    assert 'protocol_await_failure_source_consumer' in {issue.code for issue in validate(changed)}


def test_complete_caller_walker_does_not_hide_a_truncated_state_and_source_join(monkeypatch):
    # A primitive constructor has one own failure seed and no helper. Thus the
    # first caller-state charge belongs to this exact original failure key.
    graph, details = await_failure_cleanup_program(stage='wrapper_constructor_raise')
    index = _index(graph)
    checkpoints = []
    original = ValidityBudget.spend

    def record(accounting, kind, cost=1, path=''):
        if kind == 'await_failure_caller_state_uses':
            checkpoints.append(accounting.used)
        return original(accounting, kind, cost, path)

    # Observe actual work without replacing any binding, state or path result.
    # The second call runs unmodified code with an ordinary measured limit.
    with monkeypatch.context() as observed:
        observed.setattr(ValidityBudget, 'spend', record)
        complete = _report(index, details)
    full = _path(complete, details, own=True)
    assert len(complete['failure_paths']) == 1
    assert full['terminals'] == () and full['caller_terminals']
    assert checkpoints and checkpoints[0] > 0
    assert all(row['state_uses'] for row in full['caller_terminals'])

    limited = _report(index, details, budget=checkpoints[0])
    assert {row['key'] for row in limited['failure_paths']} == {
        row['key'] for row in complete['failure_paths']}
    own = _path(limited, details, own=True)
    raw, = own['caller_continuations']
    assert raw['continuation']['known_inventory_complete'] is True
    assert raw['continuation']['status'] == 'DECLARED'
    assert raw['continuation']['terminals']
    assert own['caller_terminals']
    assert all(row['state_uses'] == () and row['status'] == 'PARTIAL'
               for row in own['caller_terminals'])
    assert 'await_failure_caller_state_budget' in own['gaps']
    assert own['status'] == 'PARTIAL'
    inventory = limited['failure_path_inventory']
    assert inventory['known_inventory_complete'] is False
    assert inventory['jobs_total'] is None and inventory['pending_count'] is None
    assert inventory['cursor'] is not None or limited['cursor'] is not None
    _flags(limited)
