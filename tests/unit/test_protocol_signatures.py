"""Declared protocol rules and typed parameter sources, without source authority.

Literal port tuples below are independent oracles. The small graph fixtures do
not execute target code or lower source; catalogue enumeration checks coverage.
"""
from dataclasses import replace

import pytest

from scar.ir.program.control import ProtocolValueKind, ProtocolValueType
from scar.ir.program.functions import BodyEntryInterface, BodyLoweringProfile, FormalPort
from scar.ir.program.ids import BlockID, LocationID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, CompletionResult, CompletionSignature,
    CompletionSuccessor, DataValue, ExitKind, ExitPort, Footprint, FootprintKind,
    Operation, OperationResult, ProgramGraph, ProtocolValue, ReferenceValue, Region, StateAccess,
    StateLocation, StateVersionValue, Terminator, TerminatorKind, Use, UseRole,
    ValueKind, ValueType, LocalBindingType,
)
from scar.ir.program.source import LoweringMetadata, OperationSource, SourceRole, UseSource, ValueSource
from scar.ir.program.source_language import SourceLanguageCapability, SourceLanguageOverlay, UnpackShape
from scar.ir.program.structured import PythonProtocol, PythonProtocolKind as K, StructuredBodyModel
from scar.ir.program.validation import validate
from scar.ir.semantics_v2 import SourceSnapshot
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import OperationDefinitionID, SourceAtomID, ValueSlotID


REF = ValueType(ValueKind.REFERENCE)
BOOL = ValueType(ValueKind.DATA, 'builtins.bool')
STR = ValueType(ValueKind.DATA, 'builtins.str')
WORLD = ValueType(ValueKind.STATE, location=LocationID('world'))
OTHER_WORLD = ValueType(ValueKind.STATE, location=LocationID('other-world'))
LOCAL = LocalBindingType(ValueSlotID('local'))
OTHER_LOCAL = LocalBindingType(ValueSlotID('other-local'))
SOURCE = SourceReference(SourceAtomID('original'), '/source/micro.py', 'sha256:' + 'a' * 64, 1, 4)
SNAPSHOT = SourceSnapshot(SOURCE.path, SOURCE.fingerprint)
DEFINITION = OperationDefinitionID('function')


def _api():
    from scar.ir.program import signature_patterns as P
    from scar.ir.program import protocol_signatures as C
    return P, C


def _bindings(P, abi='EXCEPTION_WORLD', *extra):
    return (P.TypeBinding('world', WORLD), P.ChoiceBinding('exception_abi', abi), *extra)


def _reject(call):
    from scar.ir.program.signature_patterns import SignatureError
    with pytest.raises(SignatureError) as error:
        call()
    assert error.value.code and error.value.path and error.value.detail
    return error.value


def _completion_types(signature):
    return tuple((row.kind, row.types) for row in signature.completions)


def _value(identity, region, origin, sort):
    if sort.kind is ValueKind.REFERENCE:
        return ReferenceValue(identity, region, origin)
    if sort.kind is ValueKind.STATE:
        return StateVersionValue(identity, region, origin, sort.location)
    return DataValue(identity, region, origin, sort.data_type)


def _invoke_graph(normal_payload=(BOOL,), failed_payload=(REF,), *, argument_payload=(REF,)):
    """One invoke, with independently declared argument and landing ports."""
    root, entry = RegionID('root'), BlockID('entry')
    operation = OperationID('protocol')
    argument_types = (*argument_payload, WORLD)
    values = [_value(ValueID('argument-' + str(i)), root, BlockArgument(entry, i), sort)
              for i, sort in enumerate(argument_types)]
    entry_arguments = tuple(row.id for row in values)
    uses = tuple(Use(UseID('world' if sort.kind is ValueKind.STATE else 'reference-' + str(i)),
        row.id, UseRole.STATE_CONTENT if sort.kind is ValueKind.STATE else
        UseRole.REFERENCE if sort.kind is ValueKind.REFERENCE else UseRole.DATA)
        for i, (row, sort) in enumerate(zip(values, argument_types)))
    blocks, edges, signatures, exits, terminals = [], [], [], [], []
    for kind, payload in ((ExitKind.NORMAL, normal_payload), (ExitKind.RAISE, failed_payload)):
        block = BlockID(kind.value.lower())
        types = (*payload, WORLD)
        results = tuple(_value(ValueID(kind.value + '-' + str(i)), root, BlockArgument(block, i), sort)
                        for i, sort in enumerate(types))
        values.extend(results)
        terminal = OperationID('finish-' + kind.value)
        returned = tuple(Use(UseID(kind.value + '-return-' + str(i)), row.id,
            UseRole.STATE_CONTENT if sort.kind is ValueKind.STATE else
            UseRole.REFERENCE if sort.kind is ValueKind.REFERENCE else UseRole.DATA)
            for i, (row, sort) in enumerate(zip(results, types)))
        terminals.append(Operation(terminal, kind.value, (Behavior.CONTROL,), returned,
            terminator=Terminator(TerminatorKind.RETURN if kind is ExitKind.NORMAL else TerminatorKind.RAISE,
                values=tuple(row.id for row in returned), exit=kind.value.lower())))
        blocks.append(Block(block, tuple(row.id for row in results), (terminal,)))
        edges.append(CompletionSuccessor(kind, block, tuple(CompletionResult(i) for i in range(len(types)))))
        signatures.append(CompletionSignature(kind, types))
        exits.append(ExitPort(kind.value.lower(), kind, types))
    attempted = Operation(operation, 'display label', (Behavior.CONTROL, Behavior.READ, Behavior.WRITE), uses,
        terminator=Terminator(TerminatorKind.INVOKE, tuple(edges)), completions=tuple(signatures),
        invoke_arguments=tuple(row.id for row in uses))
    graph = ProgramGraph(root, (Region(root, 'body', entry,
        (Block(entry, entry_arguments, (operation,)), *blocks), tuple(exits)),),
        (attempted, *terminals), tuple(values), locations=(StateLocation(WORLD.location, 'world'),))
    assert validate(graph) == ()
    return graph


