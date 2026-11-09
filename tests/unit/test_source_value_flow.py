"""New value dependencies cross operations/locations without creating aliases."""
from types import SimpleNamespace as NS

from scar.analysis.source_value_flow import project_value_flow, data_reach
from scar.analysis.source_productions import _digest
from scar.ir.program import source_productions as P, normal_graph as G, normal_links as F, normal_targets as T
from scar.ir.program.source_template_links import SourceTemplateKey
from scar.ir.program.source_contexts import ContextState, OwnerRef
from scar.ir.program.control import LanguageCompletionKind as C
from scar.ir.program.model import ValueKind, ValueType
from scar.ir.program.ids import LocationID
from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import encode, decode
from scar.ir.program import source_value_flow as V


def test_producer_location_and_state_are_distinct():
    ref = ValueType(ValueKind.REFERENCE)
    world = ValueType(ValueKind.STATE, location=LocationID('world'))
    source = P.ProductionOccurrence(0); key = SourceTemplateKey(0, P.ProductionPurpose.VALUE)
    region = P.ProductionRegionID('body'); sid = P.ProductionStepID
    p = lambda i: P.ProductionParameter(region, i)
    r = lambda name, i: P.ProductionResult(sid(name), i)
    normal = lambda *types: P.ProductionCompletion(C.FALLTHROUGH, types)
    def step(name, instruction, args, types):
        return P.ProductionStep(sid(name), region, source, instruction, args, (normal(*types),))
    steps = (
        step('producer', P.ApplyLanguageAction(P.LanguageActionKind.CALL), (p(0), p(2)), (ref, world)),
        step('store', P.AccessBinding(P.BindingActionKind.WRITE, 0), (r('producer', 0), r('producer', 1)), (world,)),
        step('load', P.AccessBinding(P.BindingActionKind.READ, 0), (r('store', 0),), (ref, world)),
        step('consumer', P.ApplyLanguageAction(P.LanguageActionKind.CALL), (r('load', 0), p(1), r('load', 1)), (ref, world)),
        step('return', P.TransferCompletion(C.FALLTHROUGH), (r('consumer', 0), r('consumer', 1)), (ref, world)),
    )
    context = ContextState(OwnerRef(0, 'ROOT'), 0, 0, 0)
    body_region = P.ProductionRegion(region, None, P.ProductionRegionKind.EXECUTION, source, context,
        (ref, ref, world), (normal(ref, world),), tuple(s.id for s in steps))
    basis = P.ProductionInput('/source/f.py', '/source', *('a'*64 for _ in range(8)))
    plan = P.SourceProductionPlan(basis, source, P.ProductionPurpose.VALUE, region, (body_region,), steps, ())
    port = lambda owner, kind, i=0, completion=None: G.Port(key, owner, kind, i, completion)
    ports = (port(region,G.PortKind.PARAMETER,0), port(region,G.PortKind.PARAMETER,1),
        port(region,G.PortKind.PARAMETER,2), port(sid('producer'),G.PortKind.RESULT,0,C.FALLTHROUGH),
        port(sid('load'),G.PortKind.RESULT,0,C.FALLTHROUGH), port(sid('consumer'),G.PortKind.RESULT,0,C.FALLTHROUGH))
    scope = F.CodeScopeRef('unit', 5)
    namespace = F.Namespace(F.NamespaceKind.LEXICAL, 27, 'local')
    foreign = F.Namespace(F.NamespaceKind.LEXICAL, 28, 'captured')
    names = (F.NameAccess(namespace,3,True), F.NameAccess(namespace,4,False), F.NameAccess(foreign,1,False))
    calls = (F.Call(1,(0,),(),3,2,2), F.Call(1,(4,1),(),5,2,2))
    fn = NS(value=1,template=key,body=region,body_scope=NS(owner=scope))
    unit = NS(unit='unit',ports=ports,functions=(fn,),names=names,calls=calls,
        scope_groups=(F.FactScopeGroup(scope,(F.FactRange(F.FactTable.NAMES,0,3), F.FactRange(F.FactTable.CALLS,0,2))),))
    node = NS(origin=NS(plan_sha256=_digest(encode(plan,record_tags=P.PRODUCTION_RECORD_TAGS))))
    material = NS(unit='unit',closure=lambda *args,**kwargs:{key:plan},
        interfaces=dict(nodes={key:node},links={}), validate_parents=lambda:None,
        result_artifact=ProviderArtifact('/source/result.json','0'*64,0,'test'),
        fact_store=NS(load=lambda _:unit,rows={'unit':dict(facts='/source/facts.json',sha256='0'*64,bytes=0)}))
    gp = lambda i:T.GlobalPort('unit',ports[i])
    flow = project_value_flow(material,gp(1),T.Body('unit',key,region))
    assert len(flow.operations)==4  # TransferCompletion keeps its original slot-wise edges.
    assert not any(e.kind is G.EdgeKind.DATA and e.source.owner==sid('producer')
        and e.source.kind is G.PortKind.ARGUMENT and e.target==ports[3] for e in flow.edges)
    reach = data_reach(flow,gp(0),0,0,unit)
    assert (1, 'POSITIONAL', 0) in {(int(c.call.locator.rsplit('/',1)[1]),c.role,c.ordinal) for c in reach.call_inputs}
    assert not any(c.ordinal==1 and c.role=='POSITIONAL' for c in reach.call_inputs)
    assert not data_reach(flow,gp(2),1,0,unit).call_inputs  # sequencing world is not tensor data
    assert any(b.reason=='CAPTURE_OR_LEXICAL_PRODUCER_OUTSIDE_THIS_BODY' for b in flow.name_boundaries)
    assert decode(V.SourceBodyValueFlow,encode(flow,record_tags=P.PRODUCTION_RECORD_TAGS),
        record_tags=P.PRODUCTION_RECORD_TAGS)==flow
