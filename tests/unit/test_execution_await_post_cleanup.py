"""This synchronous D's C1 packet and current state reach its own caller.

The body still has two distinct cuts.  Static future continuations cannot stand
in for the terminal of this CallActivation, or for missing instance evidence.
"""
import pytest

from scar.ir.execution.composition_routes import routes
from scar.ir.execution.coordinates import InitialEntry
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validation import validate
from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.program.control import PendingPayload
from scar.ir.program.model import CompletionResult, ExitKind, StateVersionValue, TerminatorKind, ValueKind
from scar.ir.program.protocols import HostTerminal
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_await_post_cleanup_graphs import await_post_cleanup_execution


BUDGET = 1_048_576


def _index(program, model):
    require_valid(program)
    validation = validate(model, program)
    assert validation.valid, validation.issues
    return ExecutionIndex(model, program)


def _row(report, details):
    row, = tuple(row for row in report['outcomes']
        if row['definition']['drive_outcome'] == details['drive_outcome']
        and row['definition']['advance_operation'] == details['static']['advance_operation'])
    return row


def _occurrence(row, example):
    occurrence, = tuple(occurrence for occurrence in row['occurrences']
        if occurrence['advance'] is not None and occurrence['advance'].id == example['advance']
        and occurrence['drive'] is not None and occurrence['drive'].id == example['body_drives'][-1].drive)
    return occurrence


def _selected_leg(occurrence, example):
    selected, = tuple(leg for leg in occurrence['conversion_legs'] if leg['selected'] is True)
    assert selected['definition']['edge'] == example['selected_leg']['edge']
    assert selected['occurrence'].id == example['conversion']
    for other in occurrence['conversion_legs']:
        if other is not selected:
            assert other['selected'] is False
            assert not any(row.get('selected') is True for row in other['terminals'])
    return selected


def _terminal(leg, example):
    terminal, = tuple(row for row in leg['terminals']
        if row['definition']['terminal'] == HostTerminal(example['selected_leg']['terminals'][0].id))
    return terminal


def _projection(report, example):
    arguments = tuple(argument for transfer in report['transfers']
        if transfer['occurrence'].id == example['dispatch']
        for argument in transfer['arguments'] if type(argument['argument']) is PendingPayload)
    assert len(arguments) == 1
    return arguments[0]['projection']['payload']


def _current_states(program, model, terminal, example):
    """Compare current terminal inputs to this call's original state results."""
    uses = {(row.operation, row.use): row for row in model.uses}
    values = {row.id: row for row in model.values}
    canonical = {row.id: row for row in program.values}
    call = next(row for row in program.operations if row.id == example['selected_leg']['edge'].operation)
    conversion_state_values = set()
    conversion_transfer, = tuple(row for row in model.transfers if row.operation == example['conversion'])
    conversion_edge = call.terminator.successors[conversion_transfer.successor_index]
    conversion_landing = next(block for region in program.regions for block in region.blocks
                              if block.id == conversion_edge.block)
    for argument, formal in zip(conversion_edge.arguments, conversion_landing.arguments):
        if type(argument) is CompletionResult and type(canonical[formal]) is StateVersionValue:
            conversion_state_values.update(row.id for row in model.values
                if row.origin == conversion_transfer.target and row.value == formal)
    expected = {uses[example['driver_terminal'], actual.use].value
                for actual in example['selected_leg']['state_uses']}
    assert len(expected) == 2
    assert expected.isdisjoint(conversion_state_values)
    assert {row['source'].id for row in terminal['states']} == expected
    advance = next(row for row in model.operations if row.id == example['advance'])
    parent = next(operation for operation in program.operations if operation.id == advance.operation)
    transfer, = tuple(row for row in model.transfers if row.operation == example['advance'])
    edge = parent.terminator.successors[transfer.successor_index]
    landing = next(block for region in program.regions for block in region.blocks if block.id == edge.block)
    signature, = tuple(row for row in parent.completions if row.kind is edge.kind)
    state_slots = {slot: type_.location for slot, type_ in enumerate(signature.types)
                   if type_.kind is ValueKind.STATE}
    assert len(state_slots) == len(terminal['states']) == 2
    for state in terminal['states']:
        slot = state['definition']['slot']
        assert slot in state_slots
        assert canonical[state['source'].value].location == state_slots[slot]
        formal, = tuple(formal for actual, formal in zip(edge.arguments, landing.arguments)
                         if type(actual) is CompletionResult and actual.index == slot)
        current, = tuple(row for row in model.values
                          if row.origin == transfer.target and row.value == formal)
        assert state['target'] == current
        assert state['binding']['match'] is True
        assert values[state['source'].id] == state['source']


def _flags(report):
    for name in ('source_runtime_verified', 'runtime_identity_verified',
                 'value_identity_verified', 'transformation_authorized'):
        assert report[name] is False


