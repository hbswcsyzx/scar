"""Function creation schedules and separately admitted deferred bodies.

Decorators/defaults run in the original creator; annotation requests and body
execution retain their distinct C1 scopes. Type-parameter factory creation is
an explicit remaining source-rule frontier, not a guessed parent namespace.
"""
from scar.analysis.source_expression_rules import _REF, _require
from scar.analysis.source_callable_rules import prepare_defaults, complete_deferred_body
from scar.ir.program import source_productions as P
from scar.ir.program.structured import PythonProtocolKind as K


def emit_function_definition(b,root,state):
    _require(not b.value(b.site('type_params')).items, 'TYPE_PARAMETERS_FRONTIER', str(b.occurrence),
        'generic function definition needs its original type-parameter factory activation rule')
    env=b.rules.source.deferred.interface(b.occurrence,b.world,b.rules.exception_abi)
    annotations=b.rules.source.deferred.annotations(b.occurrence)
    docstring=b.rules.source.statements.function_docstring(b.occurrence)
    b.mark('name',P.ProductionDispositionKind.ROLE_PORT)
    b.mark('decorator_list',P.ProductionDispositionKind.EVALUATED_CHILD)
    decorators=[]
    for ordinal in range(len(b.value(b.site('decorator_list')).items)):
        site=b.site('decorator_list',ordinal)
        b.slots[site]=P.ProductionDispositionKind.EVALUATED_CHILD
        value,state=b.evaluate(root,site,state)
        decorators.append((site,value))
    defaults,keywords,state=prepare_defaults(b,root,state,env)
    globals_ref,state=b.environment(root,P.GlobalsEnvironment(env.globals_scope),state)
    annotate=None
    if annotations is not None:
        captures=[]
        for relay in annotations.captures:
            capture,state=b.environment(root,P.ClosureEnvironment(relay),state)
            captures.append(capture)
        for entry in annotations.entries:
            b.slots[entry.value]=P.ProductionDispositionKind.DEFERRED_CHILD
        annotate,state=b.emit(root,P.BuildFunctionAnnotations(annotations,b.rules.exception_abi),
            (globals_ref,*captures,state),(_REF,b.world))
    b.mark('body',P.ProductionDispositionKind.DEFERRED_CHILD)
    body=b.region(b.site('body'),(_REF,*(_REF for _ in env.parameters),b.world),root,P.ProductionRegionKind.DEFERRED)
    code,=b.emit(root,P.DeferRegion(body.id,env),(),(_REF,),may_raise=False)
    cells=[]
    for relay in env.captures:
        cell,state=b.environment(root,P.ClosureEnvironment(relay),state)
        cells.append(cell)
    arguments=(code,globals_ref,*defaults,*keywords,*cells,*(() if annotate is None else (annotate,)),state)
    function,state=b.emit(root,P.BuildFunction(env,annotations,docstring),arguments,(_REF,b.world))
    for site,decorator in reversed(decorators):
        function,state=b.emit(root,P.ApplyDecorator(site,b.rules.exception_abi),
            (decorator,function,state),(_REF,b.world),source=site)
    ports=[p for p in b.rules._ports.get(b.site('name'),())
        if b.rules.source.frontend.bindings.ports[p].write_target is not None]
    _require(len(ports)==1,'BINDING_INTERFACE_FRONTIER',str(b.site('name')),'function definition needs one original name write port')
    state,=b.emit(root,P.AccessBinding(P.BindingActionKind.WRITE,ports[0]),(function,state),(b.world,),source=b.site('name'))
    state,=b.protocol(root,K.FRAME_RELEASE_TEMPORARY,(function,),state)
    b.finish(root,(state,),(b.world,))

    current,=b.emit(body,P.EnterDeferredBody(env),tuple(b.parameter(body,i) for i in range(len(body.parameters))),
        (b.world,),may_raise=False)
    protected=b.region(body.source,(b.world,),body)
    b.suite(protected,'body',b.parameter(protected,0),metadata_prefix=int(docstring is not None))
    b.mark('body',P.ProductionDispositionKind.DEFERRED_CHILD)
    if docstring is not None:
        b.slots[docstring]=P.ProductionDispositionKind.METADATA
    complete_deferred_body(b,body,protected,(current,),env)
