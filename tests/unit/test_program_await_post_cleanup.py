"""A real synchronous driver C1 continuation is not a body suspension.

The original conversion, whole packet, current replacement and caller result
are separate sources.  These tests use the public await obligations view and
grant no native applicability, runtime identity or transformation authority.
"""
from dataclasses import replace

import pytest

from scar.ir.program.model import (
    CompletionResult, ExitKind, InvokeLiteralResult, StateVersionValue,
    TerminatorKind, ValueKind,
)
from scar.ir.program.protocols import HostTerminal, OwnedUse
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_await_post_cleanup_graphs import await_post_cleanup_program


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
    row, = tuple(row for row in report['outcomes']
        if row['source'] == details['source']
        and row['advance_operation'] == details['advance_operation']
        and row['drive_outcome'] == details['drive_outcome'])
    return row


def _check_receipt_fields(continuation, definition):
    allowed = {definition['packet_source']}
    if definition['replacement_source'] is not None:
        allowed.add(definition['replacement_source'])
    assert continuation['checks']
    for check in continuation['checks']:
        assert check['root_source'] == definition['packet_source']
        assert check['current_source'] == check['source']
        assert check['current_source'] in allowed
        assert type(check['choices']) is tuple
        assert definition['edge'] in check['choices']
        assert len({edge.operation for edge in check['choices']}) == len(check['choices'])
        assert type(check['context']) is tuple and check['context']
        assert check['crossed_suspend'] is False


def _legs(outcome, details):
    expected = details['post_cleanup']['legs']
    assert {row['edge'] for row in outcome['conversion_legs']} == {row['edge'] for row in expected}
    for definition in expected:
        leg, = tuple(row for row in outcome['conversion_legs'] if row['edge'] == definition['edge'])
        assert leg['kind'] is definition['kind']
        assert leg['own_result'] == definition['own_result']
        candidates = tuple(row for row in leg['continuations']
                           if row['packet']['source'] == definition['packet_source'])
        assert len(candidates) == 1
        candidate, = candidates
        assert candidate['packet'] in leg['packets']
        if definition['kind'] is ExitKind.NORMAL:
            assert candidate['packet']['definition'].value == definition['packet_value'].id
            assert candidate['packet']['exception_binding']['match'] is True
            assert definition['packet_source'] != definition['own_result']
        else:
            assert candidate['packet']['definition'] is None
            assert candidate['packet']['exception_binding'] is None
            assert definition['packet_source'] == definition['own_result']
        # These are the case's known constraints, not an enumerated full path.
        assert definition['edge'] in candidate['choices']
        continuation = candidate['continuation']
        assert continuation['frontier_only'] is False
        assert continuation['source'] == definition['packet_source']
        _check_receipt_fields(continuation, definition)
        yield definition, leg, continuation


def _terminal_receipts(continuation, definition):
    expected = set(definition['payload_uses'])
    rows = tuple(row for row in continuation['terminals'] if row['actual'] in expected)
    assert {row['actual'] for row in rows} == expected
    assert {row['terminal'] for row in rows} == {HostTerminal(row.id) for row in definition['terminals']}
    assert len(rows) == len(expected)
    for row in rows:
        assert row['root_source'] == definition['packet_source']
        assert definition['edge'] in row['choices']
        assert len({edge.operation for edge in row['choices']}) == len(row['choices'])
        assert row['crossed_suspend'] is False
        assert row['binding']['match'] is True
    return rows


def _flags(report, *continuations):
    for name in ('source_runtime_verified', 'runtime_identity_verified',
                 'value_identity_verified', 'transformation_authorized'):
        assert report[name] is False
    for continuation in continuations:
        for name in ('source_runtime_verified', 'runtime_identity_verified',
                     'native_applicability_verified', 'transformation_authorized'):
            assert continuation[name] is False
        assert all(value is False for name, value in continuation.items()
                   if name.endswith('_verified') or name == 'transformation_authorized')


