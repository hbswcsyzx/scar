"""A body exception keeps its origin when synchronous cleanup changes delivery.

The body, driver cleanup and caller completion are distinct original sites.
Supplied declarations do not establish native identity or authorize a rewrite.
"""
from dataclasses import replace

import pytest

from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.program.model import (
    CompletionResult, ExitKind, InvokeLiteralResult, StateVersionValue,
    TerminatorKind, ValueKind,
)
from scar.ir.program.protocols import HostTerminal, OwnedUse
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_await_raise_cleanup_graphs import await_raise_cleanup_program
from tests.fixtures.program_await_raise_sources_graphs import await_raise_source_program


BUDGET = 1_048_576


def _core(graph):
    return replace(graph, protocol_scopes=(), protocol_operations=(),
        protocol_call_inputs=(), protocol_result_consumers=(), protocol_bindings=())


def _index(graph):
    require_valid(_core(graph))
    require_valid(graph)
    return ProgramIndex(graph)


def _report(index, details, *, budget=BUDGET):
    return index.protocol_obligations(details['acquisition_scope'],
        budget=budget)['connections']['families']['await']


def _outcome(report, details):
    outcome, = tuple(row for row in report['outcomes']
        if row['source'] == details['source']
        and row['drive_outcome'] == details['drive_outcome']
        and row['advance_operation'] == details['advance_operation'])
    assert outcome['kind'] == 'EXCEPTION'
    assert outcome['payload'] == details['raise_cleanup']['root_source']
    assert outcome['conversion_legs'] == ()
    return outcome


def _sync_driver_and_real_body(graph, details, cuts):
    definition = details['raise_cleanup']
    operations = {operation.id: operation for operation in graph.operations}
    driver = definition['driver_region']
    assert any(row.region == driver.id for row in graph.driver_interfaces)
    assert all(row.region != driver.id for row in graph.resumable_bodies)
    assert all(operations[identity].terminator is None
        or operations[identity].terminator.kind is not TerminatorKind.SUSPEND
        for block in driver.blocks for identity in block.operations)
    body = details['body']
    body_operations = tuple(operations[identity] for block in body.blocks for identity in block.operations)
    assert sum(operation.terminator is not None
        and operation.terminator.kind is TerminatorKind.SUSPEND
        for operation in body_operations) == cuts
    assert details['body_terminal'].terminator.kind is TerminatorKind.RAISE
    assert details['drive_outcome'].source == details['body_terminal'].id
    assert definition['drive'].operation == details['drive_outcome'].drive


def _flags(view):
    names = tuple(name for name in view
        if name.endswith('_verified') or name == 'transformation_authorized')
    assert names
    assert all(view[name] is False for name in names)


def _states(graph, terminal, kind):
    operations = {operation.id: operation for operation in graph.operations}
    values = {value.id: value for value in graph.values}
    parent_result = terminal['advance_result']
    assert type(parent_result) is InvokeLiteralResult
    parent = operations[parent_result.edge.operation]
    edge = parent.terminator.successors[parent_result.edge.successor_index]
    assert edge.kind is kind
    assert parent_result.result.index == 0
    signature, = tuple(row for row in parent.completions if row.kind is kind)
    source = operations[terminal['terminal'].operation]
    uses = {values[use.value].location: OwnedUse(source.id, use.id)
        for use in source.uses if use.id in source.terminator.values
        and isinstance(values[use.value], StateVersionValue)}
    expected = {(slot, uses[type_.location],
        InvokeLiteralResult(parent_result.edge, CompletionResult(slot)))
        for slot, type_ in enumerate(signature.types) if type_.kind is ValueKind.STATE}
    assert expected
    assert {(row['slot'], row['source'], row['target'])
            for row in terminal['states']} == expected
    assert all(row['binding']['match'] is True for row in terminal['states'])


def _continuation(outcome, details):
    definition = details['raise_cleanup']
    row, = tuple(row for row in outcome['continuations']
        if row['packet']['source'] == definition['root_source'])
    assert row['packet']['definition'] is None
    assert row['packet']['exception_binding'] is None
    continuation = row['continuation']
    assert continuation['source'] == definition['root_source']
    assert continuation['frontier_only'] is False
    assert definition['drive_edge'] in row['choices']
    _flags(continuation)
    return continuation


def _terminals(outcome, details):
    definition = details['raise_cleanup']
    expected = set(definition['payload_uses'])
    rows = tuple(row for row in outcome['terminals'] if row['actual'] in expected)
    assert {row['actual'] for row in rows} == expected
    assert {row['terminal'] for row in rows} == {
        HostTerminal(operation.id) for operation in definition['terminals']}
    assert len(rows) == len(expected)
    return rows


