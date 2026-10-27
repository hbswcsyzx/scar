"""No-drive paths must retain original entry/control/completion denominators."""
from dataclasses import replace

from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.program.model import (
    CompletionResult, ExitKind, InvokeLiteralResult, StateVersionValue,
    TerminatorKind,
)
from scar.ir.program.protocol_async import async_connections
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.protocols import OwnedUse
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid
from tests.fixtures.program_async_connections import request_state_program


def _graph():
    graph, details = request_state_program(rule='IS_COMPLETE', target='value')
    require_valid(graph)
    return graph, details


def test_no_drive_inventory_keeps_original_entry_branches_and_every_own_completion_slot():
    graph, details = _graph()
    view = ProgramIndex(graph).request_no_drive_paths(budget=131072)
    item, = view['inventory']
    assert item['interface'] == details['interface']
    region = item['region']
    operations = {op.id: op for op in graph.operations}
    originals = tuple(operations[identity] for block in region.blocks for identity in block.operations)
    assert item['operations'] == originals
    assert item['entry'].id == region.entry
    assert item['receiver'].id == item['interface'].receiver
    assert item['scheduler'].id == item['interface'].scheduler_request
    assert item['branches'] == tuple(op for op in originals if op.terminator is not None
                                    and op.terminator.kind is TerminatorKind.BRANCH)
    assert item['drives'] == graph.body_drives
    for invocation in item['invokes']:
        operation = invocation['operation']
        assert len(invocation['edges']) == len(operation.terminator.successors)
        for number, row in enumerate(invocation['edges']):
            edge = operation.terminator.successors[number]
            assert row['edge'] == ControlEdgeReference(operation.id, number)
            assert row['successor'] == edge
            assert row['kind'] is edge.kind
            signature = next(sig for sig in operation.completions if sig.kind is edge.kind)
            assert row['signature'] == signature
            assert row['own_results'] == tuple(InvokeLiteralResult(row['edge'], CompletionResult(slot))
                                               for slot in range(len(signature.types)))


def test_actual_rejection_prefix_reaches_both_helper_exits_without_inventing_a_body_drive():
    graph, details = _graph()
    index = ProgramIndex(graph)
    view = index.request_no_drive_paths(budget=131072)
    assert view['known_inventory_complete'] is True
    assert view['paths_total'] == len(view['paths'])
    helper = next(op for op in graph.operations if op.id == details['helper'])
    paths = [row for row in view['paths'] if row['terminal'] is not None
             and any(op.id == helper.id for op in row['operations'])]
    assert paths
    chosen = set()
    for path in paths:
        assert path['declared_no_drive'] is True and path['drive'] is None
        assert not any(op.id in {row.operation for row in graph.body_drives}
                       for op in path['operations'])
        invocation, = tuple(row for row in path['invocations'] if row['operation'].id == helper.id)
        edge = invocation['selected_edge']
        chosen.add(helper.terminator.successors[edge.successor_index].kind)
        assert edge in path['choices']
        host = next(op for op in graph.operations if op.id == path['terminal'].operation)
        values = {value.id: value for value in graph.values}
        expected = {values[use.value].location: (OwnedUse(host.id, use.id), values[use.value])
                    for use in host.uses if use.id in host.terminator.values
                    and type(values[use.value]) is StateVersionValue}
        assert {row['location']: (row['actual'], row['value']) for row in path['states']} == expected
        # All original state domains, including context outside lifecycle, must
        # arrive from this helper's selected own completion, never old entry.
        signature = next(sig for sig in helper.completions
                         if sig.kind is helper.terminator.successors[edge.successor_index].kind)
        assert {getattr(type_, 'location', None) for type_ in signature.types
                if getattr(type_, 'location', None) is not None} == set(expected)
        for slot, type_ in enumerate(signature.types):
            location = getattr(type_, 'location', None)
            if location is not None:
                receipt = index.source_binding(InvokeLiteralResult(edge, CompletionResult(slot)),
                    expected[location][0], guard=path['choices'], budget=131072)
                assert receipt['match'] is True
        for row in invocation['own_results']:
            assert row['source'] == InvokeLiteralResult(edge, CompletionResult(row['slot']))
    assert chosen == {ExitKind.NORMAL, ExitKind.RAISE}
    assert all(view[key] is False for key in ('source_runtime_verified',
        'runtime_identity_verified', 'native_applicability_verified',
        'value_identity_verified', 'transformation_authorized'))


def test_deleting_optional_protocol_annotations_cannot_delete_original_no_drive_inventory():
    graph, _ = _graph()
    removed = replace(graph, protocol_scopes=(), protocol_operations=(), protocol_bindings=())
    require_valid(removed)
    original = ProgramIndex(graph).request_no_drive_paths(budget=131072)
    stripped = ProgramIndex(removed).request_no_drive_paths(budget=131072)
    for old, new in zip(original['inventory'], stripped['inventory'], strict=True):
        assert old['key'] == new['key']
        for field in ('interface', 'region', 'entry', 'receiver', 'scheduler',
                      'operations', 'branches', 'invokes', 'hosts', 'drives'):
            assert old[field] == new[field]
    assert {row['key'] for row in original['paths']} == {row['key'] for row in stripped['paths']}
    legacy = async_connections(ConnectionContext(removed, index=ProgramIndex(removed),
                                                budget=ValidityBudget(1)))
    assert legacy['request_no_drive_inventory'] == stripped['inventory']


def test_budget_one_retains_inventory_and_does_not_mistake_an_unvisited_drive_for_absence():
    graph, _ = _graph()
    index = ProgramIndex(graph)
    full = index.request_no_drive_paths(budget=131072)
    tiny = index.request_no_drive_paths(budget=1)
    assert tiny['inventory'] == full['inventory']
    assert tiny['cursor'] and tiny['known_inventory_complete'] is False
    assert tiny['paths_total'] is None
    assert tiny['budget']['truncated'] is True
    assert not any(row['declared_no_drive'] is True for row in tiny['paths'])
