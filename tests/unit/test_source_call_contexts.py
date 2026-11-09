"""One shared callback body must preserve two callers' distinct inputs."""
from types import SimpleNamespace as NS

from scar.analysis.source_call_contexts import ContextReferenceEngine
from scar.analysis.source_connected_bodies import StackedReferenceEngine
from scar.ir.program import normal_graph as G, normal_targets as T, normal_links as F, source_productions as P
from scar.ir.program.source_template_links import SourceTemplateKey
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference


def test_selected_incoming_interface_keeps_callbacks_separate():
    key=SourceTemplateKey(0,P.ProductionPurpose.VALUE); region=P.ProductionRegionID('shared')
    ports=tuple(G.Port(key,region,G.PortKind.PARAMETER,i) for i in range(16))
    gp=lambda i:T.GlobalPort('unit',ports[i])
    fn=NS(value=10,template=key,body=region,formals=(9,0,1,2),body_scope=NS(owner=F.CodeScopeRef('unit',0)))
    left=NS(value=5,formals=()); right=NS(value=6,formals=())
    unit=NS(unit='unit',ports=ports,aliases=((0,13),),names=(),functions=(fn,left,right),
        constants=(),classes=(),calls=(),scope_groups=())
    artifact=ProviderArtifact('/source/calls.gz','0'*64,0,'test')
    links=tuple(T.CallLink(gp(result),gp(10),gp(10),T.Body('unit',key,region),'SOURCE_FUNCTION',None,
        parameters=(T.Route(gp(0),T.RouteKind.ARGUMENT,(gp(actual),)),)) for result,actual in ((7,5),(8,6)))
    class Snapshot:
        fact_store=NS(load=lambda _:unit,rows={'unit':dict(facts='/source/unit.json',sha256='0'*64,bytes=0)})
        def rows(self,*_):
            return tuple((i,link,ProviderFactReference(artifact,'#/records/'+str(i))) for i,link in enumerate(links))
        def validate_parents(self): pass
    engine=ContextReferenceEngine(Snapshot()); engine.index(('unit',))
    slices=engine.solve(((0,gp(13)),(1,gp(13))))
    origins=tuple({s.states[o.state].port for o in s.origins} for s in slices)
    assert origins==({gp(5)},{gp(6)})
    assert all(not s.frontiers for s in slices)
    # Each route crosses only its selected incoming interface, then pops it.
    assert all(s.states[o.state].interfaces==() for s in slices for o in s.origins)
    assert {e.evidence[0].locator for e in slices[0].edges if e.kind.value=='ARGUMENT'}=={'#/records/0'}
    # Declared interfaces keep their own evidence schema; no historical row is forged.
    declared=ProviderFactReference(ProviderArtifact('/declared/edges.gz','1'*64,0,'scar.declared-context-edges'),'#/records/0')
    incoming=engine.admit(declared,links[0])
    reference=engine.solve(((incoming,gp(13)),))[0]
    assert {reference.states[o.state].port for o in reference.origins}=={gp(5)}
    assert any(e.evidence==(declared,) for e in reference.edges if e.kind.value=='ARGUMENT')


def test_body_entry_preserves_selected_outer_caller_for_forwarded_argument():
    key=SourceTemplateKey(0,P.ProductionPurpose.VALUE)
    inner=P.ProductionRegionID('inner'); outer=P.ProductionRegionID('outer')
    ports=tuple(G.Port(key,outer if i==4 else inner,G.PortKind.PARAMETER,i) for i in range(16))
    gp=lambda i:T.GlobalPort('unit',ports[i])
    functions=(NS(value=10,template=key,body=inner,formals=(0,)),
        NS(value=11,template=key,body=outer,formals=(4,)),NS(value=5,formals=()),NS(value=6,formals=()))
    unit=NS(unit='unit',ports=ports,aliases=((0,13),),names=(),functions=functions,
        constants=(),classes=(),calls=(),scope_groups=())
    snapshot=NS(fact_store=NS(load=lambda _:unit,rows={'unit':dict(facts='/unit.json',sha256='0'*64,bytes=0)}),
        rows=lambda *_:(),validate_parents=lambda:None)
    engine=StackedReferenceEngine(snapshot)
    artifact=ProviderArtifact('/interfaces.jsonl.gz','0'*64,0,'test')
    def incoming(ordinal,fn,body,formal,actual):
        link=T.CallLink(gp(7+ordinal),gp(fn),gp(fn),T.Body('unit',key,body),'SOURCE_FUNCTION',None,
            parameters=(T.Route(gp(formal),T.RouteKind.ARGUMENT,(gp(actual),)),))
        return engine.admit(ProviderFactReference(artifact,'#/records/'+str(ordinal)),link)
    left=incoming(0,11,outer,4,5); right=incoming(1,11,outer,4,6)
    shared=incoming(2,10,inner,0,4)
    slices=engine.solve_stacks(((shared,gp(13),(left,)),(shared,gp(13),(right,))))
    assert tuple({s.states[o.state].port for o in s.origins} for s in slices)==({gp(5)},{gp(6)})
    assert tuple(s.states[0].interfaces for s in slices)==((left,shared),(right,shared))
    assert all(not s.frontiers for s in slices)
    assert all(s.states[o.state].interfaces==() for s in slices for o in s.origins)


def test_derived_return_requires_its_selected_caller_stack():
    key=SourceTemplateKey(0,P.ProductionPurpose.VALUE); region=P.ProductionRegionID('caller')
    ports=tuple(G.Port(key,region,G.PortKind.PARAMETER,i) for i in range(20))
    gp=lambda i:T.GlobalPort('unit',ports[i])
    functions=tuple(NS(value=i,template=key,body=region,formals=()) for i in (5,6,10,11,14))
    unit=NS(unit='unit',ports=ports,aliases=(),names=(),functions=functions,
        constants=(),classes=(),calls=(NS(result=12),),scope_groups=())
    snapshot=NS(fact_store=NS(load=lambda _:unit,rows={'unit':dict(facts='/unit.json',sha256='0'*64,bytes=0)}),
        rows=lambda *_:(),validate_parents=lambda:None)
    engine=StackedReferenceEngine(snapshot); engine.index(('unit',))
    artifact=ProviderArtifact('/derived.jsonl.gz','0'*64,0,'test')
    evidence=lambda i:ProviderFactReference(artifact,'#/records/'+str(i))
    def link(result,fn,returns=()):
        return T.CallLink(gp(result),gp(fn),gp(fn),T.Body('unit',key,region),'SOURCE_FUNCTION',None,returns=returns)
    left=engine.admit(evidence(0),link(7,14)); right=engine.admit(evidence(1),link(8,14))
    factory_left=engine.admit_contextual(evidence(2),link(12,10,((gp(5),gp(12)),)),(left,))
    factory_right=engine.admit_contextual(evidence(3),link(12,11,((gp(6),gp(12)),)),(right,))
    slices=engine.solve_stacks(((left,gp(12),()),(right,gp(12),())))
    assert tuple({s.states[o.state].port for o in s.origins} for s in slices)==({gp(5)},{gp(6)})
    assert tuple({s.states[e.upstream].interfaces[-1] for e in s.edges
        if e.kind.value=='DATA_RETURN_ENTER_CALL'} for s in slices)==({factory_left},{factory_right})
    unknown=engine.admit(evidence(4),link(9,14))
    unresolved=engine.solve_stacks(((unknown,gp(12),()),))[0]
    assert not unresolved.origins
    assert any(f.reason=='DERIVED_RETURN_CALLER_CONTEXT_NOT_SELECTED' for f in unresolved.frontiers)
