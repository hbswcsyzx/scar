"""One complete ordinary source-only attempt of the retained20 Try entries."""
from pathlib import Path
from collections import Counter,OrderedDict
from dataclasses import asdict
import gc,hashlib,importlib.util,json,resource,signal,threading,time,traceback

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
PREVIOUS=HERE.parent/'function_try_source_entries_20261026'
spec=importlib.util.spec_from_file_location('normal_try_gate_inputs',PREVIOUS/'common.py')
common=importlib.util.module_from_spec(spec);spec.loader.exec_module(common)
O=common.OBSERVER;need=O.need;canonical=O.canonical

def ref(path):
 raw=Path(path).read_bytes();return{'path':str(Path(path).resolve()),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}

def main():
 need(not(HERE/'result').exists(),'fresh actual20 output required')
 config=json.loads((PREVIOUS/'inputs.json').read_bytes());readplan=json.loads((PREVIOUS/'READ_PLAN.json').read_bytes())
 original=json.loads(Path(json.loads((common.OLD/'inputs.json').read_bytes())['read_plan']['path']).read_bytes())
 files={f['file_key']:f for b in original['batches']for f in b['file_groups']}
 prior=HERE.parent/'function_try_real20_20261026/result'
 terminal=json.loads((prior/'terminal.json').read_bytes());retry={r['entry_key']for r in terminal['entries']if r['status']=='FAILED'}
 for path in prior.glob('batch-*/worker/attempt-*/returned-metadata.json'):
  record=json.loads(path.read_bytes())
  if record['metadata']['gaps'][-1]['detail']=='FUNCTION_TRY_LOCAL_BINDING_PROPAGATION_UNIMPLEMENTED':
   retry.add(json.loads((path.parent/'result.json').read_bytes())['entry_key'])
 entries=sorted((r for r in readplan['all_original_try_entries']if r['entry_key']in retry),key=lambda r:(-r['historical_calls'],r['entry_key']))
 config['capabilities']=[c for c in config['capabilities']if c!='PYTHON_FUNCTION_TRY_314_V1']
 groups=OrderedDict()
 for row in entries:groups.setdefault(row['file_key'],[]).append(row)
 batches=[];current=[];decoded=0
 for key,rows in groups.items():
  size=files[key]['source_graph']['declaration']['canonical_bytes']
  if current and(len(current)==8 or decoded+size>300_000_000):batches.append(current);current=[];decoded=0
  current.append((key,rows));decoded+=size
 if current:batches.append(current)
 need(len(entries)==5 and len({r['entry_key']for r in entries})==5,'failed/binding retry selection differs')
 config['budgets']={'AS_bytes':8*1024**3,'max_input_stored_plus_decoded_bytes':8_000_000_000,'max_output_stored_bytes':512_000_000,'max_record_bytes':128_000_000,'max_graph_decoded_per_batch':300_000_000}
 config['selected20']=[r['entry_key']for r in entries]
 freeze=json.loads((PREVIOUS/'freeze.json').read_bytes())
 freeze['sources']=[ref(p)for p in sorted(set((ROOT/'scar').rglob('*.py'))|{ROOT/'sitecustomize.py',Path(__file__).resolve()})]
 freeze['graph_declarations']=[{**files[k]['source_graph']['declaration'],'path':files[k]['source_graph']['path']}for k in groups]
 observer=O.Driver(config,freeze);observer.output=HERE/'result';observer.output.mkdir();O.START=time.monotonic()
 resource.setrlimit(resource.RLIMIT_AS,(8*1024**3,)*2)
 def stop(signum,frame):raise O.WallFrontier('outer actual20 wall stop')
 signal.signal(signal.SIGTERM,stop)
 heartbeat=threading.Thread(target=observer.heartbeat,daemon=True);heartbeat.start()
 (HERE/'consumer-freeze.json').write_bytes(canonical(freeze)+b'\n')
 (HERE/'READ_PLAN.json').write_bytes(canonical({'original20':entries,'batches':[[r['entry_key']for k,rows in batch for r in rows]for batch in batches],'budgets':config['budgets'],'no_name_selection':True,'all_original49_unsupported_retained_in':str(PREVIOUS/'READ_PLAN.json')})+b'\n')
 summaries=[];failure=None;owner=archives=catalog=None;started=time.monotonic()
 try:
  observer.check_frozen();observer.install_readers();observer.phase='NORMAL_CATALOG'
  owner,archives,catalog,metadata=common.normal_inputs(config,observer)
  ready={r['entry_key']:r for r in metadata['candidates']if r['status']=='CANDIDATE_SOURCE_GRAPH_UNVERIFIED'}
  for row in entries:need(ready[row['entry_key']]['basis']==row['original_candidate']['basis'],'original descriptor/source/namespace changed')
  from scar.analysis.source_frontend_worklist import SourceFrontendBudget,plan_source_entries,run_source_entries
  from scar.ir.program.source_language import SourceLanguageCapability as C
  caps=tuple(C(x)for x in config['capabilities'])
  for ordinal,batch in enumerate(batches,1):
   observer.batch=ordinal;observer.phase='PLAN';folder=observer.output/f'batch-{ordinal:02d}';folder.mkdir()
   keys=tuple(r['entry_key']for k,rows in batch for r in rows)
   observer.graph_seen={};observer.graph_allowed={files[k]['source_graph']['path']:files[k]['source_graph']['declaration']for k,rows in batch}
   budget=SourceFrontendBudget(max_catalog_files=256,max_catalog_bodies=8192,max_catalog_groups=8192,max_dispatch_bodies=64,max_source_files=8,max_source_bytes=2_000_000,max_operations_per_body=10_000,max_total_operations=200_000,max_record_bytes=128_000_000,max_output_bytes=512_000_000,max_elapsed_seconds=900)
   plan=plan_source_entries(catalog,budget=budget,capabilities=caps,eligible_entry_keys=keys,dispatch_order='FILE_GROUPED_V1',automatic_function_try=True,out_dir=folder/'plan')
   need([r['entry_key']for r in plan.dispatch]==list(keys),'ordinary file-grouped dispatch differs')
   observer.phase='WORKER'
   def progress(row):
    observer.active_key=row['entry_key'];observer.event(row);observer.check_output()
    print(json.dumps({'batch':ordinal,**row}),flush=True)
   returned=run_source_entries(plan,folder/'worker',budget=budget,progress=progress)
   observer.save(folder/'public-return.json',{'document':returned.document,'digest':returned.digest,'owned_returns_before_release':len(returned.owned_returns),'publication':'NOT_RUN'})
   summaries.append(returned.document);returned=plan=None;gc.collect();observer.active_key=None
  observer.phase='FINAL_BYTES';observer.check_frozen();observer.check_output()
 except BaseException as error:
  failure={'type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc()};error.__traceback__=None
 finally:
  ledger=[]
  for row in entries:
   candidates=list(observer.output.glob('batch-*/worker/attempt-*/result.json'))
   found=None
   for p in candidates:
    record=json.loads(p.read_bytes())
    if record['entry_key']==row['entry_key']:found=record;break
   if found is None:found={'entry_key':row['entry_key'],'status':'NOT_ATTEMPTED'}
   found['historical_calls']=row['historical_calls'];ledger.append(found)
  counts=dict(Counter(r['status']for r in ledger));observer.stop.set();heartbeat.join(timeout=1)
  final={'status':'FAILED_RETAINED'if failure or counts.get('FAILED')else'ORDINARY_TRY20_ATTEMPT_WITH_OPEN','failure':failure,'counts':counts,'entries':ledger,'batches':summaries,'normal_catalog_once':catalog is not None,'readonly_counts':[s.counts for s in archives._stores.values()]if archives else[],'all_original_denominators':{'groups':817,'calls':100438,'candidates':243,'Try_window':20,'historical_Try_calls':578,'selected_retry_window':5},'IO':observer.io(),'elapsed_s':time.monotonic()-started,'currentRun_binding_publication_target_episode':False,'whole_model_complete':False}
  observer.save(observer.output/'terminal.json',final);print(json.dumps({'status':final['status'],'counts':counts,'failure':failure,'elapsed_s':final['elapsed_s'],'IO':observer.io()}),flush=True)
 return 1 if failure or counts.get('FAILED')else 0
if __name__=='__main__':raise SystemExit(main())
