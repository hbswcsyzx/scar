"""One original attachment compiler acquisition; no graph/lower/target execution."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import resource
import signal
import time
import traceback

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
START=time.monotonic()
CONTROL=0

def canonical(x):return json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
def need(x,msg):
 if not x:raise ValueError(msg)
def receipt(p):
 global CONTROL
 p=Path(p);h=hashlib.sha256();n=0
 with p.open('rb')as stream:
  while raw:=stream.read(1048576):h.update(raw);n+=len(raw)
 CONTROL+=n
 return {'path':str(p.resolve()),'sha256':h.hexdigest(),'bytes':n}
def save(name,x):
 raw=canonical(x)+b'\n';need(len(raw)<=8_000_000,'gate record exceeds8MB')
 with(HERE/name).open('xb')as stream:stream.write(raw)

class Meter:
 def __init__(self,inputs):self.inputs=inputs;self.metadata_stored=0;self.metadata_decoded=0;self.archive_bytes=0;self.pending=0;self.calls=Counter()
 def begin(self,path,stored,decoded,kind):
  p=Path(path).resolve();need(str(p)in self.inputs or p.is_relative_to(HERE/'result'),'reader attempted undeclared input')
  need(max(stored,decoded)<=(16_000_000 if kind=='code_archive'else 8_000_000),'single metadata/code archive record exceeds its limit')
  amount=stored+decoded if kind=='metadata'else stored
  used=self.metadata_stored+self.metadata_decoded if kind=='metadata'else self.archive_bytes
  limit=3_000_000_000 if kind=='metadata'else 64_000_000
  need(used+self.pending+amount<=limit,'independent '+kind+' read budget exhausted before read')
  self.pending+=amount;return stored,decoded,kind,amount
 def complete(self,token):
  s,d,k,n=token;self.pending-=n;self.calls[k]+=1
  if k=='metadata':self.metadata_stored+=s;self.metadata_decoded+=d
  else:self.archive_bytes+=s
 def report(self):return {'metadata_stored_bytes':self.metadata_stored,'metadata_decoded_bytes':self.metadata_decoded,'metadata_total_bytes':self.metadata_stored+self.metadata_decoded,'code_archive_stored_read_bytes':self.archive_bytes,'pending_reserved_not_actual':self.pending,'calls':dict(self.calls),'source_control_SHA_bytes':CONTROL,'partial_read_actual_bytes':'OPEN if a normal reader raises after reservation'}

def main():
 freeze=json.loads((HERE/'freeze.json').read_bytes());work=json.loads((HERE/'workset.json').read_bytes());meter=Meter({r['path']for r in freeze['inputs']});writer_report=None
 class GateTermination(BaseException):pass
 def terminated(signum,frame):raise GateTermination('external gate terminated; original partial attempts retained')
 signal.signal(signal.SIGTERM,terminated)
 resource.setrlimit(resource.RLIMIT_AS,(4*1024**3,4*1024**3))
 try:
  need(not(HERE/'started.json').exists()and not(HERE/'result').exists(),'gate output must be fresh')
  save('started.json',{'status':'RUNNING','freeze':receipt(HERE/'freeze.json'),'scope':'original272038 static compiler evidence only'})
  for row in freeze['sources']+freeze['runtime']+freeze['inputs']:need(receipt(row['path'])==row,'frozen bytes changed: '+row['path'])
  for directory,names in freeze['original_archive_directory_membership'].items():
   need(sorted(str(p)for p in Path(directory).iterdir()if p.is_file())==names,'old archive membership changed')
  from scar.analysis import source_attachments as sa
  from scar.analysis.code_witness import CodeWitnessStore,CodeWitnessBudget
  from scar.analysis.compiler_witness_archives import CompilerWitnessArchives,CompilerArchiveBudget,ObservedAcquisitionBudget,plan_attachment_witness_acquisition,acquire_attachment_witnesses
  from scar.ir.program.call_demand import EnteredCallCode
  from scar.ir.record_codec import decode,encode
  from scar.ir.semantics_v2 import SourceSnapshot
  plain,aux,read=sa._plain,sa.SourceAttachments._aux,CodeWitnessStore._read
  def bounded_plain(path,*args):
   n=Path(path).stat().st_size;t=meter.begin(path,n,n,'metadata');v=plain(path,*args);meter.complete(t);return v
  def bounded_aux(self,locator,root,family):
   p,a=self._artifact_path(locator,root,family)
   if(str(p),a['canonical_sha256'])in self._auxiliary:return aux(self,locator,root,family)
   t=meter.begin(p,a['compressed_bytes'],a['canonical_bytes'],'metadata');v=aux(self,locator,root,family);meter.complete(t);return v
  def bounded_read(self,relative,limit):
   p=self.root/relative;n=p.stat().st_size;kind='metadata'if p.name=='manifest.json'else'code_archive'
   t=meter.begin(p,n,n if kind=='metadata'else 0,kind);v=read(self,relative,limit);need(len(v)==n,'archive read size changed');meter.complete(t);return v
  def forbidden(*a,**k):raise AssertionError('static compiler gate forbids source/ProgramGraph decode')
  sa._plain=bounded_plain;sa.SourceAttachments._aux=bounded_aux;CodeWitnessStore._read=bounded_read;sa.SourceAttachments._view=forbidden
  original=freeze['original_inputs']
  owner=sa.SourceAttachments(original['continuation']['path'],expected_report_sha256=original['continuation']['sha256'],project_root=original['project_root'],budget=sa.SourceAttachmentBudget())
  archives=CompilerWitnessArchives(tuple((r['directory'],r['manifest']['sha256'])for r in original['archives']),store_budget=CodeWitnessBudget(max_compile_keys=64,max_source_files=64,max_source_bytes=8_000_000,max_module_bytes=16_000_000,max_archive_bytes=256_000_000,max_manifest_bytes=8_000_000),budget=CompilerArchiveBudget(max_archives=3,max_total_modules=64,max_total_sources=64,max_declared_payload_bytes=256_000_000))
  origins=tuple(decode(EnteredCallCode,x)for x in work['origins'])
  budget=ObservedAcquisitionBudget(**work['normal_plan']['budget'])
  plan=plan_attachment_witness_acquisition(owner,archives,origins=origins,budget=budget)
  need(canonical(plan)==canonical(work['normal_plan']),'normal original window/source/compile-key plan changed')
  def progress(row):
   with(HERE/'progress.jsonl').open('a')as s:s.write(json.dumps({'elapsed_s':time.monotonic()-START,**row},sort_keys=True)+'\n')
  writer_report=acquire_attachment_witnesses(owner,archives,HERE/'result',origins=origins,
   producer={'kind':'ROOT_REVIEWED_STATIC_COMPILER_GATE','consumer_freeze':receipt(HERE/'freeze.json'),'original_workset':receipt(HERE/'workset.json')},
   budget=budget,store_budget=CodeWitnessBudget(max_compile_keys=94,max_source_files=94,max_source_bytes=8_000_000,max_module_bytes=16_000_000,max_archive_bytes=256_000_000,max_manifest_bytes=8_000_000),progress=progress)
  actual_plan=json.loads((HERE/'result/plan.json').read_bytes());need(canonical(actual_plan)==canonical(plan),'acquisition rederived a different source plan')
  need(writer_report['original_groups']==817 and writer_report['original_invocations']==100438,'original denominator changed')
  need(owner.measurements().get('graph_artifacts_read',0)==0 and writer_report['writer_counts']['source_bytes_read']==0,'compiler gate read graph/live source')
  manifest=json.loads((HERE/'result/archive/manifest.json').read_bytes())
  expected={canonical(r['snapshot']):r for r in work['source_texts']}
  for row in manifest['sources'].values():
   e=expected[canonical(row['snapshot'])];origin=row['archived_source_origin']
   need(row['original_raw_sha256']==e['raw_sha256']and row['original_encoding']==e['encoding']and row['artifact']['bytes']==e['normalized_bytes']
    and origin['artifact']==e['locator']and origin['declaration']==e['declaration']and origin['owner']==e['owner'],'new archive source provenance differs from fixed original')
  planned={canonical(x)for x in work['unique_preferred_compile_keys']}
  need(all(canonical(row['compile_key'])in planned for row in manifest['modules'].values()),'compiler emitted an unplanned key')
  for row in freeze['sources']+freeze['runtime']+freeze['inputs']:need(receipt(row['path'])==row,'final frozen bytes changed: '+row['path'])
  for directory,names in freeze['original_archive_directory_membership'].items():
   need(sorted(str(p)for p in Path(directory).iterdir()if p.is_file())==names,'final old archive membership changed')
  outputs=[{'path':str(p),'bytes':p.stat().st_size}for p in (HERE/'result').rglob('*')if p.is_file()]
  need(sum(r['bytes']for r in outputs)<=256_000_000,'post-stage output256MB exceeded')
  save('summary.json',{'status':writer_report['status'],'original_groups':817,'original_calls':100438,'selected_origins':len(work['origins']),'source_text_files':len(manifest['sources']),'unique_published_keys':len(manifest['modules']),
   'writer_counts':writer_report['writer_counts'],'readonly_counts':writer_report['read_only_counts'],'attempt_statuses':dict(Counter(r['status']for r in writer_report['attempts'])),'report':receipt(HERE/'result/report.json'),
   'metadata_and_archive_IO':meter.report(),'normal_owner_measurements':owner.measurements(),'post_stage_output_bytes':sum(r['bytes']for r in outputs),'outputs':outputs,
   'source_graph_CodeType_authority':'existing CodeWitnessStore compiler and independent readonly descriptor checks; no new graph authority',
   'current369749_body_calls':'NOT_MEASURED','graph_lower_target_capture':False,'runtime858_6882_unchanged':True,'first_stage_complete':False,'elapsed_s':time.monotonic()-START})
  print(json.dumps({'status':writer_report['status'],'elapsed_s':time.monotonic()-START,'writer_counts':writer_report['writer_counts'],'metadata_IO':meter.report()}),flush=True)
 except BaseException as error:
  save('failure.json',{'status':'FAILED_RETAINED','type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc(),'metadata_IO':meter.report(),'elapsed_s':time.monotonic()-START,'partial_outputs_retained':True,'no_automatic_retry':True,'first_stage_complete':False})
  raise

if __name__=='__main__':main()
