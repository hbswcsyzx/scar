"""A checked output prefix cannot stand for all original exit terminals."""
from dataclasses import replace

from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.program.ids import BlockID, OperationID, UseID, ValueID
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, CompletionResult, DataValue, ExitKind,
    InvokeLiteralResult, Operation, OperationResult, StateVersionValue,
    Successor, Terminator, TerminatorKind, Use, UseRole,
)
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.protocols import OwnedUse
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.region_implementation import region_implementation
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid
from tests.fixtures.program_await_final_region_graphs import await_final_region_program


def _two_normal_terminals():
    program, details = await_final_region_program()
    record = details['stage_records'][0]
    old_landing = record['landings'][ExitKind.NORMAL]
    old_terminal = record['terminals'][ExitKind.NORMAL]
    produced = record['landing_values'][ExitKind.NORMAL]
    name = 'await.final.output-budget'
    predicate_id = OperationID(name + '.predicate')
    predicate_value = DataValue(ValueID(name + '.condition'), record['region'].id,
                               OperationResult(predicate_id, 0), 'builtins.bool')
    predicate = Operation(predicate_id, 'an original branch predicate',
        (Behavior.COMPUTE,), results=(predicate_value.id,), effects_complete=True)
    condition = Use(UseID(name + '.condition.use'), predicate_value.id, UseRole.DATA)
    branch_uses, successors, blocks, operations, values, terminals = [condition], [], [], [], [], []
    for number in range(2):
        block_id = BlockID(f'{name}.path.{number}')
        formals = tuple(replace(value, id=ValueID(f'{name}.path.{number}.value.{slot}'),
            origin=BlockArgument(block_id, slot)) for slot, value in enumerate(produced))
        forwards = tuple(Use(UseID(f'{name}.path.{number}.forward.{slot}'), value.id,
            UseRole.STATE_CONTENT if type(value) is StateVersionValue else UseRole.REFERENCE)
            for slot, value in enumerate(produced))
        uses = tuple(Use(UseID(f'{name}.path.{number}.return.{slot}'), value.id,
            UseRole.STATE_CONTENT if type(value) is StateVersionValue else UseRole.REFERENCE)
            for slot, value in enumerate(formals))
        terminal = Operation(OperationID(f'{name}.path.{number}.terminal'),
            'one actual normal terminal', (Behavior.CONTROL,), uses,
            effects_complete=True, terminator=Terminator(TerminatorKind.RETURN,
                exit=old_terminal.terminator.exit, values=tuple(use.id for use in uses)))
        branch_uses.extend(forwards)
        successors.append(Successor(block_id, tuple(use.id for use in forwards)))
        blocks.append(Block(block_id, tuple(value.id for value in formals), (terminal.id,)))
        operations.append(terminal)
        values.extend(formals)
        terminals.append(OwnedUse(terminal.id, uses[0].id))
    branch = Operation(OperationID(name + '.branch'), 'two original return paths',
        (Behavior.CONTROL,), tuple(branch_uses), effects_complete=True,
        terminator=Terminator(TerminatorKind.BRANCH, tuple(successors), condition=condition.id))
    landing = replace(old_landing, operations=(predicate.id, branch.id))
    region = replace(record['region'], blocks=tuple(
        landing if block.id == landing.id else block for block in record['region'].blocks) + tuple(blocks))
    program = replace(program,
        regions=tuple(region if original.id == region.id else original for original in program.regions),
        operations=tuple(operation for operation in program.operations if operation.id != old_terminal.id)
            + (predicate, branch, *operations),
        values=(*program.values, predicate_value, *values),
        control_scopes=tuple(replace(scope, blocks=tuple(block.id for block in region.blocks))
            if scope.region == region.id else scope for scope in program.control_scopes))
    return program, details, tuple(terminals)


def _project(index, details, *, stop_at_second_terminal=False):
    accounting = ValidityBudget(1048576)
    context = ConnectionContext(index.graph, index=index, budget=accounting)
    call = details['parent_call']
    signatures = {signature.kind: signature for signature in call.completions}
    normal_index = next(number for number, edge in enumerate(call.terminator.successors)
                        if edge.kind is ExitKind.NORMAL)
    target = InvokeLiteralResult(ControlEdgeReference(call.id, normal_index), CompletionResult(0))
    target_ordinal = sum(len(signatures[edge.kind].types)
                         for edge in call.terminator.successors[:normal_index])
    observed = {'output': -1, 'terminals': 0, 'stopped': False}
    if stop_at_second_terminal:
        original_spend = context.spend

        def spend(kind, cost=1):
            if kind == 'region_interface_output_slots':
                observed['output'] += 1
            if (kind == 'region_interface_output_terminals'
                    and observed['output'] == target_ordinal):
                observed['terminals'] += 1
                if observed['terminals'] == 2:
                    # Tighten at one exact work boundary. The unchanged real
                    # ValidityBudget.spend performs and records exhaustion.
                    accounting.limit = accounting.used
                    observed['stopped'] = True
            return original_spend(kind, cost)

        context.spend = spend
    report = region_implementation(context, details['root_source'], call)
    return report, accounting, target, observed


def test_second_original_terminal_budget_exhaustion_cannot_declare_the_true_prefix_complete():
    program, details, terminals = _two_normal_terminals()
    require_valid(replace(program, protocol_scopes=(), protocol_operations=(),
        protocol_call_inputs=(), protocol_result_consumers=(), protocol_bindings=()))
    require_valid(program)
    index = ProgramIndex(program)
    complete, full_budget, source, _ = _project(index, details)
    original, = tuple(output for output in complete['outputs'] if output['source'] == source)
    assert not full_budget.truncated
    assert {row['terminal'] for row in original['terminals']} == set(terminals)
    assert len(original['terminals']) == 2
    assert all(row['match'] is True for row in original['terminals'])
    assert original['status'] == 'DECLARED'

    limited, budget, same_source, observed = _project(index, details, stop_at_second_terminal=True)

    assert same_source == source and observed['stopped'] is True
    assert observed['terminals'] == 2
    assert budget.truncated is True and budget.used == budget.limit
    assert any(gap['code'] == 'validity_budget_exhausted' for gap in budget.gaps)
    assert {output['source'] for output in limited['outputs']} == {
        output['source'] for output in complete['outputs']}
    output, = tuple(output for output in limited['outputs'] if output['source'] == source)
    assert len(output['terminals']) == 1
    assert output['terminals'][0]['terminal'] in terminals
    assert output['terminals'][0]['match'] is True
    assert output['status'] == 'PARTIAL'
    assert output['gaps']
    assert limited['inventory']['known_inventory_complete'] is False
    assert limited['inventory']['proofs_complete'] is False
    assert limited['inventory']['outputs_total'] is None
    assert limited['cursor'] is not None
