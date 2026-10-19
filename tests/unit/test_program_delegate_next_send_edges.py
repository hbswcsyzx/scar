"""Exact NEXT/SEND edges over the existing delegate protocol graphs.

These supplied graphs check original ports and consumers.  They do not prove
native lookup semantics, exception categories or runtime object identity.
"""
from dataclasses import replace

import pytest

from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.program.drivers import RawRequestDefinition, RawRequestKind
from scar.ir.program.ids import UseID, ValueID
from scar.ir.program.model import (
    BlockArgument, CompletionResult, ExitKind, InvokeLiteralResult, LiteralOrigin,
    ReferenceValue, StateVersionValue, TerminatorKind, Use, UseRole,
)
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.protocol_connections import RawOperandSource
from scar.ir.program.protocol_continuations import continuation_connections
from scar.ir.program.protocols import ContractResult, HostTerminal, OutcomeAdapter, OwnedUse
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_continuation_graphs import (
    continuation_site_program, with_continuation_connections,
)
from tests.fixtures.program_method_lookup_graphs import (
    _insert_method, method_lookup_loop_program, method_lookup_program,
)


def _core_valid(graph):
    require_valid(replace(graph, protocol_scopes=(), protocol_operations=(),
        protocol_call_inputs=(), protocol_result_consumers=(), protocol_bindings=()))


def _context(graph):
    _core_valid(graph)
    require_valid(graph)
    return ConnectionContext(graph, index=ProgramIndex(graph),
                             budget=ValidityBudget(524288))


def _codes(graph):
    _core_valid(graph)
    return {issue.code for issue in validate(graph)}


def _source(row):
    return ContractResult(row.scope, row.clause, row.operation, row.slot,
                          row.contract.result)


def _assert_binding(binding, match=True):
    assert binding['match'] is match
    assert binding['source_runtime_verified'] is False
    assert binding['runtime_identity_verified'] is False
    assert binding['transformation_authorized'] is False


def _assert_continuation(context):
    report = continuation_connections(context)
    assert not report['issues']
    assert report['source_runtime_verified'] is False
    assert report['transformation_authorized'] is False
    return report


def _literal_send_program(*, advance_kind, operand):
    """Keep a real SEND pack even when its None operand selects NEXT."""
    graph, details = method_lookup_program(request=advance_kind)
    operations = {operation.id: operation for operation in graph.operations}
    values = {value.id: value for value in graph.values}
    raw_use = next(use for use in operations[details['raw'].operation].uses
                   if use.id == details['raw'].use)
    definition, = tuple(row for row in graph.raw_driver_requests
                        if row.value == raw_use.value)
    # The canonical raw result owns its pack; labels do not select producers.
    pack = operations[values[definition.value].origin.operation]
    literal = ReferenceValue(ValueID('delegate.edge.literal'), graph.root,
                             LiteralOrigin(operand), targets=())
    packed_use = (replace(pack.uses[0], value=literal.id) if pack.uses else
                  Use(UseID('delegate.edge.raw.operand'), literal.id, UseRole.REFERENCE))
    pack = replace(pack, uses=(packed_use,))
    definition = RawRequestDefinition(definition.value, RawRequestKind.SEND,
                                      (packed_use.id,))
    advance = operations[details['advance']['operation'].id]
    argument_uses = details['advance_rows'][0].contract.argument_uses
    advance = replace(advance, uses=tuple(
        replace(use, value=literal.id) if use.id in argument_uses else use
        for use in advance.uses))
    updates = {pack.id: pack, advance.id: advance}
    graph = replace(graph, operations=tuple(updates.get(operation.id, operation)
        for operation in graph.operations), values=(*graph.values, literal),
        raw_driver_requests=tuple(definition if row.value == definition.value else row
                                 for row in graph.raw_driver_requests))
    return graph, {**details, 'advance': {**details['advance'], 'operation': advance},
                   'send_definition': definition, 'pack': pack, 'operand': packed_use}


@pytest.mark.parametrize('operand', (None, 7), ids=('none', 'non-none'))
def test_send_operand_selects_next_only_when_it_is_declared_none(operand):
    graph, details = _literal_send_program(advance_kind='next', operand=operand)
    _core_valid(graph)
    definition = details['send_definition']
    assert definition.kind is RawRequestKind.SEND
    assert definition.operands == (details['operand'].id,)
    advance = details['advance']['operation']
    assert all(row.contract.argument_uses == () for row in details['advance_rows'])
    assert len(advance.invoke_arguments) == 2  # bound method and current state
    assert tuple(edge.kind for edge in advance.terminator.successors) == (
        ExitKind.NORMAL, ExitKind.RAISE)
    if operand is not None:
        assert 'protocol_continuation_trigger' in _codes(graph)
        return
    context = _context(graph)
    _assert_continuation(context)
    assert details['method']['operation'].id != advance.id
    _assert_binding(context.bind(details['method_source'],
        OwnedUse(advance.id, details['advance']['receiver'])))


