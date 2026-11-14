"""A function's child templates share code ownership, not local identifiers."""
from types import SimpleNamespace as NS
import pytest

from scar.analysis.source_body_interfaces import BodyInterfaceResolver
from scar.analysis import source_body_activation_view as port_view
from scar.ir.program import source_body_interfaces as B, source_productions as P, normal_graph as G
from scar.ir.program.normal_targets import Body, GlobalPort
from scar.ir.program.normal_links import CodeScopeRef, CodeScopeWitness
from scar.ir.program.ids import ProviderID, LocationID
from scar.ir.program.model import ValueKind, ValueType
from scar.ir.program.protocol_signatures import ExceptionABI
from scar.ir.program.control import LanguageCompletionKind as C


@pytest.mark.parametrize('same_code_scope',(True,False))
def test_nested_template_resume_is_qualified_and_only_enters_its_code_scope(same_code_scope):
    ref=ValueType(ValueKind.REFERENCE); world=ValueType(ValueKind.STATE,location=LocationID('world'))
    main=G.SourceTemplateKey(1,P.ProductionPurpose.STATEMENT)
    child=G.SourceTemplateKey(2,P.ProductionPurpose.VALUE)
    # Local IDs intentionally collide across templates.
    local=P.ProductionRegionID('r0'); resumed=P.ProductionRegionID('r1')
    owner=CodeScopeRef('unit',1)
    scope=lambda key,region:CodeScopeWitness(owner,key,region,1)
    gp=lambda key,region,i:GlobalPort('unit',G.Port(key,region,G.PortKind.PARAMETER,i))
    body=Body('unit',main,local)
    environment=P.DeferredEnvironment(1,0,(),(),P.DeferredBodyKind.GENERATOR,world,ExceptionABI.EXCEPTION_WORLD)
    head=B.SourceBodyInterface(ProviderID('head'),body,scope(main,local),'a'*64,
        P.ProductionStepID('enter'),P.EnterDeferredBody(environment),
        (B.SourceBodyIngress(body,(gp(main,local,0),gp(main,local,1)),(ref,world)),),(),())
    call=P.ProductionStepID('child_call'); yielded=P.ProductionStepID('yield')
    saved=P.ProductionParameter(local,0)
    instruction=P.SuspendExecution(P.SuspensionKind.YIELD,ExceptionABI.EXCEPTION_WORLD,
        (P.ProductionResumeRoute(C.FALLTHROUGH,resumed),),saved=(saved,))
    main_context=NS(plan=NS(regions=(NS(id=local,parent=None),),
        steps=(NS(id=call,region=local,instruction=P.EvaluateChild(P.SlotRef(0,'FIELD',0),P.ProductionPurpose.VALUE)),)),
        owner=lambda region:scope(main,region))
    child_regions={local:NS(id=local,parent=None,parameters=(ref,world)),
        resumed:NS(id=resumed,parent=local,parameters=(ref,world,ref))}
    child_owner=owner if same_code_scope else CodeScopeRef('unit',2)
    child_context=NS(plan=NS(regions=tuple(child_regions.values()),steps=(NS(id=yielded,region=local,
        instruction=instruction,arguments=(P.ProductionParameter(local,0),P.ProductionParameter(local,1))),)),
        regions=child_regions,owner=lambda region:CodeScopeWitness(child_owner,child,region,child_owner.ordinal),
        site=lambda step:GlobalPort('unit',G.Port(child,step.id,G.PortKind.ENTER)),
        value=lambda value:gp(child,value.region,value.index),
        emitter=NS(value=lambda value:(None,(ref,world)[value.index])))
    material=NS(interfaces=dict(links={(main,call):NS(callee=child)},nodes={child:NS(root=local)}))
    view=NS(unit=lambda unit:NS(material=material,check=lambda:None))
    resolver=BodyInterfaceResolver(view)
    resolver.plans.update({('unit',main):main_context,('unit',child):child_context})
    resolver.heads[body]=head
    result=resolver.resolve(body)
    if same_code_scope:
        assert len(result.suspensions)==1 and len(result.ingresses)==2
        assert result.suspensions[0].step.port.template==child
        resume=result.ingresses[1]
        assert resume.region==Body('unit',child,resumed)
        assert resume.world_index==1 and len(resume.types)==3
        assert resume.saved==((gp(child,resumed,2),gp(child,local,0)),)
        assert result.ingresses[0].region.template!=resume.region.template
    else:
        assert not result.suspensions and len(result.ingresses)==1


def test_added_resume_reference_cannot_disappear_from_the_graph_contract(monkeypatch):
    monkeypatch.delitem(port_view._PORT_RULES,('ingresses','*','suspension'))
    with pytest.raises(ValueError,match='complete declared schema'):
        port_view.body_port_contract()
