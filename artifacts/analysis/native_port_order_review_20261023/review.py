"""Read-only saved-model ABI counterexample, never owned capture authority."""
from dataclasses import replace
from pathlib import Path
from hashlib import sha256
import json
from scar.ir.program.codec import loads as load_program,dumps as dump_program
from scar.ir.program.validation import require_valid
from scar.ir.program.model import ReferenceValue,BlockArgument,CompletionResult,ExitKind
from scar.ir.execution.codec import loads as load_execution,dumps as dump_execution
from scar.ir.execution.snapshot import snapshot_for
from scar.ir.execution.validation import validate
from scar.ir.execution.content import NativeInputRef
from scar.ir.v2.codec import values_from_dict,evidence_from_dict
BASE=Path(__file__).resolve().parents[3]
SOURCE=BASE/'artifacts/experiments/first_stage_native_protocol_bridge_attempt02_20261023/result'
OUT=Path(__file__).parent
raw={n:(SOURCE/n).read_bytes() for n in ('program.json','execution.json','source-values.json','source-evidence.json','native-interface.json','report.json')}
program=load_program(raw['program.json'].decode());model=load_execution(raw['execution.json'].decode())
report=json.loads(raw['report.json']);signature=json.loads(raw['native-interface.json'])['interfaces']
for key,name in [('program','program.json'),('interface','native-interface.json'),('values_projection','source-values.json'),('evidence_projection','source-evidence.json')]:
 a=report['artifacts'][key];assert a['sha256']==sha256(raw[name]).hexdigest() and a['size_bytes']==len(raw[name])
values=values_from_dict(json.loads(raw['source-values.json']));evidence=evidence_from_dict(json.loads(raw['source-evidence.json']))
kwargs={'value_graphs':{report['artifacts']['values_projection']['sha256']:values},'evidence_graphs':{report['artifacts']['evidence_projection']['sha256']:evidence}}
# A proposed pure checker for the adapter's *specific* flat protocol layout.
# This is not a generic NativeBoundary restriction or an evidence constructor.
def order_errors(graph,execution):
 errors=[];regions={r.id:r for r in graph.regions};defs={v.id:v for v in graph.values};ops={o.id:o for o in graph.operations}
 visits={v.id:v for v in execution.visits};actuals={(v.origin,v.value):v for v in execution.values};use_actual={(u.operation,u.use):u for u in execution.uses}
 occurrences={o.id:o for o in execution.operations}
 for boundary in graph.native_boundaries:
  sig=signature[boundary.signature.locator.rsplit('/',1)[1]]
  region=regions[boundary.region];entry=next(b for b in region.blocks if b.id==region.entry)
  invokes=[ops[o] for o in entry.operations if ops[o].terminator and ops[o].terminator.kind.value=='INVOKE']
  assert len(invokes)==1;invoke=invokes[0]
  assert len(entry.arguments)==len(sig['inputs'])+1
  for i,slot in enumerate(boundary.inputs):
   formal=entry.arguments[i];definition=defs[formal]
   if slot.port.value!=formal:errors.append({'kind':'native_input_core_ordinal','boundary':boundary.id.value,'position':i})
   assert type(definition.origin) is BlockArgument and definition.origin.block==entry.id and definition.origin.index==i
   use=invoke.uses[i]
   if invoke.invoke_arguments[i]!=use.id or use.value!=formal:errors.append({'kind':'native_input_invoke_ordinal','position':i})
   for denotation in execution.denotations:
    basis=denotation.basis
    if type(basis) is not NativeInputRef or basis.boundary!=boundary.id or basis.position!=i:continue
    matched=[o for o in execution.operations if o.visit==basis.entry and o.operation==invoke.id]
    assert len(matched)==1
    actual=actuals[basis.entry,formal];used=use_actual[matched[0].id,use.id]
    if used.value!=actual.id or denotation.value!=actual.id:errors.append({'kind':'native_input_actual_use_ordinal','position':i,'value':denotation.value.value})
  normal=next(edge for edge in invoke.terminator.successors if edge.kind is ExitKind.NORMAL)
  block=next(b for b in region.blocks if b.id==normal.block);returned=ops[block.operations[-1]]
  assert len(block.arguments)==len(sig['outputs'])+1
  for i,slot in enumerate(boundary.outputs):
   if slot.port.exit_name!=returned.terminator.exit or slot.port.index!=i:errors.append({'kind':'native_output_exit_ordinal','position':i})
   if type(normal.arguments[i]) is not CompletionResult or normal.arguments[i].index!=i:errors.append({'kind':'native_output_completion_ordinal','position':i})
   definition=defs[block.arguments[i]];assert type(definition.origin) is BlockArgument and definition.origin.block==block.id and definition.origin.index==i
   if returned.terminator.values[i]!=returned.uses[i].id or returned.uses[i].value!=block.arguments[i]:errors.append({'kind':'native_output_return_use_ordinal','position':i})
 return errors
