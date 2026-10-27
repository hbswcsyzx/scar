"""Literal content preserves producer, effects and occurrence identity routes."""
from dataclasses import replace
import struct

import pytest

from scar.ir.literals import PythonLiteral
from scar.ir.execution.common import Unresolved
from scar.ir.execution.coordinates import UseRef
from scar.ir.execution.ids import OperationOccurrenceID, ValueOccurrenceID
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.snapshot import snapshot_for
from scar.ir.execution.validation import validate
from scar.ir.program.ids import BlockID, OperationID, UseID, ValueID
from scar.ir.program.literal_sources import SourceExpression, UninterpretedConstant
from scar.ir.program.model import OperationResult
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import SourceAtomID
from tests.fixtures.execution_literals import (
    exact_data_execution, literal_calls_execution, literal_loop_execution, literal_resume_execution,
    object_denotations, two_domain_literal_invoke,
)
from tests.fixtures.execution_paths import declared_path
from tests.fixtures.program_literals import literal_program


def _direct(*, raised=False, missing_completion=False):
    program, details = literal_program(exact=False)
    model = declared_path(program, ((BlockID('entry'), int(raised)),
        (BlockID('failure' if raised else 'normal'), None)))
    if missing_completion:
        visit = model.visits[0].id
        operations = tuple(row for row in model.operations if row.visit == visit)
        owners = {row.id for row in operations} | {visit, model.activations[0].id}
        model = replace(model, visits=model.visits[:1], operations=operations,
            values=tuple(row for row in model.values if row.origin in owners),
            uses=tuple(row for row in model.uses if row.operation in owners), transfers=())
    return program, model, details


@pytest.mark.parametrize('value', (
    None, Ellipsis, True, 7, -0.0, float('inf'), complex(-0.0, float('inf')),
    b'\x00\xff', '\x00é', '\ud800\udc00', (1, None, b'x'),
))
def test_exact_abstract_content_has_activation_availability_and_no_object_identity(value):
    program, model = exact_data_execution(value)
    index = ExecutionIndex(model, program)
    literal = next(row for row in model.values if row.value == ValueID('content'))
    view = index.denotation(literal.id)
    assert view['kind'] == 'data' and literal.origin == model.activations[0].id
    assert view['literal'] == program.values[0].origin
    restored = view['literal'].literal.to_python()
    assert type(restored) is type(value)
    if type(value) is float:
        assert struct.pack('>d', restored) == struct.pack('>d', value)
    else:
        assert restored == value
    assert view['association'] is None
    assert not view['source_runtime_verified'] and not view['transformation_authorized']


@pytest.mark.parametrize('key', ('direct', 'reference'))
def test_direct_content_declaration_does_not_change_original_result_or_effects(key):
    program, model, details = _direct()
    view = ExecutionIndex(model, program).literal_evaluation(details[key], OperationOccurrenceID('0.direct'))
    canonical = view['canonical']
    assert canonical['result'].origin == details[key]
    assert view['result']['occurrence'].origin == OperationOccurrenceID('0.direct')
    assert canonical['operation'].accesses and not canonical['operation'].effects_complete
    assert tuple(row['site'].use.id for row in view['inputs']) == tuple(
        use.id for use in canonical['operation'].uses)
    assert view['inputs'][0]['value']['occurrence'].id == view['inputs'][1]['value']['occurrence'].id
    assert view['inputs'][0]['use'].use != view['inputs'][1]['use'].use
    assert view['producer_and_effects_retained']
    if key == 'reference':
        assert type(canonical['literal']) is UninterpretedConstant
        assert any(gap['code'] == 'literal_reference_identity_unresolved' for gap in view['gaps'])
    assert not view['value_identity_verified'] and not view['transformation_authorized']


@pytest.mark.parametrize('key', ('invoke', 'invoke_reference'))
@pytest.mark.parametrize('raised', (False, True))
def test_invoke_uses_actual_normal_completion_without_borrowing_raise_result(key, raised):
    program, model, details = _direct(raised=raised)
    view = ExecutionIndex(model, program).literal_evaluation(details[key], OperationOccurrenceID('0.invoke'))
    assert view['actual_transfer'].successor_index == int(raised)
    assert view['canonical']['argument'].index == details[key].result.index
    if raised:
        assert view['status'] == 'NOT_TAKEN' and view['result'] is None
        assert any(row.value == ValueID('raise.world') for row in model.values)
    else:
        result = view['result']['occurrence']
        assert result.origin == model.transfers[0].target
        assert result.value == ValueID('normal.data' if key == 'invoke' else 'normal.ref')
    assert not view['source_runtime_verified'] and not view['transformation_authorized']


