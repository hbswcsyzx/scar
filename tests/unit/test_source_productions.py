"""Independent recipe specimens, not proof of Python constructor lowering."""
from copy import deepcopy
from dataclasses import replace

import pytest

from scar.analysis import source_productions as A
from scar.ir.program import source_productions as P
from scar.ir.program.control import LanguageCompletionKind as C
from scar.ir.program.model import ValueKind, ValueType
from scar.ir.program.source_contexts import ContextState, OwnerRef


INT = ValueType(ValueKind.DATA, 'builtins.int')
BOOL = ValueType(ValueKind.DATA, 'builtins.bool')
REF = ValueType(ValueKind.REFERENCE)
SOURCE = P.ProductionOccurrence(0)
CONTEXT = ContextState(OwnerRef(0, 'ROOT'), 0, 0, 0)
BASIS = P.ProductionInput('/source/test.py', '/source', *('a' * 64 for _ in range(5)))


def normal(*types):
    return (P.ProductionCompletion(C.FALLTHROUGH, types),)


def region(name, *, parent=None, kind=P.ProductionRegionKind.EXECUTION, parameters=(INT,), outputs=None, steps=()):
    return P.ProductionRegion(P.ProductionRegionID(name), parent, kind, SOURCE, CONTEXT,
        parameters, normal(INT) if outputs is None else outputs, tuple(P.ProductionStepID(s) for s in steps))


def step(name, owner, instruction, args=(), outputs=None):
    return P.ProductionStep(P.ProductionStepID(name), owner.id, SOURCE, instruction,
        args, normal(INT) if outputs is None else outputs)


def parameter(owner, index=0):
    return P.ProductionParameter(owner.id, index)


def plan(regions, steps):
    return P.SourceProductionPlan(BASIS, SOURCE, P.ProductionPurpose.VALUE,
        regions[0].id, tuple(regions), tuple(steps), ())


def identity():
    root = region('root', steps=('return',))
    return plan((root,), (step('return', root, P.TransferCompletion(C.FALLTHROUGH), (parameter(root),)),))


def test_closed_grammar_exact_records_strict_codec_and_budgets():
    value = identity()
    summary = A.validate_production_plan(value)
    assert summary['steps'] == summary['regions'] == 1
    assert summary['source_rules_replayed'] is False
    assert summary['control_semantics_checked'] is False
    assert A.read_production_plan(A.production_plan_document(value)) == value
    catalog = A.production_type_catalog()
    assert catalog['counts'] == dict(records=36, fields=102, identifiers=4, enums=12, enum_members=185, unions=9)
    assert set(catalog['instruction_variants']) == {
        'EvaluateChild', 'ApplyLanguageAction', 'ApplyPythonProtocol', 'AccessBinding', 'ConstructValue', 'DefineLiteral', 'ApplyRegion',
        'BranchControl', 'LoopControl', 'DeferRegion', 'CleanupControl', 'HandleCompletions',
        'TransferCompletion', 'SuspendExecution'}
    assert A.read_production_type_catalog(deepcopy(catalog)) == catalog
    # bool must not silently pass as an int, and unregistered subclasses fail.
    malformed = replace(value, source=replace(SOURCE, occurrence=True))
    with pytest.raises(A.ProductionError, match='TYPE_MISMATCH'):
        A.validate_production_plan(malformed)
    class Extended(P.ProductionOccurrence):
        pass
    with pytest.raises(A.ProductionError, match='TYPE_MISMATCH'):
        A.validate_production_plan(replace(value, source=Extended(0)))
    with pytest.raises(A.ProductionError, match='BUDGET_FRONTIER'):
        A.validate_production_plan(value, max_visits=0)
    wire = A.production_plan_document(value)
    wire['unexpected'] = True
    with pytest.raises(A.ProductionError, match='WIRE_SCHEMA'):
        A.read_production_plan(wire)
    cyclic = []
    cyclic.append(cyclic)
    with pytest.raises(A.ProductionError, match='VALUE_CYCLE'):
        A.read_production_plan(cyclic)
    with pytest.raises(A.ProductionError, match='BUDGET_FRONTIER'):
        A.read_production_plan([0] * 10_000, max_visits=4)


