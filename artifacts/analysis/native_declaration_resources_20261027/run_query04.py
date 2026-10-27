import hashlib,json,pathlib,time,traceback
from scar.analysis.native_declaration_resources import NativeDeclarationResourceSession,NativeResourceBudget
from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import encode,decode,loads
B=pathlib.Path(__file__).resolve().parent;M=pathlib.Path('/home/zyf/AAA/scar-worktrees/structured-program-model');start=time.monotonic()
def artifact(p,schema):
 raw=p.read_bytes();return ProviderArtifact(str(p),hashlib.sha256(raw).hexdigest(),len(raw),schema)
try:
 index=decode(ProviderArtifact,json.loads((B/'RESOURCE_INDEX.json').read_text()))
 work=artifact(B/'work-attempt02/manifest.json','scar.native-activity-work-report')
 coords=artifact(M/'artifacts/experiments/native_inputs_full_20261026/native-import/capture-coordinates.json','scar.capture-coordinates')
 with NativeDeclarationResourceSession(index,work,coords,budget=NativeResourceBudget(max_input_bytes=512_000_000,max_seconds=180))as session:
  checked=[];selected=None
  hint=loads((B/'SELECTION_HINT.json').read_text())
  source_shard=pathlib.Path(hint['fragment']['uri']).parent.parent/'manifest.json'
  for p in (source_shard,):
   s=artifact(p,'scar.native-declaration-shard');selected=session.candidate(s);checked.append(encode(s))
   if selected:break
  assert selected is not None,'no GPU provider work host in closed source shards'
  result=session.query(selected[0],source_instances=(selected[1],));assert result['connections']
  raw=(json.dumps(encode(result),indent=2)+'\n').encode();(B/'CONNECTIONS04.json').write_bytes(raw)
  summary={'actual_status':'NORMAL_SAME_RUN_QUERY_RETURNED','elapsed_s':time.monotonic()-start,'index':encode(index),'work_manifest':encode(work),'coordinates':encode(coords),'candidate_closed_shards':checked,'native_fragment':encode(selected[0]),'selected_native_instance':encode(selected[1]),'connections':len(result['connections']),'resource_references':sum(len(c.resources)for c in result['connections']),'query_measurements':result['measurements'],'work_denominator':result['declared_work_count'],'connection_bytes':len(raw),'connection_sha256':hashlib.sha256(raw).hexdigest(),'whole_model_established':False}
 (B/'CONNECTION_RESULT04.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary),flush=True)
except BaseException as e:
 (B/'CONNECTION_FAILURE04.json').write_text(json.dumps({'error_type':type(e).__name__,'error':str(e),'traceback':traceback.format_exc(),'elapsed_s':time.monotonic()-start},indent=2)+'\n');raise