def test_unobserved_completion_cannot_materialize_a_declared_normal_value():
    program, model, details = _direct(missing_completion=True)
    view = ExecutionIndex(model, program).literal_evaluation(details['invoke'], OperationOccurrenceID('0.invoke'))
    assert view['actual_transfer'] is None and view['result'] is None
    assert any(gap['code'] == 'literal_completion_unobserved' for gap in view['gaps'])
    assert view['canonical']['result'].id == ValueID('normal.data')


@pytest.mark.parametrize('key', ('invoke', 'invoke_reference'))
@pytest.mark.parametrize('raised', (False, True))
def test_two_state_domains_and_leading_forwarded_reference_keep_exact_produced_slot(key, raised):
    program, model, details = two_domain_literal_invoke(raised)
    index = ExecutionIndex(model, program)
    view = index.literal_evaluation(details[key], OperationOccurrenceID('0.invoke'))
    assert len(program.locations) == 2
    assert view['canonical']['successor'].arguments[0] == UseID('invoke.forward')
    assert view['canonical']['argument'].index == details[key].result.index
    if raised:
        assert view['status'] == 'NOT_TAKEN' and view['result'] is None
        assert any(value.value == ValueID('second.failure') for value in model.values)
    else:
        assert view['result']['occurrence'].value == ValueID('normal.data' if key == 'invoke' else 'normal.ref')
        assert view['canonical']['result'].origin.index == (3 if key == 'invoke' else 2)
        forwarded = next(value for value in model.values if value.value == ValueID('normal.forwarded'))
        assert index.formal_route(forwarded.id).source_use.use == UseID('invoke.forward')
    assert view['producer_and_effects_retained'] and not view['transformation_authorized']


def test_forwarded_operand_and_second_state_slot_cannot_be_new_literal_producers():
    from scar.ir.program.model import CompletionResult, InvokeLiteralResult
    from scar.ir.program.queries import ProgramIndex
    program, _, details = two_domain_literal_invoke()
    with pytest.raises(TypeError, match='CompletionResult'):
        InvokeLiteralResult(details['invoke'].edge, UseID('invoke.forward'))
    state = InvokeLiteralResult(details['invoke'].edge, CompletionResult(3))
    with pytest.raises(ValueError, match='DATA or REFERENCE'):
        ProgramIndex(program).literal_evaluation(state)


@pytest.mark.parametrize('kind', ('reference', 'data'))
def test_two_loop_visits_retain_separate_original_producer_occurrences(kind):
    program, model, site = literal_loop_execution(kind=kind)
    index = ExecutionIndex(model, program)
    first, second = (index.literal_evaluation(site, OperationOccurrenceID(str(n)+'.literal.make'))
                     for n in (2, 4))
    assert first['canonical'] == second['canonical']
    assert first['result']['occurrence'].id != second['result']['occurrence'].id
    assert first['result']['occurrence'].origin != second['result']['occurrence'].origin
    assert first['canonical']['operation'].accesses and not first['canonical']['operation'].effects_complete
    assert first['inputs'][-1]['value']['occurrence'].id != second['inputs'][-1]['value']['occurrence'].id
    for n, view in ((2, first), (4, second)):
        uses = [row for row in model.uses if row.operation == OperationOccurrenceID(str(n)+'.literal.observe')]
        assert len(uses) == 2 and uses[0].value == uses[1].value == view['result']['occurrence'].id
    assert not first['value_identity_verified'] and not second['transformation_authorized']


@pytest.mark.parametrize('same', (False, True))
def test_same_loop_payload_can_keep_distinct_or_shared_existing_object_denotations(same):
    program, model, site = literal_loop_execution()
    model, evidence = object_denotations(program, model, same=same)
    index = ExecutionIndex(model, program, evidence_graphs=evidence)
    views = tuple(index.literal_evaluation(site, OperationOccurrenceID(str(n)+'.literal.make')) for n in (2, 4))
    identities = tuple(view['result']['denotation']['denotation'].identity for view in views)
    assert (identities[0] == identities[1]) is same
    assert views[0]['canonical']['literal'] == views[1]['canonical']['literal']
    assert all(not view['value_identity_verified'] for view in views)


@pytest.mark.parametrize('kind', ('reference', 'data'))
def test_shared_callee_content_uses_each_child_activation_and_original_inputs(kind):
    program, model, site = literal_calls_execution(kind=kind)
    index = ExecutionIndex(model, program)
    views = tuple(index.literal_evaluation(site, OperationOccurrenceID('child.'+str(n)+'.0.literal.make'))
                  for n in (1, 2))
    assert views[0]['activation'] != views[1]['activation']
    assert views[0]['result']['occurrence'].id != views[1]['result']['occurrence'].id
    assert views[0]['inputs'][0]['value']['occurrence'].id != views[1]['inputs'][0]['value']['occurrence'].id
    assert views[0]['canonical']['literal'] == views[1]['canonical']['literal']
    assert len(model.call_activations) == 2


