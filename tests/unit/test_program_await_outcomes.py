"""Completion consumers remain obligations when optional declarations vanish."""
from dataclasses import replace

import pytest

from scar.ir.program.model import CompletionResult, ExitKind, InvokeLiteralResult
from scar.ir.program.protocols import HostTerminal, OwnedUse
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_await_outcome_graphs import await_outcome_program


def _core(graph):
    return replace(graph, protocol_scopes=(), protocol_operations=(),
        protocol_call_inputs=(), protocol_result_consumers=(), protocol_bindings=())


def _report(graph, details):
    require_valid(graph)
    return ProgramIndex(graph).protocol_obligations(details['acquisition_scope'],
        budget=524288)['connections']['families']['await']


def _outcome(report, details):
    matches = tuple(row for row in report['outcomes']
        if row['source'] == details['source']
        and row['advance_operation'] == details['advance_operation']
        and row['drive_outcome'] == details['drive_outcome'])
    assert len(matches) == 1
    row, = matches
    assert row['scope'] == details['acquisition_scope']
    assert row['payload'] == details['payload']
    assert row['kind'] == 'RETURN_COMPLETION'
    return row


def _completion_consumers(row, details):
    matches = tuple(consumer for consumer in row['consumers']
        if consumer['actual'] == details['extract_input']
        and consumer['requires_final_extraction'] is True)
    assert matches
    return matches


def _codes(gaps):
    return {gap if type(gap) is str else gap.get('code') if type(gap) is dict
            else getattr(gap, 'code', None) for gap in gaps}


def _expected_slots(operation):
    return {ControlEdgeReference(operation.id, number): InvokeLiteralResult(
        ControlEdgeReference(operation.id, number), CompletionResult(0))
        for number in range(len(operation.terminator.successors))}


@pytest.mark.parametrize('zero_cut', (True, False), ids=('zero-cut', 'two-cut'))
def test_removing_whole_final_adapters_keeps_body_return_consumer_and_all_own_legs(zero_cut):
    complete, details = await_outcome_program(zero_cut=zero_cut)
    removed, missing = await_outcome_program(zero_cut=zero_cut, final_adapters=False)
    require_valid(_core(removed))
    assert complete.operations == removed.operations and complete.values == removed.values
    assert complete.regions == removed.regions
    assert all(row not in removed.protocol_operations for row in details['final_rows'])
    assert all(receipt.site not in details['final_sites'] for receipt in removed.protocol_result_consumers)
    before, after = _report(complete, details), _report(removed, missing)
    assert tuple(row['key'] for row in before['outcomes']) == tuple(row['key'] for row in after['outcomes'])
    assert before['outcome_inventory']['enumerated_count'] == after['outcome_inventory']['enumerated_count']
    assert before['outcome_inventory']['drive_successors_total'] == after['outcome_inventory']['drive_successors_total']
    original, retained = _outcome(before, details), _outcome(after, missing)
    assert tuple(consumer['actual'] for consumer in original['consumers']) == tuple(
        consumer['actual'] for consumer in retained['consumers'])
    expected = _expected_slots(details['extract'])
    for consumer in _completion_consumers(retained, missing):
        assert consumer['binding']['match'] is True
        assert consumer['final_rows'] == ()
        assert {leg['edge']: leg['own_result'] for leg in consumer['legs']} == expected
        assert 'await_final_adapter_missing' in _codes(consumer['gaps'])
        assert consumer['status'] in ('MISSING', 'PARTIAL')
    assert after['source_runtime_verified'] is False
    assert after['runtime_identity_verified'] is False
    assert after['transformation_authorized'] is False


