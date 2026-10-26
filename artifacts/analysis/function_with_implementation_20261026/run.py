"""At most two selected real With entries; stop on a shared hard failure."""
from collections import Counter
import gc
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import time

HERE=Path(__file__).resolve().parent; ROOT=HERE.parents[2]
spec=importlib.util.spec_from_file_location('ordinary_entry_inputs',ROOT/'artifacts/experiments/function_try_source_entries_20261026/common.py')
common=importlib.util.module_from_spec(spec);spec.loader.exec_module(common)
start=time.monotonic()
pins={str(p.relative_to(ROOT)):sha256(p.read_bytes()).hexdigest()for p in sorted((ROOT/'scar').rglob('*.py'))}
common.save(HERE/'inputs.json',{'source_sha256':pins,'selection':common.receipt(HERE/'selection.json')})
config=json.loads(Path('/home/zyf/AAA/scar-worktrees/source209-model/artifacts/experiments/source209_resume01_20261026/inputs.json').read_bytes())
owner,archives,catalog,metadata=common.normal_inputs(config,None)
from scar.analysis.source_frontend_worklist import SourceFrontendBudget,plan_source_entries,run_source_entries,SOURCE_ENTRY_PROFILE_314_V3
selected=json.loads((HERE/'selection.json').read_bytes())['selected'];results=[]
for ordinal,row in enumerate(selected,1):
    out=HERE/f'entry-{ordinal:02d}';out.mkdir()
    budget=SourceFrontendBudget(max_catalog_files=256,max_catalog_bodies=8192,max_catalog_groups=8192,
        max_dispatch_bodies=1,max_source_files=1,max_source_bytes=1_000_000,max_operations_per_body=4000,
        max_total_operations=4000,max_record_bytes=128_000_000,max_output_bytes=256_000_000,max_elapsed_seconds=300)
    plan=plan_source_entries(catalog,budget=budget,eligible_entry_keys=(row['entry_key'],),
        source_entry_profile=SOURCE_ENTRY_PROFILE_314_V3,out_dir=out/'plan')
    returned=run_source_entries(plan,out/'worker',budget=budget,progress=lambda r:print(json.dumps(r),flush=True))
    result=json.loads((out/'worker/attempt-00001/result.json').read_bytes())
    common.save(out/'public-return.json',{'document':returned.document,'digest':returned.digest})
    results.append({**result,'public_terminal':str(out/'worker/attempt-00001/result.json')})
    returned=plan=None;gc.collect()
    if result['status']=='FAILED':break
assert all(sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in pins.items())
record={'counts':dict(Counter(r['status']for r in results)),'entries':results,'selected':len(selected),
    'unattempted':len(selected)-len(results),'elapsed_seconds':time.monotonic()-start,
    'readonly_counts':[s.counts for s in archives._stores.values()],
    'compile':0,'raw':0,'target':0,'publication':0,'currentRun_binding':0,'whole_model_complete':False}
common.save(HERE/'terminal.json',record)
print(json.dumps({k:record[k]for k in('counts','unattempted','elapsed_seconds')}),flush=True)
raise SystemExit(int(any(r['status']=='FAILED'for r in results)))
