"""Two smallest same-file retained bodies; no target, lowering or compilation."""
from pathlib import Path
import hashlib,json,time,traceback,resource
from scar.analysis.program_composition import CompositionIndex
from scar.analysis.source_attachments import SourceAttachments,SourceAttachmentBudget
from scar.analysis.code_witness import CodeWitnessBudget
from scar.analysis.compiler_witness_archives import CompilerWitnessArchives,CompilerArchiveBudget
from scar.analysis.source_entry_catalog import SourceEntryCatalog
from scar.analysis.source_program_publication import plan_source_entry_publication,publish_source_entries

HERE=Path(__file__).resolve().parent
MAIN=Path('/home/zyf/AAA/scar-worktrees/structured-program-model')
CONFIG=Path('/home/zyf/AAA/scar-worktrees/source209-model/artifacts/experiments/source209_resume01_20261026/inputs.json')
BASE=MAIN/'artifacts/experiments/first_stage_source_publication_current_20261023/result/composition/index.json.gz'
def save(name,value):(HERE/name).write_text(json.dumps(value,sort_keys=True,ensure_ascii=False,indent=2)+'\n')
def pin(p):
 b=p.read_bytes();return{'path':str(p),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
started=time.monotonic();stage='normal-inputs';result={'target':0,'compile':0,'lower':0,'raw':0,'formal_current_publication':False}
try:
 resource.setrlimit(resource.RLIMIT_AS,(6*1024**3,)*2)
 config=json.loads(CONFIG.read_bytes());requests=tuple(json.loads((HERE/'selection.json').read_bytes()))
 parent=CompositionIndex(BASE,max_input_bytes=128_000_000,max_record_bytes=128_000_000)
 owner=SourceAttachments(config['continuation']['path'],expected_report_sha256=config['continuation']['sha256'],project_root=config['project_root'],budget=SourceAttachmentBudget(max_report_bytes=8_000_000,max_artifact_bytes=3_000_000_000,max_record_bytes=128_000_000,cached_files=2))
 archives=CompilerWitnessArchives(tuple((x['directory'],x['manifest']['sha256'])for x in config['archives']),store_budget=CodeWitnessBudget(max_compile_keys=94,max_source_files=94,max_source_bytes=8_000_000,max_module_bytes=16_000_000,max_archive_bytes=256_000_000,max_manifest_bytes=8_000_000),budget=CompilerArchiveBudget(max_archives=4,max_total_modules=256,max_total_sources=256,max_declared_payload_bytes=256_000_000))
 catalog=SourceEntryCatalog(archives=archives,admissions=(owner,),projects=(parent,),max_groups=8192,max_candidates=8192,max_selected_decode_bytes=3_000_000_000)
 stage='plan';print(stage,flush=True)
 plan=plan_source_entry_publication(parent,catalog,requests,max_programs=2,publication_version=3)
 stage='publisher';print(stage,flush=True);events=[]
 before=catalog.measurements()
 published=publish_source_entries(parent,catalog,requests,HERE/'publication',plan=plan,max_programs=2,max_operations_per_body=10000,max_record_bytes=128_000_000,progress=events.append)
 after=catalog.measurements();assert after['ast_parses']-before['ast_parses']==1
 assert len(events)==2
 result.update(publication=published,publication_ast_parses=after['ast_parses']-before['ast_parses'],publication_events=events)
 stage='factory-reader';print(stage,flush=True)
 calls=[];ordinary_init=CompositionIndex.__init__
 def measured_init(self,*args,**kwargs):
  calls.append(str(args[0]));ordinary_init(self,*args,**kwargs)
 CompositionIndex.__init__=measured_init
 try:
  composition=CompositionIndex.from_source_entry_publication(published['manifest'],expected_sha256=published['sha256'],archives=archives,max_input_bytes=128_000_000,max_record_bytes=128_000_000,max_programs=2,max_operations_per_body=10000,max_catalog_groups=8192,max_catalog_entries=8192,max_selected_decode_bytes=3_000_000_000,attachment_budget=owner.budget)
 finally:CompositionIndex.__init__=ordinary_init
 assert len(calls)==1,calls
 state=composition._require_entry_publication();queries=[]
 for item in state['checked']:
  reference=composition.body_reference(item['entry'].reference);typed=composition.typed_qualified_body(reference)
  assert typed.body.graph.root==reference.identity and typed.source_shape_verified and typed.source_code_witness_verified
  queries.append({'entry_key':item['entry'].key,'namespace':typed.namespace,'operations':len(typed.body.graph.operations)})
 assert len(queries)==2
 result.update(factory_composition_constructors=len(calls),queries=queries,reader_ast_parses=state['catalog'].measurements()['ast_parses'])
 stage='callback-mutation';print(stage,flush=True)
 original=parent.document['files_total'];rejected=False
 try:
  with catalog._ordinary_read_session(parent) as session:
   def mutate(_):parent.document['files_total']=original+1
   session.progress(mutate,{})
 except ValueError as error:rejected=True;result['callback_mutation_error']=str(error)
 finally:parent.document['files_total']=original
 assert rejected
 parent.source_inputs();catalog.require_unchanged()
 result.update(status='ORDINARY_TWO_BODY_READ_SESSION_PASS_WITH_OPEN',callback_mutation_rejected=True,post_restoration_public_guards='PASS',readonly=[s.counts for s in archives._stores.values()],source_pins=[pin(Path(__file__).parents[3]/'scar/analysis'/n)for n in('program_composition.py','source_entry_catalog.py','source_program_publication.py')])
except BaseException as e:
 result.update(status='FAILED_RETAINED',stage=stage,error_type=type(e).__name__,error=str(e),traceback=traceback.format_exc())
result.update(elapsed_s=time.monotonic()-started,RSS_peak_KiB=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
save('result.json',result);print(json.dumps(result,ensure_ascii=False),flush=True)
raise SystemExit(0 if result['status']=='ORDINARY_TWO_BODY_READ_SESSION_PASS_WITH_OPEN'else 1)