def _consumers(index, graph, outcome):
    assert outcome['consumers'], 'the body exception still has real caller consumers'
    for consumer in outcome['consumers']:
        assert consumer['requires_final_extraction'] is False
        assert consumer['binding']['match'] is True
        actual = consumer['actual']
        if type(actual) is HostTerminal:
            operation = next(row for row in graph.operations if row.id == actual.operation)
            values = {row.id: row for row in graph.values}
            use, = tuple(use for use in operation.uses
                if use.id in operation.terminator.values
                and not isinstance(values[use.value], StateVersionValue))
            actual = OwnedUse(operation.id, use.id)
        assert index.source_binding(consumer['advance_result'], actual,
            guard=consumer['choices'], budget=BUDGET)['match'] is True


def test_preserved_body_raise_crosses_sync_cleanup_to_current_parent_and_consumer():
    graph, details = await_raise_cleanup_program(mode='preserve')
    index = _index(graph)
    report = _report(index, details)
    outcome = _outcome(report, details)
    # Check the existing consumer relation before inspecting the new receipts;
    # preserve already had consumers, while its full continuation was absent.
    _consumers(index, graph, outcome)
    _sync_driver_and_real_body(graph, details, 2)
    continuation = _continuation(outcome, details)
    assert continuation['actions'] and continuation['projections']
    assert not continuation['overrides'] and not continuation['suspensions']
    assert not continuation['boundaries']
    assert continuation['status'] == 'DECLARED'
    for terminal in _terminals(outcome, details):
        assert terminal['root_source'] == details['raise_cleanup']['root_source']
        assert terminal['current_source'] == terminal['root_source']
        assert terminal['role'] == 'packet'
        assert terminal['binding']['match'] is True
        assert terminal['root_binding']['match'] is True
        assert terminal['delivery_binding']['match'] is True
        _states(graph, terminal, ExitKind.RAISE)
    _flags(report)


@pytest.mark.parametrize(('mode', 'role', 'kind'), (
    ('replace_raise', 'packet', ExitKind.RAISE),
    ('replace_return', 'reference', ExitKind.NORMAL),
), ids=('new-raise', 'new-return'))
def test_legal_replacement_keeps_body_raise_origin_and_delivers_its_current_completion(mode, role, kind):
    graph, details = await_raise_cleanup_program(mode=mode)
    # A legal finally override must pass the existing public validator.  The
    # old BodyRaise copy rule is exercised before reading added view fields.
    index = _index(graph)
    report = _report(index, details)
    outcome = _outcome(report, details)
    _consumers(index, graph, outcome)
    _sync_driver_and_real_body(graph, details, 2)
    continuation = _continuation(outcome, details)
    assert continuation['overrides']
    assert not continuation['suspensions']
    assert all(row['source_applicability_verified'] is False
               for row in continuation['overrides'])
    definition = details['raise_cleanup']
    for terminal in _terminals(outcome, details):
        assert terminal['root_source'] == definition['root_source']
        assert terminal['current_source'] == definition['replacement_source']
        assert terminal['current_source'] != terminal['root_source']
        assert terminal['role'] == role
        assert terminal['root_binding']['match'] is False
        assert terminal['binding']['match'] is True
        assert terminal['delivery_binding']['match'] is True
        assert index.source_binding(terminal['current_source'], terminal['actual'],
            guard=terminal['choices'], budget=BUDGET)['match'] is True
        assert index.source_binding(terminal['root_source'], terminal['actual'],
            guard=terminal['choices'], budget=BUDGET)['match'] is False
        _states(graph, terminal, kind)
    assert not report['issues']
    _flags(report)


def test_opaque_after_body_raise_cleanup_is_a_specific_incomplete_boundary():
    graph, details = await_raise_cleanup_program(mode='opaque')
    index = _index(graph)
    report = _report(index, details)
    outcome = _outcome(report, details)
    _sync_driver_and_real_body(graph, details, 2)
    continuation = _continuation(outcome, details)
    opaque = details['raise_cleanup']['opaque']
    assert continuation['status'] == 'PARTIAL'
    assert continuation['known_inventory_complete'] is False
    assert any(row['operation'].id == opaque.id and row['kind'] == 'OPAQUE_OPERATION'
               for row in continuation['boundaries'])
    assert 'packet_continuation_intervening_effects_unresolved' in continuation['gaps']
    assert not any(row['binding']['match'] is True for row in continuation['terminals'])
    assert outcome['status'] == 'PARTIAL'
    assert not all(leg['status'] == 'NOT_APPLICABLE' for leg in outcome['advance_legs'])
    assert all(consumer['requires_final_extraction'] is False for consumer in outcome['consumers'])
    _flags(report)


def test_wrong_terminal_packet_after_body_raise_cleanup_is_not_a_legal_replacement():
    graph, details = await_raise_cleanup_program(mode='wrong_terminal')
    core = _core(graph)
    require_valid(core)
    definition = details['raise_cleanup']
    index = ProgramIndex(core)
    report = index.completion_continuations(definition['root_source'],
        choices=definition['choices'], cross_resume=False, budget=BUDGET)
    receipts = tuple(row for row in report['terminals']
                     if row['actual'] in definition['payload_uses'])
    assert {row['actual'] for row in receipts} == set(definition['payload_uses'])
    assert not report['overrides']
    assert report['status'] == 'CONTRADICTED'
    for receipt in receipts:
        assert receipt['current_source'] == receipt['root_source'] == definition['root_source']
        assert receipt['binding']['match'] is False
        assert receipt['root_binding']['match'] is False
    assert validate(graph), 'a known wrong current terminal packet remains a protocol error'
    _flags(report)


