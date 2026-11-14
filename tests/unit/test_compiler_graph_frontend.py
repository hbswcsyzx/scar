"""Synthetic original F4 ports distinguish graph semantics from source text."""
from types import SimpleNamespace as NS

import pytest

from scar.analysis.source_namespace_interfaces import NamespacePlanView
from scar.compiler.graph_frontend import _GraphLowerer, GraphRegionRejected
from scar.ir.literals import PythonLiteral
from scar.ir.program import source_productions as P, normal_graph as G, normal_links as F
from scar.ir.program.control import LanguageCompletionKind as C
from scar.ir.program.ids import LocationID
from scar.ir.program.model import ValueType, ValueKind


def _graph(extra=None):
    unit='original-unit'; key=G.SourceTemplateKey(41,P.ProductionPurpose.STATEMENT)
    root=P.ProductionRegionID('original-body'); site=P.ProductionOccurrence(41)
    ref=ValueType(ValueKind.REFERENCE)
    world=ValueType(ValueKind.STATE,location=LocationID('world'))
    parameter=lambda i:P.ProductionParameter(root,i)
    result=lambda name,i=0:P.ProductionResult(P.ProductionStepID(name),i)
    steps=[]
    def step(name,ins,args,types,kind=C.FALLTHROUGH):
        item=P.ProductionStep(P.ProductionStepID(name),root,site,ins,args,
            (P.ProductionCompletion(kind,types),))
        steps.append(item)
        return item
    read=step('original-read',P.AccessBinding(P.BindingActionKind.READ,7),
        (parameter(2),),(ref,world))
    step('original-literal',P.DefineLiteral(PythonLiteral.from_python(3,exact=True)),(),(ref,))
    add=step('original-add',P.ApplyLanguageAction(P.LanguageActionKind.BINARY),
        (result('original-read'),result('original-literal'),result('original-read',1)),(ref,world))
    step('original-store',P.AccessBinding(P.BindingActionKind.WRITE,8),
        (result('original-add'),result('original-add',1)),(world,))
    alias=step('original-alias',P.AccessBinding(P.BindingActionKind.READ,9),
        (result('original-store'),),(ref,world))
    if extra is not None:
        step('original-side-effect',extra,(result('original-alias'),result('original-alias',1)),(ref,world))
    step('original-return',P.TransferCompletion(C.RETURN),
        (result('original-alias'),result('original-alias',1)),(ref,world),C.RETURN)
    region=P.ProductionRegion(root,None,P.ProductionRegionKind.DEFERRED,site,None,
        (ref,ref,world),(P.ProductionCompletion(C.RETURN,(ref,world)),),tuple(item.id for item in steps))
    flow=P.CompilationContextFlow((P.CompilationContextPort(root,2,2),),(),())
    plan=P.SourceProductionPlan(None,site,P.ProductionPurpose.STATEMENT,root,
        (region,),tuple(steps),(),compilation_flow=flow)
    context=NamespacePlanView(unit,plan)
    ports=[context.value(parameter(i)).port for i in range(3)]
    ports.extend(context.result(item).port for item in (read,add,alias))
    ports.append(context.result(context.steps[P.ProductionStepID('original-literal')]).port)
    original=F.Namespace(F.NamespaceKind.LEXICAL,70,'arbitrary_input')
    local=F.Namespace(F.NamespaceKind.LEXICAL,71,'arbitrary_alias')
    facts=NS(unit=unit,ports=tuple(ports),constants=(),
        operations=(F.LanguageOperation(F.LanguageOperationKind.BINARY,F.OperatorSelector.ADD,(3,6),4,2,2),),
        names=(F.NameAccess(original,1,True),F.NameAccess(original,3,False),
            F.NameAccess(local,4,True),F.NameAccess(local,5,False)))
    environment=NS(kind=P.DeferredBodyKind.FUNCTION,captures=(),owned_cells=(),parameters=())
    function=NS(template=key,body=root,body_scope=context.owner(root),environment=environment,
        parameter_names=('arbitrary_input',),formals=(0,1,2))
    source=NS(unit=unit,facts=facts,material=NS(interfaces={'links':{}}))
    resolver=NS(plan=lambda selected_unit,selected_key:context)
    return _GraphLowerer(source,function,resolver)


def test_lowers_original_operations_parameter_local_alias_and_return():
    lowerer=_graph()
    nodes,output,origins=lowerer.lower()
    assert [(node.op,node.inputs) for node in nodes]==[('input',()),('const',()),('add',('n0','n1'))]
    assert nodes[1].attrs['value']==3 and output=='n2'
    assert all(origin['unit']=='original-unit' for origin in origins)
    assert any(origin.get('step')==P.ProductionStepID('original-return').wire for origin in origins)
    assert any(origin.get('expression')=='n2' and origin.get('step')==P.ProductionStepID('original-add').wire
        for origin in origins)
    assert origins[0]['value']['port']['kind']=='PARAMETER'


@pytest.mark.parametrize('instruction',[
    P.ApplyLanguageAction(P.LanguageActionKind.CALL),
    P.ApplyLanguageAction(P.LanguageActionKind.ATTRIBUTE_SET),
    P.BranchControl(P.ProductionRegionCall(P.ProductionRegionID('yes'),()),
        P.ProductionRegionCall(P.ProductionRegionID('no'),())),
])
def test_rejects_actions_outside_return_dependencies(instruction):
    with pytest.raises(GraphRegionRejected) as error:
        _graph(instruction).lower()
    assert error.value.code in ('UNSUPPORTED_ACTION','UNSUPPORTED_INSTRUCTION')


def test_value_provenance_follows_optimizer_map_without_inventing_versions():
    from dataclasses import replace
    from scar.compiler.model import ArrayRegion,ExecutionPlan,Expr,SourceRef
    from scar.compiler.provenance import graph_value_sources

    nodes,output,origins=_graph().lower()
    duplicate=dict(next(row for row in origins if row.get('expression')=='n2'),expression='old-add')
    discarded=dict(duplicate,expression='dead-add')
    fake=dict(duplicate,kind='source_identity',expression='n0')
    source=SourceRef('/source.py','a'*64,'arbitrary',1,0,'pycode-v2:'+'b'*64,
        (*origins,duplicate,discarded,fake))
    region=ArrayRegion('region',source,('arbitrary_input',),nodes+(Expr('no-evidence','const',attrs={'value':7}),),output)
    plan=ExecutionPlan(region,proof={'source_operation_map':{
        'old-add':{'optimized_node':'n2','reason':'common_subexpression'},
        'dead-add':{'optimized_node':None,'reason':'dead_dependency'}}})
    selected=graph_value_sources(plan)
    assert set(selected)=={'n0','n1','n2','no-evidence'}
    assert len(selected['n0'])==1 and 'value' in selected['n0'][0]
    assert selected['no-evidence']==()
    assert [row['expression'] for row in selected['n2']]==['n2','old-add']
    assert all(row['unit']=='original-unit' and row['step'].endswith('original-add')
        and row['results'][0]['port']['kind']=='RESULT' for row in selected['n2'])
    selected['n2'][0]['unit']='caller-annotation'
    assert next(row for row in source.origins if row.get('expression')=='n2')['unit']=='original-unit'
    empty=replace(plan,region=replace(region,source=replace(source,origins=())))
    assert graph_value_sources(empty)==dict.fromkeys(selected,())
