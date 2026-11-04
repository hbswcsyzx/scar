"""Creation and later activation are distinct source graph regions.

Closures retain original F3 cell/namespace handles, not their current contents.
Formal ports use source order; native call admission/layout is not proved.
"""
from scar.analysis.source_expression_rules import _REF, _require
from scar.ir.program import source_productions as P
from scar.ir.program.control import LanguageCompletionKind as C
from scar.ir.program.signature_patterns import CountBinding
from scar.ir.program.structured import PythonProtocolKind as K


def emit_callable(b, root, state):
    env = b.rules.source.deferred.interface(b.occurrence, b.world, b.rules.exception_abi)
    generator = b.node.constructor == 'GeneratorExp'
    _require(not generator or env.kind is P.DeferredBodyKind.GENERATOR,
        'ASYNC_GENERATOR_EXPRESSION_FRONTIER', str(b.occurrence),
        'async generator expressions require async iteration/yield/finalization interfaces')
    field = 'elt' if generator else 'body'
    b.mark(field, P.ProductionDispositionKind.DEFERRED_CHILD)
    defaults, keywords = [], []
    if generator:
        from scar.analysis.source_comprehension_rules import comprehension_clauses
        clauses = comprehension_clauses(b)
    else:
        b.mark('args', P.ProductionDispositionKind.METADATA)
        arguments = b.value(b.site('args')).reference
        roles = b.rules.source.roles
        for name in roles.fields['arguments']:
            b.auxiliary(arguments, name, P.ProductionDispositionKind.METADATA)
        for p in env.parameters:
            for name in roles.fields['arg']:
                b.auxiliary(p.source.occurrence, name, P.ProductionDispositionKind.ROLE_PORT
                    if name == 'arg' else P.ProductionDispositionKind.METADATA)
        for name, output in (('defaults', defaults), ('kw_defaults', keywords)):
            site = b.auxiliary(arguments, name, P.ProductionDispositionKind.EVALUATED_CHILD)
            values = b.value(site)
            _require(values.kind == 'LIST', 'RULE_SHAPE', str(site), 'defaults require an original list')
            for ordinal, value in enumerate(values.items):
                if value.kind != 'NODE':
                    _require(name == 'kw_defaults' and value.kind == 'SCALAR' and value.scalar.to_python() is None,
                        'RULE_SHAPE', str(site), 'only missing keyword defaults may be None holes')
                    continue
                value, state = b.evaluate(root, P.SlotRef(site.occurrence, site.group, site.ordinal, (ordinal,)), state)
                output.append(value)
    body = b.region(b.site(field), (_REF, *(_REF for _ in env.parameters), b.world), root, P.ProductionRegionKind.DEFERRED)
    code, = b.emit(root, P.DeferRegion(body.id, env), (), (_REF,), may_raise=False)
    globals_ref, state = b.environment(root, P.GlobalsEnvironment(env.globals_scope), state)
    cells = []
    for hop in env.captures:
        cell, state = b.environment(root, P.ClosureEnvironment(hop), state)
        cells.append(cell)
    closure = CountBinding('closure_count', len(cells))
    if generator:
        *function_env, state = b.protocol(root, K.MAKE_GENEXPR_FUNCTION, (code, globals_ref, *cells), state, (closure,))
        iterable, state = b.evaluate(root, clauses[0][1], state)
        iterator, state = b.protocol(root, K.GET_ITERATOR, (iterable,), state)
        result = b.protocol(root, K.CREATE_GENEXPR, (*function_env, *cells, iterator), state, (closure,))
    else:
        result = b.protocol(root, K.MAKE_LAMBDA_FUNCTION, (code, globals_ref, *defaults, *keywords, *cells), state,
            (CountBinding('default_count', len(defaults)), CountBinding('keyword_default_count', len(keywords)), closure))
    b.finish(root, result, (_REF, b.world))
    current, = b.emit(body, P.EnterDeferredBody(env), tuple(b.parameter(body, i) for i in range(len(body.parameters))),
        (b.world,), may_raise=False)
    if generator:
        from scar.analysis.source_comprehension_rules import emit_clause_loops
        current = emit_clause_loops(b, body, clauses, b.parameter(body, 1), current)
        value, current = b.literal(body, None, current)
    else:
        value, current = b.evaluate(body, b.site('body'), current)
    b.transfer(body, C.RETURN, (value, current), (_REF, b.world))
