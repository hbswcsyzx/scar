"""Expanded iterator inputs keep the original loop's incoming denominator.

These are narrow inventory regressions over an existing delegate graph.  They
do not establish an await acquisition, a native method rule or a whole G path.
"""
from dataclasses import replace

from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.program.protocol_await import (
    _input_case_inventory, await_inventory, iterator_use,
)
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.protocol_connections import ProtocolOperationRef
from scar.ir.program.protocols import ContractResult, OwnedUse
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid
from tests.fixtures.program_method_lookup_graphs import method_lookup_loop_program


def _expanded_iterator_loop(*, omit_advance_inputs=False):
    graph, details = method_lookup_loop_program()
    header = next(block for region in graph.regions for block in region.blocks
                  if block.id == details['header'])
    method = details['method']
    original_lookup = method['operation']
    lookup = replace(original_lookup, uses=tuple(
        replace(use, value=header.arguments[0])
        if use.id == method['receiver'] else use
        for use in original_lookup.uses))
    advance = details['advance']['operation']
    graph = replace(graph, operations=tuple(
        lookup if operation.id == lookup.id else operation
        for operation in graph.operations))
    if omit_advance_inputs:
        graph = replace(graph, protocol_call_inputs=tuple(
            row for row in graph.protocol_call_inputs
            if row.site.operation != advance.id))

    # The denominator is the actual original header's entry and backedge,
    # independently of any input-case declaration or expected lookup result.
    guards = tuple(ControlEdgeReference(operation.id, number)
        for operation in graph.operations if operation.terminator is not None
        for number, edge in enumerate(operation.terminator.successors)
        if edge.block == header.id)
    assert len(guards) == 2 and len(set(guards)) == 2
    actual = next(use for use in lookup.uses if use.id == method['receiver'])
    assert actual.value == header.arguments[0]
    return graph, details, guards


def _context(graph):
    require_valid(replace(graph, protocol_scopes=(), protocol_operations=(),
        protocol_call_inputs=(), protocol_result_consumers=(), protocol_bindings=()))
    require_valid(graph)
    return ConnectionContext(graph, index=ProgramIndex(graph),
                             budget=ValidityBudget(524288))


def _site(row):
    return ProtocolOperationRef(row.scope, row.clause, row.operation, row.slot)


def test_expanded_universal_case_keeps_both_original_iterator_loop_incoming():
    graph, details, guards = _expanded_iterator_loop()
    context = _context(graph)
    rows = details['advance_rows']
    assert len(rows) == 2
    for row in rows:
        attachment = context.call_inputs[_site(row)]
        case, = attachment.cases
        assert case.guard is None and case.arguments == ()
        assert type(case.receiver) is ContractResult
        assert case.receiver == details['method_source']
        assert iterator_use(context, row, case) == OwnedUse(
            details['method']['operation'].id, details['method']['receiver'])
        inventory = _input_case_inventory(context, row)
        assert {guard for _, guard, _ in inventory} == set(guards)
        assert len(inventory) == len(guards)
        assert all(candidate is case and missing is False
                   for candidate, _, missing in inventory)


def test_missing_expanded_input_attachment_keeps_an_unresolved_inventory():
    graph, details, _ = _expanded_iterator_loop(omit_advance_inputs=True)
    context = _context(graph)
    for row in details['advance_rows']:
        site = _site(row)
        assert site not in context.call_inputs
        assert iterator_use(context, row) is None
        inventory = _input_case_inventory(context, row)
        assert inventory and all(case is None and missing is True
                                 for case, _, missing in inventory)
        assert context._await_input_case_pending.get(site)

    # A missing independent lookup anchor is not proof that there is only one
    # original control case.  Do not choose a lookup from the actual producer.
    report = await_inventory(context)
    assert report['known_inventory_complete'] is False
    assert report['cursor'] is not None