def _context_records(graph, kind):
    operation = graph.operations[0].id
    structured = StructuredBodyModel(DEFINITION, graph.root, SOURCE, (PythonProtocol(operation, kind, SOURCE),))
    root = next(row for row in graph.regions if row.id == graph.root)
    entry = next(row for row in root.blocks if row.id == root.entry)
    values = {row.id: row for row in graph.values}
    formals = tuple(FormalPort(ValueSlotID('argument-' + str(i)), identity)
                    for i, identity in enumerate(entry.arguments) if type(values[identity]) is ReferenceValue)
    world, = tuple(identity for identity in entry.arguments if type(values[identity]) is StateVersionValue)
    interface = BodyEntryInterface(DEFINITION, graph.root,
        formals, world, BodyLoweringProfile.STRUCTURED_BODY)
    metadata = LoweringMetadata('f', SNAPSHOT,
        operation_links=tuple(OperationSource(row.id, SOURCE, SourceRole.EXPRESSION) for row in graph.operations),
        value_links=tuple(ValueSource(row.id, SOURCE, SourceRole.EXPRESSION) for row in graph.values),
        use_links=tuple(UseSource(row.id, use.id, SOURCE, 'fixture', i)
            for row in graph.operations for i, use in enumerate(row.uses)))
    return structured, interface, metadata


def _no_authority(receipt):
    assert receipt['ports_checked'] is True and receipt['state_relations_checked'] is True
    for name in ('operation_family_authorized', 'parameter_provenance_checked',
            'source_correspondence_checked', 'transformation_authorized'):
        assert receipt[name] is False


def test_catalogue_is_closed_and_every_active_rule_instantiates_all_choice_branches():
    P, C = _api()
    rules = C.protocol_signature_catalog()
    assert len(rules) == 88 and tuple(row.kind for row in rules) == tuple(K)
    assert {row.kind for row in rules if row.signature is None} == {K.OPAQUE_EXPRESSION, K.OPAQUE_STATEMENT}
    samples = {P.TypeKind.REFERENCE: REF, P.TypeKind.DATA: BOOL, P.TypeKind.STATE: WORLD,
               P.TypeKind.LOCAL_BINDING: LOCAL,
               P.TypeKind.PROTOCOL: ProtocolValueType(ProtocolValueKind.EXCEPTION_PACKET)}
    for rule in rules:
        assert C.protocol_signature_rule(rule.kind) == rule
        if rule.signature is None:
            assert rule.state_policy is C.ProtocolStatePolicy.UNIMPLEMENTED and rule.requirements == ()
            _reject(lambda kind=rule.kind: C.resolve_protocol_signature(kind, ()))
            continue
        assert tuple(row.name for row in rule.requirements) == tuple(row.name for row in rule.signature.parameters)
        base = []
        for parameter in rule.signature.parameters:
            if parameter.kind is P.ParameterKind.COUNT:
                base.append(P.CountBinding(parameter.name, 2))
            elif parameter.kind is P.ParameterKind.CHOICE:
                choice = 'SCOPED_TARGETS' if parameter.name == 'comprehension_profile' else parameter.choices[0]
                base.append(P.ChoiceBinding(parameter.name, choice))
            elif parameter.kind is P.ParameterKind.TYPE:
                base.append(P.TypeBinding(parameter.name, samples[parameter.allowed_kinds[0]]))
            else:
                base.append(P.TypesBinding(parameter.name, (samples[parameter.allowed_kinds[0]],)))
        assert C.resolve_protocol_signature(rule.kind, tuple(base)).form is rule.signature.form
        for i, parameter in enumerate(rule.signature.parameters):
            variants = ([P.ChoiceBinding(parameter.name, choice) for choice in parameter.choices]
                if parameter.kind is P.ParameterKind.CHOICE else
                [P.CountBinding(parameter.name, 0)] if parameter.kind is P.ParameterKind.COUNT else
                [P.TypesBinding(parameter.name, ())] if parameter.kind is P.ParameterKind.TYPE_VECTOR else [])
            for variant in variants:
                C.resolve_protocol_signature(rule.kind, (*base[:i], variant, *base[i + 1:]))
    _reject(lambda: C.protocol_signature_rule('TRUTH'))
    _reject(lambda: C.protocol_signature_rule(None))