@pytest.mark.parametrize('zero_cut', (True, False), ids=('zero-cut', 'two-cut'))
def test_conversion_and_extraction_keep_own_normal_and_raised_payloads_separate(zero_cut):
    graph, details = await_outcome_program(zero_cut=zero_cut)
    report = _report(graph, details)
    row = _outcome(report, details)
    conversion = details['conversion']
    converted = {leg['edge']: leg for leg in row['conversion_legs']
                 if leg['operation'] == conversion.id}
    assert set(converted) == set(_expected_slots(conversion))
    for edge, expected_result in _expected_slots(conversion).items():
        leg = converted[edge]
        assert leg['own_result'] == expected_result
        kind = conversion.terminator.successors[edge.successor_index].kind
        assert leg['role'] == ('COMPLETION' if kind is ExitKind.NORMAL else 'CONSTRUCTION_FAILURE')
        assert leg['input_binding']['match'] is True
        assert leg['terminals']
        assert leg['states']
        if kind is ExitKind.NORMAL:
            assert leg['packets']  # The own Reference becomes a declared whole packet.

    consumers = _completion_consumers(row, details)
    for consumer in consumers:
        assert consumer['binding']['match'] is True
        assert consumer['final_rows'] == details['final_rows']
        legs = {leg['edge']: leg for leg in consumer['legs']}
        assert set(legs) == set(_expected_slots(details['extract']))
        for edge, expected_result in _expected_slots(details['extract']).items():
            leg = legs[edge]
            kind = details['extract'].terminator.successors[edge.successor_index].kind
            assert leg['own_result'] == expected_result and leg['kind'] is kind
            assert leg['bindings'] and all(binding['match'] is True for binding in leg['bindings'])
            assert leg['targets'] and leg['states']
            assert all({'slot', 'source', 'target', 'binding'} <= set(state) for state in leg['states'])
            assert all(state['binding']['match'] is True for state in leg['states'])
            if kind is ExitKind.NORMAL:
                assert HostTerminal(details['final'].id) in leg['targets']
    failure_edge = next(edge for edge in converted
                        if conversion.terminator.successors[edge.successor_index].kind is ExitKind.RAISE)
    failures = tuple(consumer for consumer in row['consumers']
                     if consumer['actual'] == details['extract_input']
                     and failure_edge in consumer['choices'])
    assert failures and all(consumer['requires_final_extraction'] is False for consumer in failures)
    assert report['source_runtime_verified'] is False
    assert report['runtime_identity_verified'] is False
    assert report['transformation_authorized'] is False


@pytest.mark.parametrize('zero_cut', (True, False), ids=('zero-cut', 'two-cut'))
def test_same_typed_entry_reference_cannot_replace_the_final_extractors_own_result(zero_cut):
    good, details = await_outcome_program(zero_cut=zero_cut)
    wrong, changed = await_outcome_program(zero_cut=zero_cut, wrong_final=True)
    require_valid(good)
    core = _core(wrong)
    require_valid(core)
    assert good.values == wrong.values and good.regions == wrong.regions
    old_use = details['original_final'].terminator.values[0]
    actual = OwnedUse(changed['final'].id, old_use)
    assert next(use for use in changed['final'].uses if use.id == old_use).value == details['sent_value']
    assert details['sent_value'] != details['original_final_value']
    normal = next(port for port in details['extraction_ports']
        if details['extract'].terminator.successors[port.edge.successor_index].kind is ExitKind.NORMAL)
    # The unchanged canonical copy query establishes the precise negative even
    # though the full invalid semantic graph cannot construct a ProgramIndex.
    binding = ProgramIndex(core).source_binding(normal, actual, budget=65536)
    assert binding['match'] is False
    issues = validate(wrong)
    assert issues
    assert {'protocol_result_consumer', 'protocol_copy', 'protocol_await_final_copy'} & {
        issue.code for issue in issues}


