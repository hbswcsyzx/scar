import hashlib,json,pathlib,threading,time,traceback
from scar.analysis.native_declaration_resources import (build_native_resource_index,NativeDeclarationResourceSession,NativeResourceBudget)
from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import encode
B=pathlib.Path(__file__).resolve().parent;M=pathlib.Path('/home/zyf/AAA/scar-worktrees/structured-program-model')
def artifact(p,schema):
 raw=p.read_bytes();return ProviderArtifact(str(p),hashlib.sha256(raw).hexdigest(),len(raw),schema)
stop=threading.Event();start=time.monotonic()
def beat():
 while not stop.wait(20):print(json.dumps({'phase':'INDEX_OR_QUERY_LIVE','elapsed_s':time.monotonic()-start}),flush=True)
threading.Thread(target=beat,daemon=True).start()
try:
 bundle=artifact(M/'artifacts/experiments/native_inputs_full_20261026/native-import/native/bundle-partitions/manifest.json','scar.partitioned-ir-bundle')
 index=build_native_resource_index(bundle,B/'resource-index',budget=NativeResourceBudget(max_input_bytes=1_600_000_000,max_seconds=240))
 (B/'RESOURCE_INDEX.json').write_text(json.dumps(encode(index),indent=2)+'\n')
 print(json.dumps({'phase':'INDEX_CLOSED','artifact':encode(index)}),flush=True)
 work=artifact(B/'work-attempt02/manifest.json','scar.native-activity-work-report')
 coords=artifact(M/'artifacts/experiments/native_inputs_full_20261026/native-import/capture-coordinates.json','scar.capture-coordinates')
 shard=artifact(M/'artifacts/analysis/native_declaration_pipeline_20261027/attempt01/shards/000000/manifest.json','scar.native-declaration-shard')
 with NativeDeclarationResourceSession(index,work,coords,budget=NativeResourceBudget(max_input_bytes=512_000_000,max_seconds=180)) as session:
  selected=session.candidate(shard);assert selected is not None,'no same-source provider-work native host in this shard'
  result=session.query(selected[0],source_instances=(selected[1],))
  assert result['connections'],'selected native host has no checked work path'
  payload=json.dumps(encode(result),indent=2)+'\n';(B/'CONNECTIONS.json').write_text(payload)
  summary={'status':'EXACT_SAME_RUN_PROVIDER_PATH','elapsed_s':time.monotonic()-start,'index':encode(index),'work_manifest':encode(work),'coordinates':encode(coords),'native_fragment':encode(selected[0]),'selected_native_instance':encode(selected[1]),'connections':len(result['connections']),'resource_references':sum(len(c.resources)for c in result['connections']),'query_measurements':result['measurements'],'work_denominator':result['declared_work_count'],'connection_bytes':len(payload.encode()),'connection_sha256':hashlib.sha256(payload.encode()).hexdigest(),'whole_model_established':False}
 (B/'CONNECTION_RESULT.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary),flush=True)
except BaseException as e:
 (B/'CONNECTION_FAILURE.json').write_text(json.dumps({'error_type':type(e).__name__,'error':str(e),'traceback':traceback.format_exc(),'elapsed_s':time.monotonic()-start},indent=2)+'\n');raise
finally:stop.set()
