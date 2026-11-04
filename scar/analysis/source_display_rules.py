"""Container display/target productions; original fields, not AST visitation."""
from scar.analysis.source_expression_rules import _REF, _require
from scar.ir.program import source_productions as P
from scar.ir.program.signature_patterns import CountBinding
from scar.ir.program.structured import PythonProtocolKind as K


def emit_display(b, region, state):
    if b.node.constructor == 'Dict':
        return _mapping(b, region, state)
    kind = b.node.constructor
    if kind != 'Set':
        b.mark('ctx', P.ProductionDispositionKind.MARKER)
        marker = b.value(b.site('ctx'))
        expected = {P.ProductionPurpose.VALUE:'Load', P.ProductionPurpose.STORE:'Store',
                    P.ProductionPurpose.DELETE:'Del'}[b.purpose]
        _require(marker.kind == 'NODE' and b.rules.source.context.syntax.nodes[marker.reference].constructor == expected,
                 'PURPOSE_SOURCE_MISMATCH', str(b.occurrence), 'display target context differs from its purpose')
    b.mark('elts', P.ProductionDispositionKind.EVALUATED_CHILD)
    elements = b.value(b.site('elts'))
    _require(elements.kind == 'LIST', 'RULE_SHAPE', str(b.occurrence), 'display requires an original element list')
    items = []
    for ordinal, item in enumerate(elements.items):
        _require(item.kind == 'NODE', 'RULE_SHAPE', str(b.occurrence), 'display element must be an expression')
        node = b.rules.source.context.syntax.nodes[item.reference]
        site, starred = b.site('elts', ordinal), node.constructor == 'Starred'
        if starred:
            _require(b.purpose is not P.ProductionPurpose.DELETE, 'SOURCE_CODEGEN_CONFLICT', str(site), 'starred deletion is invalid')
            context = b.auxiliary(item.reference, 'ctx', P.ProductionDispositionKind.MARKER)
            marker = b.value(context)
            expected = 'Store' if b.purpose is P.ProductionPurpose.STORE else 'Load'
            _require(marker.kind == 'NODE' and b.rules.source.context.syntax.nodes[marker.reference].constructor == expected,
                     'RULE_SHAPE', str(context), 'starred display context differs from its parent')
            site = b.auxiliary(item.reference, 'value', P.ProductionDispositionKind.TARGET_ADDRESS
                if b.purpose is P.ProductionPurpose.STORE else P.ProductionDispositionKind.EVALUATED_CHILD)
        items.append((site, starred))
    if b.purpose is P.ProductionPurpose.STORE:
        return _store(b, region, state, items)
    if b.purpose is P.ProductionPurpose.DELETE:
        for site, _ in items:
            state, = b.evaluate(region, site, state, P.ProductionPurpose.DELETE)
        return b.finish(region, (state,), (b.world,))

    sequence, held = None, []
    build_kind = K.BUILD_SET_DISPLAY if kind == 'Set' else K.BUILD_DISPLAY_LIST
    if len(items) > b.rules.call_profile['stack_guideline']:
        sequence, state = b.protocol(region, build_kind, (), state, (CountBinding('item_count', 0),), (b.site('elts'),))
    for site, starred in items:
        if starred and sequence is None:
            sequence, state = b.protocol(region, build_kind, tuple(held), state,
                (CountBinding('item_count', len(held)),), (b.site('elts'),))
        value, state = b.evaluate(region, site, state)
        if sequence is None:
            held.append(value)
        elif kind == 'Set':
            state, = b.action(region, P.LanguageActionKind.SET_UPDATE if starred else P.LanguageActionKind.SET_INSERT,
                             (site,), (sequence, value, state), (b.world,))
        else:
            state, = b.protocol(region, K.EXTEND_DISPLAY if starred else K.APPEND_DISPLAY,
                                 (sequence, value), state, selectors=(site,))
    if sequence is None:
        if kind == 'Tuple':
            if not held:
                sequence, state = b.literal(region, (), state, source=b.site('elts'))
            else:
                sequence, state = b.emit(region, P.ConstructValue(P.ConstructionKind.TUPLE, (b.site('elts'), b.site('ctx'))),
                                         (*held, state), (_REF, b.world))
        else:
            sequence, state = b.protocol(region, build_kind, tuple(held), state,
                (CountBinding('item_count', len(held)),), (b.site('elts'),))
    elif kind == 'Tuple':
        sequence, state = b.protocol(region, K.DISPLAY_LIST_TO_TUPLE, (sequence,), state, selectors=(b.site('elts'),))
    b.finish(region, (sequence, state), (_REF, b.world))