def test_literal_invoke_goldens_preserve_world_selector_and_exception_coupling():
    P, C = _api()
    for abi, raised in (('EXCEPTION_WORLD', (REF, WORLD)),
                        ('EXCEPTION_TRACEBACK_WORLD', (REF, REF, WORLD))):
        truth = C.resolve_protocol_signature(K.TRUTH, _bindings(P, abi))
        assert truth.arguments == (REF, WORLD)
        assert _completion_types(truth) == ((ExitKind.NORMAL, (BOOL, WORLD)), (ExitKind.RAISE, raised))
        source = C.resolve_protocol_signature(K.SOURCE_BINARY, _bindings(P, abi))
        assert source.arguments == (REF, REF, STR, WORLD)
        assert _completion_types(source) == ((ExitKind.NORMAL, (REF, WORLD)), (ExitKind.RAISE, raised))
        reraised = C.resolve_protocol_signature(K.RERAISE, _bindings(P, abi))
        assert reraised.arguments == (WORLD,)
        assert _completion_types(reraised) == ((ExitKind.NORMAL, raised), (ExitKind.RAISE, raised))
    _reject(lambda: C.resolve_protocol_signature(K.TRUTH, (P.ChoiceBinding('exception_abi', 'EXCEPTION_WORLD'),)))
    _reject(lambda: C.resolve_protocol_signature(K.TRUTH, (P.TypeBinding('world', REF),
        P.ChoiceBinding('exception_abi', 'EXCEPTION_WORLD'))))
    _reject(lambda: C.resolve_protocol_signature(K.FUNCTION_START_PROPAGATION, _bindings(P)))
    paired = C.resolve_protocol_signature(K.FUNCTION_START_PROPAGATION,
        _bindings(P, 'EXCEPTION_TRACEBACK_WORLD'))
    assert paired.arguments == (REF, WORLD)
    assert _completion_types(paired) == ((ExitKind.NORMAL, (REF, REF, WORLD)),
        (ExitKind.RAISE, (REF, REF, WORLD)))
    _reject(lambda: C.resolve_protocol_signature(K.GENEXPR_CONTAINS,
        _bindings(P, 'EXCEPTION_TRACEBACK_WORLD')))


def test_comprehension_cleanup_templates_preserve_two_different_operand_orders():
    P, C = _api()
    legacy = C.resolve_protocol_signature(K.COMPREHENSION_LEAVE,
        (P.TypeBinding('world', WORLD), P.ChoiceBinding('comprehension_profile', 'LEGACY_SINGLE_TARGET'),
         P.ChoiceBinding('container', 'ABSENT'), P.TypesBinding('binding_types', (LOCAL,))))
    assert legacy.arguments == (LOCAL, REF, WORLD) and legacy.results == (WORLD,)
    scoped = C.resolve_protocol_signature(K.COMPREHENSION_LEAVE,
        (P.TypeBinding('world', WORLD), P.ChoiceBinding('comprehension_profile', 'SCOPED_TARGETS'),
         P.ChoiceBinding('container', 'PRESENT'), P.TypesBinding('binding_types', (LOCAL, OTHER_LOCAL))))
    assert scoped.arguments == (REF, REF, LOCAL, OTHER_LOCAL, WORLD) and scoped.results == (WORLD,)
    no_container = C.resolve_protocol_signature(K.COMPREHENSION_LEAVE,
        (P.TypeBinding('world', WORLD), P.ChoiceBinding('comprehension_profile', 'SCOPED_TARGETS'),
         P.ChoiceBinding('container', 'ABSENT'), P.TypesBinding('binding_types', (LOCAL, OTHER_LOCAL))))
    assert no_container.arguments == (REF, LOCAL, OTHER_LOCAL, WORLD)
    _reject(lambda: C.resolve_protocol_signature(K.COMPREHENSION_LEAVE,
        (P.TypeBinding('world', WORLD), P.ChoiceBinding('comprehension_profile', 'guess-from-ports'),
         P.ChoiceBinding('container', 'ABSENT'), P.TypesBinding('binding_types', (LOCAL,)))))
    _reject(lambda: C.resolve_protocol_signature(K.COMPREHENSION_LEAVE,
        (P.TypeBinding('world', WORLD), P.ChoiceBinding('comprehension_profile', 'SCOPED_TARGETS'),
         P.ChoiceBinding('container', 'PRESENT'), P.TypesBinding('binding_types', (REF,)))))
    for container, bindings in (('PRESENT', (LOCAL,)), ('ABSENT', (LOCAL, OTHER_LOCAL))):
        _reject(lambda container=container, bindings=bindings: C.resolve_protocol_signature(K.COMPREHENSION_LEAVE,
            (P.TypeBinding('world', WORLD), P.ChoiceBinding('comprehension_profile', 'LEGACY_SINGLE_TARGET'),
             P.ChoiceBinding('container', container), P.TypesBinding('binding_types', bindings))))


