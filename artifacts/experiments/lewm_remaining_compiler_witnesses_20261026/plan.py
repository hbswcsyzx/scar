"""All missing original compiler witnesses: ordinary metadata plan, never acquire."""
from collections import Counter
import base64
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
import time
import tokenize

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
INPUTS=ROOT/'artifacts/experiments/lewm_external_source_entries_20261026/inputs.json'
START=time.monotonic()

def canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
def need(value,message):
 if not value:raise ValueError(message)
def receipt(path):
 path=Path(path);raw=path.read_bytes();return {'path':str(path),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def save(name,value):
 raw=canonical(value)+b'\n';need(len(raw)<=64_000_000,'metadata output exceeds64MB')
 with(HERE/name).open('xb')as stream:stream.write(raw)

class Meter:
 def __init__(self):self.stored=self.decoded=self.pending=0;self.calls=Counter()
 def begin(self,s,d,k):
  need(self.stored+self.decoded+self.pending+s+d<=1_000_000_000,'metadata1GB ceiling before normal read')
  self.pending+=s+d;return s,d,k
 def done(self,t):
  s,d,k=t;self.pending-=s+d;self.stored+=s;self.decoded+=d;self.calls[k]+=1
 def report(self):return {'stored_bytes':self.stored,'decoded_bytes':self.decoded,'stored_plus_decoded_bytes':self.stored+self.decoded,'pending':self.pending,'calls':dict(self.calls),'ceiling_bytes':1_000_000_000,'scope':'normal owner manifest/auxiliary and readonly archive manifest reads; control/source SHA and interpreter import I/O separate','partial_read_on_error':'OPEN if pending nonzero'}

def main():
 meter=Meter()
 try:
  need(not(HERE/'plan.json').exists(),'metadata plan output must be fresh')
  config=json.loads(INPUTS.read_bytes())
  from scar.analysis import source_attachments as sa
  from scar.analysis.code_witness import CodeWitnessBudget,CodeWitnessStore
  from scar.analysis.compiler_witness_archives import CompilerArchiveBudget,CompilerWitnessArchives,ObservedAcquisitionBudget,plan_attachment_witness_acquisition
  from scar.analysis.source_entry_catalog import SourceEntryCatalog
  from scar.ir.program.call_demand import EnteredCallCode
  from scar.ir.record_codec import encode
  sources=[receipt(ROOT/'scar/analysis'/name)for name in ('source_attachments.py','code_witness.py','compiler_witness_archives.py','source_entry_catalog.py')]
  plain,aux,read=sa._plain,sa.SourceAttachments._aux,CodeWitnessStore._read
  def bounded_plain(path,*args):
   n=Path(path).stat().st_size;t=meter.begin(n,n,'owner_manifest');v=plain(path,*args);meter.done(t);return v
  def bounded_aux(self,locator,root,family):
   p,a=self._artifact_path(locator,root,family)
   if(str(p),a['canonical_sha256'])in self._auxiliary:return aux(self,locator,root,family)
   t=meter.begin(a['compressed_bytes'],a['canonical_bytes'],'auxiliary');v=aux(self,locator,root,family);meter.done(t);return v
  def bounded_read(self,relative,limit):
   need(relative=='manifest.json','metadata plan forbids archive payload/CodeType reads')
   n=(self.root/relative).stat().st_size;t=meter.begin(n,n,'archive_manifest');v=read(self,relative,limit);meter.done(t);return v
  def forbidden(*a,**k):raise AssertionError('metadata plan forbids graph/CodeType/compile')
  sa._plain=bounded_plain;sa.SourceAttachments._aux=bounded_aux;sa.SourceAttachments._view=forbidden
  CodeWitnessStore._read=bounded_read;CodeWitnessStore.resolve=forbidden
  fixed=[config['continuation']]+[r['manifest']for r in config['archives']]
  for row in fixed:need(receipt(row['path'])==row,'original input changed')
  owner=sa.SourceAttachments(config['continuation']['path'],expected_report_sha256=config['continuation']['sha256'],project_root=config['project_root'],budget=sa.SourceAttachmentBudget(max_report_bytes=8_000_000,max_artifact_bytes=512_000_000))
  archives=CompilerWitnessArchives(tuple((r['directory'],r['manifest']['sha256'])for r in config['archives']),
   store_budget=CodeWitnessBudget(max_compile_keys=64,max_source_files=64,max_source_bytes=2_000_000,max_archive_bytes=64_000_000),
   budget=CompilerArchiveBudget(max_archives=3,max_total_modules=64,max_total_sources=64,max_declared_payload_bytes=64_000_000))
  catalog=SourceEntryCatalog(admissions=(owner,),projects=(),archives=archives,max_groups=8192,max_candidates=8192,max_selected_decode_bytes=512_000_000)
  metadata=catalog.metadata();missing=[r for r in metadata['candidates']if r['status']=='CODE_WITNESS_UNAVAILABLE']
  origins=[];selected=[]
  for candidate in missing:
   _owner,witness,captured,link=catalog._owners[candidate['entry_key']]
   need(_owner is owner,'candidate changed original owner')
   record=witness['record'];origin=EnteredCallCode(record['process_id'],record['code']);origins.append(origin)
   selected.append({'entry_key':candidate['entry_key'],'origin':encode(origin),'historical_calls':candidate['calls'],'captured':encode(captured),'snapshot':encode(link.snapshot)})
  need(len(metadata['groups'])==817 and metadata['entered_invocations']==100438 and len(metadata['candidates'])==243 and len(origins)==192,'original full catalog/remaining selection changed')
  budget=ObservedAcquisitionBudget()
  plan=plan_attachment_witness_acquisition(owner,archives,origins=tuple(origins),budget=budget)
  preferred={hashlib.sha256(canonical(r['preferred_compile_key'])).hexdigest():r['preferred_compile_key']for r in plan['requests']}
  allkeys={hashlib.sha256(canonical(k)).hexdigest():k for r in plan['requests']for k in r['recorded_compile_keys']}
  source_texts=[]
  for source in plan['source_text_inputs']:
   snapshot=source['snapshot'];row=owner._files[snapshot['path']]
   if row['snapshot_artifact']is None:
    source_texts.append({**source,'status':'SNAPSHOT_UNAVAILABLE'});continue
   doc,locator=owner._aux(row['snapshot_artifact'],row['source_root'],'sources')
   text=doc['decoded_text'].encode('utf-8');raw=base64.b64decode(doc['raw_base64'],validate=True);encoding,_=tokenize.detect_encoding(BytesIO(raw).readline)
   need('sha256:'+hashlib.sha256(text).hexdigest()==snapshot['fingerprint']and hashlib.sha256(raw).hexdigest()==source['raw_sha256']and len(raw)==source['raw_bytes'],'owned archived text differs')
   source_texts.append({**source,'status':'ORIGINAL_SNAPSHOT_NORMAL_OWNER_VERIFIED','normalized_bytes':len(text),'normalized_sha256':hashlib.sha256(text).hexdigest(),'original_encoding':encoding,'snapshot_locator':encode(locator)})
  need(owner.measurements().get('graph_artifacts_read',0)==0 and all(all(v==0 for v in s.counts.values())for s in archives._stores.values()),'metadata plan loaded graph or CodeType')
  for row in fixed+sources:need(receipt(row['path'])==row,'final source/input changed')
  save('plan.json',plan)
  save('workset.json',{'schema':'scar.remaining-attachment-compiler-workset/1','selection':'all normal SourceEntryCatalog CODE_WITNESS_UNAVAILABLE candidates, no name/package filtering','source_catalog_denominators':{'groups':817,'calls':100438,'source_verified_candidates':243},'catalog_statuses':dict(Counter(r['status']for r in metadata['candidates'])),'selected_origins':selected,'normal_plan':receipt(HERE/'plan.json'),'source_texts':source_texts,'preferred_keys':preferred,'all_recorded_keys':allkeys,'original_scope':'272038 static observed code evidence; no current369749 binding','graph_definition_membership':'NOT_CHECKED','live_owner_serialized':False})
  good=[r for r in source_texts if r['status']=='ORIGINAL_SNAPSHOT_NORMAL_OWNER_VERIFIED']
  future_guard_reads=2*len(plan['requests'])+4
  normal_guard=2*config['continuation']['bytes']
  result={'status':'ALL_REMAINING_COMPILER_METADATA_PLANNED_NOT_COMPILED','original_groups':817,'original_calls':100438,'source_verified_candidates':243,'catalog_statuses':dict(Counter(r['status']for r in metadata['candidates'])),'selected_missing_origins':len(origins),'requests':len(plan['requests']),'selected_historical_call_weight':sum(r['historical_calls']for r in selected),'unique_preferred_keys':len(preferred),'unique_all_recorded_keys':len(allkeys),'unique_source_files':len(source_texts),'snapshot_available':len(good),'snapshot_missing':len(source_texts)-len(good),'raw_source_bytes':sum(r['raw_bytes']for r in good),'normalized_source_bytes':sum(r['normalized_bytes']for r in good),'max_raw_source_bytes':max((r['raw_bytes']for r in good),default=0),'max_normalized_source_bytes':max((r['normalized_bytes']for r in good),default=0),'captured_python_builds':plan['captured_python_builds'],'compiler_python_build':plan['compiler_python_build'],'captured_python_build_matches':plan['captured_python_build_matches'],'frontier_counts':dict(Counter(r['status']for r in plan['frontiers'])),'existing_module_metadata_for_selected_requests':sum(bool(r['available_module_metadata'])for r in plan['requests']),'normal_metadata_IO':meter.report(),'normal_owner_measurements':owner.measurements(),'future_writer_guard_estimate':{'owner_full_reads':future_guard_reads,'stored_plus_decoded_bytes':future_guard_reads*normal_guard,'assumptions':'two require_unchanged per archived_source admission per request, plus conservative four plan/final checks; archive receipt and other metadata extra; unchanged ordinary guard','source_text_inputs_reused_cached_normal_owner_snapshot_metadata_here':True},'ordinary_acquisition_default_max_attempts':budget.max_attempts,'future_acquisition_requires_at_least_attempts':len(plan['requests']),'future_new_archive_requires_preferred_compile_key_capacity':len(preferred),'future_new_archive_requires_source_files':len(good),'source_reader_pins':sources,'fixed_inputs':fixed,'control_input':receipt(INPUTS),'plan':receipt(HERE/'plan.json'),'workset':receipt(HERE/'workset.json'),'code_graph_lower_compile_target':False,'whole_first_stage_complete':False,'elapsed_s':time.monotonic()-START}
  save('result.json',result)
  print(json.dumps({k:v for k,v in result.items()if k not in ('fixed_inputs','source_reader_pins','captured_python_builds','compiler_python_build')},sort_keys=True),flush=True)
 except BaseException as error:
  save('failure.json',{'status':'METADATA_FAILED_RETAINED','type':type(error).__name__,'detail':str(error),'metadata_IO':meter.report(),'elapsed_s':time.monotonic()-START})
  raise

if __name__=='__main__':main()
