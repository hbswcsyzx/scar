"""Phase reads, original branch routes and final gate inputs are separate joins."""
from dataclasses import replace

import pytest

from scar.ir.program.ids import BlockID, OperationID, UseID, ValueID
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, DataValue, Operation,
    OperationResult, StateAccess, StateVersionValue, Successor, Terminator,
    TerminatorKind, Use, UseRole, ExitKind, ExitPort, value_type,
)
from scar.ir.program.protocols import (
    AdmissionPredicate, BodyStateCondition, BodyStatePredicateRule as Rule,
    ProtocolClause, ProtocolOperation,
)
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.state_addresses import ExistingAccess
from tests.fixtures.program_protocol_graphs import generator_protocol_program, _role


def phase_gate_program(*, rule=Rule.IS_CREATED, target='start', truth=True, write=False):
    graph, details = generator_protocol_program(target=target)
    gate_row, = graph.final_body_gates
    gate = next(op for op in graph.operations if op.id == gate_row.operation)
    region = next(region for region in graph.regions if any(
        gate.id in block.operations for block in region.blocks))
    block = next(block for block in region.blocks if gate.id in block.operations)
    assert block.operations == (gate.id,)
    values = {value.id: value for value in graph.values}
    body = next(use.value for use in gate.uses if use.id == gate.invoke_arguments[gate_row.body_argument])
    states = tuple(use.value for use in gate.uses if use.id in gate.invoke_arguments
                   and isinstance(values[use.value], StateVersionValue))
    pred_id, branch_id = OperationID('phase.read'), OperationID('phase.branch')
    result = DataValue(ValueID('phase.bool'), region.id, OperationResult(pred_id, 0), 'builtins.bool')
    owner = Use(UseID('phase.owner'), body, UseRole.REFERENCE)
    read = Use(UseID('phase.before'), states[0], UseRole.STATE_CONTENT)
    predicate = Operation(pred_id, 'original phase read', (Behavior.CONTROL, Behavior.READ),
        (owner, read), (result.id,),
        accesses=(StateAccess(values[states[0]].location, read.id, AccessMode.READ),),
        effects_complete=True)
    row = ProtocolOperation(graph.protocol_scopes[0].id, ProtocolClause.RAW_ADMISSION, pred_id, 0,
        AdmissionPredicate(BodyStateCondition(owner.id, (ExistingAccess(pred_id, 0),), rule),
                           result.origin, branch_id), graph.protocol_scopes[0].source)
    added_values, added_operations = [result], [predicate]
    current_arguments = block.arguments
    if write:
        writer_id = OperationID('phase.write')
        after = StateVersionValue(ValueID('phase.after'), region.id,
            OperationResult(writer_id, 0), values[states[0]].location)
        before = Use(UseID('phase.write.before'), states[0], UseRole.STATE_CONTENT)
        writer = Operation(writer_id, 'intervening callback state effect', (Behavior.READ, Behavior.WRITE),
            (before,), (after.id,), (StateAccess(after.location, before.id, AccessMode.READ_WRITE, after.id),),
            effects_complete=True)
        added_values.append(after)
        added_operations.append(writer)
        current_arguments = tuple(after.id if item == states[0] else item for item in current_arguments)
        values[after.id] = after
    condition = Use(UseID('phase.condition'), result.id, UseRole.DATA)
    forwards, successors, mappings, blocks = [], [], [], []
    for ordinal in range(2):
        destination = BlockID(f'phase.route.{ordinal}')
        formals = tuple(replace(values[original], id=ValueID(f'phase.arg.{ordinal}.{index}'),
            origin=BlockArgument(destination, index)) for index, original in enumerate(current_arguments))
        actuals = tuple(Use(UseID(f'phase.forward.{ordinal}.{index}'), original, _role(values[original]))
                        for index, original in enumerate(current_arguments))
        mapping = dict(zip(block.arguments, (value.id for value in formals)))
        mappings.append(mapping)
        forwards.extend(actuals)
        successors.append(Successor(destination, tuple(use.id for use in actuals)))
        added_values.extend(formals)
        if (ordinal == 0) == truth:
            selected = replace(gate, uses=tuple(replace(use, value=mapping.get(use.value, use.value))
                                               for use in gate.uses))
            blocks.append(Block(destination, tuple(value.id for value in formals), (gate.id,)))
        else:
            # A supplied ordinary alternate path, not a claim of native phase semantics.
            returned = tuple(Use(UseID(f'phase.exit.{index}'), mapping.get(value, value), _role(values[value]))
                             for index, value in enumerate((body, *states)))
            terminal = Operation(OperationID('phase.alternate'), 'ordinary alternate host result',
                (Behavior.CONTROL,), returned, effects_complete=True,
                terminator=Terminator(TerminatorKind.RETURN, exit='phase.alternate',
                                      values=tuple(use.id for use in returned)))
            added_operations.append(terminal)
            blocks.append(Block(destination, tuple(value.id for value in formals), (terminal.id,)))
    branch = Operation(branch_id, 'branch on current original bool', (Behavior.CONTROL,),
        (condition, *forwards), effects_complete=True,
        terminator=Terminator(TerminatorKind.BRANCH, tuple(successors), condition=condition.id))
    added_operations.append(branch)
    graph = replace(graph, values=(*graph.values, *added_values),
        operations=tuple(selected if op.id == gate.id else op for op in graph.operations) + tuple(added_operations),
        regions=tuple(replace(item, exits=(*item.exits, ExitPort('phase.alternate', ExitKind.NORMAL,
            tuple(value_type(values[value]) for value in (body, *states)))),
            blocks=tuple(replace(original,
            operations=tuple(op.id for op in added_operations if op.id != OperationID('phase.alternate')))
            if original.id == block.id else original for original in item.blocks) + tuple(blocks))
            if item.id == region.id else item for item in graph.regions),
        protocol_operations=(*graph.protocol_operations, row),
        control_scopes=tuple(replace(scope, blocks=(*scope.blocks, *(item.id for item in blocks)))
                             if scope.region == region.id else scope for scope in graph.control_scopes))
    return graph, details


