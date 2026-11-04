"""Finite port-pattern rules and graph interfaces, without semantic authority.

Expected interfaces below are independent literal tuples. No workload runs,
source lowering is performed, or catalogue under test generates its oracle.
"""
from dataclasses import replace

import pytest

from scar.ir.program.control import ProtocolValueKind, ProtocolValueType
from scar.ir.program.ids import BlockID, LocationID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, CompletionResult, CompletionSignature, CompletionSuccessor,
    DataValue, ExitKind, ExitPort, LiteralOrigin, LocalBindingType, Operation, OperationResult,
    ProgramGraph, ReferenceValue, Region, StateLocation, StateVersionValue, Terminator,
    TerminatorKind, Use, UseRole, ValueKind, ValueType,
)
from scar.ir.program.validation import validate
from scar.ir.record_codec import encode, decode
from scar.ir.v2.ids import ValueSlotID


INT = ValueType(ValueKind.DATA, 'builtins.int')
BOOL = ValueType(ValueKind.DATA, 'builtins.bool')
REF = ValueType(ValueKind.REFERENCE)
WORLD = ValueType(ValueKind.STATE, location=LocationID('world'))
OTHER_WORLD = ValueType(ValueKind.STATE, location=LocationID('other-world'))
LOCAL = LocalBindingType(ValueSlotID('local'))
PACKET = ProtocolValueType(ProtocolValueKind.EXCEPTION_PACKET)


def _api():
    from scar.ir.program import signature_patterns
    return signature_patterns


def _ordinary(P, arguments, *, parameters=(), results=(INT,)):
    return P.Signature(P.SignatureForm.ORDINARY, parameters, arguments, P.Fixed(results))


def _invoke(P, world=WORLD):
    return P.Signature(P.SignatureForm.INVOKE, (), P.Fixed((REF, REF, world)),
        completions=(P.SignatureCompletion(ExitKind.NORMAL, P.Fixed((REF, world))),
                     P.SignatureCompletion(ExitKind.RAISE, P.Fixed((REF, world)))))


def _reject(P, make):
    with pytest.raises(P.SignatureError) as rejected:
        make()
    assert rejected.value.code and rejected.value.path and rejected.value.detail


def test_every_pattern_constructor_and_ground_domain_preserves_explicit_order():
    P = _api()
    signature = _ordinary(P, P.Concat((P.Fixed((REF,)), P.TypeParameter('element'),
        P.Repeat('n', P.Fixed((WORLD,))), P.Choice('abi', (
            P.PatternCase('pair', P.Fixed((REF, WORLD))),
            P.PatternCase('traceback', P.Fixed((REF, REF, WORLD))))), P.Splice('tail'))),
        parameters=(P.Parameter('n', P.ParameterKind.COUNT),
            P.Parameter('abi', P.ParameterKind.CHOICE, choices=('pair', 'traceback')),
            P.Parameter('element', P.ParameterKind.TYPE, allowed_kinds=(P.TypeKind.DATA,)),
            P.Parameter('tail', P.ParameterKind.TYPE_VECTOR,
                allowed_kinds=(P.TypeKind.LOCAL_BINDING, P.TypeKind.PROTOCOL))), results=(BOOL,))
    wire = encode(signature, record_tags=P.SIGNATURE_RECORD_TAGS)
    assert decode(P.Signature, wire, record_tags=P.SIGNATURE_RECORD_TAGS) == signature
    pair = P.instantiate_signature(signature, (P.CountBinding('n', 2), P.ChoiceBinding('abi', 'pair'),
        P.TypeBinding('element', INT), P.TypesBinding('tail', (LOCAL, PACKET))))
    assert pair.form is P.SignatureForm.ORDINARY
    assert pair.arguments == (REF, INT, WORLD, WORLD, REF, WORLD, LOCAL, PACKET)
    assert pair.results == (BOOL,) and pair.completions == ()
    short = P.instantiate_signature(signature, (P.CountBinding('n', 0), P.ChoiceBinding('abi', 'traceback'),
        P.TypeBinding('element', INT), P.TypesBinding('tail', (LOCAL, PACKET))))
    assert short.arguments == (REF, INT, REF, REF, WORLD, LOCAL, PACKET)


