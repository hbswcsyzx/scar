"""Source parameter dependencies do not authorize effects or deferred entry."""
from dataclasses import replace
from types import SimpleNamespace as NS

from scar.analysis.source_reference_consumers import bind_consumer_interface
from scar.ir.program import reference_consumers as R, normal_targets as T, normal_graph as G, source_productions as P
from scar.ir.program import source_address_paths as A
from scar.ir.program.source_template_links import SourceTemplateKey
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference


def test_keyword_projection_worlds_deferred_and_constructor_boundaries():
    key = SourceTemplateKey(0, P.ProductionPurpose.VALUE)
    ports = tuple(G.Port(key, P.ProductionRegionID('r'), G.PortKind.PARAMETER, i) for i in range(20))
    gp = lambda unit, i: T.GlobalPort(unit, ports[i])
    fn = NS(value=7, template=key, body=P.ProductionRegionID('body'), formals=(1,2,3), returns=4, return_world=5,
        environment=NS(kind=P.DeferredBodyKind.FUNCTION))
    provider = NS(unit='callee', functions=(fn,), ports=ports)
    slicer = NS(local=lambda port:(provider,7))
    artifact = ProviderArtifact('/source/rows.gz','0'*64,0,'test');evidence=ProviderFactReference(artifact,'#/records/0')
    path = A.AddressPath(gp('caller',8),A.AddressRootKind.CALL_RESULT,(A.FieldSelector('field'),),(),())
    use = R.ReferenceArgumentUse(0,evidence,R.ArgumentRole.KEYWORD,0,'value',gp('caller',11),(path,),False,
        gp('caller',12),gp('caller',13),('PARENT_CONTEXT_SELECTED',))
    argument = T.Route(gp('callee',2),T.RouteKind.ARGUMENT,(use.actual,))
    state = T.Route(gp('callee',3),T.RouteKind.STATE,(use.world_before,))
    link = T.CallLink(gp('caller',14),gp('caller',10),gp('callee',7),T.Body('callee',key,fn.body),
        'SOURCE_FUNCTION',None,(argument,state),((gp('callee',4),gp('caller',14)),(gp('callee',5),use.world_after)))
    bindings, reason = bind_consumer_interface(slicer,0,use,None,link,evidence)
    assert reason is None and len(bindings)==1
    b=bindings[0]
    assert b.argument==argument and b.state==state and b.data_return!=b.state_return
    assert not use.direct_reference  # A field value is a consumer without becoming the parent reference.
    assert 'CALLEE_EFFECTS_AND_ESCAPES_REMAIN_OPEN' in b.conditions
    receiver=replace(use,role=R.ArgumentRole.ATTRIBUTE_RECEIVER,attribute=evidence,direct_reference=True)
    receiver_bindings,reason=bind_consumer_interface(slicer,0,receiver,None,replace(link,mode='SOURCE_BOUND_METHOD'),evidence)
    assert reason is None and receiver_bindings[0].argument.formal==gp('callee',2)
    # The same attribute receiver is not silently prepended to a static call.
    assert not bind_consumer_interface(slicer,0,receiver,None,link,evidence)[0]
    callee=replace(use,role=R.ArgumentRole.CALLEE,actual=link.callee)
    environment=T.Route(gp('callee',1),T.RouteKind.FUNCTION_ENVIRONMENT,(link.callee,))
    env_bindings,reason=bind_consumer_interface(slicer,0,callee,None,replace(link,parameters=(environment,argument,state)),evidence)
    assert reason is None and env_bindings[0].argument.kind is T.RouteKind.FUNCTION_ENVIRONMENT
    wrong=replace(link,parameters=(argument,replace(state,actuals=(gp('caller',19),))))
    assert bind_consumer_interface(slicer,0,use,None,wrong,evidence)[1]=='CALLEE_WORLD_INPUT_ROUTE_UNRESOLVED'
    fn.environment.kind=P.DeferredBodyKind.GENERATOR
    deferred,reason=bind_consumer_interface(slicer,0,use,None,replace(link,returns=()),evidence)
    assert reason is None and deferred[0].activation is T.FunctionActivation.CREATE_DEFERRED_BODY
    assert deferred[0].state_return is None and 'DEFERRED_BODY_CREATION_IS_NOT_BODY_ENTRY' in deferred[0].conditions
    assert bind_consumer_interface(slicer,0,use,None,replace(link,mode='SOURCE_INIT'),evidence)[1]=='CONSTRUCTOR_PROTOCOL_CONSUMER_REMAINS_EXPLICIT'