def _gate_route(graph, details):
    report = ProgramIndex(graph).protocol_obligations(details['scope'], budget=20000)
    predicate = next(row['predicate'] for clause in report['scopes'][0]['obligations']
                     for row in clause['rows'] if row['predicate'] is not None)
    gate = next(item for item in predicate['control_routes']['frontiers'] if item['kind'] == 'FINAL_GATE')
    return predicate, gate


@pytest.mark.parametrize('rule', tuple(Rule))
@pytest.mark.parametrize('target', ('start', 'value'))
@pytest.mark.parametrize('truth', (True, False))
def test_original_branch_reaches_actual_gate_and_compares_read_with_gate_inputs(rule, target, truth):
    graph, details = phase_gate_program(rule=rule, target=target, truth=truth)
    predicate, gate = _gate_route(graph, details)
    assert gate['edge'].successor_index == (0 if truth else 1)
    assert gate['drive'].operation == details['drive']
    assert gate['read_snapshot_current'] is True
    expected = ((target == 'start') == truth if rule is Rule.IS_CREATED else
                (target == 'value') == truth if rule is Rule.IS_SUSPENDED else not truth)
    assert gate['target_compatible_at_snapshot'] is expected
    assert gate['native_gate_verified'] is False
    assert predicate['transformation_authorized'] is False


def test_changed_state_support_keeps_historical_bool_but_does_not_select_a_phase_target():
    graph, details = phase_gate_program(write=True)
    predicate, gate = _gate_route(graph, details)
    assert gate['read_snapshot_current'] is False
    assert gate['target_compatible_at_snapshot'] is None
    assert 'admission_gate_support_changed_or_unresolved' in predicate['gaps']


def test_branch_current_read_does_not_survive_a_later_effect_before_the_gate():
    graph, details = phase_gate_program()
    gate_id = graph.final_body_gates[0].operation
    gate = next(op for op in graph.operations if op.id == gate_id)
    values = {value.id: value for value in graph.values}
    state = next(use for use in gate.uses if use.id in gate.invoke_arguments
                 and isinstance(values[use.value], StateVersionValue))
    before = values[state.value]
    writer_id = OperationID('phase.later.write')
    after = StateVersionValue(ValueID('phase.later.state'), before.region,
                               OperationResult(writer_id, 0), before.location)
    actual = Use(UseID('phase.later.before'), before.id, UseRole.STATE_CONTENT)
    writer = Operation(writer_id, 'actual state change after the original branch',
        (Behavior.READ, Behavior.WRITE), (actual,), (after.id,),
        (StateAccess(before.location, actual.id, AccessMode.READ_WRITE, after.id),), effects_complete=True)
    gate = replace(gate, uses=tuple(replace(use, value=after.id) if use.value == before.id else use
                                    for use in gate.uses))
    changed = replace(graph, values=(*graph.values, after),
        operations=tuple(gate if op.id == gate_id else op for op in graph.operations) + (writer,),
        regions=tuple(replace(region, blocks=tuple(replace(block, operations=(writer.id, gate_id))
            if block.operations == (gate_id,) else block for block in region.blocks)) for region in graph.regions))
    predicate, route = _gate_route(changed, details)
    assert all(item['current'] for item in predicate['state_support'])
    assert route['read_snapshot_current'] is False
    assert route['target_compatible_at_snapshot'] is None