def test_context_derives_root_abi_from_typed_profile_and_keeps_source_authority_closed():
    P, _ = _api()
    from scar.ir.program.protocol_signature_context import ProtocolSignatureIndex
    graph = _invoke_graph()
    records = _context_records(graph, K.TRUTH)
    index = ProtocolSignatureIndex(graph, *records)
    operation = graph.operations[0].id
    receipt = index.match(operation)
    _no_authority(receipt)
    assert receipt['protocol_kind'] == 'TRUTH' and receipt['parameter_source_records_checked'] is True
    renamed = replace(graph, operations=(replace(graph.operations[0], label='GET_ITERATOR'), *graph.operations[1:]))
    assert ProtocolSignatureIndex(renamed, *records).match(operation) == receipt
    _reject(lambda: index.match(operation, (P.TypeBinding('world', WORLD),)))
    _reject(lambda: index.match(operation, (P.ChoiceBinding('exception_abi', 'EXCEPTION_WORLD'),)))
    language = SourceLanguageOverlay(SNAPSHOT, (SourceLanguageCapability.FUNCTION_TRY_314_V1,), namespace_root='/source')
    _reject(lambda: ProtocolSignatureIndex(graph, *records, language=language).match(operation))
    paired_graph = _invoke_graph(failed_payload=(REF, REF))
    paired_records = _context_records(paired_graph, K.TRUTH)
    _no_authority(ProtocolSignatureIndex(paired_graph, *paired_records, language=language).match(operation))
    # This declared-only query cannot distinguish two different source meanings
    # with the same ABI. It must expose its lack of source authorization.
    iterator_graph = _invoke_graph(normal_payload=(REF,))
    for kind in (K.GET_ITERATOR, K.ADVANCE_ITERATOR):
        _no_authority(ProtocolSignatureIndex(iterator_graph, *_context_records(iterator_graph, kind)).match(operation))
    bad_source = replace(SOURCE, fingerprint='sha256:' + 'b' * 64)
    bad_model = replace(records[0], protocols=(PythonProtocol(operation, K.TRUTH, bad_source),))
    _reject(lambda: ProtocolSignatureIndex(graph, bad_model, *records[1:]))
    _reject(lambda: index.match(OperationID('missing')))


def test_unpack_count_comes_from_original_shape_and_cannot_be_supplied_or_guessed():
    P, _ = _api()
    from scar.ir.program.protocol_signature_context import ProtocolSignatureIndex
    graph = _invoke_graph(normal_payload=(REF, REF))
    records = _context_records(graph, K.UNPACK_FIXED)
    operation = graph.operations[0].id
    children = (replace(SOURCE, atom_id=SourceAtomID('first'), start_line=2, end_line=2),
                replace(SOURCE, atom_id=SourceAtomID('second'), start_line=3, end_line=3))
    shape = UnpackShape(operation, SOURCE, children)
    language = SourceLanguageOverlay(SNAPSHOT, (SourceLanguageCapability.FIXED_UNPACK,),
        unpackings=(shape,), namespace_root='/source')
    index = ProtocolSignatureIndex(graph, *records, language=language)
    receipt = index.match(operation)
    _no_authority(receipt)
    assert any(row['record'] == 'SourceLanguageOverlay.unpackings' and row['selector'] == 'child_targets'
               for row in receipt['parameter_records'])
    _reject(lambda: index.match(operation, (P.CountBinding('child_count', 1),)))
    _reject(lambda: index.match(operation, (P.CountBinding('child_count', 2),)))
    _reject(lambda: ProtocolSignatureIndex(graph, *records).match(operation))
    empty = replace(language, unpackings=())
    _reject(lambda: ProtocolSignatureIndex(graph, *records, language=empty).match(operation))
    _reject(lambda: ProtocolSignatureIndex(graph, *records,
        language=replace(language, unpackings=(replace(shape, child_targets=children[:1]),))).match(operation))