@pytest.mark.parametrize('same', (False, True))
def test_shared_callee_payload_does_not_choose_between_existing_object_identities(same):
    program, model, site = literal_calls_execution()
    model, evidence = object_denotations(program, model, same=same)
    index = ExecutionIndex(model, program, evidence_graphs=evidence)
    identities = tuple(index.literal_evaluation(site, OperationOccurrenceID('child.'+str(n)+'.0.literal.make'))
        ['result']['denotation']['denotation'].identity for n in (1, 2))
    assert (identities[0] == identities[1]) is same


@pytest.mark.parametrize('case', ('loop', 'call'))
def test_same_static_payload_cannot_bypass_original_stale_incarnation_guard(case):
    program, model, _ = literal_loop_execution() if case == 'loop' else literal_calls_execution()
    first = ValueOccurrenceID('2.literal.object' if case == 'loop' else 'child.1.0.literal.object')
    target = OperationOccurrenceID('4.literal.observe' if case == 'loop' else 'child.2.0.literal.observe')
    uses = tuple(replace(row, value=first) if row.operation == target else row for row in model.uses)
    report = validate(replace(model, uses=uses), program)
    expected = 'stale_incarnation' if case == 'loop' else 'use_activation'
    assert not report.valid and any(row.code == expected for row in report.issues)


@pytest.mark.parametrize('edge', (0, 1))
def test_suspension_keeps_abstract_content_but_restores_object_only_through_saved_use(edge):
    program, model, site = literal_resume_execution(edge)
    index = ExecutionIndex(model, program)
    view = index.literal_evaluation(site, OperationOccurrenceID('0.literal.before.cut'))
    saved = next(row for row in model.uses if row.use == UseID('literal.cut.saved'))
    route = index.formal_route(saved.value)
    assert route.source_use.use == UseID('resume.suspend.x')
    assert route.source_use.value == view['result']['occurrence'].id
    abstract = next(row for row in model.uses if row.use == UseID('literal.cut.abstract'))
    assert index.denotation(abstract.value)['literal'] is not None
    assert view['result']['occurrence'].origin == OperationOccurrenceID('0.literal.before.cut')
    assert not view['value_identity_verified'] and not view['transformation_authorized']


def test_literal_attachment_does_not_make_unsaved_object_globally_available_after_cut():
    from scar.ir.program.validation import validate as validate_program
    program, _, _ = literal_resume_execution()
    program = replace(program, operations=tuple(replace(op, uses=tuple(
        replace(use, value=ValueID('literal.cut.object')) if use.id == UseID('literal.cut.saved') else use
        for use in op.uses)) if op.id == OperationID('literal.after.cut') else op
        for op in program.operations))
    assert any(issue.code == 'unavailable_value' for issue in validate_program(program))


def test_state_address_operand_query_retains_new_exact_content_and_original_current_state():
    from scar.ir.execution.coordinates import AccessRef
    from scar.ir.program.literal_sources import ExactLiteralOrigin
    from scar.ir.program.model import DataValue, LiteralOrigin, Use
    from scar.ir.program.state_addresses import DynamicField
    from tests.fixtures.program_state_addresses import state_address_program
    program, details = state_address_program()
    root, invoke = program.state_address_refinements
    name = DataValue(ValueID('exact.address.name'), program.root, LiteralOrigin('field'), 'builtins.str')
    use = Use(UseID('exact.address.name.use'), name.id)
    operations = tuple(replace(op, uses=(*op.uses, use)) if op.id == details['root_operation'] else op
                       for op in program.operations)
    root = replace(root, effects=(replace(root.effects[0], path=(DynamicField(use.id),)), *root.effects[1:]))
    program = replace(program, values=(*program.values, name), operations=operations,
                      state_address_refinements=(root, invoke))
    entry = next(region.entry for region in program.regions if region.id == program.root)
    model = declared_path(program, ((entry, 0), (details['invoke_normal_block'], None)))
    exact = replace(name, origin=ExactLiteralOrigin(PythonLiteral.from_python('field', exact=True)))
    program = replace(program, values=tuple(exact if value.id == name.id else value for value in program.values))
    model = replace(model, snapshot=snapshot_for(program))
    occurrence = next(row.id for row in model.operations if row.operation == details['root_operation'])
    view = ExecutionIndex(model, program).state_address(AccessRef(occurrence, 0))
    assert view['items'][0]['operands'][0]['literal'] == exact.origin
    assert view['coarse_dependencies_retained'] and not view['transformation_authorized']


