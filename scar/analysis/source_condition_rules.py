"""Control-boolean recipes distinct from value-producing Python expressions.

Matches codegen_jump_if's context propagation. In particular, a short-circuit
operand/result is never returned as an object and then truth-tested again.
"""
from scar.analysis.source_expression_rules import _REF, _BOOL, _require
from scar.ir.program import source_productions as P
from scar.ir.program.structured import PythonProtocolKind as K


def _return_decision(b,parent,source):
    done=b.region(source,(_BOOL,b.world),parent)
    b.finish(done,(b.parameter(done,0),b.parameter(done,1)),(_BOOL,b.world))
    return done


def _branch(b,region,decision,yes,yes_args,no,no_args):
    return b.control(region,P.BranchControl(P.ProductionRegionCall(yes.id,yes_args),
        P.ProductionRegionCall(no.id,no_args)),(decision,),b.union(b.completions(yes),b.completions(no)))


def emit_condition(b,region,world):
    kind=b.node.constructor
    if kind=='BoolOp':
        _boolean(b,region,world)
    elif kind=='IfExp':
        _conditional(b,region,world)
    elif kind=='UnaryOp' and b.selector('UnaryOp',b.site('op'))=='Not':
        b.mark('op',P.ProductionDispositionKind.MARKER)
        b.mark('operand',P.ProductionDispositionKind.EVALUATED_CHILD)
        decision,world=b.condition(region,b.site('operand'),world)
        inverted,=b.emit(region,P.InvertCondition(),(decision,),(_BOOL,),may_raise=False)
        b.finish(region,(inverted,world),(_BOOL,b.world))
    elif kind=='Compare' and len(b.value(b.site('ops')).items)>1:
        _comparison(b,region,world)
    else:
        site=b.role.parents.get(b.occurrence)
        _require(site is not None,'SOURCE_REFERENCE',str(b.occurrence),'condition fallback requires its original value-use slot')
        # Same occurrence, different purpose: VALUE is a distinct child template.
        for name in b.role.fields[kind]:b.mark(name,P.ProductionDispositionKind.DELEGATED_VALUE_RULE)
        b.slots[site]=P.ProductionDispositionKind.EVALUATED_CHILD
        value,world=b.evaluate(region,site,world)
        decision,world=b.protocol(region,K.TRUTH,(value,),world)
        world,=b.protocol(region,K.FRAME_RELEASE_TEMPORARY,(value,),world)
        b.finish(region,(decision,world),(_BOOL,b.world))


def _boolean(b,region,world):
    b.mark('op',P.ProductionDispositionKind.MARKER)
    b.mark('values',P.ProductionDispositionKind.EVALUATED_CHILD)
    selector=b.selector('BoolOp',b.site('op'))
    values=b.value(b.site('values'))
    _require(values.kind=='LIST' and len(values.items)>=2,'RULE_SHAPE',str(b.occurrence),'boolean condition requires at least two operands')
    for ordinal in range(len(values.items)):
        site=b.site('values',ordinal)
        decision,world=b.condition(region,site,world)
        if ordinal==len(values.items)-1:
            b.finish(region,(decision,world),(_BOOL,b.world))
            return
        done=_return_decision(b,region,site)
        follow=b.region(b.site('values',ordinal+1),(b.world,),region)
        # Each continuation requests a condition child with BOOL/world + raise.
        calls=((follow.id,(world,)),(done.id,(decision,world))) if selector=='And' else (
            (done.id,(decision,world)),(follow.id,(world,)))
        b.emit(region,P.BranchControl(*(P.ProductionRegionCall(*call) for call in calls)),(decision,),(_BOOL,b.world))
        region,world=follow,b.parameter(follow,0)


def _conditional(b,region,world):
    for name in ('test','body','orelse'):b.mark(name,P.ProductionDispositionKind.EVALUATED_CHILD)
    decision,world=b.condition(region,b.site('test'),world)
    branches=[]
    for name in ('body','orelse'):
        child=b.region(b.site(name),(b.world,),region)
        result=b.condition(child,b.site(name),b.parameter(child,0))
        b.finish(child,result,(_BOOL,b.world));branches.append(child)
    result=_branch(b,region,decision,branches[0],(world,),branches[1],(world,))
    b.finish(region,result,(_BOOL,b.world))


def _comparison(b,region,world):
    b.mark('left',P.ProductionDispositionKind.EVALUATED_CHILD)
    b.mark('ops',P.ProductionDispositionKind.MARKER)
    b.mark('comparators',P.ProductionDispositionKind.EVALUATED_CHILD)
    operators,comparators=b.value(b.site('ops')),b.value(b.site('comparators'))
    _require(operators.kind==comparators.kind=='LIST' and len(operators.items)==len(comparators.items),
        'RULE_SHAPE',str(b.occurrence),'comparison condition operand/selector lengths differ')
    left,world=b.evaluate(region,b.site('left'),world)
    for ordinal in range(len(operators.items)):
        operator,site=b.site('ops',ordinal),b.site('comparators',ordinal)
        b.selector('Compare',operator)
        right,world=b.evaluate(region,site,world)
        value,world=b.action(region,P.LanguageActionKind.COMPARE,(operator,),(left,right,world))
        decision,world=b.protocol(region,K.TRUTH,(value,),world)
        world,=b.protocol(region,K.FRAME_RELEASE_TEMPORARY,(value,),world)
        if ordinal==len(operators.items)-1:
            b.finish(region,(decision,world),(_BOOL,b.world))
            return
        done=_return_decision(b,region,operator)
        follow=b.region(b.site('comparators',ordinal+1),(_REF,b.world),region)
        b.emit(region,P.BranchControl(P.ProductionRegionCall(follow.id,(right,world)),
            P.ProductionRegionCall(done.id,(decision,world))),(decision,),(_BOOL,b.world))
        region=follow
        left,world=b.parameter(region,0),b.parameter(region,1)
