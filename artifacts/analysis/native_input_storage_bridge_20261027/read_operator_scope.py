"""Receipt-bound classification of the already selected endpoint, no raw replay."""
from pathlib import Path
from hashlib import sha256
import json,time
from scar.ir.record_codec import encode
from scar.ir.program.codec import loads as load_program
from scar.ir.execution.codec import loads as load_execution
from scar.ir.v2.codec import evidence_from_dict
B=Path(__file__).resolve().parent
q=json.loads((B/'attempt02/QUERY.json').read_bytes());reads=[]
def read(a):
 p=Path(a['uri']);before=p.stat();raw=p.read_bytes()
 assert len(raw)==a['size_bytes'] and sha256(raw).hexdigest()==a['sha256']
 assert before==p.stat();reads.append(a);return raw
start=time.monotonic()
nav=json.loads(read(q['navigation']));report=json.loads(read(nav['canonical_batch']))
parent_artifact=report['native_parent_inventory'];parents=json.loads(read(parent_artifact))
node_source=q['original_input']['locator'].split('/inputs/')[0];ordinal=int(node_source.split('/')[-1])
assert parents['source_artifact']==q['original_input']['artifact']
chunk=next(c for c in parents['chunks'] if c['first_original_ordinal']<=ordinal<=c['last_original_ordinal'])
rows=[json.loads(line)for line in read(chunk['artifact']).splitlines()]
parent=next(r for r in rows if r['source']['locator']==node_source)
program=load_program(read(q['canonical_parent']['program_snapshot']['artifact']).decode('utf8'))
operation=next(o for o in program.operations if encode(o.id)==q['operation_occurrence']['operation'])
boundary=next(b for b in program.native_boundaries if encode(b.id)==q['native_input']['boundary'])
interface_doc=json.loads(read(encode(boundary.signature.artifact)))
interface=interface_doc['interfaces'][boundary.signature.locator.split('/')[-1]]
# Recover the exact original artifact from the normal selected execution binding.
execution=load_execution(read(q['canonical_parent']['execution']).decode('utf8'))
bindings=[b for b in execution.evidence_bindings if encode(b.operation)==q['operation_occurrence']['id']]
assert len(bindings)==1
evidence_artifact=encode(bindings[0].legacy.artifact)
evidence=evidence_from_dict(json.loads(read(evidence_artifact)))
instances=[i for i in evidence.instances.values()if i.metadata.get('raw_reference')=='sha256:'+parents['source_artifact']['sha256']+node_source]
assert len(instances)==1
instance=instances[0]
assert instance.metadata['node_id']==parent['node_id']==25
assert parent['actor']['name']=='aten::lift_fresh' and interface['schema']==operation.label
result={'status':'PASS','selected':q['selector'],'original_parent_row':parent,
 'static_operation':encode(operation.id),'static_operator_schema':operation.label,'interface_source':encode(boundary.signature),
 'interface':interface,'native_instance':instance.as_dict(),'native_instance_artifact':evidence_artifact,
 'classification':'actual retained aten::lift_fresh cpu_op, not scar-dispatch input marker',
 'qualification':'retained original parent scope and normal program/evidence codecs; no original raw ETO replay',
 'read_inputs':reads,'stored_bytes':sum(r['size_bytes']for r in reads),
 'decoded_bytes':sum(r['size_bytes']for r in reads),'wall_seconds':time.monotonic()-start}
(B/'OPERATOR_SCOPE.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
print(json.dumps({'status':result['status'],'actor':parent['actor'],'schema':operation.label,'wall_seconds':result['wall_seconds'],'bytes':result['stored_bytes']}))