@pytest.mark.parametrize('kind', ('tuple', 'list', 'dict', 'set', 'fstring', 'tstring'))
def test_runtime_construction_keeps_unknown_inputs_repeated_uses_and_effects(kind):
    source = SourceExpression(SourceReference(SourceAtomID('construct.'+kind), 'construction.py',
        'sha256:'+'c'*64, 1, 1))
    contents = UninterpretedConstant(kind+' construction has references or unexpanded runtime behavior')
    program, model, site = literal_loop_execution(contents=contents, definition=source)
    view = ExecutionIndex(model, program).literal_evaluation(site, OperationOccurrenceID('2.literal.make'))
    assert view['canonical']['literal'] == contents and view['canonical']['definition'] == source
    assert len(view['inputs']) == 3 and len(view['canonical']['uses']) == 3
    assert view['canonical']['operation'].accesses and not view['canonical']['operation'].effects_complete
    assert not view['transformation_authorized']


def test_removing_content_declaration_does_not_remove_the_actual_producer():
    program, model, details = _direct()
    program = replace(program, literal_evaluations=())
    model = replace(model, snapshot=snapshot_for(program))
    view = ExecutionIndex(model, program).literal_evaluation(details['direct'], OperationOccurrenceID('0.direct'))
    assert view['canonical']['row'] is None and view['canonical']['literal'] is None
    assert view['result']['occurrence'].origin == OperationOccurrenceID('0.direct')
    assert view['canonical']['operation'].accesses
    assert any(gap['code'] == 'literal_declaration_missing' for gap in view['gaps'])


def test_tiny_budget_keeps_full_canonical_declaration_and_pending_original_uses():
    program, model, details = _direct()
    view = ExecutionIndex(model, program).literal_evaluation(details['direct'], OperationOccurrenceID('0.direct'), budget=1)
    assert view['status'] == 'TRUNCATED' and view['result'] is None
    assert len(view['canonical']['uses']) == 4 and view['canonical']['row'] is not None
    assert view['pending_operands'] == (0, 1, 2, 3)
    assert view['budget']['used'] == 1 and not view['transformation_authorized']


def test_missing_original_reference_result_is_not_recovered_from_payload():
    program, model, details = _direct()
    missing = ValueOccurrenceID('0.constructed')
    model = replace(model, values=tuple(row for row in model.values if row.id != missing),
        uses=tuple(replace(row, value=Unresolved('result capture missing', model.activations[0].entry))
                   if row.value == missing else row for row in model.uses))
    view = ExecutionIndex(model, program).literal_evaluation(details['reference'], OperationOccurrenceID('0.direct'))
    assert view['result'] is None
    assert any(gap['code'] == 'literal_result_unobserved' for gap in view['gaps'])


@pytest.mark.parametrize('budget', (True, 0, -1, '8'))
def test_bad_budget_is_rejected_before_external_snapshot_refresh(monkeypatch, budget):
    program, model, details = _direct()
    index = ExecutionIndex(model, program)
    monkeypatch.setattr(index, '_content_context', lambda: pytest.fail('invalid request triggered snapshot replay'))
    with pytest.raises((TypeError, ValueError)):
        index.literal_evaluation(details['direct'], OperationOccurrenceID('0.direct'), budget=budget)


def test_query_rejects_a_static_result_site_from_another_occurrence():
    program, model, details = _direct()
    with pytest.raises(ValueError, match='another operation'):
        ExecutionIndex(model, program).literal_evaluation(details['direct'], OperationOccurrenceID('0.invoke'))


def test_returned_literal_view_is_detached_from_the_canonical_program():
    program, model, details = _direct()
    index = ExecutionIndex(model, program)
    first = index.literal_evaluation(details['direct'], OperationOccurrenceID('0.direct'))
    first['canonical']['uses'] = ()
    first['inputs'][0]['value']['definition'] = None
    second = index.literal_evaluation(details['direct'], OperationOccurrenceID('0.direct'))
    assert len(second['canonical']['uses']) == 4
    assert second['inputs'][0]['value']['definition'] is not None


def test_existing_execution_wire_roundtrips_v16_program_snapshot_and_original_result():
    from scar.ir.execution.codec import dumps, loads
    program, model, details = _direct()
    restored = loads(dumps(model))
    assert restored == model and restored.snapshot.schema_version == 16
    view = ExecutionIndex(restored, program).literal_evaluation(details['direct'], OperationOccurrenceID('0.direct'))
    assert view['result']['occurrence'].value == ValueID('computed')
    assert not view['transformation_authorized']