def _sync_driver(graph, details):
    region = details['post_cleanup']['driver_region']
    operations = {row.id: row for row in graph.operations}
    assert any(row.region == region.id for row in graph.driver_interfaces)
    assert all(row.region != region.id for row in graph.resumable_bodies)
    assert not any(operations[identity].terminator is not None
        and operations[identity].terminator.kind is TerminatorKind.SUSPEND
        for block in region.blocks for identity in block.operations)


def _delivery_states(graph, details, terminal, kind):
    """Current terminal states map to their own parent result ordinals."""
    operations = {row.id: row for row in graph.operations}
    values = {row.id: row for row in graph.values}
    parent = operations[details['advance_operation']]
    result = terminal['advance_result']
    assert type(result) is InvokeLiteralResult and result.edge.operation == parent.id
    edge = parent.terminator.successors[result.edge.successor_index]
    assert edge.kind is kind and result.result.index == 0
    signature, = tuple(row for row in parent.completions if row.kind is kind)
    own_terminal = operations[terminal['terminal'].operation]
    actuals = {values[use.value].location: OwnedUse(own_terminal.id, use.id)
        for use in own_terminal.uses if use.id in own_terminal.terminator.values
        and isinstance(values[use.value], StateVersionValue)}
    expected = {(slot, actuals[type_.location], InvokeLiteralResult(result.edge, CompletionResult(slot)))
        for slot, type_ in enumerate(signature.types) if type_.kind is ValueKind.STATE}
    assert {(row['slot'], row['source'], row['target']) for row in terminal['states']} == expected
    assert expected
    assert terminal['delivery_binding']['match'] is True
    assert all(row['binding']['match'] is True for row in terminal['states'])


def _caller_consumers(index, graph, consumers):
    operations = {row.id: row for row in graph.operations}
    values = {row.id: row for row in graph.values}
    assert consumers
    for consumer in consumers:
        actual = consumer['actual']
        operation = operations[actual.operation]
        if type(actual) is HostTerminal:
            identities = tuple(use.id for use in operation.uses
                if use.id in operation.terminator.values and not isinstance(values[use.value], StateVersionValue))
            assert len(identities) == 1
            actual = OwnedUse(operation.id, identities[0])
        assert consumer['binding']['match'] is True
        assert index.source_binding(consumer['advance_result'], actual,
            guard=consumer['choices'], budget=BUDGET)['match'] is True
        source = consumer['advance_result']
        parent = operations[source.edge.operation]
        kind = parent.terminator.successors[source.edge.successor_index].kind
        signature, = tuple(row for row in parent.completions if row.kind is kind)
        current_uses = tuple(use for use in operation.uses
            if isinstance(values[use.value], StateVersionValue)
            and (use.id in operation.invoke_arguments if operation.terminator is not None
                 and operation.terminator.kind is TerminatorKind.INVOKE else
                 use.id in operation.terminator.values))
        for slot, type_ in enumerate(signature.types):
            if type_.kind is not ValueKind.STATE:
                continue
            actual_state, = tuple(OwnedUse(operation.id, use.id) for use in current_uses
                                  if values[use.value].location == type_.location)
            assert index.source_binding(InvokeLiteralResult(source.edge, CompletionResult(slot)),
                actual_state, guard=consumer['choices'], budget=BUDGET)['match'] is True


