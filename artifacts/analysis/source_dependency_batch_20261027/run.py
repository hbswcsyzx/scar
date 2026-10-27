"""One retained two-call/three-body dependency query; no producer replay."""
from collections import Counter
import gzip,hashlib,json,os,resource,sys,time,traceback
from pathlib import Path
from scar.analysis.source_dependency_batch import SourceDependencyBatchSession
BASE=Path(__file__).resolve().parent
MODEL=Path('/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/analysis/source_call_bridge_20261027/attempt03/source_ports.json')
EXPECTED='4a78314ff0c840f37a694150d44fc4f7adfd798d19d3206c5a09f2fc792afde0'
SOURCE=[Path('scar/analysis/source_dependencies.py'),Path('scar/analysis/source_dependency_batch.py')]
receipts=[{'uri':str(p.absolute()),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size}for p in SOURCE]
observed={'forbidden_raw_or_live_source_opens':[],'target_exec':0,'capture':0}
def audit(event,args):
 if event=='open' and args and isinstance(args[0],(str,bytes,os.PathLike)):
  p=os.fsdecode(args[0]);name=Path(p).name
  if p.startswith('/home/zyf/AAA/le-wm/') or name.startswith(('call-edges.','call-operands.','python-call-targets.','syscalls.')):
   observed['forbidden_raw_or_live_source_opens'].append(p)
   raise AssertionError('raw/live source replay forbidden: '+p)
 if event=='exec'and args and getattr(args[0],'co_filename','').startswith('/home/zyf/AAA/le-wm/'):
  observed['target_exec']+=1
  raise AssertionError('target code execution forbidden')
sys.addaudithook(audit)
start=time.perf_counter();result={}
try:
 session=SourceDependencyBatchSession(MODEL,expected_sha256=EXPECTED)
 view=session.query_bindings(max_bindings=2,max_queries=7,max_nodes=128,max_depth=32,max_routes=512)
 assert len(view['binding_indices'])==2 and len(view['queries'])==7
 allroutes=[route for row in view['queries']for route in row['view'].get('routes',())]
 assert any(row['kind']=='COMPLETION_INPUT_DEPENDENCY'for row in allroutes)
 assert any(row['kind']=='BOUND_CALLABLE_RECEIVER_PROJECTION'for row in allroutes)
 assert any(row['kind']=='ACTUAL_TO_FORMAL'for row in allroutes)
 assert any(row['kind']=='ORIGINAL_USE_CONSUMER'for row in allroutes)
 assert all(row.get('is_reference_alias')is False for row in allroutes if row['kind']in(
  'OPERATION_INPUT_DEPENDENCY','COMPLETION_INPUT_DEPENDENCY','OPERATION_OUTPUT_DEPENDENCY','COMPLETION_OUTPUT_DEPENDENCY'))
 assert observed['forbidden_raw_or_live_source_opens']==[] and observed['target_exec']==0
 assert session._counts['body_codec_reads']==3
 payload=json.dumps(view,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
 assert len(payload)<=32000000
 output=BASE/'attempt01/VIEW.json.gz'
 with output.open('xb')as raw:
  with gzip.GzipFile(filename='',fileobj=raw,mode='wb',mtime=0)as dst:dst.write(payload)
 result={'status':'PASS','model':str(MODEL),'model_sha256':EXPECTED,'queries':[
  {'kind':row['kind'],'binding_index':row['binding_index'],'actual_index':row.get('actual_index'),
   'nodes':len(row['view'].get('nodes',())),'routes':len(row['view'].get('routes',())),
   'route_kinds':dict(Counter(r['kind']for r in row['view'].get('routes',()))),
   'frontiers':dict(Counter(r['reason']for r in row['view'].get('frontiers',()))),
   'truncated':row['view'].get('truncated',False),'limits':row['view'].get('limits_reached',[])}for row in view['queries']],
  'costs':view['costs'],'truncated':view['truncated'],'output':{'uri':str(output),'stored_bytes':output.stat().st_size,
   'stored_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'decoded_bytes':len(payload),'decoded_sha256':hashlib.sha256(payload).hexdigest()}}
except BaseException as error:
 result={'status':'FAILED','type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc()}
finally:
 result.update(sources=receipts,wall_seconds=time.perf_counter()-start,max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,audit=observed)
 for receipt in receipts:
  assert hashlib.sha256(Path(receipt['uri']).read_bytes()).hexdigest()==receipt['sha256']
 (BASE/'attempt01/RESULT.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
 print(json.dumps(result,sort_keys=True,indent=2))
 if result['status']!='PASS':sys.exit(1)
