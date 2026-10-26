"""One existing local AugAssign frontend through the ordinary automatic source worker."""
from pathlib import Path
from hashlib import sha256
import importlib.util,json,time
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];start=time.monotonic()
spec=importlib.util.spec_from_file_location('ordinary_entry_inputs',ROOT/'artifacts/experiments/function_try_source_entries_20261026/common.py')
common=importlib.util.module_from_spec(spec);spec.loader.exec_module(common)
pins={str(p.relative_to(ROOT)):sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'scar').rglob('*.py'))}
common.save(HERE/'inputs.json',{'source_sha256':pins,'selection':common.receipt(HERE/'selection.json')})
config=json.loads(Path('/home/zyf/AAA/scar-worktrees/source209-model/artifacts/experiments/source209_resume01_20261026/inputs.json').read_bytes())
owner,archives,catalog,metadata=common.normal_inputs(config,None)
selection=json.loads((HERE/'selection.json').read_bytes())
from scar.analysis.source_frontend_worklist import SourceFrontendBudget,plan_source_entries,run_source_entries,LATEST_SOURCE_ENTRY_PROFILE
budget=SourceFrontendBudget(max_catalog_files=256,max_catalog_bodies=8192,max_catalog_groups=8192,
 max_dispatch_bodies=1,max_source_files=1,max_source_bytes=1_000_000,max_operations_per_body=10000,
 max_total_operations=10000,max_record_bytes=128_000_000,max_output_bytes=256_000_000,max_elapsed_seconds=600)
plan=plan_source_entries(catalog,budget=budget,eligible_entry_keys=tuple(r['entry_key']for r in selection['selected']),
 source_entry_profile=LATEST_SOURCE_ENTRY_PROFILE,dispatch_order='FILE_GROUPED_V1',out_dir=HERE/'plan')
returned=run_source_entries(plan,HERE/'worker',budget=budget,progress=lambda r:print(json.dumps(r),flush=True))
common.save(HERE/'public-return.json',{'document':returned.document,'digest':returned.digest})
rows=[json.loads(p.read_bytes())for p in sorted((HERE/'worker').glob('attempt-*/result.json'))]
assert all(sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in pins.items())
record={'status':'REAL_SOURCE_ATTEMPTS_WITH_OPEN','elapsed_seconds':time.monotonic()-start,
 'entries':[{k:r.get(k)for k in ('entry_key','status','source_calls','active_capabilities','program','operations_emitted','public_structure_reader','independent_code_reader')}for r in rows],
 'counts':returned.document['counts'],'worker':returned.document,'readonly_counts':[s.counts for s in archives._stores.values()],
 'compile':0,'raw':0,'target':0,'publication':0,'currentRun_binding':0,'whole_model_complete':False,'total_io_metered':False}
common.save(HERE/'receipt.json',record);print(json.dumps(record,sort_keys=True),flush=True)
raise SystemExit(int(any(r['status']=='FAILED'for r in rows)))
