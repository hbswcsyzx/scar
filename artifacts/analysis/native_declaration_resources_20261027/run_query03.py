import hashlib,json,pathlib,time,traceback,sqlite3
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
 # Discovery is a locator hint only; no qualification or owner is recovered.
 indexdoc=loads(pathlib.Path(index.uri).read_text());dbref=decode(ProviderArtifact,indexdoc['database'])
 raw=pathlib.Path(dbref.uri).read_bytes();assert len(raw)==dbref.size_bytes and hashlib.sha256(raw).hexdigest()==dbref.sha256
 db=sqlite3.connect(pathlib.Path(dbref.uri).as_uri()+'?mode=ro&immutable=1',uri=True);hint=None;discovery_bytes=index.size_bytes+dbref.size_bytes
 for p in sorted((M/'artifacts/experiments/native_declaration_full_20261027/attempt01/shards').glob('*/manifest.json')):
  d=loads(p.read_text());discovery_bytes+=p.stat().st_size
  for a in d['fragments']:
   f=decode(ProviderArtifact,a);raw=pathlib.Path(f.uri).read_bytes();discovery_bytes+=len(raw)
   assert len(raw)==f.size_bytes and hashlib.sha256(raw).hexdigest()==f.sha256
   document=loads(raw.decode())
   for n in document['occurrences']:
    identity=n['native']['instance'];entry=db.execute("SELECT ordinal FROM edges WHERE source=? AND relation='provider_scope_association' ORDER BY ordinal LIMIT 1",(identity['wire'],)).fetchone()
    if entry:hint={'fragment':a,'instance':identity,'edge_ordinal_hint':entry[0]};break
   if hint:break
  if hint:break
 db.close();assert hint
 hint.update({'qualification':'UNQUALIFIED_MECHANICAL_SELECTOR_ONLY','discovery_stored_bytes':discovery_bytes,'discovery_decoded_json_bytes':discovery_bytes-dbref.size_bytes,'discovery_limit_bytes':512000000})
 assert hint['discovery_stored_bytes']+hint['discovery_decoded_json_bytes']<=hint['discovery_limit_bytes']
 (B/'SELECTION_HINT.json').write_text(json.dumps(hint,indent=2)+'\n')
 with NativeDeclarationResourceSession(index,work,coords,budget=NativeResourceBudget(max_input_bytes=512_000_000,max_seconds=180))as session:
  f=decode(ProviderArtifact,hint['fragment']);from scar.ir.v2.ids import OperationInstanceID
  selected=decode(OperationInstanceID,hint['instance']);result=session.query(f,source_instances=(selected,));assert result['connections']
  raw=(json.dumps(encode(result),indent=2)+'\n').encode();(B/'CONNECTIONS03.json').write_bytes(raw)
  summary={'actual_status':'NORMAL_SAME_RUN_QUERY_RETURNED','elapsed_s':time.monotonic()-start,'index':encode(index),'work_manifest':encode(work),'coordinates':encode(coords),'native_fragment':encode(f),'selected_native_instance':encode(selected),'connections':len(result['connections']),'resource_references':sum(len(c.resources)for c in result['connections']),'query_measurements':result['measurements'],'discovery_measurements':hint,'work_denominator':result['declared_work_count'],'connection_bytes':len(raw),'connection_sha256':hashlib.sha256(raw).hexdigest(),'whole_model_established':False}
 (B/'CONNECTION_RESULT03.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary),flush=True)
except BaseException as e:
 (B/'CONNECTION_FAILURE03.json').write_text(json.dumps({'error_type':type(e).__name__,'error':str(e),'traceback':traceback.format_exc(),'elapsed_s':time.monotonic()-start},indent=2)+'\n');raise