@pytest.mark.parametrize('depth', (1, 2), ids=('E', 'E-G'))
def test_preserved_conversion_normal_and_raise_cross_sync_c1_to_exact_parent_and_final_consumers(depth):
    graph, details = await_post_cleanup_program(mode='preserve', depth=depth)
    index = _index(graph)
    _sync_driver(graph, details)
    report = _report(index, details)
    outcome = _outcome(report, details)
    assert outcome['kind'] == 'RETURN_COMPLETION'
    continuations = []
    for definition, leg, continuation in _legs(outcome, details):
        continuations.append(continuation)
        assert continuation['status'] == 'DECLARED', continuation
        assert continuation['known_inventory_complete'] is True
        assert continuation['actions'] and continuation['projections']
        assert not continuation['suspensions'] and not continuation['overrides']
        assert not continuation['boundaries']
        assert any(row['operation'].id == definition['dispatch'].id
                   and row['port'] == definition['outgoing_port'].id
                   for row in continuation['projections'])
        for receipt in _terminal_receipts(continuation, definition):
            assert receipt['role'] == 'packet'
            assert receipt['current_source'] == receipt['root_source']
            assert receipt['root_binding']['match'] is True
            assert index.source_binding(receipt['root_source'], receipt['actual'],
                guard=receipt['choices'], budget=BUDGET)['match'] is True
        assert leg['terminals']
        for terminal in leg['terminals']:
            _delivery_states(graph, details, terminal, ExitKind.RAISE)
    # The constructor NORMAL's packet retains completion semantics. Its own
    # RAISE is a separate construction failure, never a manufactured completion.
    completion = tuple(row for row in outcome['consumers']
        if row['role'] == 'COMPLETION' and row['actual'] == details['extract_input'])
    assert completion and all(row['requires_final_extraction'] is True for row in completion)
    assert all(row['requires_final_extraction'] is False for row in outcome['consumers']
               if row['role'] == 'CONSTRUCTION_FAILURE')
    _caller_consumers(index, graph, outcome['consumers'])
    implementation = completion[0]['implementation']
    assert len(implementation['frames']) == depth
    expected_outputs = {InvokeLiteralResult(ControlEdgeReference(details['extract'].id, number),
        CompletionResult(slot)) for number, edge in enumerate(details['extract'].terminator.successors)
        for signature in details['extract'].completions if signature.kind is edge.kind
        for slot in range(len(signature.types))}
    assert {row['source'] for row in implementation['outputs']} == expected_outputs
    assert all(terminal['match'] is True for row in implementation['outputs'] for terminal in row['terminals'])
    _flags(report, *continuations)


@pytest.mark.parametrize(('mode', 'role', 'kind'),
    (('replace_raise', 'packet', ExitKind.RAISE), ('replace_return', 'reference', ExitKind.NORMAL)),
    ids=('finally-new-raise', 'finally-new-return'))
def test_legal_finally_replacement_tracks_current_source_without_authorizing_old_completion(mode, role, kind):
    graph, details = await_post_cleanup_program(mode=mode)
    index = _index(graph)
    _sync_driver(graph, details)
    report = _report(index, details)
    outcome = _outcome(report, details)
    assert outcome['kind'] == 'RETURN_COMPLETION'  # B itself still really returned.
    continuations = []
    for definition, leg, continuation in _legs(outcome, details):
        continuations.append(continuation)
        assert continuation['overrides']
        assert not continuation['suspensions']
        assert all(row['source_applicability_verified'] is False for row in continuation['overrides'])
        for receipt in _terminal_receipts(continuation, definition):
            assert receipt['role'] == role
            assert receipt['current_source'] == definition['replacement_source']
            assert receipt['current_source'] != receipt['root_source']
            assert receipt['root_binding']['match'] is False
            assert index.source_binding(receipt['current_source'], receipt['actual'],
                guard=receipt['choices'], budget=BUDGET)['match'] is True
            assert index.source_binding(receipt['root_source'], receipt['actual'],
                guard=receipt['choices'], budget=BUDGET)['match'] is False
        terminals = tuple(row for row in leg['terminals']
            if row['terminal'] in {HostTerminal(row.id) for row in definition['terminals']})
        assert terminals and all(row['delivery_binding']['match'] is True for row in terminals)
        for terminal in terminals:
            _delivery_states(graph, details, terminal, kind)
    assert outcome['consumers']
    assert all(row['requires_final_extraction'] is False for row in outcome['consumers'])
    _caller_consumers(index, graph, outcome['consumers'])
    assert not report['issues'], 'a fresh legal override is not a bad copy of the old completion packet'
    _flags(report, *continuations)


def test_an_opaque_operation_after_c1_is_an_exact_boundary_not_a_successful_frontier():
    graph, details = await_post_cleanup_program(mode='opaque')
    report = _report(_index(graph), details)
    outcome = _outcome(report, details)
    rows = tuple(_legs(outcome, details))
    assert rows
    for definition, leg, continuation in rows:
        opaque = definition['opaque']
        assert continuation['status'] == 'PARTIAL'
        assert continuation['known_inventory_complete'] is False
        assert any(row['operation'].id == opaque.id and row['kind'] == 'OPAQUE_OPERATION'
                   for row in continuation['boundaries'])
        assert 'packet_continuation_intervening_effects_unresolved' in continuation['gaps']
        assert not any(row['binding']['match'] is True for row in continuation['terminals'])
    _flags(report, *(row[2] for row in rows))