def test_state_policies_check_actual_access_relations_without_claiming_purity():
    P, C = _api()
    from scar.ir.program.protocol_signature_state import validate_protocol_state
    graph = _invoke_graph()
    values = {row.id: row for row in graph.values}
    invoke = graph.operations[0]
    truth = C.resolve_protocol_signature(K.TRUTH, _bindings(P))
    receipt = validate_protocol_state(invoke, values, truth, C.ProtocolStatePolicy.INVOKE_WORLD)
    assert receipt['state_relations_checked'] is True
    assert receipt['source_effects_checked'] is False and receipt['transformation_authorized'] is False
    # effects_complete is an existing declaration, not a new source proof.
    declared = validate_protocol_state(replace(invoke, effects_complete=True), values, truth,
        C.ProtocolStatePolicy.INVOKE_WORLD)
    assert declared['effects_complete'] is True and declared['source_effects_checked'] is False
    illegal = StateAccess(WORLD.location, UseID('world'), AccessMode.READ)
    forged = replace(invoke)
    object.__setattr__(forged, 'accesses', (illegal,))
    _reject(lambda: validate_protocol_state(forged, values, truth, C.ProtocolStatePolicy.INVOKE_WORLD))

    before, after = ValueID('before'), ValueID('after')
    identity = OperationID('frame-discard')
    reference = ReferenceValue(ValueID('reference'), graph.root, BlockArgument(BlockID('entry'), 0))
    state_values = {reference.id: reference,
        before: StateVersionValue(before, graph.root, BlockArgument(BlockID('entry'), 1), WORLD.location),
        after: StateVersionValue(after, graph.root, OperationResult(identity, 0), WORLD.location)}
    access = StateAccess(WORLD.location, UseID('before-use'), AccessMode.READ_WRITE, after)
    write = Operation(identity, 'frame', (Behavior.READ, Behavior.WRITE, Behavior.MEMORY),
        (Use(UseID('reference-use'), reference.id, UseRole.REFERENCE),
         Use(UseID('before-use'), before, UseRole.STATE_CONTENT)), (after,), (access,))
    signature = C.resolve_protocol_signature(K.FRAME_DISCARD, (P.TypeBinding('world', WORLD),))
    result = validate_protocol_state(write, state_values, signature, C.ProtocolStatePolicy.WRITE_WORLD)
    assert result['state_relations_checked'] is True and access.footprint.kind is FootprintKind.UNKNOWN
    _reject(lambda: validate_protocol_state(replace(write,
        accesses=(replace(access, reference=UseID('reference-use')),)), state_values, signature,
        C.ProtocolStatePolicy.WRITE_WORLD))
    _reject(lambda: validate_protocol_state(replace(write,
        accesses=(replace(access, after=before),)), state_values, signature, C.ProtocolStatePolicy.WRITE_WORLD))
    _reject(lambda: validate_protocol_state(replace(write, accesses=()), state_values, signature,
        C.ProtocolStatePolicy.WRITE_WORLD))

    read_id, boolean = OperationID('read'), ValueID('boolean')
    read_values = {**state_values, boolean: DataValue(boolean, graph.root, OperationResult(read_id, 0), 'builtins.bool')}
    read = replace(write, id=read_id, results=(boolean,),
        accesses=(StateAccess(WORLD.location, UseID('before-use'), AccessMode.READ),))
    read_signature = C.resolve_protocol_signature(K.MATCH_STOP_ITERATION, (P.TypeBinding('world', WORLD),))
    assert validate_protocol_state(read, read_values, read_signature,
        C.ProtocolStatePolicy.READ_WORLD)['state_relations_checked'] is True
    _reject(lambda: validate_protocol_state(replace(read, accesses=(access,)), read_values, read_signature,
        C.ProtocolStatePolicy.READ_WORLD))

    packet_id, packet_value = OperationID('packet'), ValueID('packet-value')
    packet = replace(write, id=packet_id, uses=(write.uses[0],), results=(packet_value,), accesses=())
    # Packet's two reference operands can alias; their UseIDs remain distinct.
    packet = replace(packet, uses=(write.uses[0], replace(write.uses[0], id=UseID('second-reference'))))
    packet_values = {**state_values, packet_value: ProtocolValue(packet_value, graph.root,
        OperationResult(packet_id, 0), ProtocolValueKind.EXCEPTION_PACKET)}
    packet_signature = C.resolve_protocol_signature(K.FUNCTION_EXCEPTION_PACKET, ())
    assert validate_protocol_state(packet, packet_values, packet_signature,
        C.ProtocolStatePolicy.NO_STATE)['state_relations_checked'] is True
    packet_access = StateAccess(WORLD.location, packet.uses[0].id, AccessMode.READ)
    forged_packet = replace(packet)
    object.__setattr__(forged_packet, 'accesses', (packet_access,))
    _reject(lambda: validate_protocol_state(forged_packet, packet_values, packet_signature, C.ProtocolStatePolicy.NO_STATE))

    cleanup_id = OperationID('cleanup')
    pending = ProtocolValue(ValueID('pending'), graph.root, BlockArgument(BlockID('entry'), 0),
        ProtocolValueKind.PENDING_COMPLETION)
    context = ProtocolValue(ValueID('saved-context'), graph.root, BlockArgument(BlockID('entry'), 1),
        ProtocolValueKind.SAVED_HANDLED_CONTEXT)
    domains = (WORLD, OTHER_WORLD)
    before_states = tuple(StateVersionValue(ValueID('domain-before-' + str(i)), graph.root,
        BlockArgument(BlockID('entry'), i + 2), sort.location) for i, sort in enumerate(domains))
    after_states = tuple(StateVersionValue(ValueID('domain-after-' + str(i)), graph.root,
        OperationResult(cleanup_id, i), sort.location) for i, sort in enumerate(domains))
    cleanup_uses = (Use(UseID('pending-use'), pending.id, UseRole.PROTOCOL),
        Use(UseID('saved-context-use'), context.id, UseRole.PROTOCOL),
        *(Use(UseID('domain-use-' + str(i)), row.id, UseRole.STATE_CONTENT) for i, row in enumerate(before_states)))
    cleanup_accesses = tuple(StateAccess(sort.location, cleanup_uses[i + 2].id, AccessMode.READ_WRITE,
        after_states[i].id, Footprint(FootprintKind.WHOLE)) for i, sort in enumerate(domains))
    cleanup = Operation(cleanup_id, 'cleanup', (Behavior.READ, Behavior.WRITE), cleanup_uses,
        tuple(row.id for row in after_states), cleanup_accesses)
    cleanup_values = {row.id: row for row in (pending, context, *before_states, *after_states)}
    cleanup_signature = C.resolve_protocol_signature(K.FUNCTION_CLEANUP_RESUME,
        (P.TypesBinding('state_types', domains),))
    assert validate_protocol_state(cleanup, cleanup_values, cleanup_signature,
        C.ProtocolStatePolicy.WRITE_DOMAINS)['state_relations_checked'] is True
    _reject(lambda: validate_protocol_state(replace(cleanup, accesses=(
        replace(cleanup_accesses[0], footprint=Footprint()), cleanup_accesses[1])), cleanup_values,
        cleanup_signature, C.ProtocolStatePolicy.WRITE_DOMAINS))


