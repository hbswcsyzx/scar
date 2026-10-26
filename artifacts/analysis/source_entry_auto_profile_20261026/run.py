"""One original successful entry, selected mechanically, with the V2 profile."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import time

HERE = Path(__file__).resolve().parent; ROOT = HERE.parents[2]
spec = importlib.util.spec_from_file_location('ordinary_entry_inputs', ROOT/'artifacts/experiments/function_try_source_entries_20261026/common.py')
common = importlib.util.module_from_spec(spec); spec.loader.exec_module(common)
started = time.monotonic()
source = ROOT/'scar/analysis/source_frontend_worklist.py'
before = sha256(source.read_bytes()).hexdigest()
config = json.loads(Path('/home/zyf/AAA/scar-worktrees/source209-model/artifacts/experiments/source209_resume01_20261026/inputs.json').read_bytes())
owner, archives, catalog, metadata = common.normal_inputs(config, None)
rows = json.loads((ROOT/'artifacts/analysis/function_import_implementation_20261026/successful-programs-delta4.json').read_bytes())['entries']
chosen = min(rows, key=lambda r:(-r['historical_calls'], r['entry_key']))
from scar.analysis.source_frontend_worklist import (
    SourceFrontendBudget, plan_source_entries, run_source_entries, SOURCE_ENTRY_PROFILE_314_V2)
budget = SourceFrontendBudget(max_catalog_files=256, max_catalog_bodies=8192, max_catalog_groups=8192,
    max_dispatch_bodies=1, max_source_files=1, max_source_bytes=1_000_000,
    max_operations_per_body=4000, max_total_operations=4000, max_record_bytes=128_000_000,
    max_output_bytes=128_000_000, max_elapsed_seconds=180)
plan = plan_source_entries(catalog, budget=budget, eligible_entry_keys=(chosen['entry_key'],),
    source_entry_profile=SOURCE_ENTRY_PROFILE_314_V2, out_dir=HERE/'plan')
assert 'PYTHON_FUNCTION_IMPORT_314_V1' not in plan.document['capabilities']
returned = run_source_entries(plan, HERE/'worker', budget=budget,
    progress=lambda row:print(json.dumps(row, sort_keys=True),flush=True))
result = json.loads((HERE/'worker/attempt-00001/result.json').read_bytes())
assert result['status']=='SUCCEEDED' and result['public_structure_reader'] and result['independent_code_reader']
assert result['active_capabilities'] == plan.document['capabilities']+['PYTHON_FUNCTION_IMPORT_314_V1']
assert sha256(source.read_bytes()).hexdigest()==before
receipt = {'status':'VERSIONED_AUTOMATIC_SOURCE_ENTRY_PROFILE_ACTUAL_PASS_WITH_OPEN',
    'source_profile':SOURCE_ENTRY_PROFILE_314_V2,'plan_sha256':plan.digest,
    'source_sha256':before,'entry_key':chosen['entry_key'],'program':result['program'],
    'operations_emitted':result['operations_emitted'],'historical_calls':chosen['historical_calls'],
    'base_capabilities':plan.document['capabilities'],'automatically_selected':result['active_capabilities'],
    'original_groups':len(metadata['groups']),'original_calls':metadata['entered_invocations'],
    'original_candidates':len(metadata['candidates']),'readonly_counts':[s.counts for s in archives._stores.values()],
    'compile':0,'raw':0,'target':0,'publication':0,'currentRun_binding':0,'new_coverage_count':0,
    'elapsed_seconds':time.monotonic()-started}
common.save(HERE/'receipt.json',receipt)
print(json.dumps(receipt, sort_keys=True),flush=True)
