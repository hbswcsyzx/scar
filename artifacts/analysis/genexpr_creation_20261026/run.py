"""One real escaping generator reference, normal source worker, no target."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import time

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];start=time.monotonic()
spec=importlib.util.spec_from_file_location('ordinary_entry_inputs',ROOT/'artifacts/experiments/function_try_source_entries_20261026/common.py')
common=importlib.util.module_from_spec(spec);spec.loader.exec_module(common)
pins={str(p.relative_to(ROOT)):sha256(p.read_bytes()).hexdigest()for p in sorted((ROOT/'scar').rglob('*.py'))}
common.save(HERE/'inputs.json',{'source_sha256':pins,'selection':common.receipt(HERE/'selection.json')})
config=json.loads(Path('/home/zyf/AAA/scar-worktrees/source209-model/artifacts/experiments/source209_resume01_20261026/inputs.json').read_bytes())
owner,archives,catalog,metadata=common.normal_inputs(config,None)
chosen=json.loads((HERE/'selection.json').read_bytes())['selected']
from scar.analysis.source_frontend_worklist import SourceFrontendBudget,plan_source_entries,run_source_entries,LATEST_SOURCE_ENTRY_PROFILE
budget=SourceFrontendBudget(max_catalog_files=256,max_catalog_bodies=8192,max_catalog_groups=8192,
    max_dispatch_bodies=1,max_source_files=1,max_source_bytes=1_000_000,max_operations_per_body=6000,
    max_total_operations=6000,max_record_bytes=128_000_000,max_output_bytes=256_000_000,max_elapsed_seconds=300)
plan=plan_source_entries(catalog,budget=budget,eligible_entry_keys=(chosen['entry_key'],),
    source_entry_profile=LATEST_SOURCE_ENTRY_PROFILE,out_dir=HERE/'plan')
returned=run_source_entries(plan,HERE/'worker',budget=budget,progress=lambda r:print(json.dumps(r),flush=True))
common.save(HERE/'public-return.json',{'document':returned.document,'digest':returned.digest})
row=json.loads((HERE/'worker/attempt-00001/result.json').read_bytes())
assert all(sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in pins.items())
record={'worker_status':row['status'],'entry_key':row['entry_key'],'program':row['program'],
    'active_capabilities':row['active_capabilities'],'operations_emitted':row['operations_emitted'],
    'source_profile':LATEST_SOURCE_ENTRY_PROFILE,'elapsed_seconds':time.monotonic()-start,
    'readonly_counts':[s.counts for s in archives._stores.values()],'compile':0,'raw':0,'target':0,
    'publication':0,'currentRun_binding':0,'whole_model_complete':False}
if returned.owned_returns and returned.owned_returns[0].result.graph is not None:
    graph=returned.owned_returns[0].result.graph
    record['graph_counts']={k:len(getattr(graph,k))for k in('regions','resumable_bodies','resumable_creates',
        'driver_interfaces','body_drives','raw_driver_requests','final_body_gates','body_outcome_commits')}
common.save(HERE/'receipt.json',record);print(json.dumps(record,sort_keys=True),flush=True)
raise SystemExit(int(row['status']=='FAILED'))