def test_frame_entry_count_is_derived_from_formals_not_its_actual_use_count():
    from scar.ir.program.protocol_signature_context import ProtocolSignatureIndex
    root, entry, identity = RegionID('root'), BlockID('entry'), OperationID('enter')
    reference = ReferenceValue(ValueID('argument-0'), root, BlockArgument(entry, 0))
    before = StateVersionValue(ValueID('argument-1'), root, BlockArgument(entry, 1), WORLD.location)
    after = StateVersionValue(ValueID('after'), root, OperationResult(identity, 0), WORLD.location)
    access = StateAccess(WORLD.location, UseID('world'), AccessMode.READ_WRITE, after.id)
    enter = Operation(identity, 'entry', (Behavior.READ, Behavior.WRITE, Behavior.MEMORY),
        (Use(UseID('formal'), reference.id, UseRole.REFERENCE),
         Use(UseID('world'), before.id, UseRole.STATE_CONTENT)), (after.id,), (access,))
    returned = Operation(OperationID('return'), 'return', (Behavior.CONTROL,),
        (Use(UseID('returned'), reference.id, UseRole.REFERENCE),
         Use(UseID('post-world'), after.id, UseRole.STATE_CONTENT)),
        terminator=Terminator(TerminatorKind.RETURN, values=(UseID('returned'), UseID('post-world')), exit='normal'))
    graph = ProgramGraph(root, (Region(root, 'body', entry,
        (Block(entry, (reference.id, before.id), (identity, returned.id)),),
        (ExitPort('normal', ExitKind.NORMAL, (REF, WORLD)),)),), (enter, returned),
        (reference, before, after), locations=(StateLocation(WORLD.location, 'world'),))
    assert validate(graph) == ()
    records = _context_records(graph, K.FRAME_ENTER)
    _no_authority(ProtocolSignatureIndex(graph, *records).match(identity))
    _reject(lambda: ProtocolSignatureIndex(graph, records[0],
        replace(records[1], parameters=()), records[2]).match(identity))