def test_invoke_choice_comes_from_explicit_profile_not_actual_payload_arity():
    P = _api()
    signature = P.Signature(P.SignatureForm.INVOKE,
        (P.Parameter('layout', P.ParameterKind.CHOICE, choices=('pair', 'traceback')),),
        P.Fixed((REF, WORLD)), completions=(
            P.SignatureCompletion(ExitKind.NORMAL, P.Fixed((REF, WORLD))),
            P.SignatureCompletion(ExitKind.RAISE, P.Choice('layout', (
                P.PatternCase('pair', P.Fixed((REF, WORLD))),
                P.PatternCase('traceback', P.Fixed((REF, REF, WORLD))))))))
    for name, expected in (('pair', (REF, WORLD)), ('traceback', (REF, REF, WORLD))):
        resolved = P.instantiate_signature(signature, (P.ChoiceBinding('layout', name),))
        assert resolved.form is P.SignatureForm.INVOKE
        assert resolved.arguments == (REF, WORLD)
        assert [(row.kind, row.types) for row in resolved.completions] == [
            (ExitKind.NORMAL, (REF, WORLD)), (ExitKind.RAISE, expected)]
    _reject(P, lambda: P.instantiate_signature(signature, ()))
    _reject(P, lambda: P.instantiate_signature(signature, (P.ChoiceBinding('layout', 'guess-from-arity'),)))
    _reject(P, lambda: P.instantiate_signature(P.Signature(P.SignatureForm.INVOKE, (), P.Fixed(()),
        results=P.Fixed(()), completions=(P.SignatureCompletion(ExitKind.NORMAL, P.Fixed(())),)), ()))
    _reject(P, lambda: P.instantiate_signature(P.Signature(P.SignatureForm.INVOKE, (), P.Fixed(()),
        completions=(P.SignatureCompletion(ExitKind.NORMAL, P.Fixed(())),
                     P.SignatureCompletion(ExitKind.NORMAL, P.Fixed(())))), ()))


def test_parameters_bindings_and_exact_ground_types_form_a_closed_domain():
    P = _api()
    parameters = (P.Parameter('n', P.ParameterKind.COUNT),
        P.Parameter('state', P.ParameterKind.TYPE, allowed_kinds=(P.TypeKind.STATE,)))
    signature = _ordinary(P, P.Concat((P.Repeat('n', P.Fixed((REF,))), P.TypeParameter('state'))),
        parameters=parameters, results=())
    good = (P.CountBinding('n', 2), P.TypeBinding('state', WORLD))
    assert P.instantiate_signature(signature, good).arguments == (REF, REF, WORLD)
    # Locations are preserved, rather than collapsed to the STATE family.
    assert P.instantiate_signature(signature, (P.CountBinding('n', 2),
        P.TypeBinding('state', OTHER_WORLD))).arguments == (REF, REF, OTHER_WORLD)
    for bindings in (good[:1], (*good, P.CountBinding('extra', 1)), (*good, good[0]),
            (P.CountBinding('n', True), good[1]), (P.CountBinding('n', -1), good[1]),
            (P.CountBinding('n', 1.0), good[1]),
            (P.ChoiceBinding('n', 'two'), good[1]), (good[0], P.TypeBinding('state', REF)),
            (good[0], P.TypeBinding('state', 'WORLD')), list(good)):
        _reject(P, lambda bindings=bindings: P.instantiate_signature(signature, bindings))
    _reject(P, lambda: P.instantiate_signature(_ordinary(P, P.Fixed(()), parameters=(
        P.Parameter('n', P.ParameterKind.COUNT), P.Parameter('n', P.ParameterKind.COUNT))),
        (P.CountBinding('n', 0),)))
    _reject(P, lambda: P.instantiate_signature(_ordinary(P, P.Fixed(('builtins.int',))), ()))


def test_choice_validates_unselected_branches_and_parameter_kinds_statically():
    P = _api()
    p = (P.Parameter('case', P.ParameterKind.CHOICE, choices=('safe', 'other')),)
    bindings = (P.ChoiceBinding('case', 'safe'),)
    variants = (
        (P.PatternCase('safe', P.Fixed((REF,))), P.PatternCase('other', P.TypeParameter('missing'))),
        (P.PatternCase('safe', P.Fixed((REF,))),),
        (P.PatternCase('safe', P.Fixed((REF,))), P.PatternCase('safe', P.Fixed(()))),
        (P.PatternCase('safe', P.Fixed((REF,))), P.PatternCase('other', P.TypeParameter('case'))),
    )
    for cases in variants:
        _reject(P, lambda cases=cases: P.instantiate_signature(
            _ordinary(P, P.Choice('case', cases), parameters=p), bindings))
    _reject(P, lambda: P.instantiate_signature(_ordinary(P,
        P.Repeat('case', P.Fixed((REF,))), parameters=p), bindings))


