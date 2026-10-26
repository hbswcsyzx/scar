"""Ordinary related-entry worker; no target, capture, publication or binding."""
from collections import Counter,OrderedDict
from pathlib import Path
from dataclasses import replace
import gc,hashlib,importlib.util,json,resource,time,traceback
ROOT=Path(__file__).resolve().parents[3];HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('ordinary_entry_inputs',ROOT/'artifacts/experiments/function_try_source_entries_20261026/common.py')
common=importlib.util.module_from_spec(spec);spec.loader.exec_module(common)

def save(p,v):
 with p.open('x')as f:json.dump(v,f,sort_keys=True,separators=(',',':'),ensure_ascii=False);f.write('\n')
def pin(p):
 b=p.read_bytes();return{'path':str(p),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}

def main():
 start=time.monotonic();out=HERE/'result';out.mkdir();resource.setrlimit(resource.RLIMIT_AS,(8*1024**3,)*2)
 descriptions=json.loads((ROOT/'artifacts/analysis/nested_function_implementation_20261026/real-nested-definitions.json').read_bytes())['entries']
 keys={r['entry_key']for r in descriptions};assert len(keys)==13
 config=json.loads(Path('/home/zyf/AAA/scar-worktrees/source209-model/artifacts/experiments/source209_resume01_20261026/inputs.json').read_bytes())
 pins=[pin(p)for p in sorted((ROOT/'scar').rglob('*.py'))]
 save(out/'inputs.json',{'sources':pins,'selection':pin(ROOT/'artifacts/analysis/nested_function_implementation_20261026/real-nested-definitions.json'),'no_name_selection':True})
 owner,archives,catalog,metadata=common.normal_inputs(config,None)
 entries=[r for r in metadata['candidates']if r['entry_key']in keys];assert len(entries)==13
 files=OrderedDict()
 for r in entries:files.setdefault(r['file_key'],[]).append(r)
 batches=[];active=[];decoded=0
 for key,rows in files.items():
  file=owner._files[rows[0]['basis']['source']['path']];declaration=owner._artifact_path(file['source_graph_artifact'],file['source_root'],'graphs')[1]
  assert declaration['canonical_bytes']<=300_000_000
  if active and(len(active)==8 or decoded+declaration['canonical_bytes']>300_000_000):batches.append(active);active=[];decoded=0
  active.append((key,rows));decoded+=declaration['canonical_bytes']
 if active:batches.append(active)
 save(out/'read-plan.json',{'groups':817,'calls':100438,'candidates':243,'selected':[r['entry_key']for r in entries],'batches':[[r['entry_key']for k,rows in b for r in rows]for b in batches]})
 from scar.analysis.source_frontend_worklist import SourceFrontendBudget,plan_source_entries,run_source_entries
 from scar.analysis.source_function_definition_validation import validate_function_definitions
 from scar.ir.program.structured import PythonProtocolKind as K
 failure=None;summaries=[];negative=None
 try:
  for ordinal,batch in enumerate(batches,1):
   folder=out/f'batch-{ordinal:02d}';folder.mkdir();selected=tuple(r['entry_key']for k,rows in batch for r in rows)
   budget=SourceFrontendBudget(max_catalog_files=256,max_catalog_bodies=8192,max_catalog_groups=8192,max_dispatch_bodies=64,max_source_files=8,max_source_bytes=2_000_000,max_operations_per_body=10_000,max_total_operations=200_000,max_record_bytes=128_000_000,max_output_bytes=512_000_000,max_elapsed_seconds=900)
   plan=plan_source_entries(catalog,budget=budget,eligible_entry_keys=selected,dispatch_order='FILE_GROUPED_V1',automatic_function_try=True,automatic_call_expansion=True,automatic_nested_functions=True,out_dir=folder/'plan')
   assert [r['entry_key']for r in plan.dispatch]==list(selected)
   returned=run_source_entries(plan,folder/'worker',budget=budget,progress=lambda row:print(json.dumps({'batch':ordinal,**row}),flush=True))
   save(folder/'public-return.json',{'document':returned.document,'digest':returned.digest,'owned_returns_before_release':len(returned.owned_returns)})
   summaries.append(returned.document)
   if negative is None:
    for owned in returned.owned_returns:
     if owned.program_reference is None:continue
     result=owned.result;factories=[p.operation for p in result.structured.protocols if p.kind is K.MAKE_NESTED_FUNCTION]
     if not factories:continue
     factory=next(op for op in result.graph.operations if op.id==factories[0]);wrong=replace(factory,uses=(replace(factory.uses[0],value=factory.uses[1].value),)+factory.uses[1:]);graph=replace(result.graph,operations=tuple(wrong if op.id==factory.id else op for op in result.graph.operations))
     try:validate_function_definitions(result.structured,graph,result.interface,result.metadata,owned.context.semantic,result.language,source_tree=owned.context.tree,structural_only=True)
     except ValueError as err:negative={'entry_key':owned.entry.key,'wrong_code_reference_rejected':True,'detail':str(err)}
     else:raise AssertionError('foreign globals reference accepted as function code')
     save(out/'wrong-code-reference.json',negative);break
   returned=plan=None;gc.collect()
  assert [pin(Path(p['path']))for p in pins]==pins
 except BaseException as err:failure={'type':type(err).__name__,'detail':str(err),'traceback':traceback.format_exc()}
 records={}
 for p in out.glob('batch-*/worker/attempt-*/result.json'):
  r=json.loads(p.read_bytes());assert r['entry_key']not in records;records[r['entry_key']]={**r,'public_terminal':str(p)}
 rows=[{**r,**records.get(r['entry_key'],{'status':'NOT_ATTEMPTED'})}for r in entries];counts=dict(Counter(r['status']for r in rows))
 final={'status':'FAILED_RETAINED_WITH_OPEN'if failure or counts.get('FAILED')else'NESTED_FUNCTION_RELATED_RESULTS_WITH_OPEN','failure':failure,'entries':rows,'counts':counts,'batches':summaries,'elapsed_s':time.monotonic()-start,'readonly_counts':[s.counts for s in archives._stores.values()],'negative':negative,'compile':0,'target':0,'raw':0,'publication':0,'currentRun_binding':0,'whole_model_complete':False,'aggregate_stored_decoded_IO':'UNMETERED_OPEN'}
 save(out/'terminal.json',final);print(json.dumps({k:final[k]for k in('status','counts','failure','elapsed_s')}),flush=True)
 return 1 if failure or counts.get('FAILED')else 0
if __name__=='__main__':raise SystemExit(main())