def test_ordered_values_shared_subregion_and_invalid_local_edges():
    root = region('root', steps=('first', 'second'))
    shared = region('shared', parent=root.id, steps=('shared_return',))
    first = step('first', root, P.ApplyRegion(P.ProductionRegionCall(shared.id, (parameter(root),))))
    second = step('second', root, P.ApplyRegion(P.ProductionRegionCall(shared.id, (P.ProductionResult(first.id, 0),))))
    value = plan((root, shared), (first, second,
        step('shared_return', shared, P.TransferCompletion(C.FALLTHROUGH), (parameter(shared),))))
    assert A.validate_production_plan(value)['regions'] == 2  # one shared region, two uses
    for changed in (
        replace(value, regions=(replace(root, steps=tuple(reversed(root.steps))), shared)),
        replace(value, steps=(replace(first, instruction=P.ApplyRegion(P.ProductionRegionCall(shared.id,
            (parameter(shared),)))), *value.steps[1:])),
        replace(value, steps=(replace(first, instruction=P.ApplyRegion(P.ProductionRegionCall(shared.id,
            (P.ProductionResult(second.id, 0),)))), *value.steps[1:])),
        replace(value, regions=(root, replace(shared, parent=shared.id))),
        replace(value, steps=(*value.steps, first)),
    ):
        with pytest.raises(A.ProductionError):
            A.validate_production_plan(changed)


def test_early_exception_is_preserved_when_normal_path_has_a_later_return():
    exits = (*normal(INT), P.ProductionCompletion(C.RAISE, (REF,)))
    root = region('root', steps=('invoke', 'finish'), outputs=exits)
    invoke = step('invoke', root, P.ApplyLanguageAction(P.LanguageActionKind.CALL),
        (parameter(root),), exits)
    finish = step('finish', root, P.TransferCompletion(C.FALLTHROUGH),
        (P.ProductionResult(invoke.id, 0),))
    value = plan((root,), (invoke, finish))
    assert A.validate_production_plan(value)['regions'] == 1
    with pytest.raises(A.ProductionError, match='REGION_EXIT'):
        A.validate_production_plan(replace(value, regions=(replace(root, completions=normal(INT)),)))


def test_existing_protocol_signatures_are_mandatory_for_recipe_protocol_steps():
    from scar.ir.program.ids import LocationID
    from scar.ir.program.signature_patterns import CountBinding, ChoiceBinding, TypeBinding
    from scar.ir.program.structured import PythonProtocolKind as K
    world = ValueType(ValueKind.STATE, location=LocationID('world'))
    exits = (*normal(REF, world), P.ProductionCompletion(C.RAISE, (REF, world)))
    root = region('root', parameters=(REF, REF, world), outputs=exits, steps=('pack',))
    bindings = (TypeBinding('world', world), ChoiceBinding('exception_abi', 'EXCEPTION_WORLD'),
                CountBinding('item_count', 2))
    pack = step('pack', root, P.ApplyPythonProtocol(K.BUILD_CALL_POSITIONALS, bindings),
        tuple(parameter(root, i) for i in range(3)), exits)
    value = plan((root,), (pack,))
    assert A.validate_production_plan(value)['protocol_signature_checks'] == 1
    assert A.read_production_plan(A.production_plan_document(value)) == value
    for instruction in (
        replace(pack.instruction, bindings=(*bindings[:2], CountBinding('item_count', 1))),
        replace(pack.instruction, protocol=K.OPAQUE_EXPRESSION),
        replace(pack.instruction, bindings=(bindings[0], ChoiceBinding('exception_abi', 'EXCEPTION_TRACEBACK_WORLD'), bindings[2])),
    ):
        with pytest.raises(A.ProductionError):
            A.validate_production_plan(replace(value, steps=(replace(pack, instruction=instruction),)))


def test_implicit_literals_keep_exact_values_without_asserting_identity_or_allocation():
    from scar.ir.literals import PythonLiteral
    for literal in (None, '', (), ('nested', 7)):
        root = region('root', parameters=(), outputs=normal(REF), steps=('literal',))
        instruction = P.DefineLiteral(PythonLiteral.from_python(literal))
        value = plan((root,), (step('literal', root, instruction, outputs=normal(REF)),))
        result = A.read_production_plan(A.production_plan_document(value))
        assert result.steps[0].instruction.value.to_python() == literal