def test_frame_exit_uses_original_source_port_group_and_keeps_duplicate_values():
    P, _ = _api()
    from scar.ir.program.protocol_signature_context import ProtocolSignatureIndex
    root, entry, identity = RegionID('root'), BlockID('entry'), OperationID('frame-exit')
    payload = ReferenceValue(ValueID('payload'), root, BlockArgument(entry, 0))
    temporary = ReferenceValue(ValueID('temporary'), root, BlockArgument(entry, 1))
    before = StateVersionValue(ValueID('before'), root, BlockArgument(entry, 2), WORLD.location)
    after = StateVersionValue(ValueID('after'), root, OperationResult(identity, 0), WORLD.location)
    uses = (Use(UseID('payload-use'), payload.id, UseRole.REFERENCE),
        Use(UseID('first-held-use'), temporary.id, UseRole.REFERENCE),
        Use(UseID('second-held-use'), temporary.id, UseRole.REFERENCE),
        Use(UseID('world-use'), before.id, UseRole.STATE_CONTENT))
    exit_op = Operation(identity, 'exit', (Behavior.READ, Behavior.WRITE, Behavior.MEMORY), uses,
        (after.id,), (StateAccess(WORLD.location, uses[-1].id, AccessMode.READ_WRITE, after.id),))
    returned = Operation(OperationID('returned'), 'return', (Behavior.CONTROL,),
        (Use(UseID('returned-payload'), payload.id, UseRole.REFERENCE),
         Use(UseID('returned-world'), after.id, UseRole.STATE_CONTENT)),
        terminator=Terminator(TerminatorKind.RETURN,
            values=(UseID('returned-payload'), UseID('returned-world')), exit='normal'))
    graph = ProgramGraph(root, (Region(root, 'body', entry,
        (Block(entry, (payload.id, temporary.id, before.id), (identity, returned.id)),),
        (ExitPort('normal', ExitKind.NORMAL, (REF, WORLD)),)),), (exit_op, returned),
        (payload, before, temporary, after), locations=(StateLocation(WORLD.location, 'world'),))
    assert validate(graph) == ()
    model, interface, metadata = _context_records(graph, K.FRAME_EXIT)
    interface = replace(interface, parameters=(FormalPort(ValueSlotID('payload'), payload.id),
        FormalPort(ValueSlotID('temporary'), temporary.id)))
    source_ports = (UseSource(identity, uses[0].id, SOURCE, 'held-payload', 0),
        UseSource(identity, uses[1].id, SOURCE, 'held-temporary', 1),
        UseSource(identity, uses[2].id, SOURCE, 'held-temporary', 2),
        UseSource(identity, uses[3].id, SOURCE, 'frame-world', 0))
    others = tuple(row for row in metadata.use_links if row.operation != identity)
    metadata = replace(metadata, use_links=(*source_ports, *others))
    index = ProtocolSignatureIndex(graph, model, interface, metadata)
    receipt = index.match(identity)
    _no_authority(receipt)
    assert receipt['parameter_source_records_checked'] is True
    assert receipt['arguments'] == [row.id.wire for row in uses]
    assert uses[1].value == uses[2].value and uses[1].id != uses[2].id
    _reject(lambda: index.match(identity, (P.TypesBinding('held_types', (REF, REF)),)))

    # Swapping same-sort aliases preserves core typing and values, but changes
    # the original declared UseID vector and must be caught by the join.
    swapped = replace(graph, operations=(replace(exit_op,
        uses=(uses[0], uses[2], uses[1], uses[3])), returned))
    assert validate(swapped) == ()
    _reject(lambda: ProtocolSignatureIndex(swapped, model, interface, metadata).match(identity))
    for malformed in (source_ports[:2] + source_ports[3:],
            (*source_ports, replace(source_ports[1], role='held-local')),
            (source_ports[0], source_ports[1], replace(source_ports[2], index=3), source_ports[3]),
            (source_ports[0], source_ports[1], replace(source_ports[2], index=1), source_ports[3])):
        _reject(lambda malformed=malformed: ProtocolSignatureIndex(graph, model, interface,
            replace(metadata, use_links=(*malformed, *others))).match(identity))


