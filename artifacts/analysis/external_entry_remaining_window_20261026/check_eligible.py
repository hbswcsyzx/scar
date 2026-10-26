"""Three metadata-only public planner checks on one normal four-archive catalog."""
from collections import Counter
from dataclasses import asdict
import hashlib,importlib.util,json,time
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OLD=ROOT/'artifacts/experiments/lewm_external_source_entries_20261026'
NEW=ROOT/'artifacts/experiments/lewm_remaining_compiler_gate_20261026/result/archive'

def canonical(x):return json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
def need(x,msg):
 if not x:raise ValueError(msg)
def receipt(p):
 p=Path(p);raw=p.read_bytes();return {'path':str(p),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def save(name,x):
 with(HERE/name).open('xb')as s:s.write(canonical(x)+b'\n')

def main():
 tick=time.monotonic()
 spec=importlib.util.spec_from_file_location('saved_remaining_metadata_meter',HERE/'audit.py')
 saved=importlib.util.module_from_spec(spec);spec.loader.exec_module(saved)
 meter=saved.Meter()
 from scar.analysis import source_attachments as sa
 from scar.analysis.code_witness import CodeWitnessBudget,CodeWitnessStore
 from scar.analysis.compiler_witness_archives import CompilerArchiveBudget,CompilerWitnessArchives
 from scar.analysis.source_entry_catalog import SourceEntryCatalog
 from scar.analysis.source_frontend_worklist import SourceFrontendBudget,plan_source_entries
 plain,aux,read=sa._plain,sa.SourceAttachments._aux,CodeWitnessStore._read
 def bounded_plain(path,*args):
  n=Path(path).stat().st_size;t=meter.begin(n,n,'owner_manifest');v=plain(path,*args);meter.done(t);return v
 def bounded_aux(self,locator,root,family):
  p,a=self._artifact_path(locator,root,family)
  if(str(p),a['canonical_sha256'])in self._auxiliary:return aux(self,locator,root,family)
  t=meter.begin(a['compressed_bytes'],a['canonical_bytes'],'auxiliary');v=aux(self,locator,root,family);meter.done(t);return v
 def bounded_read(self,relative,limit):
  need(relative=='manifest.json','metadata check forbids archive payload')
  n=(self.root/relative).stat().st_size;t=meter.begin(n,n,'archive_manifest');v=read(self,relative,limit);meter.done(t);return v
 def forbidden(*a,**k):raise AssertionError('metadata API check forbids graph/CodeType/compile')
 sa._plain=bounded_plain;sa.SourceAttachments._aux=bounded_aux;sa.SourceAttachments._view=forbidden
 CodeWitnessStore._read=bounded_read;CodeWitnessStore.resolve=forbidden
 config=json.loads((OLD/'inputs.json').read_bytes());manifests=[r['manifest']for r in config['archives']]
 manifests.append({'path':str(NEW/'manifest.json'),'sha256':'33f6fdbc0765ec8787159ced5b1d4acda031e85aba16f77fe0eaab041bb26179','bytes':438185})
 for row in manifests+[config['continuation']]:need(receipt(row['path'])==row,'fixed manifest differs')
 owner=sa.SourceAttachments(config['continuation']['path'],expected_report_sha256=config['continuation']['sha256'],project_root=config['project_root'],budget=sa.SourceAttachmentBudget(max_report_bytes=8_000_000,max_artifact_bytes=512_000_000))
 archives=CompilerWitnessArchives(tuple((str(Path(r['path']).parent),r['sha256'])for r in manifests),store_budget=CodeWitnessBudget(max_compile_keys=94,max_source_files=94,max_source_bytes=8_000_000,max_module_bytes=16_000_000,max_archive_bytes=256_000_000,max_manifest_bytes=8_000_000),budget=CompilerArchiveBudget(max_archives=4,max_total_modules=256,max_total_sources=256,max_declared_payload_bytes=256_000_000))
 catalog=SourceEntryCatalog(admissions=(owner,),projects=(),archives=archives,max_groups=8192,max_candidates=8192,max_selected_decode_bytes=512_000_000)
 metadata=catalog.metadata();ready={r['entry_key']for r in metadata['candidates']if r['status']=='CANDIDATE_SOURCE_GRAPH_UNVERIFIED'}
 old={json.loads(p.read_bytes())['entry_key']for p in (OLD/'worker').glob('attempt-*/result.json')}
 keys=tuple(sorted(ready-old));saved_remaining=json.loads((HERE/'remaining-ready.json').read_bytes())
 need(len(old)==33 and len(keys)==209 and set(keys)=={r['entry_key']for r in saved_remaining['entries']},'fresh normal metadata/old terminal subtraction differs')
 budget=SourceFrontendBudget(max_catalog_files=256,max_catalog_bodies=8192,max_catalog_groups=8192,max_dispatch_bodies=256,max_source_files=128)
 plan=plan_source_entries(catalog,budget=budget,eligible_entry_keys=keys,dispatch_order='FILE_GROUPED_V1')
 need(len(plan.entries)==243 and len(plan.groups)==817 and plan.document['summary']['current_calls']==100438 and len(plan.dispatch)==209,'positive metadata selection changed full catalog or dispatch')
 need({r['entry_key']for r in plan.dispatch}==set(keys)and not(set(old)&{r['entry_key']for r in plan.dispatch}),'positive dispatch repeated original terminal keys')
 need(plan.document['selection']['eligible_entry_keys']==list(keys)and plan.document['selection']['eligible_entry_keys_sha256']==hashlib.sha256(canonical(list(keys))).hexdigest(),'selection keys/digest differ')
 plan.require_unchanged()
 errors={}
 for label,bad in (('duplicate',(keys[0],keys[0])),('unknown',('not-a-catalog-entry-key',))):
  try:plan_source_entries(catalog,budget=budget,eligible_entry_keys=bad,dispatch_order='FILE_GROUPED_V1')
  except ValueError as error:errors[label]={'type':type(error).__name__,'detail':str(error)}
  else:raise AssertionError(label+' entry selection accepted')
 need(owner.measurements().get('graph_artifacts_read',0)==0 and all(all(v==0 for v in s.counts.values())for s in archives._stores.values()),'metadata check loaded graph or CodeType')
 save('eligible-positive-plan.json',{**plan.document,'plan_sha256':plan.digest})
 save('eligible-api-check.json',{'status':'THREE_METADATA_API_CHECKS_PASS','positive':{'eligible_keys':209,'dispatch_entries':209,'full_candidates':243,'full_groups':817,'full_calls':100438,'dispatch_files':len({r['file_key']for r in plan.dispatch}),'excluded_old_terminal_keys':33,'plan_sha256':plan.digest,'eligible_keys_sha256':plan.document['selection']['eligible_entry_keys_sha256']},'negative_rejections':errors,'normal_metadata_IO':meter.report(),'producer_file':receipt(ROOT/'scar/analysis/source_frontend_worklist.py'),'metadata_check_budget':asdict(budget),'real_worker_budget_authorized_here':False,'source_scope':'original272038 static catalog; no current369749 qualification','catalog_lifecycle':'one fresh normal metadata reader; prior process had exited; no JSON owner restoration','graph_CodeType_compile_lower_target':False,'worker_run':False,'elapsed_s':time.monotonic()-tick})
 print(json.dumps(json.loads((HERE/'eligible-api-check.json').read_bytes()),sort_keys=True),flush=True)

if __name__=='__main__':main()
