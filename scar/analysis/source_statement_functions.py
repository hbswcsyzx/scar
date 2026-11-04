"""Function creation schedules and separately admitted deferred bodies.

Decorators/defaults run in the original creator; generic factory creation,
annotation requests and body execution retain their distinct C1 scopes.
"""
from scar.analysis.source_expression_rules import _REF, _require
from scar.analysis.source_callable_rules import prepare_defaults, complete_deferred_body
from scar.ir.program import source_productions as P
from scar.ir.program.structured import PythonProtocolKind as K


def emit_function_definition(b,root,state):
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
    if b.value(b.site('type_params')).items:
        from scar.analysis.source_type_parameter_rules import enter_factory
        result,factory,parameters,passed,active=enter_factory(b,root,state,(*defaults,*keywords))
        function,active=_build_function(b,factory,active,env,annotations,docstring,passed[:len(defaults)],passed[len(defaults):])
        active,=b.emit(factory,P.AttachTypeParameters(b.site('type_params'),b.rules.exception_abi),
            (function,parameters,active),(b.world,))
        b.finish(factory,(function,active),(_REF,b.world))
        function,state=result
    else:
        function,state=_build_function(b,root,state,env,annotations,docstring,defaults,keywords)
    for site,decorator in reversed(decorators):
        function,state=b.emit(root,P.ApplyDecorator(site,b.rules.exception_abi),
            (decorator,function,state),(_REF,b.world),source=site)
    ports=[p for p in b.rules._ports.get(b.site('name'),())
        if b.rules.source.frontend.bindings.ports[p].write_target is not None]
    _require(len(ports)==1,'BINDING_INTERFACE_FRONTIER',str(b.site('name')),'function definition needs one original name write port')
    state,=b.emit(root,P.AccessBinding(P.BindingActionKind.WRITE,ports[0]),(function,state),(b.world,),source=b.site('name'))
    state,=b.protocol(root,K.FRAME_RELEASE_TEMPORARY,(function,),state)
    b.finish(root,(state,),(b.world,))


def _build_function(b,root,state,env,annotations,docstring,defaults,keywords):
    source=P.ProductionOccurrence(b.occurrence)
    globals_ref,state=b.environment(root,P.GlobalsEnvironment(env.globals_scope),state,source=source)
    annotate=None
    if annotations is not None:
        captures=[]
        for relay in annotations.captures:
            capture,state=b.environment(root,P.ClosureEnvironment(relay),state,source=source)
            captures.append(capture)
        for entry in annotations.entries:
            b.slots[entry.value]=P.ProductionDispositionKind.DEFERRED_CHILD
        from scar.analysis.source_evaluation_rules import build_request_body
        request=build_request_body(b,root,annotations)
        annotate,state=b.emit(root,P.BuildFunctionAnnotations(annotations,b.rules.exception_abi,request.id),
            (globals_ref,*captures,state),(_REF,b.world),source=source)
    b.mark('body',P.ProductionDispositionKind.DEFERRED_CHILD)
    body=b.region(b.site('body'),(_REF,*(_REF for _ in env.parameters),b.world),root,P.ProductionRegionKind.DEFERRED)
    code,=b.emit(root,P.DeferRegion(body.id,env),(),(_REF,),may_raise=False,source=source)
    cells=[]
    for relay in env.captures:
        cell,state=b.environment(root,P.ClosureEnvironment(relay),state,source=source)
        cells.append(cell)
    arguments=(code,globals_ref,*defaults,*keywords,*cells,*(() if annotate is None else (annotate,)),state)
    function,state=b.emit(root,P.BuildFunction(env,annotations,docstring),arguments,(_REF,b.world),source=source)

    current,=b.emit(body,P.EnterDeferredBody(env),tuple(b.parameter(body,i) for i in range(len(body.parameters))),
        (b.world,),may_raise=False)
    protected=b.region(body.source,(b.world,),body)
    b.suite(protected,'body',b.parameter(protected,0),metadata_prefix=int(docstring is not None))
    b.mark('body',P.ProductionDispositionKind.DEFERRED_CHILD)
    if docstring is not None:
        b.slots[docstring]=P.ProductionDispositionKind.METADATA
    complete_deferred_body(b,body,protected,(current,),env)
    return function,state
