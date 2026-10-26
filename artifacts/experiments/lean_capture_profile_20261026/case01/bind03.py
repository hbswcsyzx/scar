"""Normal readers and the same owned source-port producer, no raw owner restore."""
from pathlib import Path
from collections import Counter
import hashlib,json,time,traceback
from scar.analysis.call_operand_reader import read_call_operands
from scar.analysis.program_inventory import inventory_program
from scar.analysis.call_operands import link_call_operands
from scar.ir.program.functions import BodyLoweringProfile
from scar.ir.program.providers import ProviderArtifact,ProviderFactReference
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.program.python_call_targets import PythonSourcePortBudget,PythonSourcePortModel
from scar.ir.record_codec import encode
ROOT=Path(__file__).resolve().parent
started=time.monotonic();results={}
def save(p,value):p.write_text(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'))+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
try:
    for mode in ('lean03',):
        out=ROOT/mode
        # This read explicitly qualifies scope/typed gaps. The live linker below
        # makes its own normal owned read; no accepted JSON restores its owner.
        trace=read_call_operands(out,ROOT/'project')
        inventory=inventory_program(ROOT/'project/sample.py',project_root=ROOT/'project',calls_trace=out,
            body_profile=BodyLoweringProfile.STRUCTURED_ENV)
        ipath=ROOT/(mode+'-inventory.json');save(ipath,inventory.to_dict())
        artifact=ProviderArtifact(str(ipath),sha(ipath),ipath.stat().st_size,'scar.program-inventory')
        catalog=ROOT/(mode+'-catalog.json');save(catalog,{'schema':'scar.python-call-source-catalog','schema_version':1,'inventory':encode(artifact)})
        declaration=ProviderFactReference(ProviderArtifact(str(catalog),sha(catalog),catalog.stat().st_size,'scar.python-call-source-catalog/1'),'#/inventory')
        locator=SourceArtifactLocator(artifact,artifact.sha256,artifact.size_bytes,'canonical-json',declaration=declaration)
        captured={}
        def consume(model,check):
            for binding in model.bindings:check(binding)
            captured['model']=model
            model_path=ROOT/(mode+'-ports.json');save(model_path,model.to_dict())
            assert PythonSourcePortModel.loads(model_path.read_text())==model
        report=link_call_operands(out,ROOT/'project',inventory,python_source_port_consumer=consume,
            python_source_port_budget=PythonSourcePortBudget(),python_source_inventory_artifact=locator)
        model=captured['model'];codes={c.code.key:c.code.qualname for c in trace.frame_scan.captures}
        planned=set(b.code.key for b in __import__('scar.trace.lean_capture',fromlist=['LeanCapturePlan']).LeanCapturePlan.from_dict(
            json.loads(next((ROOT/'lean03').glob('lean-plan.*.json')).read_text())).bodies)
        attempts={a.index:a for a in trace.attempts}
        normalized=[]
        for binding in model.bindings:
            attempt=attempts[binding.attempt.index]
            if attempt.site.code not in planned:continue
            normalized.append({'caller':codes[attempt.site.code],'call_offset':attempt.site.offset,
                'callee':codes[binding.target.code],
                'arguments':[{'index':a.index,'formal_name':a.formal_name} for a in binding.arguments],
                'receiver':None if binding.receiver is None else binding.receiver.observed.role.value})
        dispatch_meta=json.loads(next(out.glob('dispatch-meta.*.json')).read_text())
        files=[p for p in out.iterdir() if p.is_file()]
        results[mode]={'source_ports':model.summary(),'planned_port_correspondences':normalized,
            'operand_events':len(trace.events),'instructions':len(trace.instructions),'attempts':len(trace.attempts),
            'gaps':[{'kind':g.kind.value,'reason':g.reason,'owner':g.invocation_id,'code':getattr(g,'code',None)} for g in trace.gaps],
            'collector_metadata':[{'rule':m.rule,'errors':m.errors,'dropped':m.dropped_events} for m in trace.metadata],
            'frame_events':len(trace.entries)+len(trace.exits),'frame_metadata':list(trace.frame_scan.metadata),
            'legacy_reference_routes':report.routing.summary(),'dispatch_metadata':dispatch_meta,
            'capture_stored_bytes':sum(p.stat().st_size for p in files),
            'files':[{'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)} for p in files]}
    legacy=json.loads((ROOT/'RESULT02.json').read_text())['results']['legacy']
    assert results['lean03']['planned_port_correspondences']==legacy['planned_port_correspondences']
    assert results['lean03']['instructions']==0
    assert results['lean03']['source_ports']['receiver_ports']==1
    assert results['lean03']['source_ports']['effects_state_ready_established'] is False
    closed=json.loads((ROOT/'lean03/plan-cache-close.json').read_text())
    assert closed['memo_entries_after_collector_close']==0
    results['retained_legacy_comparison']=legacy
    save(ROOT/'RESULT03.json',{'status':'NORMAL_READERS_AND_OWNED_SOURCE_PORTS_RETURNED','elapsed_seconds':time.monotonic()-started,
        'results':results,'model_complete':False,'tensor_contents_or_ready_proved':False})
    print(json.dumps({'elapsed_seconds':time.monotonic()-started,'results':{k:{f:v[f] for f in ('source_ports','capture_stored_bytes','instructions','gaps','planned_port_correspondences')} for k,v in results.items()}},indent=2))
except BaseException as error:
    save(ROOT/'FAILURE03.json',{'type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc(),'elapsed_seconds':time.monotonic()-started})
    raise
