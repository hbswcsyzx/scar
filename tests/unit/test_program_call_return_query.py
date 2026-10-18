"""Public source queries preserve independent evidence and scoped choices."""
from dataclasses import replace

import pytest

from scar.ir.program.model import ExitKind, TerminatorKind
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.protocols import HostTerminal
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid
from tests.fixtures.program_call_return_graphs import call_return_program, multi_return_program
from tests.fixtures.program_call_return_state_graphs import call_return_state_program


def test_source_binding_reuses_the_prepared_index_and_reports_original_terminal_evidence(monkeypatch):
    graph, details = call_return_program(depth=2)
    require_valid(graph)
    index = ProgramIndex(graph)
    def no_reconstruction(*args, **kwargs):
        raise AssertionError('source query must reuse the prepared ProgramIndex')
    monkeypatch.setattr(ProgramIndex, '__init__', no_reconstruction)
    report = index.source_binding(details['expected'], details['actual'])
    assert report['match'] is True
    assert report['preparation']['prepared_program_index_reused'] is True
    assert len(report['call_returns']['summaries']) == 2
    for summary in report['call_returns']['summaries']:
        for exit_ in summary['exits']:
            for terminal in exit_['terminals']:
                use = terminal['use']
                operation = index.operations[use.operation]
                assert use.use in operation.terminator.values
                assert terminal['value'] == next(row.value for row in operation.uses if row.id == use.use)
    assert report['native_applicability_verified'] is False
    assert report['budget']['used'] == sum(report['budget']['costs'].values())


def test_public_source_is_one_slot_not_a_terminal_tuple():
    graph, details = call_return_program()
    require_valid(graph)
    with pytest.raises(ValueError, match='exactly one'):
        ProgramIndex(graph).source_binding(HostTerminal(details['terminals'][0]), details['actual'])


@pytest.mark.parametrize('budget,error', ((True, TypeError), (1.5, TypeError), (0, ValueError)))
def test_invalid_shared_budget_cannot_silently_enable_a_query(budget, error):
    graph, details = call_return_program()
    index = ProgramIndex(graph)
    with pytest.raises(error):
        index.source_binding(details['expected'], details['actual'], budget=budget)


def test_one_shared_context_cannot_reuse_a_guarded_summary_for_another_branch():
    graph, details = multi_return_program(mixed=True)
    require_valid(graph)
    context = ConnectionContext(graph, index=ProgramIndex(graph))
    choose = next(row for row in graph.operations if row.terminator is not None
                  and row.terminator.kind is TerminatorKind.BRANCH)
    first = context.bind(details['expected'], details['actual'], guard=ControlEdgeReference(choose.id, 0))
    other = context.bind(details['expected'], details['actual'], guard=ControlEdgeReference(choose.id, 1))
    unselected = context.bind(details['expected'], details['actual'])
    assert first['match'] is True
    assert other['match'] is False
    assert unselected['match'] is None


def test_unscoped_callee_guard_does_not_select_one_of_multiple_callers():
    graph, details = call_return_state_program(two_callers=True)
    require_valid(graph)
    choose = next(row for row in graph.operations if row.terminator is not None
        and row.terminator.kind is TerminatorKind.BRANCH
        and row.id in {op for block in details['callee'].blocks for op in block.operations})
    a = details['callers']['a']
    report = ProgramIndex(graph).source_binding(a['arguments'][0],
        a['consumers'][ExitKind.NORMAL]['payload'],
        guard=ControlEdgeReference(choose.id, 0))
    assert report['match'] is None
    assert 'call_return_guard_context_unresolved' in report['gaps']


def test_all_original_actual_ordinals_are_mapped_when_the_same_value_is_passed_twice():
    graph, details = multi_return_program(mixed=True)
    call = next(row for row in graph.operations if row.id == details['calls'][0])
    call = replace(call, uses=tuple(replace(use, value=call.uses[0].value) if number == 1 else use
                                   for number, use in enumerate(call.uses)))
    graph = replace(graph, operations=tuple(call if row.id == call.id else row for row in graph.operations))
    require_valid(graph)
    report = ProgramIndex(graph).source_binding(details['expected'], details['actual'])
    assert report['match'] is True
    assert len(report['call_returns']['calls'][0]['actual_formals']) == 2


def test_internal_source_export_keeps_its_guard_and_all_terminal_evidence():
    graph, details = multi_return_program(mixed=True)
    require_valid(graph)
    helper = next(region for region in graph.regions if region.id != graph.root)
    entry = next(block for block in helper.blocks if block.id == helper.entry)
    choose = next(row for row in graph.operations if row.id == entry.operations[0])
    source = next(value for value in graph.values if value.id == entry.arguments[0]).origin
    guard = ControlEdgeReference(choose.id, 0)
    report = ProgramIndex(graph).source_binding(source, details['actual'], guard=guard)
    assert report['match'] is True and report['conditional'] is True
    assert report['selected_guards'] == (guard,)
    frame = report['routes'][0]['frames'][0]
    assert frame['guards'] == (guard,)
    slots = frame['projection']
    assert slots and all(row['terminals'] for row in slots)
    assert {row['use'].operation for slot in slots for row in slot['terminals']} == set(details['terminals'])
    assert report['runtime_identity_verified'] is False
