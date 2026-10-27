"""Exact captured packets/results remain scoped to their original await call."""
import pytest

from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validation import validate
from scar.ir.program.model import CompletionResult, ExitKind, InvokeLiteralResult, OperationResult
from scar.ir.program.protocols import HostTerminal, OwnedUse
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_await_outcome_graphs import await_outcome_execution


def _index(program, model):
    require_valid(program)
    validation = validate(model, program)
    assert validation.valid, validation.issues
    return ExecutionIndex(model, program)


def _report(program, model, details):
    return _index(program, model).await_body_links(details['static']['acquisition_scope'], budget=1048576)


def _outcome(report, details):
    rows = tuple(row for row in report['outcomes']
        if row['definition']['drive_outcome'] == details['drive_outcome']
        and row['definition']['advance_operation'] == details['static']['drivers'][-1]['caller_call'].id)
    assert len(rows) == 1
    return rows[0]


def _occurrence(row, example):
    rows = tuple(item for item in row['occurrences']
                 if item['advance'] is not None and item['advance'].id == example['advance']
                 and item['drive'] is not None and item['drive'].id == example['body_drives'][-1].drive)
    assert len(rows) == 1
    result, = rows
    assert result['key'] == (row['key'], example['advance'], example['body_drives'][-1].drive)
    assert result['body_outcome'].id == example['body_outcome']
    assert result['selected'] is True
    return result


def _use(model, operation, use):
    rows = tuple(row for row in model.uses if row.operation == operation and row.use == use)
    assert len(rows) == 1
    return rows[0]


def _value(model, identity):
    return next(row for row in model.values if row.id == identity)


def _own_result(program, model, occurrence, port):
    operation = next(row for row in model.operations if row.id == occurrence)
    canonical = next(row for row in program.operations if row.id == operation.operation)
    if type(port) is OperationResult:
        assert port.operation == canonical.id
        return next(row for row in model.values
                    if row.origin == occurrence and row.value == canonical.results[port.index])
    assert type(port) is InvokeLiteralResult
    assert port.edge.operation == canonical.id
    transfer, = tuple(row for row in model.transfers if row.operation == occurrence)
    assert transfer.successor_index == port.edge.successor_index
    edge = canonical.terminator.successors[transfer.successor_index]
    block = next(block for region in program.regions for block in region.blocks if block.id == edge.block)
    formal, = tuple(formal for actual, formal in zip(edge.arguments, block.arguments)
                    if type(actual) is CompletionResult and actual.index == port.result.index)
    return next(row for row in model.values if row.origin == transfer.target and row.value == formal)


def _assert_binding(binding, source, target):
    assert binding['match'] is True
    assert binding['source_value'].id == source.id
    assert binding['target_value'].id == target.id
    if source.id != target.id:
        assert binding['support']


def _consumers(occurrence, details):
    return tuple(row for row in occurrence['consumers']
                 if row['definition']['actual'] == details['static']['extract_input'])


def _selected_consumer(occurrence, details):
    rows = tuple(row for row in _consumers(occurrence, details) if row['selected'] is True)
    assert len(rows) == 1
    return rows[0]


def _assert_final_leg(program, model, consumer, example):
    selected = tuple(leg for leg in consumer['legs'] if leg['selected'] is True)
    assert len(selected) == 1
    leg, = selected
    own = _own_result(program, model, example['extraction'], leg['definition']['own_result'])
    assert leg['own_value'].id == own.id
    targets = tuple(target for target in leg['targets']
                    if target['definition'] == HostTerminal(next(row.operation for row in model.operations
                                                               if row.id == example['final'])))
    assert len(targets) == 1
    target, = targets
    assert target['operation'].id == example['final']
    terminal = next(row for row in program.operations if row.id == target['operation'].operation)
    expected_use = _use(model, example['final'], terminal.terminator.values[0])
    expected_value = _value(model, expected_use.value)
    assert target['use'] == expected_use and target['value'].id == expected_value.id
    _assert_binding(target['binding'], own, expected_value)
    assert leg['states']
    for state in leg['states']:
        definition = state['definition']
        source = _own_result(program, model, example['extraction'], definition['source'])
        actual = definition['target']
        assert type(actual) is OwnedUse and actual.operation == terminal.id
        destination = _value(model, _use(model, example['final'], actual.use).value)
        assert state['source'].id == source.id and state['target'].id == destination.id
        _assert_binding(state['binding'], source, destination)
    assert all(other['status'] == 'NOT_APPLICABLE' for other in consumer['legs'] if other['selected'] is False)