def test_unrelated_terminal_packet_is_a_real_copy_contradiction_not_a_legal_override():
    graph, details = await_post_cleanup_program(mode='wrong_terminal')
    core = _core(graph)
    require_valid(core)
    index = ProgramIndex(core)
    for definition in details['post_cleanup']['legs']:
        report = index.completion_continuations(definition['packet_source'],
            choices=definition['choices'], cross_resume=False, budget=BUDGET)
        _check_receipt_fields(report, definition)
        assert report['status'] == 'CONTRADICTED'
        assert not report['overrides']
        receipts = tuple(row for row in report['terminals']
                         if row['actual'] in definition['payload_uses'])
        assert {row['actual'] for row in receipts} == set(definition['payload_uses'])
        for receipt in receipts:
            assert receipt['current_source'] == receipt['root_source'] == definition['packet_source']
            assert receipt['binding']['match'] is False
            assert receipt['root_binding']['match'] is False
            assert receipt['crossed_suspend'] is False
            assert index.source_binding(definition['packet_source'], receipt['actual'],
                guard=receipt['choices'], budget=BUDGET)['match'] is False
        _flags(report, report)
    # The source graph is core-valid above. Its false declared protocol copy
    # must be reported by full validation, without requiring an invalid graph
    # to pass the public ProgramIndex constructor.
    assert validate(graph)


def test_tiny_budget_keeps_the_declared_original_body_outcome_key_without_checked_proofs():
    graph, details = await_post_cleanup_program()
    index = _index(graph)
    report = _report(index, details, budget=1)
    outcome = _outcome(report, details)
    assert outcome['status'] == 'NOT_CHECKED'
    assert outcome['conversion_legs'] == () and outcome['consumers'] == ()
    operations = {row.id: row for row in graph.operations}
    total = sum(len(operations[drive.operation].terminator.successors) for drive in graph.body_drives)
    inventory = report['outcome_inventory']
    assert inventory['drive_successors_total'] == total
    assert inventory['known_inventory_complete'] is False
    assert inventory['jobs_total'] is None and inventory['pending_count'] is None
    assert inventory['checked_count'] == 0
    assert inventory['cursor'] is not None or report['cursor'] is not None
    _flags(report)


