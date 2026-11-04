"""Creation and later activation are distinct source graph regions.

Closures retain original F3 cell/namespace handles, not their current contents.
Formal ports use source order; native call admission/layout is not proved.
"""
from scar.analysis.source_expression_rules import _REF, _require
from scar.ir.program import source_productions as P
from scar.ir.program.control import LanguageCompletionKind as C
from scar.ir.program.signature_patterns import CountBinding
from scar.ir.program.structured import PythonProtocolKind as K


def prepare_defaults(b, root, state, env):
    """Definition-time values in source group order, not native frame order."""
    defaults, keywords = [], []
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
    return defaults, keywords, state


def complete_deferred_body(b, body, protected, arguments, env):
    """Implicit None return and compiler exception translation after the suite."""
    completions = b.completions(protected)
    routes, outputs = [], []
    for completion in completions:
        if completion.kind is C.FALLTHROUGH:
            handler = b.region(body.source, (b.world,), body, P.ProductionRegionKind.HANDLER)
            value, world = b.literal(handler,None,b.parameter(handler,0))
            b.transfer(handler,C.RETURN,(value,world),(_REF,b.world))
        elif completion.kind is C.RAISE and env.kind is not P.DeferredBodyKind.FUNCTION:
            handler = b.region(body.source,b.raised,body,P.ProductionRegionKind.HANDLER)
            payload = b.emit(handler,P.TranslateEscapingException(env.kind,b.rules.exception_abi),
                tuple(b.parameter(handler,i) for i in range(len(b.raised))),b.raised)
            b.transfer(handler,C.RAISE,payload,b.raised)
        else:
            outputs.append(completion)
            continue
        routes.append(P.CompletionRoute(completion.kind,completion.target,handler.id))
        outputs.extend(b.completions(handler))
    call = P.ProductionRegionCall(protected.id,arguments)
    instruction = P.HandleCompletions(call,tuple(routes)) if routes else P.ApplyRegion(call)
    b.control(body,instruction,(),b.union(tuple(outputs)))


def emit_callable(b, root, state):
    env = b.rules.source.deferred.interface(b.occurrence, b.world, b.rules.exception_abi)
    generator = b.node.constructor == 'GeneratorExp'
    field = 'elt' if generator else 'body'
    b.mark(field, P.ProductionDispositionKind.DEFERRED_CHILD)
    defaults, keywords = [], []
    if generator:
        from scar.analysis.source_comprehension_rules import comprehension_clauses
        clauses = comprehension_clauses(b)
    else:
        defaults, keywords, state = prepare_defaults(b,root,state,env)
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
        from scar.analysis.source_comprehension_rules import get_iterator
        iterator, state = get_iterator(b, root, iterable, state, clauses[0][3])
        result = b.protocol(root, K.CREATE_GENEXPR, (*function_env, *cells, iterator), state, (closure,))
    else:
        result = b.protocol(root, K.MAKE_LAMBDA_FUNCTION, (code, globals_ref, *defaults, *keywords, *cells), state,
            (CountBinding('default_count', len(defaults)), CountBinding('keyword_default_count', len(keywords)), closure))
    b.finish(root, result, (_REF, b.world))
    current, = b.emit(body, P.EnterDeferredBody(env), tuple(b.parameter(body, i) for i in range(len(body.parameters))),
        (b.world,), may_raise=False)
    execution = body
    if env.kind is not P.DeferredBodyKind.FUNCTION:
        execution = b.region(body.source,(_REF,b.world) if generator else (b.world,),body)
        execute_world = b.parameter(execution,len(execution.parameters)-1)
    else:
        execute_world = current
    if generator:
        from scar.analysis.source_comprehension_rules import emit_clause_loops
        execute_world = emit_clause_loops(b, execution, clauses, b.parameter(execution,0), execute_world,
            suspension=P.SuspensionKind.ASYNC_YIELD if env.kind is P.DeferredBodyKind.ASYNC_GENERATOR else P.SuspensionKind.YIELD)
        value, execute_world = b.literal(execution, None, execute_world)
    else:
        value, execute_world = b.evaluate(execution, b.site('body'), execute_world)
    b.transfer(execution, C.RETURN, (value, execute_world), (_REF, b.world))
    if execution is not body:
        complete_deferred_body(b,body,execution,(b.parameter(body,1),current) if generator else (current,),env)
