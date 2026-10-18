"""Declared address paths preserve canonical dynamic state and operand routes."""
from dataclasses import replace

import pytest

from scar.ir.execution.common import Unresolved
from scar.ir.execution.coordinates import AccessRef, UseOccurrence, UseRef
from scar.ir.execution.ids import OperationOccurrenceID, ValueOccurrenceID
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.snapshot import snapshot_for
from scar.ir.execution.validation import require_valid
from scar.ir.execution.work import ActualCompletionState, InvokeBoundaryStateEffect
from scar.ir.program.ids import BlockID, OperationID, UseID, ValueID
from scar.ir.program.model import AccessMode, CompletionResult, DataValue, LiteralOrigin, Use, UseRole
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.state_addresses import (
    AddressCoverage, AddressEffect, DomainOwner, Element, ExistingAccess,
    AddressUnit, CellContent, DynamicField, InvokeStateOperand, NamespaceKey, ObjectField,
    ReferenceOwner, ResourceOwner, Slice, StateAddressRefinement, StorageRange, WholeOwner,
)
from scar.ir.program.validation import validate as validate_program
from tests.fixtures.execution_paths import declared_path


def _attach(program, model, *rows):
    program = replace(program, state_address_refinements=tuple(rows))
    return program, replace(model, snapshot=snapshot_for(program))


def _whole(site, mode):
    return StateAddressRefinement(site, (AddressEffect(DomainOwner(), (WholeOwner(),), mode),),
                                  AddressCoverage.PARTIAL)


def _declared(raised=False):
    from tests.fixtures.program_state_addresses import state_address_program
    program, details = state_address_program()
    entry = next(row.entry for row in program.regions if row.id == program.root)
    landing = details['invoke_raise_block'] if raised else details['invoke_normal_block']
    model = declared_path(program, ((entry, int(raised)), (landing, None)))
    access = next(row for row in model.operations if row.operation == details['root_operation'])
    return program, model, details, AccessRef(access.id, details['root_access_index'])


def test_atomic_multi_owner_query_retains_original_carrier_and_each_operand():
    program, model, details, effect = _declared()
    index = ExecutionIndex(model, program)
    view = index.state_address(effect)
    assert len(view['items']) >= 3
    assert view['canonical']['access'] == next(
        row for row in program.operations if row.id == details['root_operation']).accesses[effect.index]
    assert view['before'] == next(row for row in model.uses
        if row.operation == effect.operation and row.use == view['canonical']['access'].before)
    assert view['after'].value == view['canonical']['access'].after
    for item in view['items']:
        if item['owner_use'] is not None:
            assert item['owner_use']['use'].operation == effect.operation
        for operand in item['operands']:
            assert operand['use'].operation == effect.operation
            assert operand['use'].use == operand['site'].use.id
    assert view['coarse_dependencies_retained']
    assert not view['value_identity_verified'] and not view['transformation_authorized']


@pytest.mark.parametrize('selector', ('namespace', 'field', 'dynamic_field', 'cell', 'slice', 'storage'))
def test_selector_variants_bind_existing_operand_ports_without_claiming_address_interpretation(selector):
    program, _, details, _ = _declared()
    root, invoke = program.state_address_refinements
    op = next(op for op in program.operations if op.id == details['root_operation'])
    name = DataValue(ValueID('address.literal.field'), program.root, LiteralOrigin('field'), 'builtins.str')
    name_use = Use(UseID('address.literal.field.use'), name.id)
    op = replace(op, uses=(*op.uses, name_use))
    key = details['root_dynamic_key_use']
    path = {'namespace': NamespaceKey(key), 'field': ObjectField('field'),
            'dynamic_field': DynamicField(name_use.id), 'cell': CellContent(),
            'slice': Slice(key, None, None), 'storage': StorageRange(AddressUnit.BYTE, key, key)}[selector]
    root = replace(root, effects=(replace(root.effects[0], path=(path,), stage=2), *root.effects[1:]))
    program = replace(program, values=(*program.values, name),
        operations=tuple(op if old.id == op.id else old for old in program.operations),
        state_address_refinements=(root, invoke))
    entry = next(region.entry for region in program.regions if region.id == program.root)
    model = declared_path(program, ((entry, 0), (details['invoke_normal_block'], None)))
    effect = AccessRef(next(row.id for row in model.operations if row.operation == op.id), 0)
    view = ExecutionIndex(model, program).state_address(effect)
    expected = {'namespace': (key,), 'field': (), 'dynamic_field': (name_use.id,),
                'cell': (), 'slice': (key,), 'storage': (key, key)}[selector]
    assert tuple(item['use'].use for item in view['items'][0]['operands']) == expected
    assert all(item['value'] is not None for item in view['items'][0]['operands'])
    assert view['items'][0]['effect'].stage == 2
    assert not view['address_interpretation_verified'] and view['coarse_dependencies_retained']


