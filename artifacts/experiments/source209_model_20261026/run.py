"""Normal single-catalog source entry batches. Root starts this driver once."""
from pathlib import Path
import gc,hashlib,json,os,resource,signal,threading,time,traceback
from collections import Counter

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
START=time.monotonic()

def canonical(x):return json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
def need(x,msg):
 if not x:raise ValueError(msg)
class BudgetFrontier(BaseException):pass
class WallFrontier(BaseException):pass

class Driver:
 def __init__(self,config,freeze):
  self.config,self.freeze=config,freeze;self.limits=config['budgets'];self.output=HERE/'result'
  self.stored=self.decoded=self.pending=0;self.calls=Counter();self.refusals=[]
  self.phase='INITIALIZING';self.batch=None;self.active_key=None;self.graph_allowed={};self.graph_seen={}
  self.output_refs={};self.batch_summaries=[];self.entries={};self.stop=threading.Event();self.lock=threading.Lock()
  self.allowed={r['path']for r in freeze['inputs']+freeze['sources']+freeze['runtime']}
  self.allowed.update(r['path']for r in freeze['graph_declarations'])
 def begin(self,path,stored,decoded,kind):
  path=Path(path).resolve()
  need(str(path)in self.allowed or path.is_relative_to(self.output),'undeclared model/control read: '+str(path))
  amount=stored+decoded
  # Reserve part of the same total cap for final original started/terminal reads.
  ceiling=self.limits['max_input_stored_plus_decoded_bytes']
  if kind not in ('ledger_started','ledger_terminal'):ceiling-=32_000_000
  if self.stored+self.decoded+self.pending+amount>ceiling:
   self.refusals.append({'kind':kind,'path':str(path),'stored':stored,'decoded':decoded})
   raise BudgetFrontier('GLOBAL_INPUT_STORED_PLUS_DECODED_LIMIT')
  self.pending+=amount;return stored,decoded,kind
 def done(self,token):
  s,d,k=token;self.pending-=s+d;self.stored+=s;self.decoded+=d;self.calls[k]+=1
 def io(self):return {'stored_read_bytes':self.stored,'decoded_payload_bytes':self.decoded,'stored_plus_decoded_bytes':self.stored+self.decoded,'pending_reserved_not_actual':self.pending,'read_calls':dict(self.calls),'refusals':self.refusals,'ceiling':self.limits['max_input_stored_plus_decoded_bytes'],'scope':'normal owner/aux/graphs/archive payloads; SP5 gzip and separate normal hash passes; explicit controls/source/runtime SHA and ledger reads','runtime_import_IO':'OPEN, not a full interpreter/syscall I/O meter','code_payload_logical_bytes':'text/marshal payload size is also charged as decoded, not CodeType heap size','partial_reads':'OPEN if a delegated reader raised with reservation pending'}
 def read_json(self,path,expected=None,kind='driver_metadata'):
  path=Path(path);n=path.stat().st_size;t=self.begin(path,n,n,kind);raw=path.read_bytes()
  need(len(raw)==n,'metadata bytes changed')
  if expected:need(len(raw)==expected['bytes']and hashlib.sha256(raw).hexdigest()==expected['sha256'],'fixed metadata SHA/size differs: '+str(path))
  value=json.loads(raw);self.done(t);return value
 def sha(self,path):
  path=Path(path);n=path.stat().st_size;t=self.begin(path,n,0,'frozen_control_SHA');h=hashlib.sha256();size=0
  with path.open('rb')as stream:
   while raw:=stream.read(1_048_576):h.update(raw);size+=len(raw)
  need(size==n,'SHA input changed');self.done(t);return {'path':str(path),'bytes':size,'sha256':h.hexdigest()}
 def output_bytes(self):return sum(p.stat().st_size for p in self.output.rglob('*')if p.is_file())
 def check_output(self):
  if self.output_bytes()>self.limits['max_output_stored_bytes']:raise BudgetFrontier('GLOBAL_POST_PUBLISH_OUTPUT_LIMIT')
 def save(self,path,value):
  path=Path(path);raw=canonical(value)+b'\n';need(len(raw)<=self.limits['max_record_bytes'],'driver metadata record limit')
  old=path.stat().st_size if path.exists()else 0
  if self.output_bytes()-old+len(raw)>self.limits['max_output_stored_bytes']:raise BudgetFrontier('GLOBAL_OUTPUT_BEFORE_DRIVER_METADATA_PUBLISH')
  path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_name('.'+path.name+'.tmp')
  with temporary.open('xb')as stream:stream.write(raw)
  os.replace(temporary,path)
 def event(self,value):
  row={'elapsed_s':time.monotonic()-START,'phase':self.phase,'batch':self.batch,**value}
  with self.lock:
   with(self.output/'progress.jsonl').open('a')as stream:stream.write((canonical(row)+b'\n').decode())
 def heartbeat(self):
  while not self.stop.wait(30):
   self.event({'heartbeat':True,'active_entry':self.active_key,'IO':self.io(),'RSS_peak_KiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})
 def check_frozen(self):
  for row in self.freeze['sources']+self.freeze['runtime']+self.freeze['inputs']:need(self.sha(row['path'])==row,'frozen bytes differ: '+row['path'])
  for directory,members in self.freeze['archive_members'].items():need(sorted(str(p)for p in Path(directory).iterdir()if p.is_file())==members,'original archive directory membership changed')
 def install_readers(self):
  from scar.analysis import source_attachments as sa
  from scar.analysis import source_frontend_worklist as sf
  from scar.analysis import inventory_partitions as ip
  from scar.analysis.code_witness import CodeWitnessStore
  plain,aux,graph,read,filehash,write,replay=sa._plain,sa.SourceAttachments._aux,sa.load_source_graph_artifact,CodeWitnessStore._read,ip._file_hash,sf._write_shard,sf._read_receipt
  def bounded_plain(path,*args):
   n=Path(path).stat().st_size;t=self.begin(path,n,n,'owner_manifest');v=plain(path,*args);self.done(t);return v
  def bounded_aux(owner,locator,root,family):
   p,a=owner._artifact_path(locator,root,family)
   if(str(p),a['canonical_sha256'])in owner._auxiliary:return aux(owner,locator,root,family)
   t=self.begin(p,a['compressed_bytes'],a['canonical_bytes'],'source_provider_aux');v=aux(owner,locator,root,family);self.done(t);return v
  def bounded_graph(path,**kw):
   p=str(Path(path).resolve());need(p in self.graph_allowed,'graph outside current whole-file batch')
   a=self.graph_allowed[p];need(all(kw[k]==a[k]for k in ('schema','canonical_sha256','canonical_bytes','compressed_bytes')),'graph declaration differs from read-plan')
   if p not in self.graph_seen:
    total=sum(v['canonical_bytes']for v in self.graph_seen.values())+a['canonical_bytes']
    if total>self.limits['max_graph_decoded_per_batch']:raise BudgetFrontier('BATCH_UNIQUE_GRAPH_DECLARATION_LIMIT')
    self.graph_seen[p]=a
   t=self.begin(path,kw['compressed_bytes'],kw['canonical_bytes'],'source_graph');v=graph(path,**kw);self.done(t);return v
  def bounded_read(store,relative,limit):
   p=store.root/relative;n=p.stat().st_size;t=self.begin(p,n,n,'archive_manifest'if relative=='manifest.json'else'archive_text_marshal');v=read(store,relative,limit);need(len(v)==n,'archive size differs');self.done(t);return v
  def bounded_hash(path):
   n=Path(path).stat().st_size;t=self.begin(path,n,0,'normal_output_or_readback_hash');v=filehash(path);need(v[1]==n,'normal hash input size differs');self.done(t);return v
  def tracked_write(root,relative,document,*,limit):
   ref=write(root,relative,document,limit=limit);self.output_refs[str((root/ref['uri']).resolve())]=ref;self.check_output();return ref
  def bounded_replay(path,*,limit):
   p=str(Path(path).resolve());need(p in self.output_refs,'ordinary readback lacks exact original writer receipt')
   ref=self.output_refs[p];need(Path(path).stat().st_size==ref['physical_bytes'],'new artifact size differs')
   # _read_receipt also performs a separate _file_hash, charged by bounded_hash.
   t=self.begin(path,ref['physical_bytes'],ref['decoded_bytes'],'ordinary_SP5_gzip_readback')
   v=replay(path,limit=limit);need(v[1]['decoded_bytes']==ref['decoded_bytes'],'ordinary readback canonical size differs');self.done(t);return v
  sa._plain,sa.SourceAttachments._aux,sa.load_source_graph_artifact=bounded_plain,bounded_aux,bounded_graph
  CodeWitnessStore._read=bounded_read;ip._file_hash=bounded_hash;sf._write_shard=tracked_write;sf._read_receipt=bounded_replay
 def build_catalog(self,read_plan,remaining):
  from scar.analysis.source_attachments import SourceAttachments,SourceAttachmentBudget
  from scar.analysis.code_witness import CodeWitnessBudget
  from scar.analysis.compiler_witness_archives import CompilerArchiveBudget,CompilerWitnessArchives
  from scar.analysis.source_entry_catalog import SourceEntryCatalog
  c=self.config
  owner=SourceAttachments(c['continuation']['path'],expected_report_sha256=c['continuation']['sha256'],project_root=c['project_root'],budget=SourceAttachmentBudget(max_report_bytes=8_000_000,max_artifact_bytes=self.limits['max_selected_and_aux_decoded_total'],max_record_bytes=self.limits['max_record_bytes'],cached_files=2))
  archives=CompilerWitnessArchives(tuple((r['directory'],r['manifest']['sha256'])for r in c['archives']),store_budget=CodeWitnessBudget(max_compile_keys=94,max_source_files=94,max_source_bytes=8_000_000,max_module_bytes=16_000_000,max_archive_bytes=256_000_000,max_manifest_bytes=8_000_000),budget=CompilerArchiveBudget(max_archives=4,max_total_modules=256,max_total_sources=256,max_declared_payload_bytes=256_000_000))
  catalog=SourceEntryCatalog(admissions=(owner,),projects=(),archives=archives,max_groups=8192,max_candidates=8192,max_selected_decode_bytes=self.limits['max_selected_and_aux_decoded_total'])
  metadata=catalog.metadata();ready={r['entry_key']:r for r in metadata['candidates']if r['status']=='CANDIDATE_SOURCE_GRAPH_UNVERIFIED'}
  need(len(metadata['groups'])==817 and metadata['entered_invocations']==100438 and len(metadata['candidates'])==243 and len(ready)==242,'full normal catalog denominator/status differs')
  old={}
  for ref in c['old_terminal_receipts']:
   row=self.read_json(ref['path'],ref,'old_terminal_metadata')
   if row.get('schema')=='scar.source-frontend-attempt':
    need(row['entry_key']not in old,'duplicate old terminal');old[row['entry_key']]=row
  need(Counter(r['status']for r in old.values())==Counter({'SUCCEEDED':26,'UNSUPPORTED':7})and len(old)==33,'original33 outcomes differ')
  keys=set(ready)-set(old);planned=[k for b in read_plan['batches']for k in b['entry_keys']]
  need(len(keys)==len(planned)==len(set(planned))==209 and set(planned)==keys and keys=={r['entry_key']for r in remaining['entries']},'whole209 selection differs or repeats original terminal')
  need(not read_plan['oversized_or_unschedulable_files']and len(read_plan['batches'])==13,'approved13 complete batch schedule differs')
  seen_files=set()
  for batch in read_plan['batches']:
   need(batch['files']<=8 and batch['entries']<=64 and batch['unique_graph_decoded_bytes_declared']<=300_000_000,'batch limit differs')
   need(batch['entry_keys']==[k for f in batch['file_groups']for k in f['entry_keys']],'whole-file batch key order differs')
   for item in batch['file_groups']:
    need(item['file_key']not in seen_files,'same file repeated across batches');seen_files.add(item['file_key'])
    for key in item['entry_keys']:need(ready[key]['file_key']==item['file_key']and ready[key]['basis']['source_snapshot']==item['source_snapshot'],'fresh candidate file/snapshot differs')
    row=owner._files[item['source_snapshot']['path']];p,a=owner._artifact_path(row['source_graph_artifact'],row['source_root'],'graphs')
    need(str(p)==item['source_graph']['path']and a==item['source_graph']['declaration']and row['source_graph_artifact']==item['source_graph']['original_locator']and p.stat().st_size==a['compressed_bytes'],'fresh original graph declaration differs')
  need(len(seen_files)==99,'normal99-file scope differs')
  self.entries={r['entry_key']:{'entry_key':r['entry_key'],'historical_calls':r['calls'],'file_key':r['file_key'],'status':'PENDING_NOT_STARTED','batch':b['batch']}for b in read_plan['batches']for r in (ready[k]for k in b['entry_keys'])}
  self.save(self.output/'catalog-manifest.json',{'full_groups':817,'full_calls':100438,'candidates':243,'ready_entries':242,'remaining_entries':209,'batches':13,'source_inputs':catalog.inputs(),'old_terminal_outcomes':read_plan['old_terminal_outcomes_retained'],'old_producer_and_capabilities':read_plan['old_producer_and_capabilities'],'resumable_frontiers':read_plan['resumable_frontiers'],'qualification':'normal metadata only, no source graph or CodeType loaded yet'})
  return owner,archives,catalog
 def refresh_entries(self,batch,folder,stop_reason=None,manifest=None):
  starts={};terminals={}
  for p in (folder/'worker').glob('attempt-*/started.json'):
   r=self.read_json(p,kind='ledger_started');starts[r['entry_key']]={'uri':str(p),'record':r}
  for p in (folder/'worker').glob('attempt-*/result.json'):
   r=self.read_json(p,kind='ledger_terminal');terminals[r['entry_key']]={'uri':str(p),'record':r}
  need(set(starts)<=set(batch['entry_keys'])and set(terminals)<=set(batch['entry_keys']),'worker wrote foreign batch entry')
  for key in batch['entry_keys']:
   entry=self.entries[key]
   if key in terminals:
    r=terminals[key]['record'];entry.update(status=r['status'],public_terminal=terminals[key]['uri'],operations_emitted=r['operations_emitted'],public_structure_reader=r['public_structure_reader'],independent_code_reader=r['independent_code_reader'],program=r['program'],error=r.get('error'))
    if r['status']=='FAILED':entry['frontier_class']='SOURCE_OR_LOWERER_EXCEPTION_REQUIRES_REVIEW'
   elif key in starts:entry.update(status='STARTED_NO_TERMINAL',public_started=starts[key]['uri'],frontier_class=stop_reason or'INCOMPLETE_PUBLIC_ATTEMPT')
   else:entry.update(status='PENDING_NOT_STARTED'if self.phase=='BATCH_WORKER'else'NOT_ATTEMPTED',frontier_class=stop_reason or('BATCH_WALL_OR_OPERATIONS_BUDGET'if manifest and manifest['unattempted_window_entries']else'NOT_STARTED'))
  if manifest:need(manifest['unattempted_window_entries']==len(batch['entry_keys'])-len(terminals),'normal worker unattempted denominator differs')
 def save_ledger(self,read_plan):
  rows=list(self.entries.values());counts=Counter(r['status']for r in rows)
  self.save(self.output/'entry-ledger.json',{'original_groups':817,'original_calls':100438,'source_verified_candidates':243,'remaining_selected':209,'current_entry_statuses':dict(counts),'entries':rows,'old_terminal_outcomes_retained':read_plan['old_terminal_outcomes_retained'],'old_producer_and_capabilities':read_plan['old_producer_and_capabilities'],'resumable_frontiers':read_plan['resumable_frontiers'],'scope':'272038 static entry results; no publication/currentRun binding; pending is never unsupported','IO':self.io()})
 def run_batch(self,batch,catalog,archives,read_plan):
  from scar.analysis.source_frontend_worklist import SourceFrontendBudget,plan_source_entries,run_source_entries
  from scar.ir.program.source_language import SourceLanguageCapability
  self.batch=batch['batch'];self.phase='BATCH_PLAN';self.graph_seen={};self.graph_allowed={f['source_graph']['path']:f['source_graph']['declaration']for f in batch['file_groups']}
  folder=self.output/'batches'/f'batch-{self.batch:03d}';folder.mkdir(parents=True)
  budget=SourceFrontendBudget(max_catalog_files=256,max_catalog_bodies=8192,max_catalog_groups=8192,max_dispatch_bodies=64,max_source_files=8,max_source_bytes=2_000_000,max_operations_per_body=10_000,max_total_operations=1_000_000,max_record_bytes=self.limits['max_record_bytes'],max_output_bytes=self.limits['max_output_stored_bytes'],max_elapsed_seconds=900)
  capabilities=tuple(SourceLanguageCapability(v)for v in read_plan['old_producer_and_capabilities']['capabilities'])
  result=plan=None;failure=None;manifest=None;live_count=0;abort=False
  try:
   plan=plan_source_entries(catalog,budget=budget,capabilities=capabilities,eligible_entry_keys=tuple(batch['entry_keys']),dispatch_order='FILE_GROUPED_V1',out_dir=folder/'plan')
   need([r['entry_key']for r in plan.dispatch]==batch['entry_keys']and len(plan.entries)==243 and len(plan.groups)==817 and plan.document['summary']['current_calls']==100438,'normal public plan differs from approved batch/read-plan')
   self.phase='BATCH_WORKER'
   def progress(row):
    self.active_key=row['entry_key'];self.check_output();self.event(row)
    self.refresh_entries(batch,folder);self.save_ledger(read_plan)
   result=run_source_entries(plan,folder/'worker',budget=budget,progress=progress)
   # Public worker already independently reads/checks every successful SP5.
   # Retain its document/digest; do not repeat full graph validation here.
   need(hashlib.sha256(canonical(result.document)).hexdigest()==result.digest,'normal result document changed')
   live_count=len(result.owned_returns);manifest=result.document
   self.save(folder/'public-return.json',{'document':manifest,'result_digest':result.digest,'actual_live_owned_returns_before_release':live_count,'second_full_consumer_validation':'NOT_REPEATED','future_saved_artifact_admission':'independent strict CP2, live owner not restorable'})
  except BaseException as error:
   kind='INPUT_OR_OUTPUT_BUDGET_FRONTIER'if isinstance(error,BudgetFrontier)else'GLOBAL_WALL_FRONTIER'if isinstance(error,WallFrontier)else'SOURCE_CATALOG_OR_UNCAUGHT_WORKER_EXCEPTION'
   failure={'kind':kind,'type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc()};abort=True;error.__traceback__=None
  finally:
   self.phase='BATCH_RELEASE';result=None;plan=None;collected=gc.collect();self.active_key=None
   reason=failure['kind']if failure else None
   self.refresh_entries(batch,folder,reason,manifest)
   summary={'batch':self.batch,'public_worker_manifest':manifest,'failure':failure,'owned_result_and_plan_references_released':True,'gc_collected':collected,'owned_returns_count_before_normal_release':live_count,'normal_cached_source_files_limit':2,'actual_batch_unique_graph_declarations_read':len(self.graph_seen),'actual_batch_unique_graph_decoded_bytes':sum(v['canonical_bytes']for v in self.graph_seen.values()),'entry_statuses':dict(Counter(self.entries[k]['status']for k in batch['entry_keys'])),'RSS_peak_KiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'IO':self.io(),'same_entry_automatically_retried':False}
   self.save(folder/'batch-result.json',summary);self.batch_summaries.append(summary);self.save_ledger(read_plan)
  return abort
 def run(self):
  resource.setrlimit(resource.RLIMIT_AS,(self.limits['AS_bytes'],self.limits['AS_bytes']))
  self.output.mkdir();thread=threading.Thread(target=self.heartbeat,daemon=True);thread.start()
  read_plan=None;failure=None;owner=archives=catalog=None
  try:
   self.check_frozen();self.install_readers();self.phase='NORMAL_METADATA_ONCE'
   read_plan=self.read_json(self.config['read_plan']['path'],self.config['read_plan']);remaining=self.read_json(self.config['remaining_metadata']['path'],self.config['remaining_metadata'])
   batch_by_key={key:batch['batch']for batch in read_plan['batches']for key in batch['entry_keys']}
   self.entries={r['entry_key']:{'entry_key':r['entry_key'],'historical_calls':r['calls'],'file_key':r['file_key'],'status':'PENDING_NOT_STARTED','batch':batch_by_key[r['entry_key']]}for r in remaining['entries']}
   self.save_ledger(read_plan)
   owner,archives,catalog=self.build_catalog(read_plan,remaining);self.save_ledger(read_plan)
   for batch in read_plan['batches']:
    if self.run_batch(batch,catalog,archives,read_plan):break
   failed_batch=next((b for b in self.batch_summaries if b['failure']),None)
   if failed_batch:failure={'batch':failed_batch['batch'],**failed_batch['failure']}
   self.phase='FINAL_FROZEN_CHECK';self.check_frozen();self.check_output()
   need(all(s.counts['compile_attempts']==0 and s.counts['source_bytes_read']==0 for s in archives._stores.values()),'readonly modeling compiled or read live source')
  except BaseException as error:
   latest={'kind':'GLOBAL_WALL_FRONTIER'if isinstance(error,WallFrontier)else'INPUT_OR_OUTPUT_BUDGET_FRONTIER'if isinstance(error,BudgetFrontier)else'SOURCE_CATALOG_OR_DRIVER_EXCEPTION','type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc()}
   if failure:failure['postcheck_failure']=latest
   else:failure=latest
   error.__traceback__=None
  finally:
   self.stop.set();thread.join(timeout=1);self.phase='TERMINAL'
   if read_plan and self.entries:
    try:self.save_ledger(read_plan)
    except BudgetFrontier:pass
   counts=dict(Counter(r['status']for r in self.entries.values()))
   batch_failed=any(b['failure']for b in self.batch_summaries)
   final={'status':'FAILED_RETAINED_WITH_OPEN'if failure or batch_failed else'STATIC_BATCH_ATTEMPTS_WITH_OPEN','failure':failure,'batches_completed_or_stopped':len(self.batch_summaries),'batch_summaries':self.batch_summaries,'entry_statuses':counts,'all209_have_public_terminal':sum(v for k,v in counts.items()if k not in ('PENDING_NOT_STARTED','NOT_ATTEMPTED','STARTED_NO_TERMINAL'))==209,'IO':self.io(),'output_bytes_before_final_record':self.output_bytes(),'normal_catalog_constructed_once':catalog is not None,'normal_catalog_measurements':catalog.measurements()if catalog is not None else None,'readonly_counts':[dict(s.counts)for s in archives._stores.values()]if archives else [],'source_scope':'original272038 static source modeling; no current369749 binding/publication','live_owner_restored_from_JSON':False,'old26_success_and7_unsupported_repeated':False,'whole_first_stage_complete':False,'elapsed_s':time.monotonic()-START}
   try:self.save(self.output/'terminal.json',final)
   except BudgetFrontier:
    # Retain the reason outside the capped result directory if its final small receipt cannot publish.
    (HERE/'terminal-budget-frontier.json').write_bytes(canonical(final)+b'\n')
   print(json.dumps({'status':final['status'],'entry_statuses':counts,'IO':self.io(),'elapsed_s':final['elapsed_s']}),flush=True)
  return 1 if failure or any(b['failure']for b in self.batch_summaries)else 0

def main():
 need(not(HERE/'result').exists(),'fresh output required; no implicit resume/retry')
 config=json.loads((HERE/'inputs.json').read_bytes());freeze=json.loads((HERE/'freeze.json').read_bytes())
 driver=Driver(config,freeze)
 def terminated(signum,frame):raise WallFrontier('external wall/termination; current original attempts retained')
 signal.signal(signal.SIGTERM,terminated)
 raise SystemExit(driver.run())

if __name__=='__main__':main()
