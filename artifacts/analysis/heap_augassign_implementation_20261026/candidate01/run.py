"""One retained heap AugAssign through normal automatic V11 worker/readers."""
from pathlib import Path
from hashlib import sha256
import importlib.util,json,time,traceback,threading,resource
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];started=time.monotonic();stop=threading.Event()
spec=importlib.util.spec_from_file_location('ordinary_inputs',Path('/home/zyf/AAA/scar-worktrees/source-try-model/artifacts/experiments/function_try_source_entries_20261026/common.py'))
common=importlib.util.module_from_spec(spec);spec.loader.exec_module(common)
pins={str(p.relative_to(ROOT)):sha256(p.read_bytes()).hexdigest()for p in sorted((ROOT/'scar').rglob('*.py'))}
config=json.loads(Path('/home/zyf/AAA/scar-worktrees/source209-model/artifacts/experiments/source209_resume01_20261026/inputs.json').read_bytes())
selection=json.loads((HERE/'READ_PLAN.json').read_bytes())['selected']
record={'status':'FAILED_RETAINED','failure':None,'raw':0,'executable_compile':0,'target':0,'publication':0,'currentRun_binding':0}
phase='NORMAL_INPUTS'
def heartbeat():
 while not stop.wait(20):print(json.dumps({'heartbeat':phase,'elapsed_seconds':time.monotonic()-started}),flush=True)
threading.Thread(target=heartbeat,daemon=True).start()
try:
 owner,archives,catalog,metadata=common.normal_inputs(config,None)
 from scar.analysis.source_frontend_worklist import SourceFrontendBudget,plan_source_entries,run_source_entries,LATEST_SOURCE_ENTRY_PROFILE
 budget=SourceFrontendBudget(max_catalog_files=256,max_catalog_bodies=8192,max_catalog_groups=8192,max_dispatch_bodies=1,max_source_files=1,max_source_bytes=1_000_000,max_operations_per_body=4000,max_total_operations=4000,max_record_bytes=128_000_000,max_output_bytes=256_000_000,max_elapsed_seconds=600)
 phase='NORMAL_PLAN'
 plan=plan_source_entries(catalog,budget=budget,eligible_entry_keys=tuple(r['entry_key']for r in selection),source_entry_profile=LATEST_SOURCE_ENTRY_PROFILE,dispatch_order='FILE_GROUPED_V1',out_dir=HERE/'plan')
 phase='ONE_REAL_BODY_AND_NORMAL_READERS'
 returned=run_source_entries(plan,HERE/'worker',budget=budget,progress=lambda r:print(json.dumps(r),flush=True))
 common.save(HERE/'public-return.json',{'document':returned.document,'digest':returned.digest})
 rows=[json.loads(p.read_bytes())for p in sorted((HERE/'worker').glob('attempt-*/result.json'))]
 record.update(status='ONE_REAL_HEAP_AUGASSIGN_ATTEMPT_WITH_OPEN',entries=rows,counts=returned.document['counts'],readonly_counts=[s.counts for s in archives._stores.values()])
except BaseException as error:record['failure']={'type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc()}
finally:
 stop.set()
 record.update(elapsed_seconds=time.monotonic()-started,max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,source_sha256=pins,source_unchanged=all(sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in pins.items()))
 common.save(HERE/'receipt.json',record)
 print(json.dumps({k:v for k,v in record.items()if k not in('entries','source_sha256')},sort_keys=True),flush=True)
raise SystemExit(int(record['status']=='FAILED_RETAINED' or any(r['status']=='FAILED'for r in record.get('entries',()))))
