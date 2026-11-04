"""Expandable deferred value/annotation requests, separate from their creation."""
from scar.analysis.source_expression_rules import _REF,_BOOL,_require
from scar.ir.program import source_productions as P
from scar.ir.program.control import LanguageCompletionKind as C
from scar.ir.program.signature_patterns import CountBinding
from scar.ir.program.structured import PythonProtocolKind as K


def _value(b,region,site,world,*,unpack=False):
    value=b.value(site)
    if unpack:
        _require(b.rules.source.context.syntax.nodes[value.reference].constructor=='Starred',
            'RULE_SHAPE',str(site),'single-item unpack requires its original starred annotation/default')
        b.auxiliary(value.reference,'ctx',P.ProductionDispositionKind.MARKER)
        nested=b.auxiliary(value.reference,'value',P.ProductionDispositionKind.EVALUATED_CHILD)
        value,world=b.evaluate(region,nested,world)
        return b.protocol(region,K.UNPACK_FIXED,(value,),world,(CountBinding('child_count',1),),selectors=(site,))
    return b.evaluate(region,site,world)


def _scope_entry(b,region,entry,mapping,world):
    value,world=_value(b,region,entry.source,world)
    key,world=b.literal(region,entry.key,world,source=entry.name)
    world,=b.protocol(region,K.STORE_SUBSCRIPT,(mapping,key,value),world,selectors=(entry.source,entry.name))
    for reference in (key,value):
        world,=b.protocol(region,K.FRAME_RELEASE_TEMPORARY,(reference,),world)
    b.slots[entry.source]=P.ProductionDispositionKind.DEFERRED_CHILD
    return world


def _scope_variant(b,region,variant,environment,mapping,world):
    for entry in variant.entries:
        if entry.registration is None:
            world=_scope_entry(b,region,entry,mapping,world)
            continue
        registered,world=b.emit(region,P.ReadAnnotationRegistration(entry.registration,b.rules.exception_abi),
            (environment,world),(_BOOL,b.world),source=entry.source)
        yes=b.region(entry.source,(_REF,_REF,b.world),region)
        no=b.region(entry.source,(b.world,),region)
        current=_scope_entry(b,yes,entry,b.parameter(yes,1),b.parameter(yes,2))
        b.finish(yes,(current,),(b.world,));b.finish(no,(b.parameter(no,0),),(b.world,))
        world,=b.control(region,P.BranchControl(P.ProductionRegionCall(yes.id,(environment,mapping,world)),
            P.ProductionRegionCall(no.id,(world,))),(registered,),b.union(b.completions(yes),b.completions(no)))
    return world


def _scope_body(b,body,request,world):
    mapping,world=b.protocol(body,K.BUILD_MAP,(),world,(CountBinding('pair_count',0),))
    variants=request.variants
    if all(v.entries==variants[0].entries for v in variants):
        world=_scope_variant(b,body,variants[0],b.parameter(body,0),mapping,world)
        return mapping,world
    # Target options are symbolic compiler inputs, not the analyzer's flags.
    enabled,=b.emit(body,P.ReadCompilationOption(P.CompilationOption.ASSERTIONS_ENABLED),(),(_BOOL,),may_raise=False)
    yes=b.region(request.source,(_REF,_REF,b.world),body)
    no=b.region(request.source,(_REF,_REF,b.world),body)
    current=_scope_variant(b,yes,variants[0],b.parameter(yes,0),b.parameter(yes,1),b.parameter(yes,2))
    b.finish(yes,(current,),(b.world,))
    docs,=b.emit(no,P.ReadCompilationOption(P.CompilationOption.DOCSTRINGS_ENABLED),(),(_BOOL,),may_raise=False)
    children=[]
    for variant in variants[1:]:
        child=b.region(request.source,(_REF,_REF,b.world),no)
        current=_scope_variant(b,child,variant,b.parameter(child,0),b.parameter(child,1),b.parameter(child,2))
        b.finish(child,(current,),(b.world,));children.append(child)
    args=tuple(b.parameter(no,i) for i in range(3))
    current,=b.control(no,P.BranchControl(*(P.ProductionRegionCall(child.id,args) for child in children)),
        (docs,),b.union(*(b.completions(child) for child in children)))
    b.finish(no,(current,),(b.world,))
    args=(b.parameter(body,0),mapping,world)
    world,=b.control(body,P.BranchControl(P.ProductionRegionCall(yes.id,args),P.ProductionRegionCall(no.id,args)),
        (enabled,),b.union(b.completions(yes),b.completions(no)))
    return mapping,world


def build_request_body(b,parent,request):
    environment=b.rules.source.evaluations.environment(request,b.world,b.rules.exception_abi)
    body=b.region(environment.source,(_REF,_REF,b.world),parent,P.ProductionRegionKind.DEFERRED)
    world,=b.emit(body,P.EnterEvaluationRequest(environment),tuple(b.parameter(body,i) for i in range(3)),
        (b.world,),may_raise=False)
    maximum,world=b.literal(body,2,world)
    compared,world=b.emit(body,P.ApplyImplicitComparison(P.ImplicitComparisonKind.GREATER,b.rules.exception_abi),
        (b.parameter(body,1),maximum,world),(_REF,b.world))
    rejected,world=b.protocol(body,K.TRUTH,(compared,),world)
    world,=b.protocol(body,K.FRAME_RELEASE_TEMPORARY,(compared,),world)
    failure=b.region(environment.source,(b.world,),body)
    error,current=b.emit(failure,P.ReadCommonConstant(P.CommonConstantKind.NOT_IMPLEMENTED_ERROR),
        (b.parameter(failure,0),),(_REF,b.world),may_raise=False)
    payload=b.protocol(failure,K.RAISE_EXCEPTION,(error,),current)
    b.transfer(failure,C.RAISE,payload,b.raised)
    accepted=b.region(environment.source,(b.world,),body)
    b.finish(accepted,(b.parameter(accepted,0),),(b.world,))
    world,=b.control(body,P.BranchControl(P.ProductionRegionCall(failure.id,(world,)),
        P.ProductionRegionCall(accepted.id,(world,))),(rejected,),b.union(b.completions(failure),b.completions(accepted)))
    if type(request) is P.FunctionAnnotationInterface:
        pairs=[]
        for entry in request.entries:
            key,world=b.literal(body,entry.name,world,source=entry.parameter or entry.value)
            if request.stringized:
                value,world=b.emit(body,P.DefineAnnotationString(entry.value,b.rules.source.evaluations.stringize(entry.value)),
                    (world,),(_REF,b.world),may_raise=False,source=entry.value)
            else:
                selected=b.value(entry.value).reference
                unpack=b.rules.source.context.syntax.nodes[selected].constructor=='Starred'
                value,world=_value(b,body,entry.value,world,unpack=unpack)
            pairs.extend((key,value));b.slots[entry.value]=P.ProductionDispositionKind.DEFERRED_CHILD
        value,world=b.protocol(body,K.BUILD_MAP,tuple(pairs),world,
            (CountBinding('pair_count',len(request.entries)),),selectors=tuple(e.value for e in request.entries))
    elif type(request) is P.ScopeAnnotationInterface:
        value,world=_scope_body(b,body,request,world)
    else:
        value,world=_value(b,body,request.source,world,unpack=request.unpack_starred)
        b.slots[request.source]=P.ProductionDispositionKind.DEFERRED_CHILD
    b.transfer(body,C.RETURN,(value,world),(_REF,b.world))
    return body
