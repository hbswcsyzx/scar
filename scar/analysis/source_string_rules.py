"""Formatted/template string schedules with conversion and capture distinct."""
from scar.analysis.source_expression_rules import _REF, _require
from scar.ir.program import source_productions as P
from scar.ir.program.signature_patterns import CountBinding
from scar.ir.program.structured import PythonProtocolKind as K


def emit_string(b, region, state):
    kind = b.node.constructor
    if kind in ('FormattedValue', 'Interpolation'):
        return _formatted(b, region, state, template=kind == 'Interpolation')
    b.mark('values', P.ProductionDispositionKind.EVALUATED_CHILD)
    values = b.value(b.site('values'))
    _require(values.kind == 'LIST', 'RULE_SHAPE', str(b.occurrence), 'string parts must be an original list')
    if kind == 'TemplateStr':
        return _template(b, region, state, values.items)
    held, sequence = [], None
    if len(values.items) > b.rules.call_profile['stack_guideline']:
        sequence, state = b.protocol(region, K.BUILD_DISPLAY_LIST, (), state,
            (CountBinding('item_count', 0),), (b.site('values'),))
    for ordinal, item in enumerate(values.items):
        _part(b, item, ('Constant', 'FormattedValue'))
        value, state = b.evaluate(region, b.site('values', ordinal), state)
        if sequence is None:
            held.append(value)
        else:
            state, = b.protocol(region, K.APPEND_DISPLAY, (sequence, value), state, selectors=(b.site('values', ordinal),))
    if sequence is not None:
        value, state = b.action(region, P.LanguageActionKind.STRING_JOIN, (b.site('values'),), (sequence, state))
    elif not held:
        value, state = b.literal(region, '', state, source=b.site('values'))
    elif len(held) == 1:
        value = held[0]
    else:
        value, state = b.protocol(region, K.BUILD_STRING, tuple(held), state,
            (CountBinding('item_count', len(held)),), (b.site('values'),))
    b.finish(region, (value, state), (_REF, b.world))


def _part(b, item, kinds):
    _require(item.kind == 'NODE', 'RULE_SHAPE', str(b.occurrence), 'string part must be an expression')
    node = b.rules.source.context.syntax.nodes[item.reference]
    _require(node.constructor in kinds, 'RULE_SHAPE', str(b.occurrence), 'unexpected string part constructor')
    if node.constructor == 'Constant':
        raw = b.role.field(item.reference, 'value')
        _require(raw.kind == 'SCALAR' and type(raw.scalar.to_python()) is str,
                 'RULE_SHAPE', str(item.reference), 'literal string part must be an exact string')
    return node.constructor


def _formatted(b, region, state, template):
    b.mark('value', P.ProductionDispositionKind.EVALUATED_CHILD)
    value, state = b.evaluate(region, b.site('value'), state)
    conversion = b.value(b.site('conversion'))
    _require(conversion.kind == 'SCALAR', 'RULE_SHAPE', str(b.occurrence), 'conversion requires a source integer')
    code = conversion.scalar.to_python()
    _require(type(code) is int and code in (-1, 115, 114, 97), 'RULE_SELECTOR', str(b.occurrence), 'invalid string conversion')
    expression = None
    if template:
        expression, state = b.emit(region, P.ConstructValue(P.ConstructionKind.LITERAL, (b.site('str'),)),
                                   (state,), (_REF, b.world), source=b.site('str'))
    elif code != -1:
        selector, state = b.emit(region, P.ConstructValue(P.ConstructionKind.LITERAL, (b.site('conversion'),)),
                                 (state,), (_REF, b.world), source=b.site('conversion'))
        value, state = b.protocol(region, K.FSTRING_CONVERT, (value, selector), state, selectors=(b.site('conversion'),))
    spec = b.value(b.site('format_spec'))
    if spec.kind == 'NODE':
        b.mark('format_spec', P.ProductionDispositionKind.EVALUATED_CHILD)
        format_spec, state = b.evaluate(region, b.site('format_spec'), state)
    else:
        _require(spec.kind == 'SCALAR' and spec.scalar.to_python() is None, 'RULE_SHAPE', str(b.occurrence), 'absent format spec must be None')
        format_spec, state = b.literal(region, '', state, source=b.site('format_spec'))
    if template:
        value, state = b.emit(region, P.ConstructValue(P.ConstructionKind.INTERPOLATION,
            (b.site('str'), b.site('conversion'), b.site('format_spec'))),
            (value, expression, format_spec, state), (_REF, b.world))
    else:
        value, state = b.protocol(region, K.FSTRING_FORMAT, (value, format_spec), state, selectors=(b.site('format_spec'),))
    b.finish(region, (value, state), (_REF, b.world))


def _template(b, region, state, items):
    strings, interpolations, previous = [], [], True
    for ordinal, item in enumerate(items):
        kind = _part(b, item, ('Constant', 'Interpolation'))
        if kind == 'Interpolation':
            if previous:
                empty, state = b.literal(region, '', state, source=b.site('values', ordinal))
                strings.append(empty)
            previous = True
        else:
            literal, state = b.evaluate(region, b.site('values', ordinal), state)
            strings.append(literal)
            previous = False
    if previous:
        empty, state = b.literal(region, '', state, source=b.site('values'))
        strings.append(empty)
    string_tuple, state = b.emit(region, P.ConstructValue(P.ConstructionKind.TUPLE, (b.site('values'),),
                                 P.TupleConstructionLayout.TEMPLATE_STRINGS),
                                 (*strings, state), (_REF, b.world))
    for ordinal, item in enumerate(items):
        if b.rules.source.context.syntax.nodes[item.reference].constructor == 'Interpolation':
            value, state = b.evaluate(region, b.site('values', ordinal), state)
            interpolations.append(value)
    if interpolations:
        interpolation_tuple, state = b.emit(region, P.ConstructValue(P.ConstructionKind.TUPLE, (b.site('values'),),
                                            P.TupleConstructionLayout.TEMPLATE_INTERPOLATIONS),
                                            (*interpolations, state), (_REF, b.world))
    else:
        interpolation_tuple, state = b.literal(region, (), state, source=b.site('values'))
    value, state = b.emit(region, P.ConstructValue(P.ConstructionKind.TEMPLATE_STRING, (b.site('values'),)),
                         (string_tuple, interpolation_tuple, state), (_REF, b.world))
    b.finish(region, (value, state), (_REF, b.world))