def test_branch_has_boolean_decision_explicit_capture_ports_and_completion_union():
    root = region('root', parameters=(BOOL, INT), steps=('branch',))
    yes = region('yes', parent=root.id, kind=P.ProductionRegionKind.ALTERNATIVE, steps=('yes_return',))
    no = region('no', parent=root.id, kind=P.ProductionRegionKind.ALTERNATIVE, steps=('no_return',))
    branch = step('branch', root, P.BranchControl(
        P.ProductionRegionCall(yes.id, (parameter(root, 1),)),
        P.ProductionRegionCall(no.id, (parameter(root, 1),))), (parameter(root),))
    value = plan((root, yes, no), (branch,
        step('yes_return', yes, P.TransferCompletion(C.FALLTHROUGH), (parameter(yes),)),
        step('no_return', no, P.TransferCompletion(C.FALLTHROUGH), (parameter(no),))))
    assert A.read_production_plan(A.production_plan_document(value)) == value
    with pytest.raises(A.ProductionError, match='PORT_TYPES'):
        A.validate_production_plan(replace(value, steps=(replace(branch, arguments=(parameter(root, 1),)), *value.steps[1:])))


def test_loop_template_carries_ports_without_iterations_or_cross_region_value_edges():
    root = region('loop', kind=P.ProductionRegionKind.LOOP, parameters=(REF, INT), steps=('drive',))
    condition = region('condition', parent=root.id, kind=P.ProductionRegionKind.LOOP_CONDITION,
        parameters=(REF, INT), outputs=normal(BOOL, INT), steps=('test', 'condition_return'))
    body = region('body', parent=root.id, parameters=(REF, INT),
        kind=P.ProductionRegionKind.LOOP_BODY, steps=('body_return',))
    test = step('test', condition, P.ApplyLanguageAction(P.LanguageActionKind.TRUTH), (parameter(condition, 1),), normal(BOOL))
    value = plan((root, condition, body), (
        step('drive', root, P.LoopControl(condition.id, body.id, invariant_count=1),
            (parameter(root), parameter(root, 1))), test,
        step('condition_return', condition, P.TransferCompletion(C.FALLTHROUGH),
            (P.ProductionResult(test.id, 0), parameter(condition, 1)), normal(BOOL, INT)),
        step('body_return', body, P.TransferCompletion(C.FALLTHROUGH), (parameter(body, 1),))))
    assert A.validate_production_plan(value)['regions'] == 3
    assert 'iteration' not in str(A.production_plan_document(value)).lower()
    with pytest.raises(A.ProductionError, match='LOOP_INTERFACE'):
        A.validate_production_plan(replace(value, regions=(root, condition, replace(body, parameters=(BOOL,)))))
    # Deferred body parameters belong to its later invocation, not the declaration.
    outer = region('outer', parameters=(REF,), outputs=normal(REF), steps=('defer',))
    deferred = region('deferred', parent=outer.id, kind=P.ProductionRegionKind.DEFERRED, steps=('later_return',))
    delayed = plan((outer, deferred), (
        step('defer', outer, P.DeferRegion(deferred.id), (parameter(outer),), normal(REF)),
        step('later_return', deferred, P.TransferCompletion(C.FALLTHROUGH), (parameter(deferred),))))
    assert A.validate_production_plan(delayed)['regions'] == 2


def test_exception_payload_enters_handler_ports_instead_of_normal_value_edges():
    root = region('root', steps=('handle',))
    protected = region('protected', parent=root.id, steps=('invoke',), outputs=(
        *normal(INT), P.ProductionCompletion(C.RAISE, (REF,))))
    handler = region('handler', parent=root.id, kind=P.ProductionRegionKind.HANDLER,
        parameters=(REF, INT), steps=('recovered',))
    value = plan((root, protected, handler), (
        step('handle', root, P.HandleCompletions(P.ProductionRegionCall(protected.id, (parameter(root),)),
            (P.CompletionRoute(C.RAISE, None, handler.id, (parameter(root),)),))),
        step('invoke', protected, P.ApplyLanguageAction(P.LanguageActionKind.CALL), (parameter(protected),),
            protected.completions),
        step('recovered', handler, P.TransferCompletion(C.FALLTHROUGH), (parameter(handler, 1),))))
    assert A.read_production_plan(A.production_plan_document(value)) == value
    with pytest.raises(A.ProductionError, match='PORT_TYPES'):
        A.validate_production_plan(replace(value, regions=(root, protected, replace(handler, parameters=(INT, REF)))))
    with pytest.raises(A.ProductionError, match='VALUE_ORDER'):
        A.validate_production_plan(replace(value, steps=(*value.steps[:2], replace(value.steps[2],
            arguments=(P.ProductionResult(value.steps[1].id, 0),)))))