@pytest.mark.parametrize('edge', (0, 1))
def test_branch_owner_and_key_are_forwarded_as_the_selected_pair(edge):
    from tests.fixtures.execution_state_addresses import branch_address_program
    program = branch_address_program()
    block, op = ('normal', 'read') if edge == 0 else ('failure', 'read.failure')
    model = declared_path(program, ((BlockID('entry'), edge), (BlockID(block), None)))
    index = ExecutionIndex(model, program)
    view = index.state_address(AccessRef(OperationOccurrenceID('1.'+op), 0))
    owner = view['items'][0]['owner_use']['value']
    key = view['items'][0]['operands'][0]['value']
    owner_route, key_route = index.formal_route(owner.id), index.formal_route(key.id)
    assert owner_route.transfer.successor_index == key_route.transfer.successor_index == edge
    assert owner_route.source_use.value == ValueOccurrenceID('0.reference' if edge == 0 else '0.other.reference')
    assert key_route.source_use.value == ValueOccurrenceID('0.input' if edge == 0 else 'literal.other.key')
    assert not view['value_identity_verified']


@pytest.mark.parametrize('wrong_subject', (False, True))
def test_address_declaration_cannot_bypass_original_content_read_reference_alignment(wrong_subject):
    from scar.ir.execution.validation import validate
    from tests.fixtures.execution_content_graphs import content_connection_fixture
    program, model, values, evidence, details = content_connection_fixture(kind='reference')
    old = next(op for op in program.operations if op.id == OperationID('content.read'))
    reference = next(use for use in old.uses if use.id == UseID('content.read.reference'))
    second = Use(UseID('content.read.same-value-second-use'), reference.value, UseRole.REFERENCE)
    program = replace(program, operations=tuple(replace(op, uses=(*op.uses, second))
        if op.id == old.id else op for op in program.operations))
    actual = next(use for use in model.uses if use.operation == details['operation'] and use.use == reference.id)
    model = replace(model, uses=(*model.uses, UseOccurrence(actual.operation, second.id, actual.value)))
    row = StateAddressRefinement(ExistingAccess(old.id, 0),
        (AddressEffect(ReferenceOwner(second.id), (ObjectField('field'),), AccessMode.READ),),
        AddressCoverage.PARTIAL)
    program, model = _attach(program, model, row)
    if wrong_subject:
        read = model.content_reads[0]
        read = replace(read, consumer=replace(read.consumer, subject=UseRef(actual.operation, second.id)))
        model = replace(model, content_reads=(read,))
        report = validate(model, program, value_graphs=values, evidence_graphs=evidence)
        assert 'content_effect_reference' in {issue.code for issue in report.issues}
    else:
        index = ExecutionIndex(model, program, value_graphs=values, evidence_graphs=evidence)
        view = index.state_address(AccessRef(actual.operation, 0))
        assert view['items'][0]['owner_use']['use'].use == second.id
        assert index.content_read(details['read'])['read'].consumer.subject.use == reference.id