@pytest.mark.parametrize('constructor_raised', (False, True), ids=('constructor-N', 'constructor-R'))
def test_each_actual_constructor_leg_crosses_sync_c1_and_its_own_call_completion(constructor_raised):
    program, model, details = await_post_cleanup_execution(constructor_raised=constructor_raised)
    index = _index(program, model)
    report = index.await_body_links(details['static']['acquisition_scope'], budget=BUDGET)
    projected = routes(index._content_context(), budget=ValidityBudget(BUDGET))
    row = _row(report, details)
    for example in details['instances']:
        assert len(example['body_segments']) == 3
        segments = tuple(segment for segment in model.segments
                         if segment.activation == example['driver_activation'])
        assert len(segments) == 1 and type(segments[0].ingress) is InitialEntry
        definition = example['selected_leg']
        assert not any(operation.terminator is not None
            and operation.terminator.kind is TerminatorKind.SUSPEND
            for operation in program.operations if any(operation.id in block.operations
                for block in details['static']['post_cleanup']['driver_region'].blocks))
        receipt = _projection(projected, example)
        assert receipt['definition'] == example['pending_definition']
        assert receipt['constructor'].id == example['pending_constructor']
        assert receipt['payload_use'].operation == example['pending_constructor']
        assert receipt['payload_use'].use == example['pending_payload_use']
        assert receipt['selector'].operation == example['dispatch']
        assert receipt['binding']['match'] is True and receipt['token_path']
        token_use, = tuple(use for use in model.uses if use.operation == example['dispatch']
                          and use.use == receipt['selector'].use)
        assert token_use.value != receipt['payload_value'].id
        occurrence = _occurrence(row, example)
        assert occurrence['selected'] is True
        leg = _selected_leg(occurrence, example)
        terminal = _terminal(leg, example)
        assert terminal['selected'] is True
        assert terminal['operation'].id == example['driver_terminal']
        assert terminal['operation'].id == example['call_activations'][-1].completion
        assert terminal['packet_use'].operation == example['driver_terminal']
        assert terminal['packet_use'].use == definition['payload_uses'][0].use
        assert terminal['packet_value'] == receipt['target_value']
        assert terminal['binding']['match'] is True
        assert terminal['root_binding']['match'] is True
        _current_states(program, model, terminal, example)
        consumers = tuple(consumer for consumer in terminal['consumers']
            if consumer['definition']['actual'] == details['static']['extract_input'])
        assert consumers and all(consumer['binding']['match'] is True for consumer in consumers)
        assert all(consumer['operation'].id == example['extraction'] for consumer in consumers)
        assert all(consumer['definition']['requires_final_extraction'] is (not constructor_raised)
                   for consumer in consumers)
        _flags(receipt['binding'])
    _flags(report)


def test_actual_replace_return_has_its_own_reference_normal_completion_without_extraction():
    program, model, details = await_post_cleanup_execution(mode='replace_return')
    index = _index(program, model)
    report = index.await_body_links(details['static']['acquisition_scope'], budget=BUDGET)
    projected = routes(index._content_context(), budget=ValidityBudget(BUDGET))
    row = _row(report, details)
    for example in details['instances']:
        occurrence = _occurrence(row, example)
        terminal = _terminal(_selected_leg(occurrence, example), example)
        receipt = _projection(projected, example)
        assert receipt['definition'] == example['selected_leg']['replacement_pending']
        assert receipt['constructor'].id == example['pending_constructor']
        assert receipt['binding']['match'] is True
        assert terminal['selected'] is True
        assert terminal['operation'].id == example['driver_terminal']
        assert terminal['packet_value'] == receipt['target_value']
        assert terminal['binding']['match'] is True
        assert terminal['root_binding']['match'] is not True
        assert terminal['status'] != 'CONTRADICTED'
        assert terminal['definition']['current_source'] == example['selected_leg']['replacement_source']
        _current_states(program, model, terminal, example)
        expected = HostTerminal(details['static']['post_cleanup']['caller_normal_terminal'].id)
        consumers = tuple(consumer for consumer in terminal['consumers']
                          if consumer['definition']['actual'] == expected)
        assert consumers and all(consumer['binding']['match'] is True for consumer in consumers)
        assert all(consumer['operation'].id == example['final'] for consumer in consumers)
        assert all(consumer['definition']['requires_final_extraction'] is False for consumer in consumers)
        assert example['extraction'] is None and example['implementation_calls'] == ()
        assert not any(call.caller == example['advance']
            and call.completion != example['driver_terminal'] for call in model.call_activations)
    _flags(report)


@pytest.mark.parametrize('missing', ('missing_payload_use', 'missing_dispatch'))
def test_missing_sync_c1_instance_zero_evidence_never_borrows_the_complete_sibling(missing):
    program, model, details = await_post_cleanup_execution(**{missing: 0})
    index = _index(program, model)
    report = index.await_body_links(details['static']['acquisition_scope'], budget=BUDGET)
    row = _row(report, details)
    first, second = details['instances']
    partial = _occurrence(row, first)
    complete = _occurrence(row, second)
    assert partial['status'] not in ('DECLARED', 'NOT_APPLICABLE')
    assert partial['gaps']
    missing_terminal = _terminal(_selected_leg(partial, first), first)
    present_terminal = _terminal(_selected_leg(complete, second), second)
    assert missing_terminal['status'] not in ('DECLARED', 'NOT_APPLICABLE')
    assert missing_terminal['gaps']
    assert missing_terminal['binding']['match'] is not True
    assert present_terminal['selected'] is True
    assert present_terminal['operation'].id == second['driver_terminal']
    assert present_terminal['binding']['match'] is True
    if missing == 'missing_dispatch':
        assert missing_terminal['operation'] is None and missing_terminal['selected'] is None
    else:
        projected = routes(index._content_context(), budget=ValidityBudget(BUDGET))
        absent, present = _projection(projected, first), _projection(projected, second)
        assert absent['binding']['match'] is not True and absent['gaps']
        assert present['binding']['match'] is True
        assert present['constructor'].id != first['pending_constructor']
    _flags(report)