@pytest.mark.parametrize('zero_cut', (True, False), ids=('zero-cut', 'two-cut'))
def test_actual_completion_packet_and_final_value_stay_in_their_exact_instance(zero_cut):
    program, model, details = await_outcome_execution(zero_cut=zero_cut, instances=2)
    report = _report(program, model, details)
    row = _outcome(report, details)
    for example in details['instances']:
        occurrence = _occurrence(row, example)
        assert {source['occurrence'].id for source in occurrence['matched_sources']} == {example['acquisition']}
        assert tuple(call['association'].id for call in occurrence['call_chain']) == (example['call_activations'][-1].id,)
        selected = tuple(leg for leg in occurrence['conversion_legs'] if leg['selected'] is True)
        assert len(selected) == 1
        conversion, = selected
        assert conversion['occurrence'].id == example['conversion']
        assert conversion['definition']['role'] == 'COMPLETION'
        own = _own_result(program, model, example['conversion'], conversion['definition']['own_result'])
        assert conversion['own_value'].id == own.id
        assert len(conversion['packets']) == 1
        packet, = conversion['packets']
        origin = next(value.origin for value in program.values if value.id == packet['definition'].value)
        assert packet['occurrence'].id == example['driver_scopes'][-1][2][origin.operation]
        expected_use = _use(model, packet['occurrence'].id, packet['definition'].exception)
        assert packet['exception_use'] == expected_use
        assert packet['exception_value'].id == _value(model, expected_use.value).id == own.id
        expected_packet = _own_result(program, model, packet['occurrence'].id, origin)
        assert packet['value'].id == expected_packet.id and packet['value'].id != own.id
        _assert_binding(packet['binding'], own, _value(model, expected_use.value))
        consumer = _selected_consumer(occurrence, details)
        assert consumer['operation'].id == example['extraction']
        assert consumer['definition']['requires_final_extraction'] is True
        actual = _use(model, example['extraction'], details['static']['extract_input'].use)
        assert consumer['use'] == actual
        advance_value = _own_result(program, model, example['advance'], consumer['definition']['advance_result'])
        assert consumer['advance_value'].id == advance_value.id
        _assert_binding(consumer['binding'], advance_value, _value(model, actual.value))
        terminals = tuple(terminal for terminal in conversion['terminals']
                          if terminal['operation'] is not None and terminal['operation'].id == example['driver_terminal'])
        assert len(terminals) == 1
        terminal, = terminals
        assert terminal['parent_value'].id == advance_value.id
        assert terminal['packet_value'].id == expected_packet.id
        _assert_binding(terminal['binding'], expected_packet, advance_value)
        _assert_final_leg(program, model, consumer, example)
    assert all(report[key] is False for key in ('source_runtime_verified', 'runtime_identity_verified',
                                               'value_identity_verified', 'transformation_authorized'))


@pytest.mark.parametrize('constructor_raised', (False, True), ids=('completion-packet', 'constructor-failure'))
def test_actual_extractor_raise_uses_its_own_packet_after_the_selected_constructor_leg(constructor_raised):
    program, model, details = await_outcome_execution(zero_cut=True,
        constructor_raised=constructor_raised, extractor_raised=True)
    report = _report(program, model, details)
    example, = details['instances']
    occurrence = _occurrence(_outcome(report, details), example)
    selected, = tuple(leg for leg in occurrence['conversion_legs'] if leg['selected'] is True)
    assert selected['occurrence'].id == example['conversion']
    assert selected['definition']['role'] == ('CONSTRUCTION_FAILURE' if constructor_raised else 'COMPLETION')
    own = _own_result(program, model, example['conversion'], selected['definition']['own_result'])
    assert selected['own_value'].id == own.id
    consumer = _selected_consumer(occurrence, details)
    assert consumer['definition']['requires_final_extraction'] is (not constructor_raised)
    final, = tuple(leg for leg in consumer['legs'] if leg['selected'] is True)
    assert final['definition']['kind'] is ExitKind.RAISE
    _assert_final_leg(program, model, consumer, example)


def test_missing_exact_extractor_use_does_not_borrow_the_sibling_instance():
    program, model, details = await_outcome_execution(instances=2, missing_use=0)
    report = _report(program, model, details)
    row = _outcome(report, details)
    missing, sibling = details['instances']
    current = _occurrence(row, missing)
    consumers = _consumers(current, details)
    assert consumers
    assert all(consumer['use'] is None for consumer in consumers if consumer['selected'] is not False)
    assert all(consumer['operation'] is None or consumer['operation'].id == missing['extraction']
               for consumer in consumers)
    assert all(consumer['status'] != 'DECLARED' for consumer in consumers if consumer['selected'] is not False)
    assert current['status'] == 'PARTIAL' and current['gaps']
    actual_sibling = _selected_consumer(_occurrence(row, sibling), details)
    assert actual_sibling['operation'].id == sibling['extraction']
    assert actual_sibling['use'] == _use(model, sibling['extraction'], details['static']['extract_input'].use)


def test_missing_extractor_suffix_keeps_the_static_key_and_other_instance_terminal():
    program, model, details = await_outcome_execution(instances=2, missing_suffix=0)
    report = _report(program, model, details)
    row = _outcome(report, details)
    missing, sibling = details['instances']
    assert missing['extraction'] not in {operation.id for operation in model.operations}
    current = _occurrence(row, missing)
    consumers = _consumers(current, details)
    assert consumers and all(consumer['operation'] is None and consumer['use'] is None for consumer in consumers)
    assert current['status'] == 'PARTIAL' and current['gaps']
    observed = _selected_consumer(_occurrence(row, sibling), details)
    assert observed['operation'].id == sibling['extraction']
    _assert_final_leg(program, model, observed, sibling)


