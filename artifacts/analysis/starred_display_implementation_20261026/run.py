"""One original starred-display frontier through automatic V10."""
from pathlib import Path
from hashlib import sha256
import importlib.util,json,time,traceback
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];started=time.monotonic()
spec=importlib.util.spec_from_file_location('ordinary_inputs',Path('/home/zyf/AAA/scar-worktrees/source-try-model/artifacts/experiments/function_try_source_entries_20261026/common.py'))
common=importlib.util.module_from_spec(spec);spec.loader.exec_module(common)
pins={str(p.relative_to(ROOT)):sha256(p.read_bytes()).hexdigest()for p in sorted((ROOT/'scar').rglob('*.py'))}
config=json.loads(Path('/home/zyf/AAA/scar-worktrees/source209-model/artifacts/experiments/source209_resume01_20261026/inputs.json').read_bytes())
selection=json.loads((HERE/'READ_PLAN.json').read_bytes())['selected']
record={'status':'FAILED_RETAINED','failure':None,'raw':0,'compile':0,'target':0,'publication':0,'currentRun_binding':0}
try:
 owner,archives,catalog,metadata=common.normal_inputs(config,None)
 from scar.analysis.source_frontend_worklist import SourceFrontendBudget,plan_source_entries,run_source_entries,LATEST_SOURCE_ENTRY_PROFILE
 budget=SourceFrontendBudget(max_catalog_files=256,max_catalog_bodies=8192,max_catalog_groups=8192,max_dispatch_bodies=1,max_source_files=1,max_source_bytes=1_000_000,max_operations_per_body=10000,max_total_operations=10000,max_record_bytes=128_000_000,max_output_bytes=256_000_000,max_elapsed_seconds=900)
 plan=plan_source_entries(catalog,budget=budget,eligible_entry_keys=tuple(r['entry_key']for r in selection),source_entry_profile=LATEST_SOURCE_ENTRY_PROFILE,dispatch_order='FILE_GROUPED_V1',out_dir=HERE/'plan')
 returned=run_source_entries(plan,HERE/'worker',budget=budget,progress=lambda r:print(json.dumps(r),flush=True))
 common.save(HERE/'public-return.json',{'document':returned.document,'digest':returned.digest})
 rows=[json.loads(p.read_bytes())for p in sorted((HERE/'worker').glob('attempt-*/result.json'))]
 record.update(status='REAL_EXISTING_CAPABILITY_ATTEMPT_WITH_OPEN',entries=rows,counts=returned.document['counts'],readonly_counts=[s.counts for s in archives._stores.values()])
except BaseException as error:record['failure']={'type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc()}
finally:
 record.update(elapsed_seconds=time.monotonic()-started,source_sha256=pins,source_unchanged=all(sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in pins.items()))
 common.save(HERE/'receipt.json',record)
 print(json.dumps({k:v for k,v in record.items()if k not in('entries','source_sha256')},sort_keys=True),flush=True)
raise SystemExit(int(record['status']=='FAILED_RETAINED' or any(r['status']=='FAILED'for r in record.get('entries',()))))
