"""One smallest original failed source, normal producer/readers before widening."""
from run import ROOT,HERE,common,pin,save
from pathlib import Path
import json,time,gc

def main():
 out=HERE/'retry02';out.mkdir();start=time.monotonic()
 config=json.loads(Path('/home/zyf/AAA/scar-worktrees/source209-model/artifacts/experiments/source209_resume01_20261026/inputs.json').read_bytes())
 pins=[pin(p)for p in sorted((ROOT/'scar').rglob('*.py'))]
 owner,archives,catalog,metadata=common.normal_inputs(config,None)
 previous=json.loads((HERE/'result/terminal.json').read_bytes());failed=[r for r in previous['entries']if r['status']=='FAILED'];assert len(failed)==7
 def declaration_bytes(row):
  file=owner._files[row['basis']['source']['path']]
  return owner._artifact_path(file['source_graph_artifact'],file['source_root'],'graphs')[1]['canonical_bytes']
 selected=min(failed,key=lambda r:(declaration_bytes(r),r['entry_key']))
 save(out/'inputs.json',{'selected':selected,'selection':'minimum original declared source-graph bytes among seven exact consumer-guard failures','original_failures':pin(HERE/'result/terminal.json'),'source_pins':pins})
 from scar.analysis.source_frontend_worklist import SourceFrontendBudget,plan_source_entries,run_source_entries
 budget=SourceFrontendBudget(max_catalog_files=256,max_catalog_bodies=8192,max_catalog_groups=8192,max_dispatch_bodies=1,max_source_files=1,max_source_bytes=2_000_000,max_operations_per_body=10_000,max_total_operations=10_000,max_record_bytes=128_000_000,max_output_bytes=128_000_000,max_elapsed_seconds=900)
 plan=plan_source_entries(catalog,budget=budget,eligible_entry_keys=(selected['entry_key'],),automatic_function_try=True,automatic_call_expansion=True,automatic_nested_functions=True,out_dir=out/'plan')
 result=run_source_entries(plan,out/'worker',budget=budget,progress=lambda row:print(json.dumps(row),flush=True))
 save(out/'public-return.json',{'document':result.document,'digest':result.digest,'owned_returns_before_release':len(result.owned_returns)})
 result=plan=None;gc.collect()
 assert [pin(Path(p['path']))for p in pins]==pins
 rows=[dict(json.loads(p.read_bytes()),public_terminal=str(p))for p in out.glob('worker/attempt-*/result.json')]
 final={'entries':rows,'elapsed_s':time.monotonic()-start,'readonly_counts':[s.counts for s in archives._stores.values()],'compile':0,'raw':0,'target':0,'publication':0,'current_binding':0,'old_result_unchanged':True}
 save(out/'terminal.json',final);print(json.dumps({'status':rows[0]['status'],'elapsed_s':final['elapsed_s']}),flush=True)
 return 0 if rows[0]['status']=='SUCCEEDED'else 1
if __name__=='__main__':raise SystemExit(main())
