"""The production pure ABI checker on saved typed declarations; no raw authority."""
from dataclasses import replace
from pathlib import Path
from hashlib import sha256
import json
from scar.ir.program.codec import loads as load_program,dumps as dump_program
from scar.ir.program.validation import require_valid
from scar.ir.program.model import ReferenceValue
from scar.ir.execution.codec import loads as load_execution,dumps as dump_execution
from scar.ir.execution.snapshot import snapshot_for
from scar.ir.execution.validation import validate
from scar.ir.execution.content import NativeInputRef
from scar.ir.v2.codec import values_from_dict,evidence_from_dict
from scar.ir.execution.native_port_protocol import _require_native_port_order,_native_port_order_errors,NativePortOrderError


def make_order_candidate(program, model):
    """A hypothetical internally legal declaration, never an observed new run."""
    definitions={v.id:v for v in program.values}
    boundary=next(b for b in program.native_boundaries if len(b.inputs)>=2
        and all(type(definitions[s.port.value]) is ReferenceValue for s in b.inputs[:2]))
    slots=list(boundary.inputs)
    slots[0]=replace(slots[0],port=boundary.inputs[1].port)
    slots[1]=replace(slots[1],port=boundary.inputs[0].port)
    wrong_boundary=replace(boundary,inputs=tuple(slots))
    wrong_program=replace(program,native_boundaries=tuple(wrong_boundary if b.id==boundary.id else b for b in program.native_boundaries))
    denotations=[]
    for d in model.denotations:
        b=d.basis
        if type(b) is NativeInputRef and b.boundary==boundary.id and b.position in (0,1):
            formal=wrong_boundary.inputs[b.position].port.value
            actual=next(v for v in model.values if v.origin==b.entry and v.value==formal)
            d=replace(d,value=actual.id)
        denotations.append(d)
    wrong_model=replace(model,snapshot=snapshot_for(wrong_program,'memory:internally-valid-native-order-counterexample'),denotations=tuple(denotations))
    require_valid(wrong_program)
    return wrong_program,wrong_model


def main():
    base=Path(__file__).resolve().parents[3]
    source=base/'artifacts/experiments/first_stage_native_protocol_bridge_attempt02_20261023/result'
    out=Path(__file__).parent
    names=('program.json','execution.json','native-interface.json','source-values.json','source-evidence.json','report.json')
    raw={n:(source/n).read_bytes() for n in names}
    report=json.loads(raw['report.json'])
    for key,name in (('program','program.json'),('interface','native-interface.json'),('values_projection','source-values.json'),('evidence_projection','source-evidence.json')):
        a=report['artifacts'][key];assert a['sha256']==sha256(raw[name]).hexdigest() and a['size_bytes']==len(raw[name])
    program=load_program(raw['program.json'].decode());model=load_execution(raw['execution.json'].decode())
    sigs=json.loads(raw['native-interface.json'])['interfaces']
    # Declared saved-model coordinates suffice to test the *pure* order rule.
    # They do not recreate raw-observed interfaces or an owned session.
    interfaces=[{'signature_id':a.region.value.removeprefix('aten-interface:'),
        'sequence':int(a.id.value.rsplit(':',1)[1]),
        'signature':sigs[a.region.value.removeprefix('aten-interface:')]} for a in model.activations]
    run=model.runs[0].id.value
    _require_native_port_order(program,model,interfaces,run)
    wrong_program,wrong_model=make_order_candidate(program,model)
    values=values_from_dict(json.loads(raw['source-values.json']));evidence=evidence_from_dict(json.loads(raw['source-evidence.json']))
    generic=validate(wrong_model,wrong_program,
        value_graphs={report['artifacts']['values_projection']['sha256']:values},
        evidence_graphs={report['artifacts']['evidence_projection']['sha256']:evidence})
    assert generic.valid,generic.issues
    try:_require_native_port_order(wrong_program,wrong_model,interfaces,run)
    except NativePortOrderError as error:rejection=str(error)
    else:raise AssertionError('freshly sealed internally legal wrong layout accepted')
    result={'status':'PRODUCTION_PURE_PORT_ORDER_PREFLIGHT_PASS','input_files':{n:{'sha256':sha256(b).hexdigest(),'bytes':len(b)} for n,b in raw.items()},
        'native_port_protocol_sha256':sha256((base/'scar/ir/execution/native_port_protocol.py').read_bytes()).hexdigest(),
        'positive_actual_saved_program_order_errors':0,'positive_actual_activation_count':len(interfaces),
        'counterexample_core_valid':True,'counterexample_generic_execution_issue_count':len(generic.issues),
        'counterexample_new_program_sha256':wrong_model.snapshot.artifact.sha256,
        'counterexample_new_execution_sha256':sha256(dump_execution(wrong_model).encode()).hexdigest(),
        'counterexample_snapshot_matches_own_program':wrong_model.snapshot.artifact.sha256==sha256(dump_program(wrong_program).encode()).hexdigest(),
        'order_rejection':rejection,'order_errors':_native_port_order_errors(wrong_program,wrong_model,interfaces,run),
        'owned_evidence_created_or_restored':False,'raw_sources_read':0,'target_executions':0,'prepare_calls':0,'compiler_witness_calls':0}
    (out/'order-preflight.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    print(json.dumps({'status':result['status'],'positive_activations':len(interfaces),'counterexample_generic_issues':len(generic.issues),'production_order_error_count':len(result['order_errors'])}))


if __name__=='__main__':main()