def test_non_none_send_keeps_its_original_ordinal_at_the_bound_method_call():
    graph, details = _literal_send_program(advance_kind='send', operand=7)
    context = _context(graph)
    _assert_continuation(context)
    advance = details['advance']['operation']
    assert len(advance.invoke_arguments) == 3  # method, original operand, state
    for row in details['advance_rows']:
        attachment = next(item for item in graph.protocol_call_inputs
            if item.site.operation == row.operation and item.site.slot == row.slot)
        case, = attachment.cases
        assert case.arguments == (RawOperandSource(details['raw'], 0),)
        argument, = row.contract.argument_uses
        actual = next(use for use in advance.uses if use.id == argument)
        assert actual.value == details['operand'].value
        _assert_binding(context.bind(case.arguments[0], OwnedUse(advance.id, argument)))


@pytest.mark.parametrize('request_kind', ('next', 'send'))
def test_advance_own_raise_packet_and_current_state_reach_their_host_without_extraction(request_kind):
    graph, details = with_continuation_connections(*continuation_site_program(
        request=request_kind, exhaustion=False))
    graph, details = _insert_method(graph, details, name='delegate.edge.method')
    context = _context(graph)
    _assert_continuation(context)
    assert details['extraction'] is None and details['extraction_rows'] == ()
    assert details['value_exit'] is None
    advance = details['advance']['operation']
    terminal = details['error_exit']
    assert terminal.terminator.kind is TerminatorKind.RAISE
    raised, = tuple((number, edge) for number, edge in enumerate(advance.terminator.successors)
                    if edge.kind is ExitKind.RAISE)
    number, _ = raised
    own_packet = InvokeLiteralResult(ControlEdgeReference(advance.id, number), CompletionResult(0))
    own_state = InvokeLiteralResult(ControlEdgeReference(advance.id, number), CompletionResult(1))
    row, = tuple(row for row in details['advance_rows']
                 if row.contract.result == own_packet)
    adapter, = tuple(row for row in graph.protocol_operations
        if row.operation == terminal.id and type(row.contract) is OutcomeAdapter)
    assert adapter.contract.input == _source(row)
    assert adapter.contract.output == HostTerminal(terminal.id)
    packet = OwnedUse(terminal.id, terminal.terminator.values[0])
    state = OwnedUse(terminal.id, terminal.terminator.values[1])
    _assert_binding(context.bind(_source(row), packet))
    _assert_binding(context.bind(own_state, state))
    assert isinstance(context.values[context.owned_use(state.operation, state.use).value],
                      StateVersionValue)
    # The successful arm still delivers its own item; no fake extraction or
    # successful completion edge was introduced to obtain the failure route.
    item = details['item_exit']
    _assert_binding(context.bind(_source(details['advance_rows'][0]),
        OwnedUse(item.id, item.terminator.values[0])))
    assert not graph.body_drives and not graph.frame_context_attaches

    # Both packets have the same canonical role, but the lookup's RAISE ends
    # before this call. Change only the independent expected source.
    wrong = replace(adapter, contract=replace(adapter.contract,
        input=_source(details['method_rows'][1])))
    bad = replace(graph, protocol_operations=tuple(wrong if candidate == adapter else candidate
                                                  for candidate in graph.protocol_operations))
    assert 'protocol_copy' in _codes(bad)


def _loop_with_previous_item():
    graph, details = method_lookup_loop_program()
    previous = next(value for value in graph.values if value.id == details['previous'])
    assert type(previous.origin) is BlockArgument
    header = next(block for region in graph.regions for block in region.blocks
                  if block.id == previous.origin.block)
    branch = next(operation for operation in graph.operations
                  if operation.id == details['item_exit'].id)
    backedge, = tuple(edge for edge in branch.terminator.successors if edge.block == header.id)
    carried_use = backedge.arguments[previous.origin.index]
    item = details['advance']['normal_values'][0]
    branch = replace(branch, uses=tuple(replace(use, value=item)
        if use.id == carried_use else use for use in branch.uses))
    graph = replace(graph, operations=tuple(branch if operation.id == branch.id else operation
                                           for operation in graph.operations))
    assert next(use for use in branch.uses if use.id == carried_use).value == item
    return graph, details


def test_a_real_previous_delegate_item_cannot_replace_the_extracted_final_value():
    graph, details = _loop_with_previous_item()
    context = _context(graph)
    _assert_continuation(context)
    terminal = details['value_exit']
    actual = OwnedUse(terminal.id, terminal.terminator.values[0])
    final_source = details['extraction_rows'][0].contract.output
    assert final_source == details['extraction']['ports'][0]
    _assert_binding(context.bind(final_source, actual))
    assert context.owned_use(actual.operation, actual.use).value != details['previous']

    # Header's previous-item formal dominates the exceptional/extraction arm.
    # Its seed and backedge remain original operands, so this is a legal
    # same-type substitution rather than an item from a disjoint NORMAL arm.
    wrong = replace(terminal, uses=tuple(replace(use, value=details['previous'])
        if use.id == actual.use else use for use in terminal.uses))
    bad = replace(graph, operations=tuple(wrong if operation.id == wrong.id else operation
                                         for operation in graph.operations))
    assert bad.protocol_result_consumers == graph.protocol_result_consumers
    assert 'protocol_result_consumer' in _codes(bad)

