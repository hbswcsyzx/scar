"""One actual ordinary GeneratorExp entry through automatic V4 selection."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import time

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];start=time.monotonic()
spec=importlib.util.spec_from_file_location('ordinary_entry_inputs',ROOT/'artifacts/experiments/function_try_source_entries_20261026/common.py')
common=importlib.util.module_from_spec(spec);spec.loader.exec_module(common)
source=ROOT/'scar/analysis/source_frontend_worklist.py';before=sha256(source.read_bytes()).hexdigest()
config=json.loads(Path('/home/zyf/AAA/scar-worktrees/source209-model/artifacts/experiments/source209_resume01_20261026/inputs.json').read_bytes())
owner,archives,catalog,metadata=common.normal_inputs(config,None)
chosen=json.loads((HERE/'selection.json').read_bytes())['selected']
from scar.analysis.source_frontend_worklist import SourceFrontendBudget,plan_source_entries,run_source_entries,LATEST_SOURCE_ENTRY_PROFILE,SOURCE_ENTRY_PROFILES
budget=SourceFrontendBudget(max_catalog_files=256,max_catalog_bodies=8192,max_catalog_groups=8192,
    max_dispatch_bodies=1,max_source_files=1,max_source_bytes=1_000_000,max_operations_per_body=4000,
    max_total_operations=4000,max_record_bytes=128_000_000,max_output_bytes=128_000_000,max_elapsed_seconds=300)
plan=plan_source_entries(catalog,budget=budget,eligible_entry_keys=(chosen['entry_key'],),
    source_entry_profile=LATEST_SOURCE_ENTRY_PROFILE,out_dir=HERE/'plan')
returned=run_source_entries(plan,HERE/'worker',budget=budget,progress=lambda r:print(json.dumps(r),flush=True))
common.save(HERE/'public-return.json',{'document':returned.document,'digest':returned.digest})
row=json.loads((HERE/'worker/attempt-00001/result.json').read_bytes())
meta=json.loads((HERE/'worker/attempt-00001/returned-metadata.json').read_bytes())
assert 'PYTHON_GENEXPR_314_V1' not in plan.document['capabilities'] and 'PYTHON_GENEXPR_314_V1' in row['active_capabilities']
assert sha256(source.read_bytes()).hexdigest()==before
frontiers=[g for g in meta['metadata']['gaps']if g['kind']in('UNSUPPORTED_SYNTAX','SOURCE_MAPPING','CODE_VERSION')]
receipt={'status':'AUTOMATIC_GENEXPR_SOURCE_ATTEMPT_WITH_OPEN','worker_status':row['status'],'entry_key':row['entry_key'],
    'source_profile':LATEST_SOURCE_ENTRY_PROFILE,'supported_profiles':SOURCE_ENTRY_PROFILES,
    'source_sha256':before,'active_capabilities':row['active_capabilities'],'operations_emitted':row['operations_emitted'],
    'program':row['program'],'frontiers':frontiers,'historical_calls':chosen['historical_calls'],
    'full_denominators':{'groups':len(metadata['groups']),'calls':metadata['entered_invocations'],'candidates':len(metadata['candidates'])},
    'readonly_counts':[s.counts for s in archives._stores.values()],'compile':0,'raw':0,'target':0,'publication':0,'currentRun_binding':0,
    'source_body_reader_ran':row['public_structure_reader'],'independent_body_code_reader_ran':row['independent_code_reader'],
    'elapsed_seconds':time.monotonic()-start}
common.save(HERE/'receipt.json',receipt)
print(json.dumps(receipt,sort_keys=True),flush=True)
raise SystemExit(int(row['status']=='FAILED'))
