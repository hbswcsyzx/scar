"""Normal continuation/catalog/archive metadata only. No graph/CodeType/target."""
from collections import Counter
import hashlib
import inspect
import json
from pathlib import Path
import sys
import time
import traceback

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
START=time.monotonic()
CONTROL_BYTES=0
OUTPUT_BYTES=0

def canonical(x):return json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()

def receipt(p):
 global CONTROL_BYTES
 p=Path(p);h=hashlib.sha256();size=0
 with p.open('rb')as stream:
  while b:=stream.read(1048576):h.update(b);size+=len(b)
 CONTROL_BYTES+=size
 return {'path':str(p.resolve()),'sha256':h.hexdigest(),'bytes':size}

def save(name,x):
 global OUTPUT_BYTES
 raw=canonical(x)+b'\n'
 ceiling=8_000_000 if name=='failure.json' else 7_750_000
 if len(raw)>8_000_000 or OUTPUT_BYTES+len(raw)>ceiling:raise ValueError('G0 output budget exceeded before write; failure space reserved')
 with(HERE/name).open('xb')as stream:stream.write(raw)
 OUTPUT_BYTES+=len(raw)

def need(x,message):
 if not x:raise ValueError(message)

class MetadataMeter:
 def __init__(self,allowed):
  self.allowed=allowed;self.stored=0;self.decoded=0;self.pending=0;self.calls=Counter();self.by_path={}
 def begin(self,p,stored,decoded,role):
  p=str(Path(p).resolve())
  need(p in self.allowed,'G0 metadata reader attempted an unpinned input')
  need(0<=stored<=8_000_000 and 0<=decoded<=8_000_000,'single metadata record budget exceeded')
  amount=stored+decoded
  need(self.stored+self.decoded+self.pending+amount<=128_000_000,'actual metadata stored+decoded budget exhausted before read')
  self.pending+=amount
  return p,stored,decoded,role
 def complete(self,item):
  p,s,d,role=item;self.pending-=s+d;self.stored+=s;self.decoded+=d;self.calls[role]+=1
  row=self.by_path.setdefault(p,{'stored_bytes':0,'decoded_bytes':0,'reads':0});row['stored_bytes']+=s;row['decoded_bytes']+=d;row['reads']+=1
 def report(self):return {'stored_bytes':self.stored,'decoded_bytes':self.decoded,'stored_plus_decoded':self.stored+self.decoded,'pending_reserved_bytes':self.pending,'calls':dict(self.calls),'by_path':self.by_path,'partial_failed_read_bytes':'OPEN if a normal reader fails after reservation; pending is not claimed actual','source_and_control_hash_bytes':CONTROL_BYTES}