def test_budgets_bound_nonempty_and_zero_port_huge_repeats():
    P = _api()
    one = _ordinary(P, P.Fixed((REF,)))
    _reject(P, lambda: P.instantiate_signature(one, (), max_nodes=0))
    _reject(P, lambda: P.instantiate_signature(one, (), max_ports=0))
    signature = _ordinary(P, P.Repeat('n', P.Fixed((REF,))),
        parameters=(P.Parameter('n', P.ParameterKind.COUNT),), results=())
    _reject(P, lambda: P.instantiate_signature(signature,
        (P.CountBinding('n', 10**30),), max_nodes=8, max_ports=4))
    # An empty body may be eliminated in constant time, rather than expanded.
    zero_ports = _ordinary(P, P.Repeat('n', P.Fixed(())),
        parameters=(P.Parameter('n', P.ParameterKind.COUNT),), results=())
    assert P.instantiate_signature(zero_ports, (P.CountBinding('n', 10**30),)).arguments == ()
    empty = _ordinary(P, P.Repeat('n', P.Fixed((REF,))),
        parameters=(P.Parameter('n', P.ParameterKind.COUNT),), results=())
    assert P.instantiate_signature(empty, (P.CountBinding('n', 0),)).arguments == ()


def test_cycles_and_unregistered_subclasses_are_rejected_before_recursion():
    P = _api()
    class ForeignFixed(P.Fixed):
        pass
    _reject(P, lambda: P.instantiate_signature(_ordinary(P, ForeignFixed((REF,))), ()))
    class ForeignValueType(ValueType):
        pass
    _reject(P, lambda: P.instantiate_signature(_ordinary(P,
        P.Fixed((ForeignValueType(ValueKind.REFERENCE),))), ()))
    cyclic = P.Concat(())
    object.__setattr__(cyclic, 'parts', (cyclic,))
    _reject(P, lambda: P.instantiate_signature(_ordinary(P, cyclic), ()))


def _ordinary_graph():
    r, b, opid, retid = RegionID('root'), BlockID('entry'), OperationID('add'), OperationID('return')
    values = (DataValue(ValueID('left'), r, BlockArgument(b, 0), 'builtins.int'),
        DataValue(ValueID('right'), r, BlockArgument(b, 1), 'builtins.int'),
        DataValue(ValueID('sum'), r, OperationResult(opid, 0), 'builtins.int'))
    op = Operation(opid, 'ADD', (Behavior.COMPUTE,), (Use(UseID('left'), values[0].id),
        Use(UseID('right'), values[1].id)), (values[2].id,))
    ret = Operation(retid, 'return', (Behavior.CONTROL,), (Use(UseID('returned'), values[2].id),),
        terminator=Terminator(TerminatorKind.RETURN, values=(UseID('returned'),), exit='normal'))
    return ProgramGraph(r, (Region(r, 'root', b, (Block(b, tuple(v.id for v in values[:2]),
        (opid, retid)),), (ExitPort('normal', ExitKind.NORMAL, (INT,)),)),), (op, ret), values)


def _invoke_graph():
    r, entry, normal, raised = RegionID('root'), BlockID('entry'), BlockID('normal'), BlockID('raised')
    invoke_id = OperationID('invoke')
    values = (ReferenceValue(ValueID('left'), r, BlockArgument(entry, 0)),
        ReferenceValue(ValueID('right'), r, BlockArgument(entry, 1)),
        StateVersionValue(ValueID('before'), r, BlockArgument(entry, 2), WORLD.location),
        DataValue(ValueID('carry'), r, LiteralOrigin(42), 'builtins.int'),
        DataValue(ValueID('normal.carry'), r, BlockArgument(normal, 0), 'builtins.int'),
        ReferenceValue(ValueID('result'), r, BlockArgument(normal, 1)),
        StateVersionValue(ValueID('after.normal'), r, BlockArgument(normal, 2), WORLD.location),
        ReferenceValue(ValueID('error'), r, BlockArgument(raised, 0)),
        DataValue(ValueID('raise.carry'), r, BlockArgument(raised, 1), 'builtins.int'),
        StateVersionValue(ValueID('after.raise'), r, BlockArgument(raised, 2), WORLD.location))
    invoke = Operation(invoke_id, 'ADD', (Behavior.CONTROL, Behavior.READ, Behavior.WRITE),
        (Use(UseID('left'), ValueID('left'), UseRole.REFERENCE),
         Use(UseID('right'), ValueID('right'), UseRole.REFERENCE),
         Use(UseID('world'), ValueID('before'), UseRole.STATE_CONTENT),
         Use(UseID('carry.normal'), ValueID('carry')),
         Use(UseID('carry.raise'), ValueID('carry'))),
        terminator=Terminator(TerminatorKind.INVOKE, successors=(
            CompletionSuccessor(ExitKind.NORMAL, normal, (UseID('carry.normal'), CompletionResult(0), CompletionResult(1))),
            CompletionSuccessor(ExitKind.RAISE, raised, (CompletionResult(0), UseID('carry.raise'), CompletionResult(1))))),
        completions=(CompletionSignature(ExitKind.NORMAL, (REF, WORLD)),
                     CompletionSignature(ExitKind.RAISE, (REF, WORLD))),
        invoke_arguments=(UseID('left'), UseID('right'), UseID('world')))
    done = Operation(OperationID('done'), 'return', (Behavior.CONTROL,),
        (Use(UseID('returned'), ValueID('result'), UseRole.REFERENCE),
         Use(UseID('normal.world'), ValueID('after.normal'), UseRole.STATE_CONTENT)),
        terminator=Terminator(TerminatorKind.RETURN,
            values=(UseID('returned'), UseID('normal.world')), exit='normal'))
    fail = Operation(OperationID('fail'), 'raise', (Behavior.CONTROL,),
        (Use(UseID('error'), ValueID('error'), UseRole.REFERENCE),
         Use(UseID('raise.world'), ValueID('after.raise'), UseRole.STATE_CONTENT)),
        terminator=Terminator(TerminatorKind.RAISE,
            values=(UseID('error'), UseID('raise.world')), exit='raise'))
    return ProgramGraph(r, (Region(r, 'root', entry, (
        Block(entry, (ValueID('left'), ValueID('right'), ValueID('before')), (invoke_id,)),
        Block(normal, (ValueID('normal.carry'), ValueID('result'), ValueID('after.normal')), (done.id,)),
        Block(raised, (ValueID('error'), ValueID('raise.carry'), ValueID('after.raise')), (fail.id,))),
        (ExitPort('normal', ExitKind.NORMAL, (REF, WORLD)), ExitPort('raise', ExitKind.RAISE, (REF, WORLD)))),),
        (invoke, done, fail), values, locations=(StateLocation(WORLD.location, 'world'),))


