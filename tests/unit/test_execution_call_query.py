"""Dynamic calls expose canonical ports without inferring object/value identity."""
from dataclasses import replace

import pytest

from scar.ir.execution.common import Unresolved
from scar.ir.execution.coordinates import UseOccurrence, ValueOccurrence
from scar.ir.execution.ids import CallActivationID, OperationOccurrenceID, ValueOccurrenceID
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.snapshot import snapshot_for
from scar.ir.execution.validation import ExecutionIssue
from scar.ir.program.ids import UseID, ValueID
from scar.ir.program.model import BlockArgument, CompletionResult, StateVersionValue, TerminatorKind
from tests.fixtures.execution_call_graphs import invoke_call_execution, shared_calls_execution


def _index(fixture):
    program, model, *_ = fixture
    return ExecutionIndex(model, program)


def _without_authority(result):
    assert not result['source_runtime_verified']
    assert not result['runtime_identity_verified']
    assert not result['value_identity_verified']
    assert not result['transformation_authorized']


def test_two_calls_share_static_body_but_have_distinct_dynamic_input_output_and_state_routes():
    fixture = shared_calls_execution()
    program, model, *_ = fixture
    index = _index(fixture)
    rows = model.call_activations
    assert len(rows) == 2 and rows[0].caller != rows[1].caller
    assert rows[0].activation != rows[1].activation and rows[0].entry != rows[1].entry
    operations = {row.id: row for row in program.operations}
    occurrences = {row.id: row for row in model.operations}
    values = {row.id: row for row in program.values}
    dynamic = {row.id: row for row in model.values}
    by_definition = {(row.origin, row.value): row for row in model.values}
    uses = {(row.operation, row.use): row for row in model.uses}
    state_actuals, state_results = [], []
    for row in rows:
        view = index.call_activation(row.id)
        listing = index.call_entries(row.caller)
        caller = operations[occurrences[row.caller].operation]
        child_exit = operations[occurrences[row.completion].operation]
        assert listing['status'] == view['status'] == 'DECLARED'
        assert tuple(entry['association'] for entry in listing['entries']) == (row,)
        assert view['association'] == row
        assert view['caller'] == occurrences[row.caller]
        assert view['activation'].id == row.activation
        assert view['entry'].id == row.entry and view['completion'].id == row.completion
        assert len(view['inputs']) == len(caller.call_arguments)
        for ordinal, route in enumerate(view['inputs']):
            assert route['ordinal'] == ordinal
            actual = uses[row.caller, caller.call_arguments[ordinal]]
            assert route['actual'] == actual
            assert route['actual_definition'] == next(use for use in caller.uses if use.id == actual.use)
            assert route['actual_value'] == dynamic[actual.value]
            assert route['formal'] == by_definition[row.entry, route['formal_definition'].id]
            assert route['formal'].id != actual.value  # a route, not a producer substitution
            if type(route['formal_definition']) is StateVersionValue:
                state_actuals.append(actual.value)
        for ordinal, route in enumerate(view['outputs']):
            assert route['ordinal'] == ordinal
            assert route['callee_exit'] == occurrences[row.completion]
            assert route['callee_use'] == uses[row.completion, child_exit.terminator.values[ordinal]]
            assert route['caller_result_definition'] == values[caller.results[ordinal]]
            assert route['caller_result'] == by_definition[row.caller, caller.results[ordinal]]
            assert route['caller_result'].origin == row.caller
            assert route['caller_formal'] is None and route['caller_transfer'] is None
            if type(route['caller_result_definition']) is StateVersionValue:
                state_results.append(route['caller_result'].id)
        _without_authority(view)
        _without_authority(listing)
    assert state_actuals[1] == state_results[0]
    assert state_actuals[0] != state_actuals[1]


