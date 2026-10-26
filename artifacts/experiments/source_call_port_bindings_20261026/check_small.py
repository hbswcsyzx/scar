"""Synthetic type/strict-reader checks only; no graph, target or raw replay."""
from pathlib import Path
from dataclasses import replace
import ast,hashlib,json,time
from scar.ir.program.source_call_bindings import *
from scar.ir.program.call_edges import CodeSourceLink,CallLinkStatus,CapturedSite
from scar.ir.program.providers import ProviderArtifact,ProviderFactReference
from scar.ir.program.functions import CallArgument,ArgumentKind,FormalParameter,FunctionSignature,ParameterKind
from scar.ir.program.ids import RegionID,OperationID,UseID,ValueID
from scar.ir.v2.ids import OperationDefinitionID,ValueSlotID,SourceAtomID
from scar.ir.v2.common import SourceReference
from scar.ir.semantics_v2 import SourceSnapshot
from scar.analysis.function_binding import bind_call
from scar.ir.record_codec import encode,decode
from scar.analysis.call_operands import CallOperandReport,_FIELDS,_PARTITION_FIELDS
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
start=time.monotonic();checks=[]
def check(name,value):
 if not value:raise AssertionError(name)
 checks.append(name)
def reject(name,call):
 try:call()
 except (ValueError,TypeError):checks.append(name);return
 raise AssertionError('accepted '+name)
changed=('scar/ir/program/source_call_bindings.py','scar/analysis/source_call_bindings.py','scar/analysis/call_operands.py','scar/analysis/current_source_evidence.py')
for n in changed:ast.parse((ROOT/n).read_text(),filename=n)
path='/synthetic/type-only.py';fp='sha256:'+'a'*64
sr=lambda n:SourceReference(SourceAtomID(n),path,fp,1,1,0,10)
cd,td=OperationDefinitionID('caller'),OperationDefinitionID('callee')
cr,tr=RegionID('caller'),RegionID('callee');op=OperationID('call');use=UseID('actual');value=ValueID('expression');slot=ValueSlotID('parameter');formal=ValueID('formal')
declaration=ProviderFactReference(ProviderArtifact('/synthetic/composition.json','b'*64,2,'scar.program-composition'),'#/files/0/bodies/0/graph_locator')
def ns(name,definition,region):
 loc=SourceArtifactLocator(ProviderArtifact('/synthetic/'+name+'.json','c'*64,2,'scar.body-construction-checkpoint/1'),'c'*64,2,'canonical-json','#/graph',declaration)
 return SourceBodyNamespace(loc,'scar.program-graph/28',definition,sr(name),name,region)
caller,callee=ns('caller',cd,cr),ns('callee',td,tr)
arg=CallArgument(0,sr('x+y'),ArgumentKind.POSITIONAL,use=use)
sig=FunctionSignature(td,sr('callee'),(FormalParameter('parameter',ParameterKind.POSITIONAL,slot,sr('formal')),))
candidate=bind_call(sig,call=OperationDefinitionID('call'),target=td,source=sr('call'),arguments=(arg,))
site=CapturedSite('pycode-v2:'+'d'*64,2,'CALL',(1,1,0,10))
call=CallSiteLink(site,CallLinkStatus.VERIFIED,sr('call'),candidate.call,cd,cr,op,UseID('callee'),ValueID('callee'))
cc=CodeSourceLink(site.code,CallLinkStatus.VERIFIED,SourceSnapshot(path,fp),cd,sr('caller'))
tc=CodeSourceLink('pycode-v2:'+'e'*64,CallLinkStatus.VERIFIED,SourceSnapshot(path,fp),td,sr('callee'))
port=SourceArgumentPort(0,caller,op,arg.source,use,value,callee,slot,formal,'parameter',candidate.routes[0])
anchor=lambda i:CallRecordAnchor('/synthetic/events.jsonl',i,'f'*64,i)
binding=SourceCallPortBinding(anchor(1),anchor(2),anchor(3),InvocationKey(1,2,1),InvocationKey(1,2,2),cc,tc,call,caller,callee,candidate,(port,))
model=SourceCallPortModel(SourceCallPortBudget(),1,(binding,),())
wire=json.dumps(model.to_dict(),sort_keys=True)
check('normal_strict_model_reader_roundtrip',SourceCallPortModel.loads(wire)==model)
check('expression_source_use_kept',model.bindings[0].candidate.arguments[0].source==sr('x+y'))
check('actual_formal_endpoints_qualified',port.actual_body.graph.artifact.uri!=port.formal_body.graph.artifact.uri)
check('no_observation_identity_authority',model.summary()['reference_identity_established'] is False)
check('original_namespace_roundtrip',decode(SourceBodyNamespace,encode(caller)).original_namespace()==caller.original_namespace())
reject('missing_original_declaration_rejected',lambda:replace(caller,graph=replace(caller.graph,declaration=None)))
reject('wrong_parameter_route_rejected',lambda:replace(port,index=1))
reject('wrong_caller_namespace_rejected',lambda:replace(binding,caller_body=callee))
reject('duplicate_attempt_denominator_rejected',lambda:SourceCallPortModel(SourceCallPortBudget(),2,(binding,binding),()))
wrong=model.to_dict();wrong['summary']['reference_identity_established']=True
reject('summary_cannot_grant_reference_identity',lambda:SourceCallPortModel.from_dict(wrong))
wrong=model.to_dict();wrong['model']['bindings'][0]['ports'][0]['load_anchor']=encode(anchor(8))
reject('no_fabricated_load_anchor_wire',lambda:SourceCallPortModel.from_dict(wrong))
# The old report method and its field tables have not changed at all.
base=ast.parse((OUT/'call_operands.baseline.py').read_text());new=ast.parse((ROOT/'scar/analysis/call_operands.py').read_text())
def method(tree,name):
 return next(n for c in tree.body if isinstance(c,ast.ClassDef) and c.name=='CallOperandReport' for n in c.body if isinstance(n,ast.FunctionDef) and n.name==name)
check('legacy_report_to_dict_ast_unchanged',ast.dump(method(base,'to_dict'))==ast.dump(method(new,'to_dict')))
check('legacy_report_summary_ast_unchanged',ast.dump(method(base,'summary'))==ast.dump(method(new,'summary')))
check('no_ports_added_to_legacy_wire_fields','source_ports' not in _FIELDS|_PARTITION_FIELDS)
result={'status':'PASS_SYNTHETIC_TYPED_STRICT_READER_API_ONLY','checks':checks,'elapsed_s':time.monotonic()-start,'production_sources':[{'path':n,'sha256':hashlib.sha256((ROOT/n).read_bytes()).hexdigest(),'bytes':(ROOT/n).stat().st_size} for n in changed],'scope':'NO_REAL_SOURCE_OR_RUNTIME_BINDING_PROOF; NO_GRAPH_CONSTRUCTED','raw_read':False,'target_exec':False,'lower_or_prepare':False}
(OUT/'SMALL_CHECK.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
