"""Normal tiny retained capture/source graph check; no LeWM/target replay."""
from pathlib import Path
import hashlib,json,time
from scar.analysis.call_operand_reader import read_call_operands
from scar.analysis.call_edges import _link_call_model
from scar.analysis.program_inventory import inventory_program
from scar.analysis.python_call_targets import read_python_call_targets,build_python_source_ports,PythonSourcePortModel
from scar.ir.program.functions import BodyLoweringProfile
from scar.ir.program.compilation import CallCompilationProfile
from scar.ir.program.providers import ProviderArtifact,ProviderFactReference
from scar.ir.record_codec import encode
from scar.ir.program.source_references import SourceArtifactLocator

OUT=Path(__file__).resolve().parent
HERE=OUT.parent
started=time.monotonic()
scan=read_call_operands(HERE/'capture',HERE/'project')
observed=read_python_call_targets(scan)
inventory=inventory_program(HERE/'project/sample.py',project_root=HERE/'project',
    calls_trace=HERE/'capture',body_profile=BodyLoweringProfile.STRUCTURED_ENV)
payload=json.dumps(inventory.to_dict(),sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
path=OUT/'inventory.json';path.write_bytes(payload)
sha=hashlib.sha256(payload).hexdigest()
artifact=ProviderArtifact(str(path),sha,len(payload),'scar.program-inventory')
catalog_path=OUT/'source-catalog.json'
catalog_raw=json.dumps({'schema':'scar.python-call-source-catalog','schema_version':1,'inventory':encode(artifact)},sort_keys=True,separators=(',',':')).encode()
catalog_path.write_bytes(catalog_raw)
declaration=ProviderFactReference(ProviderArtifact(str(catalog_path),hashlib.sha256(catalog_raw).hexdigest(),len(catalog_raw),'scar.python-call-source-catalog/1'),'#/inventory')
locator=SourceArtifactLocator(artifact,sha,len(payload),'canonical-json',declaration=declaration)
call_model,sources=_link_call_model(HERE/'capture',HERE/'project',inventory,scan.frame_budget,
    compilation_profile=CallCompilationProfile.RECORDED_FUTURE_FLAGS,
    frame_scan=scan.frame_scan,entries=scan.entries,exits=scan.exits,include_identity_routes=False,allow_v6=True)
model=build_python_source_ports(observed=observed,trace=scan,call_model=call_model,
    inventory=inventory,sources=sources,inventory_artifact=locator)
payload=json.dumps(model.to_dict(),sort_keys=True,ensure_ascii=False,separators=(',',':'))
out=OUT/'model.json';out.write_text(payload)
assert PythonSourcePortModel.loads(payload)==model
assert observed.summary()['receiver_entries']==2
assert model.summary()['receiver_ports']==2,model.summary()
assert sum(t.scope.value=='OBSERVED_EXTERNAL_PYTHON' for t in observed.targets)==1
assert any(t.kind.value=='NATIVE_BUILTIN' for t in observed.targets)
assert any(b.receiver is None for b in model.bindings)
summary={'status':'ACTUAL_CAPTURE_AND_NORMAL_SOURCE_PORT_READBACK_WITH_OPEN','wall_seconds':time.monotonic()-started,
    'observed':observed.summary(),'source_ports':model.summary(),'legacy_handshakes':len(scan.handshakes),
    'code_links':{k:v.status.value for k,v in sources.links.items()},
    'source_issues':[{'attempt':i.attempt_index,'detail':i.detail} for i in model.issues],
    'inventory':{'path':str(path),'bytes':path.stat().st_size,'sha256':sha,'summary':inventory.summary()},
    'model':{'path':str(out),'bytes':out.stat().st_size,'sha256':hashlib.sha256(out.read_bytes()).hexdigest()},
    'dynamic_value_identity_or_contents_established':False,'whole_program_complete':False}
(OUT/'RESULT.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))
