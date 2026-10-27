"""One ordinary source-only model-run over the original closed CPU capture."""
import hashlib,json,os,resource,sys,time,traceback
from pathlib import Path
from scar.analysis.model_run import run_model,ModelRunBudget
# Preload normal source producers before prohibiting original captured filenames.
import scar.analysis.call_seeds,scar.analysis.call_demand,scar.analysis.source_discovery
import scar.analysis.source_layers,scar.analysis.program_composition,scar.analysis.source_invocations
import scar.analysis.code_witness,scar.analysis.program_expansion,scar.trace.capture_coordinates

BASE=Path(__file__).resolve().parent
CAPTURE=Path('/home/zyf/AAA/scar-worktrees/program-ports-capture/artifacts/experiments/program_ports_cpu_20261027/capture')
META=CAPTURE/'trace/captured-source-meta.2026697.json'
metadata=json.loads(META.read_text())
originals={r['path']for r in metadata['files']if r['status']=='ARCHIVED_SOURCE_BYTES'}
observed={'blocked_live_opens':[],'target_exec':0,'compile_events':0,'source_compile_events':0,'capture':0}
def audit(event,args):
 if event=='open' and args and isinstance(args[0],(str,bytes,os.PathLike)):
  path=os.fsdecode(args[0])
  if path in originals:
   observed['blocked_live_opens'].append(path)
   raise AssertionError('live captured source open forbidden: '+path)
 if event=='compile':
  observed['compile_events']+=1
  if len(args)>1 and args[1] in originals:observed['source_compile_events']+=1
 if event=='exec' and args and getattr(args[0],'co_filename',None)in originals:
  observed['target_exec']+=1
  raise AssertionError('captured code execution forbidden')
sys.addaudithook(audit)
started=time.monotonic()
result={}
try:
 result=run_model(CAPTURE,BASE/'attempt01'/'model',source_only=True,
  budget=ModelRunBudget(max_calls=512,max_source_files=4,max_codes=128,max_bodies=4,
   max_compile_keys=4,max_seconds=180))
 if result['status']!='SOURCE_BOOTSTRAP_WITH_OPEN':raise AssertionError(result.get('failure',result['status']))
 assert observed['blocked_live_opens']==[] and observed['target_exec']==0
 assert result['source_input_scope']['namespace_policy']['basis']=='CURRENT_STATIC_NAMESPACE_INPUT'
 assert result['workload_witness_summary']['acquired_codes']
 result={'status':'PASS','model_run':result,'audit':observed}
except BaseException as error:
 result={'status':'FAILED','exception':type(error).__name__,'detail':str(error),
         'traceback':traceback.format_exc(),'audit':observed,'model_run':result}
finally:
 result.update(wall_seconds=time.monotonic()-started,max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
               capture=str(CAPTURE),captured_source_meta_sha256=hashlib.sha256(META.read_bytes()).hexdigest(),
               guarded_original_files=sorted(originals),scope='ordinary automatic source bootstrap only; no native import, no new capture or target')
 (BASE/'attempt01'/'RESULT.json').write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
 print(json.dumps({'status':result['status'],'wall_seconds':result['wall_seconds'],
                   'detail':result.get('detail'),'audit':observed},ensure_ascii=False))
 if result['status']!='PASS':sys.exit(1)