@pytest.mark.parametrize('raised', (False, True))
def test_invoke_address_uses_actual_completion_and_retains_other_declared_exit(raised):
    program, model, details, _ = _declared(raised)
    op = next(row for row in program.operations if row.id == details['invoke_operation'])
    occurrence = next(row for row in model.operations if row.operation == op.id)
    row = next(row for row in program.state_address_refinements
               if type(row.site) is InvokeStateOperand)
    edge = int(raised)
    post = next(port for port in ProgramIndex(program).state_address(row.site)['completions']
                if port['successor_index'] == edge and type(port['argument']) is CompletionResult)
    formal = next(value for value in model.values if value.value == post['formal'].id)
    effect = InvokeBoundaryStateEffect(occurrence.id, UseRef(occurrence.id, details['invoke_state_use']),
        ActualCompletionState(edge, post['argument'].index, formal.id))
    index = ExecutionIndex(model, program)
    view = index.state_address(effect)
    assert view['dynamic']['actual_successor_index'] == edge
    assert view['after'] == formal and view['after'].id != view['before'].value
    assert {port['successor_index'] for port in view['canonical']['completions']} == {0, 1}
    wrong = replace(effect, post=replace(effect.post, successor_index=1-edge))
    with pytest.raises(ValueError):
        index.state_address(wrong)


def test_truncated_query_keeps_declaration_and_original_state_ports():
    program, model, _, effect = _declared()
    view = ExecutionIndex(model, program).state_address(effect, budget=1)
    assert view['status'] == 'TRUNCATED' and view['budget']['used'] == 1
    assert view['canonical']['refinement'] in program.state_address_refinements
    assert view['canonical']['effects'] and not view['items']
    assert view['pending'] == tuple(range(len(view['canonical']['effects'])))
    assert view['before'] is not None and view['after'] is not None


@pytest.mark.parametrize('missing_forward', (False, True))
def test_forwarded_invoke_state_is_exposed_without_inventing_an_outcome_result(missing_forward):
    program, _, details, _ = _declared()
    row = next(row for row in program.state_address_refinements
               if type(row.site) is InvokeStateOperand)
    static = ProgramIndex(program).state_address(row.site)
    op = static['operation']
    port = next(port for port in static['completions'] if port['successor_index'] == 0)
    target = next(block for region in program.regions for block in region.blocks
                  if block.id == port['successor'].block)
    position = target.arguments.index(port['formal'].id)
    forwarded = Use(UseID('address.forwarded.state'), static['before'].use.value,
                    UseRole.STATE_CONTENT)
    args = list(port['successor'].arguments)
    args[position] = forwarded.id
    removed = port['argument'].index
    args = [CompletionResult(arg.index - 1) if type(arg) is CompletionResult
            and arg.index > removed else arg for arg in args]
    successors = list(op.terminator.successors)
    successors[0] = replace(successors[0], arguments=tuple(args))
    signatures = tuple(replace(sig, types=tuple(kind for position, kind in enumerate(sig.types)
                                               if position != removed))
                       if sig.kind == port['successor'].kind else sig for sig in op.completions)
    op = replace(op, uses=(*op.uses, forwarded), effects_complete=True,
                 completions=signatures,
                 terminator=replace(op.terminator, successors=tuple(successors)))
    program = replace(program, operations=tuple(op if old.id == op.id else old for old in program.operations))
    entry = next(region.entry for region in program.regions if region.id == program.root)
    model = declared_path(program, ((entry, 0), (target.id, None)))
    if missing_forward:
        model = replace(model, uses=tuple(use for use in model.uses if use.use != forwarded.id))
    occurrence = next(old for old in model.operations if old.operation == op.id)
    unresolved = Unresolved('no Outcome result exists for the forwarded state port', model.activations[0].entry)
    effect = InvokeBoundaryStateEffect(occurrence.id,
        UseRef(occurrence.id, details['invoke_state_use']), unresolved)
    view = ExecutionIndex(model, program).state_address(effect)
    assert view['after'] == unresolved
    assert view['completion']['port']['argument'] == forwarded.id
    if missing_forward:
        assert view['completion']['forwarded_use'] is None
        assert any(gap['code'] == 'state_address_forward_unobserved' for gap in view['gaps'])
    else:
        assert view['completion']['forwarded_use'].value == view['before'].value
    assert view['completion']['formal'].origin == view['dynamic']['actual_transfer'].target
    assert not view['transformation_authorized']