def test_original_source_inputs_fields_contexts_and_binding_ports():
    # Reuse official static material factories; the target text is not run.
    from scar.analysis.source_bytes import source_bytes_document
    from scar.analysis.source_tokens import source_tokens_document
    from scar.analysis.source_syntax import source_syntax_document
    from scar.analysis.source_roles import source_roles_document
    from scar.analysis.source_contexts import source_contexts_document
    from scar.analysis.source_declarations import source_declarations_document
    from scar.analysis.source_bindings import source_bindings_document
    from scar.analysis.source_symbols import source_symbols_document
    from scar.analysis.compiler_topology import compiler_topology_document
    from scar.analysis.compiler_symbols import compiler_symbols_document
    from scar.analysis.frontend_bindings import read_frontend_bindings
    from scar.analysis.source_context_view import SourceContextView
    from scar.ir.program.source_syntax import SourceSyntaxMaterial
    from scar.ir.record_codec import decode

    f0 = source_bytes_document(b'x = 3\ny = x.attr\n', path='/source/test.py', namespace_root='/source')
    f1 = source_tokens_document(f0)
    f2 = source_syntax_document(f0, f1)
    b = source_roles_document(f0, f1, f2)
    c = source_contexts_document(f0, f1, f2, b)
    d = source_declarations_document(f0, f1, f2, b, c)
    q = source_bindings_document(f0, f1, f2, b, c, d)
    a = source_symbols_document(f0, f1, f2)
    t = compiler_topology_document(f0, f1, f2, b, c, a)
    s = compiler_symbols_document(f0, f1, f2, b, c, d, a, t)
    frontend = read_frontend_bindings(f0, f1, f2, b, c, d, q, a, t, s)
    context = SourceContextView(decode(SourceSyntaxMaterial, f2), frontend.roles, frontend.contexts)
    index = A.ProductionSourceIndex(f0, context, frontend)
    names = [i for i, n in enumerate(context.syntax.nodes)
        if n.constructor == 'Name' and context.role_view.context(i) == 'Load']
    assert len(names) == 1
    occurrence = names[0]
    site = P.SlotRef(occurrence, 'FIELD', context.role_view.fields['Name']['id'])
    port = next(i for i, p in enumerate(frontend.roles.ports) if p.site == site)
    root = replace(region('name', parameters=(), outputs=normal(REF), steps=('read',)),
        source=P.ProductionOccurrence(occurrence), context=context.entry_context(occurrence))
    read = replace(step('read', root, P.AccessBinding(P.BindingActionKind.READ, port), outputs=normal(REF)), source=root.source)
    value = replace(plan((root,), (read,)), input=index.input, source=root.source,
        slots=(P.ProductionSlotDisposition(site, P.ProductionDispositionKind.ROLE_PORT),))
    result = index.match(value)
    assert result['original_source_references_checked'] is True
    assert result['upstream_fresh_replayed'] is result['source_rules_replayed'] is False
    bad_port = next(i for i, p in enumerate(frontend.roles.ports) if p.site.occurrence != occurrence)
    for changed, code in (
        (replace(value, input=replace(index.input, f2_sha256='b' * 64)), 'INPUT_LINEAGE'),
        (replace(value, regions=(replace(root, context=replace(root.context, region=99)),)), 'SOURCE_CONTEXT'),
        (replace(value, steps=(replace(read, instruction=P.AccessBinding(P.BindingActionKind.READ, bad_port)),)), 'SOURCE_PORT'),
        (replace(value, slots=(P.ProductionSlotDisposition(replace(site, ordinal=999),
            P.ProductionDispositionKind.METADATA),)), 'SOURCE_REFERENCE'),
    ):
        with pytest.raises(A.ProductionError, match=code):
            index.match(changed)
    # Attribute labels are original role ports, but are not namespace reads.
    label_port = next(i for i, p in enumerate(frontend.roles.ports)
        if context.syntax.nodes[p.site.occurrence].constructor == 'Attribute')
    label = frontend.roles.ports[label_port].site
    attribute_root = replace(root, source=label, context=context.context_at_slot(label).state)
    attribute_step = replace(read, source=label, instruction=P.AccessBinding(P.BindingActionKind.READ, label_port))
    attribute_plan = replace(value, source=label, regions=(attribute_root,), steps=(attribute_step,), slots=())
    with pytest.raises(A.ProductionError, match='SOURCE_PORT'):
        index.match(attribute_plan)
