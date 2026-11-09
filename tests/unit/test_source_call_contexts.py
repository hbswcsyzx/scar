"""One shared callback body must preserve two callers' distinct inputs."""
from types import SimpleNamespace as NS

from scar.analysis.source_call_contexts import ContextReferenceEngine
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