assert not order_errors(program,model)
# Mechanically choose a real interface with two same-typed Tensor reference
# inputs. No operator/function name or sequence number selects the candidate.
definitions={v.id:v for v in program.values}
boundary=next(b for b in program.native_boundaries if len(b.inputs)>=2 and all(type(definitions[s.port.value]) is ReferenceValue for s in b.inputs[:2]))
slots=list(boundary.inputs);slots[0]=replace(slots[0],port=boundary.inputs[1].port);slots[1]=replace(slots[1],port=boundary.inputs[0].port)
wrong_boundary=replace(boundary,inputs=tuple(slots))
wrong_program=replace(program,native_boundaries=tuple(wrong_boundary if b.id==boundary.id else b for b in program.native_boundaries))
# Make the *wrong* declarations mutually consistent with the observed dynamic
# native-port lookup. Actual canonical Uses/formals are unchanged and legal.
wrong_denotations=[]
for d in model.denotations:
 b=d.basis
 if type(b) is NativeInputRef and b.boundary==boundary.id and b.position in (0,1):
  new_formal=wrong_boundary.inputs[b.position].port.value
  value=next(v for v in model.values if v.origin==b.entry and v.value==new_formal)
  d=replace(d,value=value.id)
 wrong_denotations.append(d)
wrong_model=replace(model,snapshot=snapshot_for(wrong_program,'memory:static-native-order-counterexample'),denotations=tuple(wrong_denotations))
require_valid(wrong_program)
generic=validate(wrong_model,wrong_program,**kwargs)
assert generic.valid,generic.issues
errors=order_errors(wrong_program,wrong_model);assert errors
# Re-sealed program/model hashes are real canonical hashes, not old-proof scope
# mismatch. No NativePortEvidence/_OwnedNativeCapture is created or restored.
g= dump_program(wrong_program).encode();e=dump_execution(wrong_model).encode()
result={'status':'STATIC_COUNTEREXAMPLE_CONFIRMED','kind':'saved-declaration-only; not a runtime gate',
 'inputs':{n:{'sha256':sha256(b).hexdigest(),'bytes':len(b)} for n,b in raw.items()},
 'actual_saved_builder_order_errors':0,'counterexample_core_public_validation_valid':True,
 'counterexample_generic_execution_issues':len(generic.issues),'counterexample_generic_execution_gaps':len(generic.gaps),
 'counterexample_program_sha256':sha256(g).hexdigest(),'counterexample_execution_sha256':sha256(e).hexdigest(),
 'counterexample_snapshot_is_its_own_program':wrong_model.snapshot.artifact.sha256==sha256(g).hexdigest(),
 'changed_boundary':boundary.id.value,'changed_positions':[0,1],
 'proposed_independent_order_errors':errors,'owned_evidence_created':False,'raw_sources_read':0,
 'target_executions':0,'prepare_calls':0,'compiler_witness_calls':0,'production_files_modified':False}
(OUT/'review.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
print(json.dumps({k:result[k] for k in ('status','actual_saved_builder_order_errors','counterexample_core_public_validation_valid','counterexample_generic_execution_issues','counterexample_snapshot_is_its_own_program','owned_evidence_created','raw_sources_read')}));print('proposed_errors',len(errors))
