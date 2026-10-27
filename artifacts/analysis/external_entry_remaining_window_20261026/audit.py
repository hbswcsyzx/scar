"""Ordinary four-archive catalog and exact old-terminal subtraction; metadata only."""
from collections import Counter, defaultdict
import hashlib,json,time
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OLD=ROOT/'artifacts/experiments/lewm_external_source_entries_20261026'
NEW=ROOT/'artifacts/experiments/lewm_remaining_compiler_gate_20261026/result/archive'
START=time.monotonic()

def canonical(x):return json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
def need(x,msg):
 if not x:raise ValueError(msg)
def receipt(p):
 p=Path(p);raw=p.read_bytes();return {'path':str(p),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def save(name,x):
 with(HERE/name).open('xb')as stream:stream.write(canonical(x)+b'\n')

class Meter:
 def __init__(self):self.stored=self.decoded=self.pending=0;self.calls=Counter()
 def begin(self,s,d,kind):
  need(self.stored+self.decoded+self.pending+s+d<=1_000_000_000,'metadata1GB ceiling before normal read')
  self.pending+=s+d;return s,d,kind
 def done(self,t):
  s,d,k=t;self.pending-=s+d;self.stored+=s;self.decoded+=d;self.calls[k]+=1
 def report(self):return {'stored_bytes':self.stored,'decoded_bytes':self.decoded,'stored_plus_decoded_bytes':self.stored+self.decoded,'pending_reserved_not_actual':self.pending,'calls':dict(self.calls),'ceiling_bytes':1_000_000_000,'scope':'all delegated owner manifests/auxiliary and four archive manifest reads; small controls and producer SHA separately recorded','partial_read_if_pending':'OPEN'}

def main():
 meter=Meter();controls=[]
 try:
  from scar.analysis import source_attachments as sa
  from scar.analysis.code_witness import CodeWitnessBudget,CodeWitnessStore
  from scar.analysis.compiler_witness_archives import CompilerArchiveBudget,CompilerWitnessArchives
  from scar.analysis.source_entry_catalog import SourceEntryCatalog
  names=('source_attachments.py','code_witness.py','compiler_witness_archives.py','source_entry_catalog.py','source_frontend_worklist.py')
  sources=[receipt(ROOT/'scar/analysis'/name)for name in names]
  config=json.loads((OLD/'inputs.json').read_bytes());controls.append(receipt(OLD/'inputs.json'))
  manifests=[r['manifest']for r in config['archives']]
  manifests.append({'path':str(NEW/'manifest.json'),'bytes':438185,'sha256':'33f6fdbc0765ec8787159ced5b1d4acda031e85aba16f77fe0eaab041bb26179'})
  for row in manifests+[config['continuation']]:need(receipt(row['path'])==row,'fixed original manifest differs')
  plain,aux,read=sa._plain,sa.SourceAttachments._aux,CodeWitnessStore._read
  def bounded_plain(path,*args):
   n=Path(path).stat().st_size;t=meter.begin(n,n,'owner_manifest');value=plain(path,*args);meter.done(t);return value
  def bounded_aux(self,locator,root,family):
   p,a=self._artifact_path(locator,root,family)
   if(str(p),a['canonical_sha256'])in self._auxiliary:return aux(self,locator,root,family)
   t=meter.begin(a['compressed_bytes'],a['canonical_bytes'],'auxiliary');value=aux(self,locator,root,family);meter.done(t);return value
  def bounded_read(self,relative,limit):
   need(relative=='manifest.json','pure metadata forbids archive payload/CodeType read')
   n=(self.root/relative).stat().st_size;t=meter.begin(n,n,'archive_manifest');value=read(self,relative,limit);meter.done(t);return value
  def forbidden(*a,**k):raise AssertionError('pure metadata forbids graph/CodeType/compile/lower')
  sa._plain=bounded_plain;sa.SourceAttachments._aux=bounded_aux;sa.SourceAttachments._view=forbidden
  CodeWitnessStore._read=bounded_read;CodeWitnessStore.resolve=forbidden
  owner=sa.SourceAttachments(config['continuation']['path'],expected_report_sha256=config['continuation']['sha256'],project_root=config['project_root'],budget=sa.SourceAttachmentBudget(max_report_bytes=8_000_000,max_artifact_bytes=512_000_000))
  archives=CompilerWitnessArchives(tuple((str(Path(r['path']).parent),r['sha256'])for r in manifests),
   store_budget=CodeWitnessBudget(max_compile_keys=94,max_source_files=94,max_source_bytes=8_000_000,max_module_bytes=16_000_000,max_archive_bytes=256_000_000,max_manifest_bytes=8_000_000),
   budget=CompilerArchiveBudget(max_archives=4,max_total_modules=256,max_total_sources=256,max_declared_payload_bytes=256_000_000))
  catalog=SourceEntryCatalog(admissions=(owner,),projects=(),archives=archives,max_groups=8192,max_candidates=8192,max_selected_decode_bytes=512_000_000)
  metadata=catalog.metadata()
  need(metadata['entered_code_groups']==817 and metadata['entered_invocations']==100438 and len(metadata['candidates'])==243,'full denominator changed')
  ready={r['entry_key']:r for r in metadata['candidates']if r['status']=='CANDIDATE_SOURCE_GRAPH_UNVERIFIED'}
  prior_plan=json.loads((OLD/'actual-plan/plan.json').read_bytes());controls.append(receipt(OLD/'actual-plan/plan.json'))
  old_rows={};old_reasons={};old_receipts=[]
  for p in sorted((OLD/'worker').glob('attempt-*/result.json')):
   row=json.loads(p.read_bytes());key=row['entry_key'];need(key not in old_rows,'duplicate original terminal key')
   old_rows[key]=row;old_receipts.append(receipt(p))
   if row['status']=='UNSUPPORTED':
    q=p.parent/'returned-metadata.json';m=json.loads(q.read_bytes())['metadata'];old_receipts.append(receipt(q))
    old_reasons[key]=sorted({g['detail']for g in m['gaps']if g['kind']=='UNSUPPORTED_SYNTAX'})
  need(len(old_rows)==33 and Counter(r['status']for r in old_rows.values())==Counter({'SUCCEEDED':26,'UNSUPPORTED':7}),'original33 terminals changed')
  need(set(old_rows)<=set(ready),'old terminal no longer exact same ready entry key')
  for key,row in old_rows.items():need(row['source_calls']==ready[key]['calls'],'old terminal weight differs from exact source entry')
  remaining=[r for r in metadata['candidates']if r['entry_key']in ready and r['entry_key']not in old_rows]
  declarations={};graph_gaps=[]
  for row in remaining:
   filename=row['basis']['source_snapshot']['path'];original=owner._files[filename]
   if original['source_graph_artifact']is None:
    graph_gaps.append({'entry_key':row['entry_key'],'source_path':filename,'frontier':'SOURCE_GRAPH_DECLARATION_UNAVAILABLE'});continue
   path,declaration=owner._artifact_path(original['source_graph_artifact'],original['source_root'],'graphs')
   need(path.stat().st_size==declaration['compressed_bytes'],'declared original graph stored size differs')
   declarations[filename]={'source_path':filename,'source_root':original['source_root'],'path':str(path),'original_locator':original['source_graph_artifact'],'declaration':declaration,'canonical_payload_verified_here':False}
  old_producer={'plan':receipt(OLD/'actual-plan/plan.json'),'plan_sha256':prior_plan['plan_sha256'],'profile':prior_plan['profile'],'capabilities':prior_plan['capabilities'],'producer':prior_plan['producer'],'producer_list_sha256':hashlib.sha256(canonical(prior_plan['producer'])).hexdigest()}
  accounting=[{'entry_key':r['entry_key'],'status':r['status'],'historical_calls':r['source_calls'],'recorded_unsupported_reasons':old_reasons.get(r['entry_key'],[])}for r in old_rows.values()]
  save('catalog.json',metadata)
  save('remaining-ready.json',{'status':'METADATA_ELIGIBLE_KEYS_NOT_DISPATCHED','selection':'all current normal ready keys minus exact original33 terminal keys; no package/function filter','entries':remaining,'old_excluded':accounting,'old_producer_and_capabilities':old_producer,'old_terminal_receipts':old_receipts,'source_graph_declarations':list(declarations.values()),'graph_declaration_gaps':graph_gaps,'new_graph_CodeType_evidence':False})
  measurements=owner.measurements();activity=[dict(s.counts)for s in archives._stores.values()]
  need(measurements.get('graph_artifacts_read',0)==0 and all(all(v==0 for v in row.values())for row in activity),'metadata read graph or CodeType')
  for row in manifests+[config['continuation']]+sources:need(receipt(row['path'])==row,'final source/control manifest changed')
  result={'status':'NORMAL_FOUR_ARCHIVE_CATALOG_REMAINING_METADATA_WITH_OPEN','original_groups':817,'original_calls':100438,'candidates':243,'candidate_statuses':dict(Counter(r['status']for r in metadata['candidates'])),'current_ready_entries':len(ready),'excluded_old_terminal_counts':dict(Counter(r['status']for r in old_rows.values())),'excluded_historical_weight':sum(r['source_calls']for r in old_rows.values()),'remaining_ready_entries':len(remaining),'remaining_historical_weight':sum(r['calls']for r in remaining),'remaining_unique_source_files':len({r['basis']['source_snapshot']['path']for r in remaining}),'remaining_declared_graph_files':len(declarations),'unique_declared_graph_stored_bytes':sum(r['declaration']['compressed_bytes']for r in declarations.values()),'unique_declared_graph_decoded_bytes':sum(r['declaration']['canonical_bytes']for r in declarations.values()),'remaining_unique_module_keys':len({v['module_key']for r in remaining for v in r['archive_variants']}),'resumable_frontiers':[{'entry_key':r['entry_key'],'status':r['status'],'historical_calls':r['calls']}for r in metadata['candidates']if r['status'].startswith('ENTRY_ADAPTER_MISSING:RESUMABLE')],'other_unready_frontiers':[{'entry_key':r['entry_key'],'status':r['status'],'historical_calls':r['calls']}for r in metadata['candidates']if r['entry_key']not in ready and not r['status'].startswith('ENTRY_ADAPTER_MISSING:RESUMABLE')],'graph_declaration_frontiers':graph_gaps,'actual_metadata_IO':meter.report(),'source_owner_measurements':measurements,'readonly_counts':activity,'source_pins':sources,'original_archive_manifests':manifests,'control_receipts':controls+old_receipts,'small_control_and_SHA_read_bytes_separate':sum(r['bytes']for r in controls+old_receipts+sources+manifests+[config['continuation']])*2,'control_SHA_scope':'estimate of explicit two source/manifest reads and controls; runtime import I/O remains unmetered','catalog':receipt(HERE/'catalog.json'),'remaining_ready':receipt(HERE/'remaining-ready.json'),'worklist_interface_frontier':'current plan_source_entries has no eligible_entry_keys/resume exclusion argument; this metadata key set is not an editable SourceEntryFrontendPlan or permission to mutate dispatch','old_UNSUPPORTED_scope':'retained only as original producer/profile/capability outcomes; not erased or reclassified as universal unsupported','source_scope':'original272038 static source catalog; no current369749 binding','Graph_CodeType_compile_lower_target':False,'official_source_snapshot':858,'official_runtime_calls':6882,'whole_first_stage_complete':False,'elapsed_s':time.monotonic()-START}
  save('result.json',result)
  print(json.dumps({k:v for k,v in result.items()if k not in ('source_pins','original_archive_manifests','control_receipts','resumable_frontiers','other_unready_frontiers','graph_declaration_frontiers')},sort_keys=True),flush=True)
 except BaseException as error:
  save('failure.json',{'type':type(error).__name__,'detail':str(error),'metadata_IO':meter.report(),'elapsed_s':time.monotonic()-START})
  raise

if __name__=='__main__':main()