@pytest.mark.parametrize('coarse_write', (False, True))
def test_address_refinement_cannot_hide_stale_state_between_coarse_and_fine_requests(coarse_write):
    program, _, details, _ = _declared()
    root, invoke = program.state_address_refinements
    if coarse_write:
        root = replace(root, effects=(AddressEffect(DomainOwner(), (WholeOwner(),),
                                                   AccessMode.READ_WRITE),),
                       coverage=AddressCoverage.PARTIAL)
        invoke = replace(invoke, effects=(replace(invoke.effects[0], mode=AccessMode.READ),),
                         coverage=AddressCoverage.PARTIAL)
    else:
        invoke = replace(invoke, effects=(AddressEffect(DomainOwner(), (WholeOwner(),),
                                                       AccessMode.READ),),
                         coverage=AddressCoverage.PARTIAL)
    old = ProgramIndex(program).state_address(root.site)['before'].use.value
    program = replace(program, state_address_refinements=(root, invoke), operations=tuple(
        replace(op, uses=tuple(replace(use, value=old) if use.id == details['invoke_state_use']
                                else use for use in op.uses))
        if op.id == details['invoke_operation'] else op for op in program.operations))
    assert 'stale_state' in {issue.code for issue in validate_program(program)}


def test_missing_owner_capture_is_unknown_and_does_not_erase_other_effects():
    program, model, _, effect = _declared()
    index = ExecutionIndex(model, program)
    expected = index.state_address(effect)
    owner = next(item['owner_use']['use'] for item in expected['items'] if item['owner_use'])
    model = replace(model, uses=tuple(row for row in model.uses
                                     if (row.operation, row.use) != (owner.operation, owner.use)))
    require_valid(model, program)
    view = ExecutionIndex(model, program).state_address(effect)
    assert any(gap['code'] == 'state_address_operand_unobserved' for gap in view['gaps'])
    assert len(view['items']) == len(expected['items'])
    assert view['canonical']['refinement'] == expected['canonical']['refinement']


def test_absent_refinement_retains_coarse_access_and_never_means_no_effect():
    program, model, _, effect = _declared()
    program, model = _attach(program, model)
    view = ExecutionIndex(model, program).state_address(effect)
    assert view['status'] == 'PARTIAL' and view['canonical']['refinement'] is None
    assert view['canonical']['access'] and view['before'] and view['after']
    assert any(gap['code'] == 'state_address_refinement_missing' for gap in view['gaps'])


def test_loop_address_sites_have_distinct_current_state_occurrences():
    from tests.fixtures.program_graphs import loop_state_program
    program = loop_state_program()
    row = _whole(ExistingAccess(OperationID('read.counter'), 0), AccessMode.READ)
    program = replace(program, state_address_refinements=(row,))
    path = [('loop.entry', 0), ('header', 0), ('body', 0), ('header', 0),
            ('body', 0), ('header', 1), ('exit', None)]
    model = declared_path(program, tuple((BlockID(block), edge) for block, edge in path))
    index = ExecutionIndex(model, program)
    one = index.state_address(AccessRef(OperationOccurrenceID('1.read.counter'), 0))
    two = index.state_address(AccessRef(OperationOccurrenceID('3.read.counter'), 0))
    assert one['site'] == two['site']
    assert one['before'].value == ValueOccurrenceID('1.header.state')
    assert two['before'].value == ValueOccurrenceID('3.header.state')
    assert one['before'].value != two['before'].value