def test_same_actual_value_in_two_call_slots_keeps_two_distinct_owned_use_and_formal_ports():
    program, model, *_ = shared_calls_execution()
    rows = model.call_activations
    activation = next(item for item in model.activations if item.id == rows[0].activation)
    region = next(item for item in program.regions if item.id == activation.region)
    entry = next(block for block in region.blocks if block.id == region.entry)
    definition = next(value for value in program.values if value.id == entry.arguments[0])
    second = replace(definition, id=ValueID('call.query.second.formal'), origin=BlockArgument(entry.id, 1))
    callers = {next(item.operation for item in model.operations if item.id == row.caller): row for row in rows}
    operations, extra_uses = [], []
    for operation in program.operations:
        row = callers.get(operation.id)
        if row is not None:
            first = next(use for use in operation.uses if use.id == operation.call_arguments[0])
            duplicate = replace(first, id=UseID(operation.id.value + '.second.actual'))
            original = next(use for use in model.uses if (use.operation, use.use) == (row.caller, first.id))
            extra_uses.append(UseOccurrence(row.caller, duplicate.id, original.value))
            operation = replace(operation, uses=(*operation.uses, duplicate),
                call_arguments=(operation.call_arguments[0], duplicate.id, *operation.call_arguments[1:]))
        operations.append(operation)
    values = tuple(replace(value, origin=replace(value.origin, index=value.origin.index + 1))
        if type(value.origin) is BlockArgument and value.origin.block == entry.id and value.origin.index >= 1
        else value for value in program.values)
    region = replace(region, blocks=tuple(replace(block,
        arguments=(entry.arguments[0], second.id, *entry.arguments[1:]))
        if block.id == entry.id else block for block in region.blocks))
    program = replace(program, regions=tuple(region if item.id == region.id else item for item in program.regions),
                      operations=tuple(operations), values=(*values, second))
    model = replace(model, snapshot=snapshot_for(program), uses=(*model.uses, *extra_uses),
        values=(*model.values, *(ValueOccurrence(ValueOccurrenceID(row.id.value + '.second.formal'),
                                                second.id, row.entry) for row in rows)))
    index = ExecutionIndex(model, program)
    for row in rows:
        first, second, *_ = index.call_activation(row.id)['inputs']
        assert first['actual_value'] == second['actual_value']
        assert first['actual_definition'].id != second['actual_definition'].id
        assert first['actual'].use != second['actual'].use
        assert first['formal'].id != second['formal'].id


@pytest.mark.parametrize('raised', (False, True))
def test_invoke_result_routes_use_actual_completion_kind_and_landing_positions(raised):
    fixture = invoke_call_execution(raised=raised)
    program, model, *_ = fixture
    index = _index(fixture)
    row, = model.call_activations
    view = index.call_activation(row.id)
    ops = {op.id: op for op in program.operations}
    occurrences = {op.id: op for op in model.operations}
    caller = ops[occurrences[row.caller].operation]
    child = ops[occurrences[row.completion].operation]
    assert caller.terminator.kind is TerminatorKind.INVOKE
    assert child.terminator.kind is (TerminatorKind.RAISE if raised else TerminatorKind.RETURN)
    actual_transfer, = (transfer for transfer in model.transfers if transfer.operation == row.caller)
    edge = caller.terminator.successors[actual_transfer.successor_index]
    block = next(block for region in program.regions for block in region.blocks if block.id == edge.block)
    assert view['outputs']
    for route in view['outputs']:
        assert route['caller_result'] is None  # INVOKE has no ordinary operation result
        assert route['caller_transfer'] == actual_transfer
        assert type(route['edge_argument']) is CompletionResult
        source_index = route['edge_argument'].index
        assert route['callee_use'].use == child.terminator.values[source_index]
        target_index = block.arguments.index(route['caller_formal_definition'].id)
        assert edge.arguments[target_index] == route['edge_argument']
        assert route['caller_formal'].origin == actual_transfer.target
        assert route['caller_formal'].value == block.arguments[target_index]
    assert all(route['caller_formal_definition'].id not in {
        block.arguments[i] for i, argument in enumerate(edge.arguments)
        if type(argument) is not CompletionResult} for route in view['outputs'])
    _without_authority(view)


@pytest.mark.parametrize('missing', ('entry', 'completion'))
def test_unresolved_association_end_is_preserved_without_inventing_running_failed_or_normal(missing):
    program, model, *_ = shared_calls_execution()
    row = model.call_activations[0]
    point = next(activation.entry for activation in model.activations if activation.id == row.activation)
    changed = replace(row, **{missing: Unresolved('capture omitted this exact end', point)})
    model = replace(model, call_activations=(changed, *model.call_activations[1:]))
    index = ExecutionIndex(model, program)
    view = index.call_activation(changed.id)
    assert view['status'] == 'DECLARED' and view[missing] is None
    assert getattr(view['association'], missing) == getattr(changed, missing)
    assert any(missing in gap.code for gap in view['gaps'])
    assert all(type(gap) is ExecutionIssue for gap in view['gaps'])
    if missing == 'entry':
        assert view['inputs']
        assert all(route['formal'] is None for route in view['inputs'])
        assert all(route['actual_definition'].id is not None for route in view['inputs'])
    else:
        assert view['outputs'] == ()
    assert index.call_entries(row.caller)['status'] == 'DECLARED'
    _without_authority(view)