@pytest.mark.parametrize('zero_cut', (True, False), ids=('zero-cut', 'two-cut'))
@pytest.mark.parametrize('final_adapters', (True, False), ids=('with-final', 'without-final'))
def test_removing_whole_producer_adapter_keeps_original_return_and_extractor_consumer(
        zero_cut, final_adapters):
    from tests.fixtures.program_await_outcome_graphs import completion_adapter_program

    complete, details = completion_adapter_program(zero_cut=zero_cut, final_adapters=final_adapters)
    removed, missing = completion_adapter_program(zero_cut=zero_cut,
        final_adapters=final_adapters, producer_adapter=False)
    require_valid(_core(removed))
    assert complete.operations == removed.operations and complete.values == removed.values
    assert complete.regions == removed.regions and complete.exception_packets == removed.exception_packets
    assert details['conversion_receipts']
    assert all(receipt in complete.protocol_result_consumers for receipt in details['conversion_receipts'])
    assert all(row not in removed.protocol_operations for row in details['conversion_rows'])
    assert all(receipt.site not in details['conversion_sites'] for receipt in removed.protocol_result_consumers)
    before, after = _report(complete, details), _report(removed, missing)
    assert tuple(row['key'] for row in before['outcomes']) == tuple(row['key'] for row in after['outcomes'])
    assert before['outcome_inventory']['enumerated_count'] == after['outcome_inventory']['enumerated_count']
    assert before['outcome_inventory']['drive_successors_total'] == after['outcome_inventory']['drive_successors_total']
    retained = _outcome(after, missing)
    assert 'await_completion_adapter_missing' in _codes(retained['gaps'])
    assert retained['status'] == 'PARTIAL'
    consumers = tuple(row for row in retained['consumers'] if row['actual'] == details['extract_input'])
    assert consumers
    for consumer in consumers:
        assert consumer['binding']['match'] is True
        assert consumer['requires_final_extraction'] is None
        assert {leg['edge']: leg['own_result'] for leg in consumer['legs']} == _expected_slots(details['extract'])
        assert consumer['final_rows'] == (details['final_rows'] if final_adapters else ())


@pytest.mark.parametrize('zero_cut', (True, False), ids=('zero-cut', 'two-cut'))
def test_budget_one_preserves_all_original_drive_successors_and_unknown_job_total(zero_cut):
    graph, details = await_outcome_program(zero_cut=zero_cut)
    require_valid(graph)
    operations = {row.id: row for row in graph.operations}
    original_total = sum(len(operations[drive.operation].terminator.successors)
                         for drive in graph.body_drives)
    assert original_total > 0
    public = ProgramIndex(graph).protocol_obligations(details['acquisition_scope'], budget=1)
    report = public['connections']['families']['await']
    inventory = report['outcome_inventory']
    assert inventory['drive_successors_total'] == original_total
    assert inventory['enumerated_count'] == len(report['outcomes'])
    assert inventory['checked_count'] <= inventory['enumerated_count']
    assert inventory['known_inventory_complete'] is False
    assert inventory['jobs_total'] is None
    assert inventory['pending_count'] is None
    assert inventory['cursor'] is not None
    assert public['budget']['used'] <= 1
    assert public['budget']['truncated'] is True
    assert report['source_runtime_verified'] is False
    assert report['transformation_authorized'] is False


def test_two_cut_handoff_keeps_its_original_export_without_final_extraction():
    from scar.ir.program.lifecycle import DriveOutcomeRef
    from scar.ir.program.model import UseRole
    from scar.ir.program.resumption import SuspendTerminator

    graph, details = await_outcome_program(zero_cut=False)
    report = _report(graph, details)
    operations = {row.id: row for row in graph.operations}
    expected = {DriveOutcomeRef(item['drive'].operation, edge.source)
        for item in details['drivers'] if not item['direct']
        for edge in operations[item['drive'].operation].terminator.successors
        if type(operations[edge.source].terminator) is SuspendTerminator}
    handoffs = tuple(row for row in report['outcomes']
                     if row['source'] == details['source'] and row['kind'] == 'HANDOFF')
    assert expected
    assert {row['drive_outcome'] for row in handoffs} == expected
    observed = {OwnedUse(operation.id, use.id) for operation in details['handoffs']
                for use in operation.uses if use.role is UseRole.REFERENCE}
    for row in handoffs:
        assert row['payload'].outcome == row['drive_outcome']
        assert row['consumers']
        assert all(consumer['requires_final_extraction'] is False for consumer in row['consumers'])
        assert any(consumer['actual'] in observed for consumer in row['consumers'])
        assert 'await_final_adapter_missing' not in _codes(row['gaps'])