def _replace_operation(graph, identity, **changes):
    return replace(graph, operations=tuple(replace(row, **changes) if row.id == identity else row
        for row in graph.operations))


def _no_authority(receipt):
    assert receipt['ports_checked'] is True
    assert all(receipt[key] is False for key in ('operation_family_authorized',
        'parameter_provenance_checked', 'source_correspondence_checked',
        'state_relations_checked', 'use_roles_checked', 'transformation_authorized'))


def test_ordinary_ports_keep_result_origin_and_do_not_classify_labels():
    P = _api()
    from scar.ir.program.operation_signatures import OperationSignatureIndex
    graph = _ordinary_graph()
    assert validate(graph) == ()
    resolved = P.instantiate_signature(_ordinary(P, P.Fixed((INT, INT))), ())
    receipt = OperationSignatureIndex(graph).match(OperationID('add'), resolved)
    _no_authority(receipt)
    renamed = _replace_operation(graph, OperationID('add'), label='display only: not an opcode')
    assert OperationSignatureIndex(renamed).match(OperationID('add'), resolved) == receipt
    bad = P.instantiate_signature(_ordinary(P, P.Fixed((INT, INT)), results=(BOOL,)), ())
    _reject(P, lambda: OperationSignatureIndex(graph).match(OperationID('add'), bad))
    _reject(P, lambda: OperationSignatureIndex(graph).match(OperationID('missing'), resolved))
    _reject(P, lambda: OperationSignatureIndex(graph).match(OperationID('return'), resolved))


def test_invoke_uses_explicit_arguments_and_maps_completion_indices_through_forwarding():
    P = _api()
    from scar.ir.program.operation_signatures import OperationSignatureIndex
    graph = _invoke_graph()
    assert validate(graph) == ()
    resolved = P.instantiate_signature(_invoke(P), ())
    receipt = OperationSignatureIndex(graph).match(OperationID('invoke'), resolved)
    _no_authority(receipt)
    normal = next(row for row in receipt['completions'] if row['kind'] == 'NORMAL')
    assert normal['results'][0] == dict(result_index=0, block_argument=ValueID('result').wire)
    assert normal['forwarded'][0] == dict(use=UseID('carry.normal').wire, block_argument=ValueID('normal.carry').wire)
    original = graph.operations[0]
    reordered = _replace_operation(graph, original.id, uses=tuple(reversed(original.uses)), label='arbitrary display')
    assert validate(reordered) == ()
    assert OperationSignatureIndex(reordered).match(original.id, resolved) == receipt
    wrong_order = _replace_operation(graph, original.id,
        invoke_arguments=(UseID('left'), UseID('world'), UseID('right')))
    assert validate(wrong_order) == ()
    _reject(P, lambda: OperationSignatureIndex(wrong_order).match(original.id, resolved))
    wrong_world = P.instantiate_signature(_invoke(P, OTHER_WORLD), ())
    _reject(P, lambda: OperationSignatureIndex(graph).match(original.id, wrong_world))
    extra = _replace_operation(graph, original.id, uses=(*original.uses, Use(UseID('unused'), ValueID('carry'))))
    assert {issue.code for issue in validate(extra)} == {'control_binding'}
    _reject(P, lambda: OperationSignatureIndex(extra).match(original.id, resolved))