def test_source_port_groups_bind_variadics_options_and_nonzero_map_pair_indices():
    from scar.ir.program.protocol_signature_context import ProtocolSignatureIndex

    def declared(kind, ports):
        graph = _invoke_graph(normal_payload=(REF,), argument_payload=(REF,) * len(ports))
        operation = graph.operations[0]
        # Equal ValueIDs do not merge distinct source argument Uses.
        if len(ports) > 1:
            uses = (operation.uses[0], *(replace(row, value=operation.uses[0].value)
                for row in operation.uses[1:-1]), operation.uses[-1])
            operation = replace(operation, uses=uses)
            graph = replace(graph, operations=(operation, *graph.operations[1:]))
            assert validate(graph) == ()
        model, interface, metadata = _context_records(graph, kind)
        arguments = tuple(UseSource(operation.id, use.id, SOURCE, role, index)
            for use, (role, index) in zip(operation.uses[:-1], ports))
        rows = (*arguments, UseSource(operation.id, operation.uses[-1].id, SOURCE, 'state', 0))
        others = tuple(row for row in metadata.use_links if row.operation != operation.id)
        return graph, model, interface, replace(metadata, use_links=(*rows, *others)), rows, others

    cases = (
        (K.CALL_FUNCTION_EX, (('callee', 0), ('call-positionals', 0))),
        (K.CALL_FUNCTION_EX, (('callee', 0), ('call-starred-positionals', 0), ('call-keywords', 0))),
        (K.BUILD_CALL_POSITIONAL_LIST, ()),
        (K.BUILD_CALL_POSITIONAL_LIST, (('argument', 0), ('argument', 1), ('argument', 2))),
        (K.BUILD_STRING, ()),
        (K.BUILD_STRING, (('protocol-input', 0), ('protocol-input', 1))),
        (K.MAKE_ASSERTION_ERROR, ()),
        (K.MAKE_ASSERTION_ERROR, (('protocol-input', 0),)),
        (K.BUILD_MAP, ()),
        (K.BUILD_MAP, (('mapping-key', 7), ('mapping-value', 7), ('mapping-key', 8), ('mapping-value', 8))),
        (K.BUILD_MAP, (('call-keyword-name', 11), ('keyword:alpha', 11),
                       ('call-keyword-name', 12), ('keyword:beta', 12))),
    )
    for kind, ports in cases:
        graph, model, interface, metadata, rows, others = declared(kind, ports)
        operation = graph.operations[0]
        receipt = ProtocolSignatureIndex(graph, model, interface, metadata).match(operation.id)
        _no_authority(receipt)
        assert receipt['parameter_source_records_checked'] is True
        assert receipt['arguments'] == [row.id.wire for row in operation.uses]
        if not ports:
            empty = [row for row in receipt['parameter_records']
                     if row.get('completeness') == 'DECLARED_EMPTY_GROUP']
            assert len(empty) == 1 and empty[0]['uses'] == [] and empty[0]['explicit_empty_marker'] is False
        if len(ports) > 1:
            assert len({row.value for row in operation.uses[:-1]}) == 1
            swapped_uses = (operation.uses[1], operation.uses[0], *operation.uses[2:])
            swapped = replace(graph, operations=(replace(operation, uses=swapped_uses,
                invoke_arguments=tuple(row.id for row in swapped_uses)), *graph.operations[1:]))
            assert validate(swapped) == ()
            _reject(lambda: ProtocolSignatureIndex(swapped, model, interface, metadata).match(operation.id))
        unknown = replace(rows[0], role='not-a-declared-source-port')
        _reject(lambda: ProtocolSignatureIndex(graph, model, interface,
            replace(metadata, use_links=(unknown, *rows[1:], *others))).match(operation.id))

    for kind, ports in (
        (K.BUILD_STRING, (('protocol-input', 0), ('protocol-input', 0))),
        (K.MAKE_ASSERTION_ERROR, (('protocol-input', 1),)),
        (K.CALL_FUNCTION_EX, (('callee', 0), ('call-positionals', 0), ('call-starred-positionals', 0))),
        (K.BUILD_MAP, (('mapping-key', 7), ('mapping-value', 7), ('mapping-key', 7), ('mapping-value', 7))),
        (K.BUILD_MAP, (('mapping-key', 7), ('mapping-value', 8))),
        (K.BUILD_MAP, (('call-keyword-name', 11), ('keyword:', 11))),
    ):
        graph, model, interface, metadata, _, _ = declared(kind, ports)
        _reject(lambda: ProtocolSignatureIndex(graph, model, interface, metadata).match(graph.operations[0].id))
