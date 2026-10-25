"""One actual CPU capture only; root reviews before invocation."""
from pathlib import Path
from hashlib import sha256
import json,os,subprocess,sys,time
B=Path(__file__).resolve().parents[3];O=Path(__file__).resolve().parent
assert not (O/'capture').exists() and not (O/'time.txt').exists()
freeze=json.loads((O/'freeze.json').read_text())
for item in freeze['sources']+freeze['runner']:
 raw=(B/item['path']).read_bytes()
 assert len(raw)==item['bytes'] and sha256(raw).hexdigest()==item['sha256'],item['path']
from scar.trace.collector_execution_witness import read_collector_execution_witness,bind_collector_execution_witness
from scar.trace.capture_coordinates import bind_capture_coordinates
from scar.ir.record_codec import encode
env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(B),CUDA_VISIBLE_DEVICES='',
 SCAR_COLLECTOR_EXECUTION_WITNESS='1',SCAR_COLLECTOR_PROBE_OUT=str(O/'observed-registration.json'),SCAR_TRACE_DEBUG='1')
cmd=[sys.executable,'-B','-m','scar.cli','trace','--call-operands','--execution-evidence','--os-capture-root',str(O/'capture'),
 '--out',str(O/'capture/trace'),'--project-root',str(O/'target'),'--max-os-bytes','128000000','--os-timeout','120',
 '--',sys.executable,'-B',str(O/'target/probe.py')]
start=time.monotonic()
with (O/'stdout.txt').open('x') as out,(O/'stderr.txt').open('x') as err:
 p=subprocess.run(cmd,cwd=B,env=env,stdout=out,stderr=err,timeout=180)
(O/'launch.json').write_text(json.dumps({'command':cmd,'actual_exit':p.returncode,'wall_seconds':time.monotonic()-start}))
assert p.returncode==0,p.returncode
witnesses=list((O/'capture/trace').glob('collector-witness.*/manifest.json'));assert len(witnesses)==1
path=witnesses[0];raw=path.read_bytes();digest=sha256(raw).hexdigest()
doc=read_collector_execution_witness(path,expected_sha256=digest)
observed=json.loads((O/'observed-registration.json').read_text());assert observed['issuer']==doc['issuer'] and observed['process_id']==doc['registration_scope']['process_id']
coordinates=bind_capture_coordinates(O/'capture',max_bytes=300000000,max_lines=500000)
binding=bind_collector_execution_witness(path,expected_sha256=digest,coordinates=coordinates)
# Re-sealed same-directory candidate: reject issuer change, not old SHA mismatch.
bad=json.loads(raw);bad['issuer']['generation']=2
badpath=path.parent/'rejected-generation-candidate.json';candidate=json.dumps(bad,sort_keys=True).encode()
with badpath.open('xb') as f:f.write(candidate)
try:read_collector_execution_witness(badpath,expected_sha256=sha256(candidate).hexdigest())
except ValueError as error:rejection=str(error)
else:raise AssertionError('re-sealed changed issuer was accepted')
result={'status':'CPU_ACTUAL_SHARED_REGISTRATION_CLOSED_AND_BOUND','actual_exit':0,'witness':{'uri':str(path),'sha256':digest,'size_bytes':len(raw)},
 'roles':observed['roles'],'binding':encode(binding),'changed_issuer_rejected':rejection,'candidate_resealed':True,
 'whole_model':'OPEN','continuous_mutation_exclusion_established':False,'target_CPU_capture_runs':1,'LeWM_runs':0,'GPU_runs':0}
for item in freeze['sources']+freeze['runner']:
 raw=(B/item['path']).read_bytes()
 assert len(raw)==item['bytes'] and sha256(raw).hexdigest()==item['sha256'],item['path']
with (O/'result.json').open('x') as f:json.dump(result,f,indent=2,sort_keys=True);f.write('\n')
print(json.dumps(result),flush=True)