def test_route_budget_exhaustion_keeps_the_predicate_and_does_not_invent_a_gate_proof():
    graph, details = phase_gate_program()
    index = ProgramIndex(graph)
    full = index.protocol_obligations(details['scope'], budget=20000)
    limited = index.protocol_obligations(details['scope'], budget=40)
    assert limited['budget']['truncated'] and limited['cursor']
    assert tuple(item['clause'] for item in full['scopes'][0]['obligations']) == tuple(
        item['clause'] for item in limited['scopes'][0]['obligations'])
    assert limited['transformation_authorized'] is limited['source_runtime_verified'] is False


def test_an_exiting_alternative_does_not_hide_an_unselected_cycle_before_the_gate():
    graph, details = phase_gate_program()
    gate_id = graph.final_body_gates[0].operation
    region = next(region for region in graph.regions if any(
        gate_id in block.operations for block in region.blocks))
    gate_block = next(block for block in region.blocks if block.operations == (gate_id,))
    values = {value.id: value for value in graph.values}
    loop_id = BlockID('phase.loop')
    formals = tuple(replace(values[value], id=ValueID(f'phase.loop.arg.{index}'),
        origin=BlockArgument(loop_id, index)) for index, value in enumerate(gate_block.arguments))
    compute_id, branch_id = OperationID('phase.loop.test'), OperationID('phase.loop.branch')
    decision = DataValue(ValueID('phase.loop.again'), region.id, OperationResult(compute_id, 0), 'builtins.bool')
    compute = Operation(compute_id, 'an unselected original iteration condition', (Behavior.COMPUTE,),
                        results=(decision.id,), effects_complete=True)
    condition = Use(UseID('phase.loop.condition'), decision.id, UseRole.DATA)
    forward_sets = tuple(tuple(Use(UseID(f'phase.loop.forward.{edge}.{index}'),
        formal.id, _role(formal)) for index, formal in enumerate(formals)) for edge in range(2))
    loop_branch = Operation(branch_id, 'original loop or exit', (Behavior.CONTROL,),
        (condition, *forward_sets[0], *forward_sets[1]), effects_complete=True,
        terminator=Terminator(TerminatorKind.BRANCH, (
            Successor(loop_id, tuple(use.id for use in forward_sets[0])),
            Successor(gate_block.id, tuple(use.id for use in forward_sets[1]))), condition=condition.id))
    original_branch = next(op for op in graph.operations if op.id == OperationID('phase.branch'))
    original_branch = replace(original_branch, terminator=replace(original_branch.terminator,
        successors=(replace(original_branch.terminator.successors[0], block=loop_id),
                    original_branch.terminator.successors[1])))
    loop = Block(loop_id, tuple(value.id for value in formals), (compute.id, loop_branch.id))
    changed = replace(graph, values=(*graph.values, *formals, decision),
        operations=tuple(original_branch if op.id == original_branch.id else op for op in graph.operations)
                   + (compute, loop_branch),
        regions=tuple(replace(item, blocks=(*item.blocks, loop)) if item.id == region.id else item
                      for item in graph.regions),
        control_scopes=tuple(replace(scope, blocks=(*scope.blocks, loop_id))
                             if scope.region == region.id else scope for scope in graph.control_scopes))
    predicate, gate = _gate_route(changed, details)
    assert gate['kind'] == 'FINAL_GATE'
    assert 'admission_route_cycle_or_budget_unresolved' in predicate['gaps']
    assert predicate['control_routes']['dynamic_path_selected'] is False
    assert predicate['status'] == 'PARTIAL'

