"""Context-manager schedules and completion-preserving exception restoration.

Each source withitem nests one protected template. Enter failures precede its
own protection; target stores and later managers are inside it. No execution
or assumption about the selected context-manager implementation is involved.
"""
from scar.analysis.source_expression_rules import _REF, _require
from scar.analysis.source_delegation_rules import emit_delegate_loop
from scar.ir.program import source_productions as P
from scar.ir.program.control import LanguageCompletionKind as C
from scar.ir.program.structured import PythonProtocolKind as K


def restore_handled_completions(b,region,protected,arguments,previous):
    """Restore on every normal/abrupt completion, using the delivered world."""
    routes=[];outputs=[]
    for completion in b.completions(protected):
        handler=b.region(protected.source,(*completion.types,_REF),region,P.ProductionRegionKind.HANDLER)
        payload=tuple(b.parameter(handler,i) for i in range(len(completion.types)))
        world,=b.emit(handler,P.RestoreHandledException(),
            (b.parameter(handler,len(completion.types)),payload[-1]),(b.world,),may_raise=False)
        b.transfer(handler,completion.kind,(*payload[:-1],world),completion.types,completion.target)
        routes.append(P.CompletionRoute(completion.kind,completion.target,handler.id,(previous,)))
        outputs.extend(b.completions(handler))
    call=P.ProductionRegionCall(protected.id,arguments)
    return b.control(region,P.HandleCompletions(call,tuple(routes)) if routes else P.ApplyRegion(call),(),b.union(tuple(outputs)))


def _await(b,region,value,world,site,method):
    iterator,world=b.emit(region,P.ContextAwaitable(site,method,b.rules.exception_abi),
        (value,world),(_REF,b.world),source=site)
    return emit_delegate_loop(b,region,iterator,world,P.SuspensionKind.AWAIT)


def _invoke(b,region,callable,arguments,world,site,method):
    value,world=b.emit(region,P.InvokeContextMethod(site,method,b.rules.exception_abi),
        (callable,*arguments,world),(_REF,b.world),source=site)
    if method in (P.ContextMethodKind.ASYNC_ENTER,P.ContextMethodKind.ASYNC_EXIT):
        value,world=_await(b,region,value,world,site,method)
    return value,world


def _exceptional_exit(b,handler,site,method):
    payload=tuple(b.parameter(handler,i) for i in range(len(b.raised)))
    exit_method=b.parameter(handler,len(b.raised))
    previous,world=b.emit(handler,P.EnterHandledException(b.rules.exception_abi),payload,(_REF,b.world),may_raise=False)
    protected=b.region(handler.source,(*b.raised[:-1],_REF,b.world),handler)
    original=tuple(b.parameter(protected,i) for i in range(len(b.raised)-1))
    state=b.parameter(protected,len(b.raised))
    kind,value,trace,state=b.emit(protected,P.ContextExceptionArguments(b.rules.exception_abi),
        (*original,state),(_REF,_REF,_REF,b.world),may_raise=False)
    result,state=_invoke(b,protected,b.parameter(protected,len(b.raised)-1),(kind,value,trace),state,site,method)
    suppress,state=b.protocol(protected,K.TRUTH,(result,),state)
    state,=b.protocol(protected,K.FRAME_RELEASE_TEMPORARY,(result,),state)
    yes=b.region(handler.source,(b.world,),protected)
    b.finish(yes,(b.parameter(yes,0),),(b.world,))
    no=b.region(handler.source,b.raised,protected)
    fresh=b.emit(no,P.PrepareReraise(b.rules.exception_abi),
        tuple(b.parameter(no,i) for i in range(len(b.raised))),b.raised,may_raise=False)
    b.transfer(no,C.RAISE,fresh,b.raised)
    b.control(protected,P.BranchControl(P.ProductionRegionCall(yes.id,(state,)),
        P.ProductionRegionCall(no.id,(*original,state))),(suppress,),b.union(b.completions(yes),b.completions(no)))
    result=restore_handled_completions(b,handler,protected,(*payload[:-1],exit_method,world),previous)
    if result:b.finish(handler,result,(b.world,))