def _store(b, region, state, items):
    stars = [i for i, (_, star) in enumerate(items) if star]
    _require(len(stars) <= 1, 'SOURCE_CODEGEN_CONFLICT', str(b.occurrence), 'assignment permits at most one starred target')
    assigned = b.parameter(region, 0)
    if stars:
        index = stars[0]
        _require(index < 256 and len(items)-index-1 < ((1 << 31)-1) >> 8,
                 'SOURCE_CODEGEN_CONFLICT', str(b.occurrence), 'extended target counts exceed the compiler encoding')
        unpacked = b.action(region, P.LanguageActionKind.UNPACK_EXTENDED,
            (b.site('elts'), b.site('elts', index)), (assigned, state), (*((_REF,)*len(items)), b.world))
    else:
        unpacked = b.protocol(region, K.UNPACK_FIXED, (assigned,), state,
            (CountBinding('child_count', len(items)),), (b.site('elts'),))
    state = unpacked[-1]
    for (site, _), value in zip(items, unpacked[:-1]):
        state, = b.evaluate(region, site, state, P.ProductionPurpose.STORE, value)
    b.finish(region, (state,), (b.world,))


def _mapping(b, region, state):
    b.mark('keys', P.ProductionDispositionKind.EVALUATED_CHILD)
    b.mark('values', P.ProductionDispositionKind.EVALUATED_CHILD)
    keys, values = b.value(b.site('keys')), b.value(b.site('values'))
    _require(keys.kind == values.kind == 'LIST' and len(keys.items) == len(values.items),
             'RULE_SHAPE', str(b.occurrence), 'dict key/value source lists differ')
    mapping, elements = None, 0

    def commit(update):
        nonlocal mapping, state
        if mapping is None:
            mapping = update
        else:
            state, = b.protocol(region, K.DICT_UPDATE, (mapping, update), state, selectors=(b.site('keys'), b.site('values')))

    def subdict(begin, end):
        nonlocal state
        result, pairs = None, []
        if (end-begin)*2 > b.rules.call_profile['stack_guideline']:
            result, state = b.protocol(region, K.BUILD_MAP, (), state, (CountBinding('pair_count', 0),), (b.site('keys'),))
        for ordinal in range(begin, end):
            key, state = b.evaluate(region, b.site('keys', ordinal), state)
            value, state = b.evaluate(region, b.site('values', ordinal), state)
            if result is None:
                pairs.extend((key, value))
            else:
                state, = b.protocol(region, K.MAP_ADD, (result, key, value), state,
                    selectors=(b.site('keys', ordinal), b.site('values', ordinal)))
        if result is None:
            result, state = b.protocol(region, K.BUILD_MAP, tuple(pairs), state,
                (CountBinding('pair_count', end-begin),), (b.site('keys'),))
        return result

    for ordinal, key in enumerate(keys.items):
        hole = key.kind == 'SCALAR' and key.scalar.to_python() is None
        _require(hole or key.kind == 'NODE', 'RULE_SHAPE', str(b.site('keys', ordinal)), 'dict key must be an expression or an unpack hole')
        if hole:
            b.slots[b.site('keys', ordinal)] = P.ProductionDispositionKind.METADATA
            if elements:
                commit(subdict(ordinal-elements, ordinal))
                elements = 0
            if mapping is None:
                mapping, state = b.protocol(region, K.BUILD_MAP, (), state, (CountBinding('pair_count', 0),), (b.site('keys'),))
            update, state = b.evaluate(region, b.site('values', ordinal), state)
            state, = b.protocol(region, K.DICT_UPDATE, (mapping, update), state, selectors=(b.site('values', ordinal),))
        elif elements*2 > b.rules.call_profile['stack_guideline']:
            commit(subdict(ordinal-elements, ordinal+1))
            elements = 0
        else:
            elements += 1
    if elements:
        commit(subdict(len(keys.items)-elements, len(keys.items)))
    if mapping is None:
        mapping, state = b.protocol(region, K.BUILD_MAP, (), state, (CountBinding('pair_count', 0),), (b.site('keys'),))
    b.finish(region, (mapping, state), (_REF, b.world))