def test_shared_callee_address_operand_is_bound_within_each_child_activation():
    from tests.fixtures.execution_call_graphs import shared_calls_execution
    program, model, _ = shared_calls_execution()
    op_id = OperationID('count.call')
    key = Use(UseID('address.call.input'), ValueID('body.input'), UseRole.DATA)
    program = replace(program, operations=tuple(replace(op, uses=(*op.uses, key))
        if op.id == op_id else op for op in program.operations))
    additions = []
    for occurrence in model.operations:
        if occurrence.operation == op_id:
            actual = next(row for row in model.values
                          if row.value == key.value and row.origin == occurrence.visit)
            additions.append(UseOccurrence(occurrence.id, key.id, actual.id))
    model = replace(model, uses=(*model.uses, *additions))
    row = StateAddressRefinement(ExistingAccess(op_id, 0),
        (AddressEffect(DomainOwner(), (Element(key.id),), AccessMode.READ_WRITE),), AddressCoverage.PARTIAL)
    program, model = _attach(program, model, row)
    index = ExecutionIndex(model, program)
    views = [index.state_address(AccessRef(occurrence.id, 0)) for occurrence in model.operations
             if occurrence.operation == op_id]
    assert len(views) == 2 and views[0]['activation'] != views[1]['activation']
    one, two = (view['items'][0]['operands'][0] for view in views)
    assert one['site'] == two['site']
    assert one['value'].id != two['value'].id
    assert one['value'].origin != two['value'].origin


@pytest.mark.parametrize('edge', (0, 1))
def test_resume_addresses_use_fresh_segment_state_and_preserve_saved_reference_route(edge):
    from tests.fixtures.program_resumption_graphs import resumption_program
    program = resumption_program()
    block = 'resume.value' if edge == 0 else 'resume.packet'
    op_id = OperationID(block + '.write' if edge == 0 else block + '.attach')
    op = next(row for row in program.operations if row.id == op_id)
    row = _whole(ExistingAccess(op_id, 0), op.accesses[0].mode)
    program = replace(program, state_address_refinements=(row,))
    model = declared_path(program, ((BlockID('resume.entry'), edge), (BlockID(block), None)))
    view = ExecutionIndex(model, program).state_address(
        AccessRef(OperationOccurrenceID('1.' + op_id.value), 0))
    assert len(model.segments) == 2
    assert view['before'].value == ValueOccurrenceID('1.' + block +
        ('.world' if edge == 0 else '.context'))
    route = ExecutionIndex(model, program).formal_route(ValueOccurrenceID('1.' + block + '.x'))
    assert route.source_use.value == ValueOccurrenceID('0.resume.x')


def test_resource_owner_keeps_original_requirement_and_captured_instance_binding():
    from tests.fixtures.execution_work_graphs import ordinary_work_execution
    program, model, values = ordinary_work_execution()
    effect = model.submissions[0].effects[0]
    op = next(row for row in program.operations if row.id == next(
        row.operation for row in model.operations if row.id == effect.operation))
    resource = next(row for row in program.resource_uses
                    if row.operation == op.id and row.handle is not None)
    row = StateAddressRefinement(ExistingAccess(op.id, effect.index),
        (AddressEffect(ResourceOwner(resource.requirement), (WholeOwner(),),
                       op.accesses[effect.index].mode),), AddressCoverage.PARTIAL)
    program, model = _attach(program, model, row)
    view = ExecutionIndex(model, program, value_graphs=values).state_address(effect)
    assert view['items'][0]['resource_use'] == resource
    assert view['items'][0]['resource_matches']
    assert all(item['access'].operation == effect.operation
               and item['binding'].requirement == resource.requirement
               for item in view['items'][0]['resource_matches'])


@pytest.mark.parametrize('budget', (True, 0, -1, '8'))
def test_invalid_budget_is_rejected_before_snapshot_replay(monkeypatch, budget):
    program, model, _, effect = _declared()
    index = ExecutionIndex(model, program)
    monkeypatch.setattr(index, '_content_context', lambda: pytest.fail('unexpected snapshot replay'))
    with pytest.raises((ValueError, TypeError)):
        index.state_address(effect, budget=budget)
