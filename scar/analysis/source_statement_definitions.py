"""Class construction and lazy type-alias declarations over original scopes.

Class callbacks are templates passed to the selected builder, not eager calls.
Namespace setup/finalization remain typed language boundaries; their native
implementation and the builder's call admission are separate obligations.
"""
from scar.analysis.source_expression_rules import _REF, _require
from scar.analysis.source_type_parameter_rules import enter_factory, lazy_factory
from scar.ir.program import source_productions as P
from scar.ir.program.control import LanguageCompletionKind as C
from scar.ir.program.structured import PythonProtocolKind as K


def _bind_definition(b,root,value,world):
    site=b.site('name')
    if b.node.constructor=='TypeAlias':
        b.mark('name',P.ProductionDispositionKind.TARGET_ADDRESS)
        world,=b.evaluate(root,site,world,P.ProductionPurpose.STORE,value)
    else:
        b.mark('name',P.ProductionDispositionKind.ROLE_PORT)
        ports=[p for p in b.rules._ports.get(site,())
            if b.rules.source.frontend.bindings.ports[p].write_target is not None]
        _require(len(ports)==1,'BINDING_INTERFACE_FRONTIER',str(site),'class declaration needs one original name write port')
        world,=b.emit(root,P.AccessBinding(P.BindingActionKind.WRITE,ports[0]),(value,world),(b.world,),source=site)
    world,=b.protocol(root,K.FRAME_RELEASE_TEMPORARY,(value,),world)
    b.finish(root,(world,),(b.world,))


def emit_definition(b,root,world):
    if b.node.constructor=='TypeAlias':
        return _emit_alias(b,root,world)
    decorators=[]
    b.mark('decorator_list',P.ProductionDispositionKind.EVALUATED_CHILD)
    for ordinal in range(len(b.value(b.site('decorator_list')).items)):
        site=b.site('decorator_list',ordinal)
        b.slots[site]=P.ProductionDispositionKind.EVALUATED_CHILD
        value,world=b.evaluate(root,site,world)
        decorators.append((site,value))
    if b.value(b.site('type_params')).items:
        result,factory,parameters,_,active=enter_factory(b,root,world,())
        value,active=_build_class(b,factory,active,parameters)
        b.finish(factory,(value,active),(_REF,b.world))
        value,world=result
    else:
        value,world=_build_class(b,root,world,None)
    for site,decorator in reversed(decorators):
        value,world=b.emit(root,P.ApplyDecorator(site,b.rules.exception_abi),
            (decorator,value,world),(_REF,b.world),source=site)
    _bind_definition(b,root,value,world)


def _build_class(b,region,world,parameters):
    owner=P.ProductionOccurrence(b.occurrence)
    interface=b.rules.source.definitions.class_body(b.occurrence,b.world,b.rules.exception_abi)
    builder,world=b.emit(region,P.ReadBuildClass(b.rules.exception_abi),(world,),(_REF,b.world),source=owner)
    body=b.region(b.site('body'),(_REF,_REF,b.world),region,P.ProductionRegionKind.DEFERRED)
    code,=b.emit(region,P.DeferClassBody(body.id,interface),(),(_REF,),may_raise=False,source=owner)
    globals_ref,world=b.environment(region,P.GlobalsEnvironment(interface.globals_scope),world,source=owner)
    cells=[]
    for relay in interface.captures:
        cell,world=b.environment(region,P.ClosureEnvironment(relay),world,source=owner)
        cells.append(cell)
    callback,world=b.emit(region,P.BuildClassBody(interface),
        (code,globals_ref,*cells,*(() if parameters is None else (parameters,)),world),(_REF,b.world),source=owner)
    name,world=b.emit(region,P.ConstructValue(P.ConstructionKind.LITERAL,(b.site('name'),)),
        (world,),(_REF,b.world),source=b.site('name'))
    suffix=()
    if parameters is not None:
        generic,world=b.emit(region,P.BuildGenericBase(b.rules.exception_abi),(parameters,world),(_REF,b.world),source=owner)
        suffix=(generic,)
    result=b.invoke_source_call(region,builder,world,argument_field='bases',prefix=(callback,name),suffix=suffix)

    env,namespace=b.parameter(body,0),b.parameter(body,1)
    active,=b.emit(body,P.EnterClassBody(interface),(env,namespace,b.parameter(body,2)),(b.world,),may_raise=False)
    active,=b.emit(body,P.InitializeClassNamespace(interface),(env,namespace,active),(b.world,))
    protected=b.region(body.source,(b.world,),body)
    b.suite(protected,'body',b.parameter(protected,0),metadata_prefix=int(interface.docstring is not None))
    b.mark('body',P.ProductionDispositionKind.DEFERRED_CHILD)
    if interface.docstring is not None:
        b.slots[interface.docstring]=P.ProductionDispositionKind.METADATA
    routes=[];outputs=[]
    for completion in b.completions(protected):
        if completion.kind is C.FALLTHROUGH:
            final=b.region(body.source,(b.world,_REF,_REF),body,P.ProductionRegionKind.HANDLER)
            returned,state=b.emit(final,P.FinalizeClassNamespace(interface),
                (b.parameter(final,1),b.parameter(final,2),b.parameter(final,0)),(_REF,b.world))
            b.transfer(final,C.RETURN,(returned,state),(_REF,b.world))
            routes.append(P.CompletionRoute(C.FALLTHROUGH,None,final.id,(env,namespace)))
            outputs.extend(b.completions(final))
        else:
            _require(completion.kind is C.RAISE,'RULE_INTERFACE',str(owner),'class body cannot return or jump out of its scope')
            outputs.append(completion)
    call=P.ProductionRegionCall(protected.id,(active,))
    b.control(body,P.HandleCompletions(call,tuple(routes)) if routes else P.ApplyRegion(call),(),b.union(tuple(outputs)))
    return result


def _emit_alias(b,root,world):
    instruction=b.rules.source.definitions.alias(b.occurrence,b.rules.exception_abi)
    owner=P.ProductionOccurrence(b.occurrence)
    if instruction.type_parameters is not None:
        result,factory,parameters,_,active=enter_factory(b,root,world,())
        evaluator,active=lazy_factory(b,factory,instruction.expression,active)
        alias,active=b.emit(factory,instruction,(evaluator,parameters,active),(_REF,b.world),source=owner)
        b.finish(factory,(alias,active),(_REF,b.world))
        alias,world=result
    else:
        evaluator,world=lazy_factory(b,root,instruction.expression,world)
        alias,world=b.emit(root,instruction,(evaluator,world),(_REF,b.world),source=owner)
    _bind_definition(b,root,alias,world)