def test_missing_dynamic_actual_retains_its_original_ordered_use_port():
    program, model, *_ = shared_calls_execution()
    row = model.call_activations[0]
    caller = next(op for op in program.operations if op.id == next(
        occurrence.operation for occurrence in model.operations if occurrence.id == row.caller))
    missing_use = caller.call_arguments[0]
    model = replace(model, uses=tuple(use for use in model.uses
        if (use.operation, use.use) != (row.caller, missing_use)))
    view = ExecutionIndex(model, program).call_activation(row.id)
    route = view['inputs'][0]
    assert route['actual'] is None and route['actual_value'] is None
    assert route['actual_definition'] == next(use for use in caller.uses if use.id == missing_use)
    assert route['formal_definition'].id == route['formal'].value
    assert view['gaps']


def test_observed_child_raise_without_caller_transfer_does_not_invent_a_normal_landing():
    program, model, *_ = invoke_call_execution(raised=True, caller_transfer=False)
    row, = model.call_activations
    assert not any(transfer.operation == row.caller for transfer in model.transfers)
    view = ExecutionIndex(model, program).call_activation(row.id)
    assert view['completion'].id == row.completion
    assert view['outputs'] and any(route['callee_use'] is not None for route in view['outputs'])
    assert all(route['caller_transfer'] is None and route['caller_formal'] is None
               and route['edge_argument'] is None for route in view['outputs'])
    assert any('transfer' in gap.code for gap in view['gaps'])
    assert view['status'] == 'DECLARED'
    _without_authority(view)


def test_no_association_does_not_select_a_child_by_same_static_body_or_source():
    program, model, *_ = shared_calls_execution()
    row = model.call_activations[0]
    model = replace(model, call_activations=model.call_activations[1:])
    index = ExecutionIndex(model, program)
    view = index.call_entries(row.caller)
    assert view['status'] == 'MISSING' and view['entries'] == ()
    assert view['callee'].id == next(activation.region for activation in model.activations
                                    if activation.id == row.activation)
    assert view['operation'].call_arguments
    assert any(type(gap) is ExecutionIssue and gap.code == 'call_activation_missing' for gap in view['gaps'])
    assert index.call_entries(model.call_activations[0].caller)['status'] == 'DECLARED'
    _without_authority(view)


def test_noncallee_operation_is_not_reclassified_as_a_call_and_results_are_detached():
    fixture = shared_calls_execution()
    program, model, *_ = fixture
    index = _index(fixture)
    row = model.call_activations[0]
    noncaller = next(occurrence.id for occurrence in model.operations if next(
        op for op in program.operations if op.id == occurrence.operation).callee is None)
    assert index.call_entries(noncaller)['status'] == 'NO_DECLARED_CALLEE'
    first = index.call_activation(row.id)
    original = first['inputs'][0]['actual'].value
    object.__setattr__(first['inputs'][0]['actual'], 'value', ValueOccurrenceID('detached.poison'))
    first['outputs'] = ()
    again = index.call_activation(row.id)
    assert again['inputs'][0]['actual'].value == original
    assert again['outputs']
    assert index.call_entries(row.caller)['entries'][0]['inputs'][0]['actual'].value == original


def test_query_ids_are_exact_namespaces_with_strict_nested_values_and_existing_foreign_keys():
    index = _index(shared_calls_execution())

    class CallSubclass(CallActivationID):
        pass

    class TextSubclass(str):
        pass

    for wrong in ('call', True, OperationOccurrenceID('call'), CallSubclass('call')):
        with pytest.raises(TypeError):
            index.call_activation(wrong)
    for wrong in ('caller', False, CallActivationID('caller')):
        with pytest.raises(TypeError):
            index.call_entries(wrong)
    malformed = CallActivationID('bad')
    object.__setattr__(malformed, 'value', TextSubclass('bad'))
    with pytest.raises(ValueError):
        index.call_activation(malformed)
    with pytest.raises(KeyError):
        index.call_activation(CallActivationID('not-declared'))
    with pytest.raises(KeyError):
        index.call_entries(OperationOccurrenceID('not-observed'))
