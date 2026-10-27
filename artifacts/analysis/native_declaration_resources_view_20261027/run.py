import hashlib,json,pathlib,time,traceback
from scar.analysis.native_declaration_interfaces import NativeDeclarationBudget,read_native_declaration_fragment
from scar.analysis.native_declaration_resources import NativeDeclarationResourceSession,NativeResourceBudget
from scar.ir.record_codec import decode,encode,loads
from scar.ir.program.providers import ProviderArtifact
from scar.ir.v2.ids import OperationInstanceID
BASE=pathlib.Path(__file__).resolve().parent
OLD=BASE.parent/'native_declaration_resources_20261027'
start=time.monotonic()
try:
 source=pathlib.Path('scar/analysis/native_declaration_resources.py').resolve();before=source.read_bytes()
 receipt=loads((OLD/'CONNECTION_RESULT04.json').read_text())
 view=read_native_declaration_fragment(decode(ProviderArtifact,receipt['native_fragment']),budget=NativeDeclarationBudget(max_input_bytes=512_000_000,max_seconds=180))
 with NativeDeclarationResourceSession(decode(ProviderArtifact,receipt['index']),decode(ProviderArtifact,receipt['work_manifest']),decode(ProviderArtifact,receipt['coordinates']),budget=NativeResourceBudget(max_input_bytes=512_000_000,max_seconds=180)) as session:
  result=session.query_view(view,source_instances=(decode(OperationInstanceID,receipt['selected_native_instance']),))
  previous=loads((OLD/'CONNECTIONS04.json').read_text())
  assert encode(result['connections'])==previous['connections'],'original connection identities/source refs changed'
  assert len(result['connections'])==2 and len({c.submission.id for c in result['connections']})==1
  assert source.read_bytes()==before,'source changed during actual query'
  report={'actual_exit':0,'status':'LIVE_NORMAL_VIEW_REUSED','elapsed_s':time.monotonic()-start,
   'normal_reader_measurements':view.measurements,'resource_session_measurements':result['measurements'],
   'query_measurements':result['query_measurements'],'query_measurement_scope':result['query_measurement_scope'],
   'connection_count':len(result['connections']),'distinct_work_count':len({c.submission.id for c in result['connections']}),
   'source_refs_and_connections_equal_to_query04':True,'source':{'path':str(source),'bytes':len(before),'sha256':hashlib.sha256(before).hexdigest()},
   'inputs':{k:receipt[k]for k in ('index','work_manifest','coordinates','native_fragment','selected_native_instance')},
   'cache_entries':{str(k):len(v)for k,v in session.records.cache.items()},'whole_model_established':False}
 (BASE/'RESULT.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
except BaseException as e:
 (BASE/'FAILURE.json').write_text(json.dumps({'error_type':type(e).__name__,'error':str(e),'traceback':traceback.format_exc(),'elapsed_s':time.monotonic()-start},indent=2)+'\n');raise