def main():
 freeze=json.loads((HERE/'freeze.json').read_bytes());meter=MetadataMeter({r['path']for r in freeze['inputs']});owner=None;archives=None
 try:
  need(not(HERE/'started.json').exists()and not(HERE/'result.json').exists(),'G0 output must be fresh')
  save('started.json',{'status':'RUNNING','scope':'normal metadata only','freeze':receipt(HERE/'freeze.json')})
  for row in freeze['sources']+freeze['inputs']:need(receipt(row['path'])==row,'frozen source/control input changed: '+row['path'])
  from scar.analysis import source_attachments as sa
  from scar.analysis.code_witness import CodeWitnessStore,CodeWitnessBudget
  from scar.analysis.compiler_witness_archives import CompilerWitnessArchives,CompilerArchiveBudget
  from scar.analysis.source_entry_catalog import SourceEntryCatalog
  # Budget wrappers delegate to the unchanged normal readers; they neither cache
  # receipts nor skip verification. Graph/CodeType APIs are forbidden in G0.
  plain,aux,store_read=sa._plain,sa.SourceAttachments._aux,CodeWitnessStore._read
  def bounded_plain(path,*args):
   n=Path(path).stat().st_size;token=meter.begin(path,n,n,'plain_manifest');result=plain(path,*args);meter.complete(token);return result
  def bounded_aux(self,locator,source_root,family):
   path,artifact=self._artifact_path(locator,source_root,family)
   if(str(path),artifact['canonical_sha256'])in self._auxiliary:return aux(self,locator,source_root,family)
   token=meter.begin(path,artifact['compressed_bytes'],artifact['canonical_bytes'],'source_provider_auxiliary')
   result=aux(self,locator,source_root,family);meter.complete(token);return result
  def bounded_store_read(self,relative,limit):
   p=self.root/relative;n=p.stat().st_size;token=meter.begin(p,n,n,'archive_manifest');result=store_read(self,relative,limit);need(len(result)==n,'archive read size changed');meter.complete(token);return result
  def forbidden(*a,**k):raise ValueError('G0 forbids graph/CodeType resolution or source preparation')
  sa._plain=bounded_plain;sa.SourceAttachments._aux=bounded_aux;CodeWitnessStore._read=bounded_store_read
  sa.SourceAttachments._view=forbidden;CodeWitnessStore.resolve=forbidden
  owner=sa.SourceAttachments(freeze['continuation']['path'],expected_report_sha256=freeze['continuation']['sha256'],project_root='/home/zyf/AAA/le-wm',
   budget=sa.SourceAttachmentBudget(max_report_bytes=8_000_000,max_files=128,max_codes=1024,max_artifact_bytes=128_000_000,max_record_bytes=128_000_000))
  # max_record_bytes retains the original *unread graph locator* contract. The
  # wrappers enforce <=8MB on every actually-read metadata record.
  archives=CompilerWitnessArchives(tuple((r['directory'],r['manifest']['sha256'])for r in freeze['archives']),
   store_budget=CodeWitnessBudget(max_compile_keys=20,max_source_files=32,max_manifest_bytes=8_000_000),
   budget=CompilerArchiveBudget(max_archives=2,max_total_modules=64,max_total_sources=64))
  catalog=SourceEntryCatalog(archives=archives,admissions=(owner,),projects=(),max_groups=1024,max_candidates=512,max_selected_decode_bytes=128_000_000)
  metadata=catalog.metadata();rows=owner.catalog_rows();external=[r for r in rows if r['status']=='SOURCE_VERIFIED']
  need(len(rows)==817 and sum(r['entered_invocations']for r in rows)==100438 and len(external)==243,'original LeWM denominator changed')
  need(metadata['entered_code_groups']==817 and metadata['entered_invocations']==100438,'normal catalog changed original scope')
  flags=inspect.CO_GENERATOR|inspect.CO_COROUTINE|inspect.CO_ASYNC_GENERATOR|inspect.CO_ITERABLE_COROUTINE
  original={(r['process_id'],r['code']):r for r in rows}
  candidates=metadata['candidates'];ordinary=[];resumable=[]
  for entry in candidates:
   (resumable if entry['basis']['captured']['flags']&flags else ordinary).append(entry)
  def window(entries):
   selected=[];files=set()
   for entry in sorted(entries,key=lambda x:(-x['calls'],x['entry_key'])):
    p=entry['basis']['source_snapshot']['path']
    if len(selected)>=16:break
    if p not in files and len(files)>=8:continue
    selected.append({'entry_key':entry['entry_key'],'calls':entry['calls'],'file':p,'status':entry['status'],'archive_variant_count':len(entry['archive_variants'])});files.add(p)
   return {'mechanical_selection':'call weight descending then entry_key; first16 ordinary entries within8 files','entries':selected,'files':len(files),'call_weight':sum(x['calls']for x in selected),'not_an_actual_dispatch_or_current_369749_body_count':True}
  ready=[r for r in ordinary if r['status']=='CANDIDATE_SOURCE_GRAPH_UNVERIFIED']
  missing=[r for r in ordinary if not r['archive_variants']]
  source_rows=owner._report['source_files'];graphs={}
  for row in source_rows:
   loc=row['source_graph_artifact']
   if loc is not None:
    art=loc['artifact'];graphs[(loc['origin'],art['canonical_sha256'])]=art
  need(owner.measurements().get('graph_artifacts_read',0)==0,'G0 decoded a source graph')
  activity=[dict(store.counts)for store in archives._stores.values()]
  need(all(all(v==0 for v in row.values())for row in activity),'G0 loaded/compiled CodeType or read target source')
  save('catalog.json',metadata)
  result={'schema':'scar.lewm-external-entry-g0/1','status':'METADATA_CATALOG_WITH_OPEN','scope':'original272038 source evidence; no current369749 dynamic qualification',
   'continuation':freeze['continuation'],'archives':freeze['archives'],'original_groups':817,'original_calls':100438,
   'external_verified_groups':len(external),'external_historical_call_weight':sum(r['entered_invocations']for r in external),
   'candidate_entries':len(candidates),'candidate_statuses':dict(Counter(r['status']for r in candidates)),
   'definition_source_present':sum(r['code_source_link']['definition']is not None and r['code_source_link']['source']is not None for r in external),
   'ordinary_candidates':len(ordinary),'resumable_candidates':len(resumable),'resumable_facet_independent_of_archive_availability':True,
   'metadata_existing_key_entries':sum(bool(r['archive_variants'])for r in candidates),'metadata_missing_key_entries':sum(not r['archive_variants']for r in candidates),
   'unsupported_lowering':'NOT_ASSESSED; no graph/CodeType/lower invocation','unique_external_sources':len(source_rows),
   'unique_declared_source_graphs':len(graphs),'source_graph_declared_stored_bytes':sum(a['compressed_bytes']for a in graphs.values()),
   'source_graph_declared_decoded_bytes':sum(a['canonical_bytes']for a in graphs.values()),'source_graph_bytes_read':0,
   'normal_owner_measurements':owner.measurements(),'archive_activity':activity,'metadata_io':meter.report(),
   'ready_readonly_window':window(ready),'missing_witness_acquisition_window':window(missing),
   'budget':freeze['budgets'],'graph_membership_established':False,'nested_descriptor_verified':False,
   'current_body_linked_calls':'NOT_MEASURED','source_prepare_lower_compile_target':False,'raw_trace_read':False,'metadata_contains_archived_source_and_provider_bytes':True,'SP5_origin_migrated':False,'first_stage_complete':False,'wall_seconds':time.monotonic()-START}
  for row in freeze['sources']+freeze['inputs']:need(receipt(row['path'])==row,'final source/control input changed')
  result['metadata_io']=meter.report();result['output_bytes_before_result']=OUTPUT_BYTES
  save('result.json',result);save('terminal.json',{'status':result['status'],'result':receipt(HERE/'result.json'),'wall_seconds':time.monotonic()-START,'first_stage_complete':False})
  print(json.dumps({'status':result['status'],'candidate_entries':len(candidates),'metadata_bytes':meter.stored+meter.decoded,'wall_seconds':time.monotonic()-START}),flush=True)
 except BaseException as error:
  save('failure.json',{'status':'FAILED_RETAINED','type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc(),'metadata_io':meter.report(),'wall_seconds':time.monotonic()-START,'first_stage_complete':False})
  raise

if __name__=='__main__':main()
