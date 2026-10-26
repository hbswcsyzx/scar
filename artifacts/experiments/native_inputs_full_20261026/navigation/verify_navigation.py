from pathlib import Path
import hashlib,json,time,traceback
from scar.trace.native_input_index import publish_native_input_port_navigation,query_native_input_associations,_query_regular_bytes
from scar.ir.record_codec import encode
from scar.ir.execution.codec import loads as load_execution
from scar.ir.program.codec import loads as load_program
from scar.ir.program.model import TerminatorKind
D=Path(__file__).resolve().parent
T=time.monotonic()
def artifact_bytes(a):
 b=_query_regular_bytes(Path(a['uri']),a['size_bytes'])
 assert len(b)==a['size_bytes'] and hashlib.sha256(b).hexdigest()==a['sha256']
 return b
try:
 parent=D/'native-input-connections/report.json'
 navigation=D/'port-navigation/manifest.json'
 receipt={'uri':str(navigation),'sha256':hashlib.sha256(navigation.read_bytes()).hexdigest(),'size_bytes':navigation.stat().st_size,'schema':'scar.native-input-port-navigation'}
 q=query_native_input_associations(receipt['uri'],expected_sha256=receipt['sha256'],associations=True,limit=3)
 a=q['matches'][0];context=a['canonical_parent']
 execution=load_execution(artifact_bytes(context['execution']).decode())
 program=load_program(artifact_bytes(context['program_snapshot']['artifact']).decode())
 assert encode(execution.snapshot)==context['program_snapshot']
 denotations=[d for d in execution.denotations if encode(d.id)==context['denotation']]
 assert len(denotations)==1
 d=denotations[0]
 assert encode(d.basis)==a['native_input'] and encode(d.value)==a['value_occurrence'] and encode(d.source)==a['original_input']
 bindings=[b for b in execution.evidence_bindings if encode(b.legacy)==a['native_producer']['instance'] and encode(b.source)==a['native_producer']['source']]
 assert len(bindings)==1
 operations=[o for o in execution.operations if o.id==bindings[0].operation and o.visit==d.basis.entry]
 assert len(operations)==1
 static=[o for o in program.operations if o.id==operations[0].operation]
 assert len(static)==1 and static[0].terminator.kind==TerminatorKind.INVOKE
 uses=[u for u in execution.uses if u.operation==operations[0].id and u.use==static[0].uses[d.basis.position].id and u.value==d.value]
 values=[v for v in execution.values if v.id==d.value and v.origin==d.basis.entry]
 assert len(uses)==len(values)==1
 rows=query_native_input_associations(receipt['uri'],expected_sha256=receipt['sha256'],row=a['row'],limit=1)
 node=rows['matches'][0]['node_id']
 by_node=query_native_input_associations(receipt['uri'],expected_sha256=receipt['sha256'],node_id=node,limit=1)
 assert by_node['matches'][0]['index']==a['row']
 try:query_native_input_associations(receipt['uri'],expected_sha256=receipt['sha256'],node_id=node,associations=True)
 except ValueError as e:unsupported={'status':'EXPLICITLY_REJECTED','error':str(e)}
 else:raise AssertionError('unscoped node association selection was silent')
 result={'status':'EXACT_CANONICAL_PARENT_NAVIGATION_WITH_OPEN','manifest':receipt,'ordinary_sample':{'row':a['row'],'node_id':node,'parent':context,'value_occurrence_record':encode(values[0]),'use_occurrence_record':encode(uses[0]),'original_binding':encode(bindings[0]),'scope':'ordinary typed records and exact receipt cross-references; no owner restored'},'unsupported_node_association_combination':unsupported,'query_matches':len(q['matches']),'elapsed_seconds':time.monotonic()-T,'whole_model_established':False,'target_runs_added':0}
 (D/'NAVIGATION_READBACK.json').write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps({'status':result['status'],'manifest':receipt,'elapsed_seconds':result['elapsed_seconds']}))
except BaseException as e:
 (D/'NAVIGATION_READBACK_FAILURE.json').write_text(json.dumps({'type':type(e).__name__,'error':str(e),'traceback':traceback.format_exc(),'elapsed_seconds':time.monotonic()-T},indent=2)+'\n');raise
