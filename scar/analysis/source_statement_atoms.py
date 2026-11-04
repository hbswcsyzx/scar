"""Assignment, assertion and raise schedules over original source ports.

Address components are evaluated once; annotations retain their original C1
phase. Symbolic compilation options are not observations of the target run.
Native helper expansion and full reference/exception-context cleanup remain
separate obligations, as for the other local source recipes.
"""
from scar.analysis.source_expression_rules import _REF, _BOOL, _require
from scar.ir.program import source_productions as P
from scar.ir.program.control import LanguageCompletionKind as C
from scar.ir.program.signature_patterns import ChoiceBinding
from scar.ir.program.structured import PythonProtocolKind as K


def _release(b, root, value, state):
    return b.protocol(root, K.FRAME_RELEASE_TEMPORARY, (value,), state)[0]


def _binding(b, root, occurrence, action, state, value=None):
    site = b.auxiliary(occurrence, 'id', P.ProductionDispositionKind.ROLE_PORT)
    b.auxiliary(occurrence, 'ctx', P.ProductionDispositionKind.MARKER)
    field = 'read_plan' if action is P.BindingActionKind.READ else 'write_target'
    ports = [p for p in b.rules._ports.get(site, ()) if getattr(b.rules.source.frontend.bindings.ports[p], field) is not None]
    _require(len(ports) == 1, 'BINDING_INTERFACE_FRONTIER', str(site), 'target requires one original namespace access')
    return b.emit(root, P.AccessBinding(action, ports[0]), (state,) if value is None else (value, state),
        (_REF, b.world) if value is None else (b.world,), source=P.ProductionOccurrence(occurrence))


def _inplace(b, root, state):
    b.mark('target', P.ProductionDispositionKind.TARGET_ADDRESS)
    b.mark('op', P.ProductionDispositionKind.MARKER)
    b.mark('value', P.ProductionDispositionKind.EVALUATED_CHILD)
    b.selector('BinOp', b.site('op'))
    target = b.value(b.site('target')).reference
    kind = b.rules.source.context.syntax.nodes[target].constructor
    _require(kind in ('Name', 'Attribute', 'Subscript') and b.role.context(target) == 'Store',
        'RULE_SHAPE', str(target), 'inplace target requires an original name/attribute/subscript Store')
    saved = ()
    sliced = False
    if kind == 'Name':
        old, state = _binding(b, root, target, P.BindingActionKind.READ, state)
    else:
        for name in b.role.fields[kind]:
            b.auxiliary(target, name, P.ProductionDispositionKind.METADATA)
        site = b.auxiliary(target, 'value', P.ProductionDispositionKind.EVALUATED_CHILD)
        receiver, state = b.evaluate(root, site, state)
        saved = (receiver,)
        if kind == 'Attribute':
            selector = b.auxiliary(target, 'attr', P.ProductionDispositionKind.ROLE_PORT)
            old, state = b.action(root, P.LanguageActionKind.ATTRIBUTE_GET, (selector,), (*saved, state))
        else:
            site = b.auxiliary(target, 'slice', P.ProductionDispositionKind.EVALUATED_CHILD)
            index = b.value(site).reference
            sliced = b.rules.source.statements.two_part_slice(index)
            if sliced:
                for name in ('lower', 'upper', 'step'):
                    b.auxiliary(index, name, P.ProductionDispositionKind.METADATA)
                for name in ('lower', 'upper'):
                    part = b.auxiliary(index, name, P.ProductionDispositionKind.EVALUATED_CHILD)
                    if b.value(part).kind == 'NODE':
                        bound, state = b.evaluate(root, part, state)
                    else:
                        bound, state = b.literal(root, None, state, source=part)
                    saved = (*saved, bound)
                old, state = b.protocol(root, K.BINARY_SLICE, saved, state)
            else:
                value, state = b.evaluate(root, site, state)
                saved = (*saved, value)
                old, state = b.action(root, P.LanguageActionKind.ITEM_GET, (), (*saved, state))
    right, state = b.evaluate(root, b.site('value'), state)
    result, state = b.emit(root, P.ApplyInplaceOperator(b.site('op'), b.rules.exception_abi),
        (old, right, state), (_REF, b.world))
    if kind == 'Name':
        state, = _binding(b, root, target, P.BindingActionKind.WRITE, state, result)
    elif kind == 'Attribute':
        state, = b.action(root, P.LanguageActionKind.ATTRIBUTE_SET, (selector,), (*saved, result, state), (b.world,))
    elif sliced:
        # Preserve the existing source-helper order: value, receiver, bounds.
        state, = b.protocol(root, K.STORE_SLICE, (result, *saved), state)
    else:
        state, = b.action(root, P.LanguageActionKind.ITEM_SET, (), (*saved, result, state), (b.world,))
    state = _release(b, root, result, state)
    b.finish(root, (state,), (b.world,))