def _normal_exit(b,handler,completion,site,method):
    payload=tuple(b.parameter(handler,i) for i in range(len(completion.types)))
    exit_method=b.parameter(handler,len(completion.types))
    null,world=b.literal(handler,None,payload[-1])
    result,world=_invoke(b,handler,exit_method,(null,null,null),world,site,method)
    # A normal exit's result is discarded, never truth-tested.
    world,=b.protocol(handler,K.FRAME_RELEASE_TEMPORARY,(result,),world)
    b.transfer(handler,completion.kind,(*payload[:-1],world),completion.types,completion.target)


def emit_context_statement(b,root,world):
    if b.node.constructor=='AsyncWith':
        owner=b.rules.source.context.entry_context(b.occurrence).owner
        _require(owner.kind=='FUNCTION_BODY'
            and b.rules.source.context.syntax.nodes[owner.occurrence].constructor=='AsyncFunctionDef',
            'SUSPENSION_CONTEXT_FRONTIER',str(b.occurrence),'async with requires its original resumable function owner')
    items=b.value(b.site('items'))
    _require(items.kind=='LIST' and bool(items.items),'RULE_SHAPE',str(b.occurrence),'with requires original manager descriptors')
    b.mark('items',P.ProductionDispositionKind.EVALUATED_CHILD)
    _manager(b,root,world,items.items,0)


def _manager(b,region,world,items,ordinal):
    item=items[ordinal]
    _require(item.kind=='NODE' and b.rules.source.context.syntax.nodes[item.reference].constructor=='withitem',
        'RULE_SHAPE',str(b.occurrence),'manager must retain its original withitem')
    b.slots[b.site('items',ordinal)]=P.ProductionDispositionKind.EVALUATED_CHILD
    site=b.auxiliary(item.reference,'context_expr',P.ProductionDispositionKind.EVALUATED_CHILD)
    target=b.auxiliary(item.reference,'optional_vars',P.ProductionDispositionKind.METADATA)
    asynchronous=b.node.constructor=='AsyncWith'
    enter_kind=P.ContextMethodKind.ASYNC_ENTER if asynchronous else P.ContextMethodKind.ENTER
    exit_kind=P.ContextMethodKind.ASYNC_EXIT if asynchronous else P.ContextMethodKind.EXIT
    manager,world=b.evaluate(region,site,world)
    exit_method,world=b.emit(region,P.ReadContextMethod(site,exit_kind,b.rules.exception_abi),
        (manager,world),(_REF,b.world),source=site)
    enter,world=b.emit(region,P.ReadContextMethod(site,enter_kind,b.rules.exception_abi),
        (manager,world),(_REF,b.world),source=site)
    entered,world=_invoke(b,region,enter,(),world,site,enter_kind)
    protected=b.region(b.site('items',ordinal),(_REF,b.world),region)
    value,state=b.parameter(protected,0),b.parameter(protected,1)
    if b.value(target).kind=='NODE':
        b.slots[target]=P.ProductionDispositionKind.TARGET_ADDRESS
        state,=b.evaluate(protected,target,state,P.ProductionPurpose.STORE,value)
    else:
        _require(b.value(target).kind=='SCALAR' and b.value(target).scalar.to_python() is None,
            'RULE_SHAPE',str(target),'missing as-target requires an explicit None field')
    state,=b.protocol(protected,K.FRAME_RELEASE_TEMPORARY,(value,),state)
    if ordinal+1<len(items):_manager(b,protected,state,items,ordinal+1)
    else:b.suite(protected,'body',state)
    routes=[];outputs=[]
    for completion in b.completions(protected):
        handler=b.region(protected.source,(*completion.types,_REF),region,P.ProductionRegionKind.HANDLER)
        if completion.kind is C.RAISE:_exceptional_exit(b,handler,site,exit_kind)
        else:_normal_exit(b,handler,completion,site,exit_kind)
        routes.append(P.CompletionRoute(completion.kind,completion.target,handler.id,(exit_method,)))
        outputs.extend(b.completions(handler))
    call=P.ProductionRegionCall(protected.id,(entered,world))
    result=b.control(region,P.HandleCompletions(call,tuple(routes)) if routes else P.ApplyRegion(call),(),b.union(tuple(outputs)))
    if result:b.finish(region,result,(b.world,))