def _controlled_structured_join(monkeypatch, *, copied, root, delivery):
    """Exercise the connector with typed original ports and explicit premises.

    The seven public integration cases above exercise the relation solvers.
    Here only their returned relation channels are controlled: manufacturing
    an unknown copy by corrupting a canonical graph would test an invalid
    producer rather than this connector's handling of legitimate uncertainty.
    The connector, its selected-edge join and consumer aggregation stay real.
    """
    from scar.ir.execution.validity_budget import ValidityBudget
    from scar.ir.program import await_structured_completion as join
    from scar.ir.program.operation_results import result_legs
    from scar.ir.program.protocol_connection_flow import ConnectionContext

    graph, details = await_post_cleanup_program(mode='preserve')
    core = _core(graph)
    require_valid(core)
    index = ProgramIndex(core)
    ctx = ConnectionContext(core, index=index, budget=ValidityBudget(BUDGET))
    definition, = tuple(row for row in details['post_cleanup']['legs'] if row['kind'] is ExitKind.NORMAL)
    advance = ctx.operations[details['advance_operation']]
    parents = tuple(result_legs(ctx, advance))
    parent, = tuple(row for row in parents if row['kind'] is ExitKind.RAISE)
    actual = details['extract_input']
    # The controlled consumer's copy premise is an actual original edge.
    assert index.source_binding(parent['own_result'], actual, budget=BUDGET)['match'] is True
    terminal, = definition['terminals']
    terminal_actual, = definition['payload_uses']
    packet = {'source': definition['packet_source'],
        'definition': next(row for row in graph.exception_packets
                           if row.value == definition['packet_value'].id),
        'exception_binding': {'match': True, 'gaps': ()}}
    copy_gaps = () if copied is not None else ('controlled_current_copy_unproved',)
    root_gaps = () if root is not None else ('controlled_root_copy_unproved',)
    receipt = {'terminal': HostTerminal(terminal.id), 'actual': terminal_actual,
        'root_source': definition['packet_source'], 'current_source': definition['packet_source'],
        'role': 'packet', 'choices': definition['choices'], 'crossed_suspend': False,
        'binding': {'match': copied, 'gaps': copy_gaps},
        'root_binding': {'match': root, 'gaps': root_gaps},
        'status': 'PARTIAL' if None in (copied, root) else 'DECLARED',
        'gaps': (*copy_gaps, *root_gaps)}
    continuation = {'terminals': (receipt,), 'known_inventory_complete': True,
        'gaps': receipt['gaps'], 'status': receipt['status']}
    returned = ({'packet': packet, 'start': (definition['entry'].id, 0),
                 'choices': definition['choices'], 'continuation': continuation},)
    monkeypatch.setattr(join, 'continuation_rows', lambda *args, **kwargs: (returned, receipt['gaps']))
    monkeypatch.setattr('scar.ir.program.protocol_await._result_copy',
        lambda *args, **kwargs: {'match': delivery,
            'gaps': ('controlled_delivery_unproved',) if delivery is None else ()})
    # State delivery is independently covered by both real conversion legs in
    # the integration tests. No state-equality premise is needed by this join.
    monkeypatch.setattr(join, 'state_links', lambda *args, **kwargs: ())
    calls = []

    def consumers(_ctx, _advance, target, choices, role, requires, _issues):
        calls.append((target, choices, role, requires))
        return ({'actual': actual, 'advance_result': target['own_result'],
            'binding': {'match': True, 'gaps': ()}, 'choices': choices,
            'role': role, 'requires_final_extraction': requires,
            'status': 'DECLARED', 'gaps': ()},), ()

    own_rows = tuple(row for row in details['conversion_rows']
                     if row.contract.output == definition['own_result'])
    assert own_rows
    issues = []
    result = join.structured_completion(ctx, definition['own_result'], (packet,),
        definition['choices'], parents, advance, {'match': True, 'gaps': ()},
        own_rows, 'COMPLETION', consumers, issues)
    return result, calls, issues, actual


def test_unknown_root_preservation_is_not_a_declared_override_or_false_extraction_obligation(monkeypatch):
    result, calls, issues, actual = _controlled_structured_join(monkeypatch,
        copied=None, root=None, delivery=True)
    assert not issues
    assert calls and all(role != 'OVERRIDE' and requires is None for _, _, role, requires in calls)
    assert result['consumers']
    assert all(row['actual'] == actual and row['requires_final_extraction'] is None
               for row in result['consumers'])
    assert result['gaps']


def test_failed_or_unknown_parent_delivery_cannot_launder_a_true_consumer_copy(monkeypatch):
    # These are two independent relation sets over the same valid typed graph,
    # not a cached unknown receipt being mutated into a different assertion.
    for delivery in (False, None):
        with monkeypatch.context() as patch:
            result, _calls, _issues, actual = _controlled_structured_join(patch,
                copied=True, root=True, delivery=delivery)
        assert result['terminals']
        assert all(row['delivery_binding']['match'] is delivery for row in result['terminals'])
        assert all(row['status'] != 'DECLARED' for row in result['consumers'])
        if delivery is None:
            assert result['consumers']
            assert {row['actual'] for row in result['consumers']} == {actual}
            assert all(row['delivery_binding']['match'] is None and row['status'] == 'PARTIAL'
                and row['requires_final_extraction'] is None and row['gaps']
                for row in result['consumers'])
        else:
            assert not result['consumers'] or all(row['delivery_binding']['match'] is False
                and row['status'] in ('NOT_APPLICABLE', 'CONTRADICTED') for row in result['consumers'])


__all__ = []