def _annotation_address_checks(b, root, target, state):
    """Declaration-only attributes/subscripts evaluate addresses, never get/set.

    A declaration slice checks its components individually: constructing a
    tuple or slice object here would add work that CPython does not perform.
    """
    kind = b.rules.source.context.syntax.nodes[target].constructor
    for name in b.role.fields[kind]:
        b.auxiliary(target, name, P.ProductionDispositionKind.METADATA)
    if kind == 'Name':
        b.auxiliary(target, 'id', P.ProductionDispositionKind.ROLE_PORT)
        return state
    _require(kind in ('Attribute', 'Subscript'), 'RULE_SHAPE', str(target), 'invalid annotation target')
    fields = [b.auxiliary(target, 'value', P.ProductionDispositionKind.EVALUATED_CHILD)]
    if kind == 'Subscript':
        fields.append(b.auxiliary(target, 'slice', P.ProductionDispositionKind.EVALUATED_CHILD))
    pending = list(reversed(fields))
    while pending:
        site = pending.pop()
        node = b.value(site)
        _require(node.kind == 'NODE', 'RULE_SHAPE', str(site), 'annotation address requires an expression')
        constructor = b.rules.source.context.syntax.nodes[node.reference].constructor
        if constructor == 'Slice':
            children = []
            for name in ('lower', 'upper', 'step'):
                child = b.auxiliary(node.reference, name, P.ProductionDispositionKind.METADATA)
                if b.value(child).kind == 'NODE':
                    b.slots[child] = P.ProductionDispositionKind.EVALUATED_CHILD
                    children.append(child)
            pending.extend(reversed(children))
        elif constructor == 'Tuple':
            b.auxiliary(node.reference, 'ctx', P.ProductionDispositionKind.MARKER)
            field = b.auxiliary(node.reference, 'elts', P.ProductionDispositionKind.EVALUATED_CHILD)
            pending.extend(P.SlotRef(field.occurrence, field.group, field.ordinal, (i,))
                for i in reversed(range(len(b.value(field).items))))
        else:
            value, state = b.evaluate(root, site, state)
            state = _release(b, root, value, state)
    return state


def _annotated(b, root, state):
    b.mark('target', P.ProductionDispositionKind.TARGET_ADDRESS)
    b.mark('annotation', P.ProductionDispositionKind.SUPPRESSED)
    target = b.value(b.site('target')).reference
    if b.value(b.site('value')).kind == 'NODE':
        b.mark('value', P.ProductionDispositionKind.EVALUATED_CHILD)
        value, state = b.evaluate(root, b.site('value'), state)
        state, = b.evaluate(root, b.site('target'), state, P.ProductionPurpose.STORE, value)
        state = _release(b, root, value, state)
    else:
        state = _annotation_address_checks(b, root, target, state)
    publication = b.rules.source.statements.annotation_publication(b.occurrence, b.rules.exception_abi)
    if publication is not None:
        b.mark('annotation', P.ProductionDispositionKind.DEFERRED_CHILD
            if publication.publication is P.AnnotationPublicationKind.DEFERRED else P.ProductionDispositionKind.METADATA)
        state, = b.emit(root, publication, (state,), (b.world,), may_raise=(
            publication.publication is P.AnnotationPublicationKind.STRINGIZED or publication.conditional_registration))
    b.finish(root, (state,), (b.world,))


def _raise(b, root, state):
    arguments = []
    for name in ('exc', 'cause'):
        site = b.site(name)
        value = b.value(site)
        if value.kind == 'NODE':
            _require(name != 'cause' or arguments, 'RULE_SHAPE', str(site), 'raise cause requires an exception expression')
            b.mark(name, P.ProductionDispositionKind.EVALUATED_CHILD)
            argument, state = b.evaluate(root, site, state)
            arguments.append(argument)
    protocol = (K.RERAISE, K.RAISE_EXCEPTION, K.RAISE_WITH_CAUSE)[len(arguments)]
    payload = b.protocol(root, protocol, tuple(arguments), state)
    b.transfer(root, C.RAISE, payload, b.raised)


def _assert(b, root, state):
    enabled, = b.emit(root, P.ReadCompilationOption(P.CompilationOption.ASSERTIONS_ENABLED), (), (_BOOL,), may_raise=False)
    checked = b.region(root.source, (b.world,), root)
    omitted = b.region(root.source, (b.world,), root)
    b.finish(omitted, (b.parameter(omitted, 0),), (b.world,))
    b.mark('test', P.ProductionDispositionKind.EVALUATED_CHILD)
    condition, current = b.condition(checked,b.site('test'),b.parameter(checked,0))
    decision_state = current
    passed = b.region(root.source, (b.world,), checked)
    b.finish(passed, (b.parameter(passed, 0),), (b.world,))
    failed = b.region(root.source, (b.world,), checked)
    current = b.parameter(failed, 0)
    message = ()
    if b.value(b.site('msg')).kind == 'NODE':
        b.mark('msg', P.ProductionDispositionKind.EVALUATED_CHILD)
        value, current = b.evaluate(failed, b.site('msg'), current)
        message = (value,)
    error, current = b.protocol(failed, K.MAKE_ASSERTION_ERROR, message, current,
        (ChoiceBinding('message', 'PRESENT' if message else 'ABSENT'),))
    payload = b.protocol(failed, K.RAISE_EXCEPTION, (error,), current)
    b.transfer(failed, C.RAISE, payload, b.raised)
    result = b.control(checked, P.BranchControl(P.ProductionRegionCall(passed.id, (decision_state,)),
        P.ProductionRegionCall(failed.id, (decision_state,))), (condition,), b.union(b.completions(passed), b.completions(failed)))
    b.finish(checked, result, (b.world,))
    result = b.control(root, P.BranchControl(P.ProductionRegionCall(checked.id, (state,)),
        P.ProductionRegionCall(omitted.id, (state,))), (enabled,), b.union(b.completions(checked), b.completions(omitted)))
    b.finish(root, result, (b.world,))


def emit_atomic_statement(b, root, state):
    {'AugAssign': _inplace, 'AnnAssign': _annotated, 'Assert': _assert, 'Raise': _raise}[b.node.constructor](b, root, state)