@pytest.mark.parametrize(('source_kind', 'zero_cut', 'mode'), (
    ('general', True, 'preserve'), ('general', False, 'replace_raise'),
    ('wrapper', True, 'replace_raise'), ('wrapper', False, 'preserve'),
), ids=('general-zero-preserve', 'general-two-new-raise',
        'wrapper-zero-new-raise', 'wrapper-two-preserve'))
def test_real_general_and_wrapper_sources_reach_body_raise_cleanup_without_a_converter(
        source_kind, zero_cut, mode):
    graph, details = await_raise_source_program(source_kind=source_kind,
        zero_cut=zero_cut, cleanup_mode=mode)
    index = _index(graph)
    report = _report(index, details)
    outcome = _outcome(report, details)
    _sync_driver_and_real_body(graph, details, 0 if zero_cut else 2)
    assert outcome['source'] == details['source']
    assert details['extract'] is None
    assert details['stage_regions'] == ()
    _consumers(index, graph, outcome)
    continuation = _continuation(outcome, details)
    assert continuation['actions'] and continuation['projections']
    for terminal in _terminals(outcome, details):
        assert terminal['root_source'] == details['raise_cleanup']['root_source']
        assert terminal['current_source'] == details['raise_cleanup']['current_source']
        assert terminal['role'] == 'packet'
        assert terminal['binding']['match'] is True
        assert terminal['delivery_binding']['match'] is True
        assert terminal['root_binding']['match'] is (mode == 'preserve')
        _states(graph, terminal, ExitKind.RAISE)
    _flags(report)


def test_budget_one_retains_original_exception_and_drive_successor_denominators():
    graph, details = await_raise_cleanup_program()
    report = _report(_index(graph), details, budget=1)
    outcome = _outcome(report, details)
    assert outcome['status'] == 'NOT_CHECKED'
    assert outcome['consumers'] == ()
    operations = {operation.id: operation for operation in graph.operations}
    original_successors = sum(len(operations[row.operation].terminator.successors)
                              for row in graph.body_drives)
    inventory = report['outcome_inventory']
    assert inventory['drive_successors_total'] == original_successors
    assert inventory['enumerated_count'] == len(report['outcomes'])
    assert inventory['checked_count'] == 0
    assert inventory['known_inventory_complete'] is False
    assert inventory['jobs_total'] is None and inventory['pending_count'] is None
    assert inventory['cursor'] is not None or report['cursor'] is not None
    _flags(report)


def test_budget_ending_after_complete_walker_does_not_exclude_unjoined_parent_legs(monkeypatch):
    # The zero-cut native-wrapper graph has one BodyRaise source/outcome and
    # no completion constructor. Its first structured terminal charge therefore
    # belongs to this exact target, rather than an earlier sibling outcome.
    graph, details = await_raise_source_program(source_kind='wrapper',
        zero_cut=True, cleanup_mode='preserve')
    index = _index(graph)
    checkpoints = []
    original = ValidityBudget.spend

    def record(accounting, kind, cost=1, path=''):
        if kind == 'await_structured_terminals':
            checkpoints.append(accounting.used)
        return original(accounting, kind, cost, path)

    # Observe real accounting only. All source/current/copy solvers and the
    # walker execute unchanged; the second public query uses an ordinary limit.
    with monkeypatch.context() as observed:
        observed.setattr(ValidityBudget, 'spend', record)
        complete = _report(index, details)
    exceptions = tuple(row for row in complete['outcomes'] if row['kind'] == 'EXCEPTION')
    assert len(exceptions) == 1
    full = _outcome(complete, details)
    assert exceptions[0] is full
    assert full['conversion_legs'] == ()
    assert checkpoints and checkpoints[0] > 0
    assert full['terminals'] and all(row['delivery_binding']['match'] is True
                                   for row in full['terminals'])

    limited = _report(index, details, budget=checkpoints[0])
    assert {row['key'] for row in limited['outcomes']} == {row['key'] for row in complete['outcomes']}
    outcome = _outcome(limited, details)
    continuation = _continuation(outcome, details)
    assert continuation['known_inventory_complete'] is True
    assert continuation['status'] == 'DECLARED'
    assert continuation['terminals']
    assert outcome['terminals'] == ()
    assert outcome['status'] == 'PARTIAL'
    assert {row['own_result'] for row in outcome['advance_legs']} == {
        row['own_result'] for row in full['advance_legs']}
    assert outcome['advance_legs']
    assert all(row['status'] == 'PARTIAL' for row in outcome['advance_legs'])
    assert limited['outcome_inventory']['known_inventory_complete'] is False
    assert limited['outcome_inventory']['cursor'] is not None or limited['cursor'] is not None
    _flags(limited)
