"""Original bool/read/branch joins, distinct from native phase verification."""
from dataclasses import replace

import pytest

from scar.ir.program.ids import OperationID, UseID, ValueID
from scar.ir.program.model import (
    AccessMode, Behavior, BlockArgument, DataValue, LiteralOrigin, Operation,
    OperationResult, ReferenceValue, StateAccess, StateVersionValue, Use, UseRole,
)
from scar.ir.program.protocols import BodyStatePredicateRule
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_admission_graphs import admission_program


def _change_row(graph, row):
    return replace(graph, protocol_operations=(row,))


def _codes(graph):
    require_valid(replace(graph, protocol_scopes=(), protocol_operations=()))
    return {issue.code for issue in validate(graph)}


def _view(graph, details, *, budget=4096):
    report = ProgramIndex(graph).protocol_obligations(details['scope'], budget=budget)
    row = next(item for scope in report['scopes'] for clause in scope['obligations']
               for item in clause['rows'])
    return report, row['predicate']


@pytest.mark.parametrize('rule', tuple(BodyStatePredicateRule))
def test_actual_body_read_bool_and_branch_are_connected_without_a_raw_operand(rule):
    graph, details = admission_program(rule=rule)
    report, view = _view(graph, details)
    assert view['bool_must_copy'] is True
    assert view['state_support'] and all(item['current'] for item in view['state_support'])
    assert len(view['operation'].uses) == 2  # owner and the one real read
    assert view['successors'] == tuple(enumerate(view['branch'].terminator.successors))
    assert not view['native_phase_verified'] and not report['transformation_authorized']


def test_none_subject_preserves_an_original_binary_none_operand():
    graph, details = admission_program(subject='none')
    operation = next(op for op in graph.operations if op.id == details['predicate'])
    none = ReferenceValue(ValueID('admission.binary.none'), next(v.region for v in graph.values
        if v.id == operation.uses[0].value), LiteralOrigin(None), targets=())
    extra = Use(UseID('admission.binary.other'), none.id, UseRole.REFERENCE)
    changed = replace(graph, values=(*graph.values, none), operations=tuple(
        replace(op, uses=(*op.uses, extra)) if op.id == operation.id else op for op in graph.operations))
    _, view = _view(changed, details)
    assert view['operation'].uses == (*operation.uses, extra)
    assert view['input'] is operation.uses[0]
    assert not view['state_support']


def test_an_available_other_bool_cannot_replace_the_intended_predicate_result():
    graph, details = admission_program()
    branch = next(op for op in graph.operations if op.id == details['branch'])
    region = next(v.region for v in graph.values if v.id == branch.uses[0].value)
    other = DataValue(ValueID('admission.unrelated.bool'), region, LiteralOrigin(True), 'builtins.bool')
    changed = replace(graph, values=(*graph.values, other), operations=tuple(
        replace(op, uses=tuple(replace(use, value=other.id) if use.id == details['condition_use'] else use
                               for use in op.uses)) if op.id == branch.id else op for op in graph.operations))
    assert 'admission_bool_source' in _codes(changed)


def test_a_known_state_slot_is_not_the_none_subject_reference_input():
    graph, details = admission_program(subject='none')
    operation = next(op for op in graph.operations if op.id == details['predicate'])
    state = next(v for v in graph.values if isinstance(v, StateVersionValue)
                 and isinstance(v.origin, BlockArgument)
                 and v.region == next(v.region for v in graph.values if v.id == operation.uses[0].value))
    # Use an existing state Use on the branch as a deliberately foreign owner.
    branch = next(op for op in graph.operations if op.id == details['branch'])
    foreign = next(use.id for use in branch.uses if use.value == state.id)
    row, = graph.protocol_operations
    changed = _change_row(graph, replace(row, contract=replace(row.contract,
        subject=replace(row.contract.subject, input_use=foreign))))
    assert 'admission_reference' in _codes(changed)


def test_a_predicate_cannot_silently_retarget_its_bound_body_owner():
    graph, details = admission_program()
    interface, = graph.driver_interfaces
    region = next(item for item in graph.regions if item.id == interface.region)
    entry = next(block for block in region.blocks if block.id == region.entry)
    other = ReferenceValue(ValueID('admission.other.owner'), region.id,
                           BlockArgument(entry.id, len(entry.arguments)))
    predicate = next(op for op in graph.operations if op.id == details['predicate'])
    row, = graph.protocol_operations
    changed = replace(graph, values=(*graph.values, other), regions=tuple(
        replace(item, blocks=tuple(replace(block, arguments=(*block.arguments, other.id))
            if block.id == entry.id else block for block in item.blocks)) if item.id == region.id else item
        for item in graph.regions), operations=tuple(replace(op, uses=tuple(
            replace(use, value=other.id) if use.id == row.contract.subject.instance_use else use
            for use in op.uses)) if op.id == predicate.id else op for op in graph.operations))
    assert 'admission_owner' in _codes(changed)


def _write_between_read_and_branch(graph, details):
    predicate = next(op for op in graph.operations if op.id == details['predicate'])
    access, = predicate.accesses
    values = {value.id: value for value in graph.values}
    before = next(use.value for use in predicate.uses if use.id == access.before)
    identity = OperationID('admission.intervening.write')
    after = StateVersionValue(ValueID('admission.intervening.after'), values[before].region,
                              OperationResult(identity, 0), access.location)
    use = Use(UseID('admission.intervening.before'), before, UseRole.STATE_CONTENT)
    writer = Operation(identity, 'an actual intervening state update', (Behavior.READ, Behavior.WRITE),
        (use,), (after.id,), (StateAccess(access.location, use.id, AccessMode.READ_WRITE, after.id),),
        effects_complete=True)
    branch = next(op for op in graph.operations if op.id == details['branch'])
    branch = replace(branch, uses=tuple(replace(use, value=after.id) if use.value == before else use
                                        for use in branch.uses))
    return replace(graph, values=(*graph.values, after), operations=tuple(
        branch if op.id == branch.id else op for op in graph.operations) + (writer,),
        regions=tuple(replace(region, blocks=tuple(replace(block,
            operations=tuple(item for original in block.operations
                             for item in ((identity, original) if original == branch.id else (original,))))
            if predicate.id in block.operations else block for block in region.blocks))
            for region in graph.regions))


def test_a_historical_bool_stays_valid_but_does_not_prove_current_phase_after_a_write():
    graph, details = admission_program()
    changed = _write_between_read_and_branch(graph, details)
    require_valid(changed)
    _, view = _view(changed, details)
    assert view['bool_must_copy'] is True
    assert view['status'] == 'PARTIAL'
    assert 'admission_read_currentness_unproved' in view['gaps']
    assert not any(item['current'] for item in view['state_support'])
    assert view['native_phase_verified'] is False


def test_bounded_predicate_queries_keep_clause_inventory_and_never_grant_phase_truth():
    graph, details = admission_program()
    index = ProgramIndex(graph)
    full = index.protocol_obligations(details['scope'])
    limited = index.protocol_obligations(details['scope'], budget=1)
    assert tuple(row['clause'] for row in full['scopes'][0]['obligations']) == tuple(
        row['clause'] for row in limited['scopes'][0]['obligations'])
    assert limited['cursor'] and limited['budget']['truncated']
    assert limited['source_runtime_verified'] is limited['transformation_authorized'] is False
