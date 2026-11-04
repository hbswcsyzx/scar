"""Ordered except* partitions, accumulated failures and metadata-aware merge.

The remaining group, original exception and accumulated list are distinct
references. Split owns its conditional handled-exception update. Only body
failures are accumulated; admission/cleanup failures leave the dispatcher.
"""
from scar.analysis.source_expression_rules import _REF, _BOOL, _require
from scar.analysis.source_statement_exceptions import _clear_name
from scar.ir.program import source_productions as P
from scar.ir.program.control import LanguageCompletionKind as C
from scar.ir.program.signature_patterns import CountBinding
from scar.ir.program.structured import PythonProtocolKind as K


def _group_body(b,region,owner):
    matched,accumulated,world=(b.parameter(region,i) for i in range(3))
    name=P.SlotRef(owner,'FIELD',b.role.fields['ExceptHandler']['name'])
    body=P.SlotRef(owner,'FIELD',b.role.fields['ExceptHandler']['body'])
    port=b.rules.source.statements.exception_binding(owner)
    if port is not None:
        # Binding occurs before the body-failure collection boundary.
        world,=b.emit(region,P.AccessBinding(P.BindingActionKind.WRITE,port),(matched,world),(b.world,),source=name)
    protected=b.region(body,(b.world,),region)
    b.suite_at(protected,body,b.parameter(protected,0))
    routes=[];outputs=[]
    for completion in b.completions(protected):
        _require(completion.kind in (C.FALLTHROUGH,C.RAISE),'SOURCE_CODEGEN_CONFLICT',str(body),
            'return/break/continue cannot escape an except* handler')
        raised=completion.kind is C.RAISE
        handler=b.region(body,(*completion.types,*((_REF,) if raised else ())),region,P.ProductionRegionKind.HANDLER)
        state=b.parameter(handler,len(completion.types)-1)
        if port is not None:state=_clear_name(b,handler,state,port,name)
        if raised:
            state,=b.protocol(handler,K.APPEND_DISPLAY,
                (b.parameter(handler,len(completion.types)),b.parameter(handler,0)),state,selectors=(body,))
        b.finish(handler,(state,),(b.world,))
        routes.append(P.CompletionRoute(completion.kind,completion.target,handler.id,(accumulated,) if raised else ()))
        outputs.extend(b.completions(handler))
    call=P.ProductionRegionCall(protected.id,(world,))
    result=b.control(region,P.HandleCompletions(call,tuple(routes)) if routes else P.ApplyRegion(call),(),b.union(tuple(outputs)))
    if result:b.finish(region,result,(b.world,))


def emit_group_dispatch(b,region,handlers):
    original,world=b.parameter(region,0),b.parameter(region,1)
    remaining=original
    accumulated,world=b.protocol(region,K.BUILD_DISPLAY_LIST,(),world,
        (CountBinding('item_count',0),),selectors=(b.site('handlers'),))
    for ordinal,owner in enumerate(handlers):
        site=P.SlotRef(owner,'FIELD',b.role.fields['ExceptHandler']['type'])
        # Do not short-circuit after the remaining group becomes None.
        expected,world=b.evaluate(region,site,world)
        remaining,matched,world=b.emit(region,P.SplitExceptionGroup(site,b.rules.exception_abi),
            (remaining,expected,world),(_REF,_REF,b.world),source=site)
        world,=b.protocol(region,K.FRAME_RELEASE_TEMPORARY,(expected,),world)
        absent,=b.emit(region,P.ReferenceIsNone(),(matched,),(_BOOL,),may_raise=False,source=site)
        skipped=b.region(b.site('handlers',ordinal),(b.world,),region)
        b.finish(skipped,(b.parameter(skipped,0),),(b.world,))
        selected=b.region(b.site('handlers',ordinal),(_REF,_REF,b.world),region)
        _group_body(b,selected,owner)
        world,=b.control(region,P.BranchControl(P.ProductionRegionCall(skipped.id,(world,)),
            P.ProductionRegionCall(selected.id,(matched,accumulated,world))),(absent,),
            b.union(b.completions(skipped),b.completions(selected)))
    world,=b.protocol(region,K.APPEND_DISPLAY,(accumulated,remaining),world,selectors=(b.site('handlers'),))
    merged,world=b.emit(region,P.MergeExceptionGroup(b.site('handlers'),b.rules.exception_abi),
        (original,accumulated,world),(_REF,b.world),source=b.site('handlers'))
    empty,=b.emit(region,P.ReferenceIsNone(),(merged,),(_BOOL,),may_raise=False)
    done=b.region(region.source,(b.world,),region)
    b.finish(done,(b.parameter(done,0),),(b.world,))
    failed=b.region(region.source,(_REF,b.world),region)
    packet=b.emit(failed,P.PrepareReraise(b.rules.exception_abi),
        (b.parameter(failed,0),b.parameter(failed,1)),b.raised,may_raise=False)
    b.transfer(failed,C.RAISE,packet,b.raised)
    result=b.control(region,P.BranchControl(P.ProductionRegionCall(done.id,(world,)),
        P.ProductionRegionCall(failed.id,(merged,world))),(empty,),b.union(b.completions(done),b.completions(failed)))
    if result:b.finish(region,result,(b.world,))