def test_deleting_final_metadata_keeps_captured_consumer_and_its_static_outcome_key():
    before_program, before_model, before_details = await_outcome_execution(zero_cut=True)
    program, model, details = await_outcome_execution(zero_cut=True, attach_final_adapter=False)
    assert before_model.operations == model.operations and before_model.uses == model.uses
    before = _report(before_program, before_model, before_details)
    report = _report(program, model, details)
    assert tuple(row['key'] for row in before['outcomes']) == tuple(row['key'] for row in report['outcomes'])
    example, = details['instances']
    occurrence = _occurrence(_outcome(report, details), example)
    consumer = _selected_consumer(occurrence, details)
    assert consumer['operation'].id == example['extraction']
    assert consumer['use'] == _use(model, example['extraction'], details['static']['extract_input'].use)
    assert consumer['definition']['final_rows'] == ()
    assert 'await_final_adapter_missing' in consumer['definition']['gaps']
    assert consumer['legs'] and consumer['status'] == 'PARTIAL'
    assert occurrence['status'] == 'PARTIAL'


def test_budget_one_preserves_original_successor_inventory_and_reports_unchecked_work():
    program, model, details = await_outcome_execution()
    index = _index(program, model)
    report = index.await_body_links(details['static']['acquisition_scope'], budget=1)
    operations = {row.id: row for row in program.operations}
    original = sum(len(operations[drive.operation].terminator.successors) for drive in program.body_drives)
    assert report['outcome_inventory']['drive_successors_total'] == original
    assert report['outcome_inventory']['known_inventory_complete'] is False
    assert report['outcome_inventory']['jobs_total'] is None
    assert report['outcome_inventory']['cursor'] is not None
    assert report['budget']['used'] <= 1 and report['budget']['truncated'] is True
    assert report['status'] == 'PARTIAL'


def test_late_budget_exhaustion_never_reports_a_complete_tail_or_unchecked_compatibility():
    program, model, details = await_outcome_execution(zero_cut=True)
    index = _index(program, model)
    scope = details['static']['acquisition_scope']
    complete = index.await_body_links(scope, budget=1048576)
    assert complete['budget']['truncated'] is False
    cost = complete['budget']['used']
    assert cost > 1
    limited = index.await_body_links(scope, budget=cost - 1)
    assert limited['budget']['truncated'] is True
    assert limited['budget']['used'] <= cost - 1
    exhausted = tuple(limited[field] for field in ('outcome_inventory', 'failure_path_inventory')
                      if limited[field]['cursor'] is not None)
    assert exhausted
    tail = exhausted[-1]
    assert tail['known_inventory_complete'] is False
    assert tail['jobs_total'] is None and tail['pending_count'] is None
    assert tail['cursor'] is not None

    def applicable_bindings(value, seen):
        if type(value) not in (dict, tuple, list) or id(value) in seen:
            return
        seen.add(id(value))
        if type(value) is dict:
            if value.get('selected') is False or value.get('status') == 'NOT_APPLICABLE':
                return
            if {'source_value', 'target_value', 'match', 'compatibility'} <= value.keys():
                yield value
            for key, child in value.items():
                if key != 'definition':  # Static D4 evidence has no dynamic compatibility duty.
                    yield from applicable_bindings(child, seen)
        else:
            for child in value:
                yield from applicable_bindings(child, seen)

    for binding in applicable_bindings(limited, set()):
        if binding['match'] is True:
            assert binding['compatibility'] is not None


def test_unselected_extractor_raise_gap_stays_static_without_poisoning_actual_normal():
    program, model, details = await_outcome_execution(zero_cut=True,
        omit_extractor_raise_adapter=True)
    assert details['omitted_final_rows']
    report = _report(program, model, details)
    row = _outcome(report, details)
    static_consumers = tuple(consumer for consumer in row['definition']['consumers']
        if consumer['actual'] == details['static']['extract_input']
        and consumer['requires_final_extraction'] is True)
    assert static_consumers
    missing = 'await_final_adapter_leg_missing'
    assert any(missing in leg['gaps'] for consumer in static_consumers for leg in consumer['legs']
               if leg['kind'] is ExitKind.RAISE)
    example, = details['instances']
    occurrence = _occurrence(row, example)
    consumer = _selected_consumer(occurrence, details)
    assert missing not in consumer['gaps']
    assert missing not in occurrence['gaps']
    selected, = tuple(leg for leg in consumer['legs'] if leg['selected'] is True)
    assert selected['definition']['kind'] is ExitKind.NORMAL
    assert missing not in selected['gaps']
    inactive, = tuple(leg for leg in consumer['legs']
                       if leg['definition']['kind'] is ExitKind.RAISE)
    assert inactive['selected'] is False and inactive['status'] == 'NOT_APPLICABLE'
    assert missing in inactive['definition']['gaps']
    _assert_final_leg(program, model, consumer, example)
