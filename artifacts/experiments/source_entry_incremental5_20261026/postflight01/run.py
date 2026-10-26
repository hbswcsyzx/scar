"""Independent end-parent check plus one new selected body; original exit1 retained."""
from pathlib import Path
from hashlib import sha256
import json,os,resource,signal,time,traceback
HERE=Path(__file__).resolve().parent;OLD=HERE.parent;REPO=OLD.parents[2];started=time.monotonic()
def sha(p):return sha256(Path(p).read_bytes()).hexdigest()
def write(name,d):
 with(HERE/name).open('x')as s:json.dump(d,s,sort_keys=True,separators=(',',':'));s.write('\n')
def deadline(*_):raise TimeoutError('independent selected-body postflight1800s ceiling')
resource.setrlimit(resource.RLIMIT_AS,(8*1024**3,8*1024**3));signal.signal(signal.SIGALRM,deadline);signal.alarm(1800)
pins={str(p.relative_to(REPO)):sha(p)for p in sorted((REPO/'scar').rglob('*.py'))};original=json.loads((OLD/'RESULT.json').read_bytes());assert original['status']=='FAILED_RETAINED_WITH_OPEN'
record={'status':'FAILED_RETAINED_WITH_OPEN','failure':None,'original_gate_status':original['status'],'original_gate_exit':1,'lower':0,'compile':0,'raw':0,'target':0,'publication_repeated':False,'currentRun_binding':0,'pid':os.getpid()}
print(json.dumps({'pid':os.getpid(),'phase':'independent-parent-and-five-admission-metadata'}),flush=True)
try:
 from scar.analysis.source_entry_incremental import _publication,read_source_entry_publication_body
 from scar.analysis.program_composition import CompositionIndex
 from scar.analysis.source_attachments import SourceAttachments,SourceAttachmentBudget
 from scar.analysis.compiler_witness_archives import CompilerWitnessArchives,CompilerArchiveBudget
 from scar.analysis.code_witness import CodeWitnessBudget
 from scar.analysis.source_entry_catalog import SourceEntryCatalog
 from scar.ir.program.providers import ProviderArtifact
 inc=json.loads((OLD/'result/increment.json').read_bytes());typed=lambda r:ProviderArtifact(r['uri'],r['sha256'],r['size_bytes'],r['schema'])
 parent=_publication(typed(inc['parent_publication']),32_000_000);publication=_publication(typed(inc['publication']),32_000_000);delta=_publication(typed(inc['delta_publication']),32_000_000)
 assert len(parent['bodies'])==196 and len(delta['bodies'])==5 and len(publication['bodies'])==201
 assert publication['bodies'][:196]==parent['bodies'] and publication['bodies'][196:]==delta['bodies']
 assert publication['plan']['expectations'][:196]==parent['plan']['expectations'] and publication['plan']['expectations'][196:]==delta['plan']['expectations']
 journals=sorted((OLD/'result/delta/admissions').glob('*.json'));assert len(journals)==5
 actual={json.loads(p.read_bytes())['record']['entry_key']:json.loads(p.read_bytes())for p in journals}
 checks=[]
 for row in delta['bodies']:
  journal=actual[row['entry_key']];assert journal['record']==row and journal['plan_sha256']==delta['plan_sha256']
  ref=row['checkpoint'];raw=Path(ref['uri']).read_bytes();assert len(raw)==ref['physical_bytes'] and sha256(raw).hexdigest()==ref['physical_sha256']
  checks.append({'entry_key':row['entry_key'],'checkpoint':ref,'closed_journal_matches':True,'stored_checkpoint_verified':True})
 restoration=Path('/home/zyf/AAA/scar-worktrees/source-entry-project/artifacts/analysis/source_entry_full_binding_20261026/RESTORATION_MANIFEST.json')
 record['restoration_receipt']={'path':str(restoration),'bytes':restoration.stat().st_size,'sha256':sha(restoration)}
 print(json.dumps({'pid':os.getpid(),'phase':'normal-original-owners-then-one-new-query','new_admissions':5,'retained_parent':196}),flush=True)
 owner_ref=parent['catalog_inputs']['admissions'][0]['report']['artifact'];owner_doc=json.loads(Path(owner_ref['uri']).read_bytes())
 owner=SourceAttachments(owner_ref['uri'],expected_report_sha256=owner_ref['sha256'],project_root=owner_doc['program_root'],budget=SourceAttachmentBudget(max_report_bytes=8_000_000,max_artifact_bytes=3_000_000_000,max_record_bytes=128_000_000,cached_files=2))
 archives=CompilerWitnessArchives(tuple((str(Path(r['path']).parent),r['sha256'])for r in parent['catalog_inputs']['archives']),store_budget=CodeWitnessBudget(max_compile_keys=256,max_source_files=256,max_source_bytes=8_000_000,max_module_bytes=16_000_000,max_archive_bytes=256_000_000,max_manifest_bytes=8_000_000),budget=CompilerArchiveBudget(max_archives=4,max_total_modules=256,max_total_sources=256,max_declared_payload_bytes=256_000_000))
 target=CompositionIndex(parent['parent_composition']['path'],max_input_bytes=128_000_000,max_record_bytes=128_000_000)
 catalog=SourceEntryCatalog(archives=archives,admissions=(owner,),projects=(target,),max_groups=8192,max_candidates=8192,max_selected_decode_bytes=3_000_000_000)
 selected=delta['bodies'][0]['entry_key'];print(json.dumps({'pid':os.getpid(),'phase':'one-selected-new-normal-source-code-cp2','entry_key':selected}),flush=True)
 checked=read_source_entry_publication_body(typed(inc['publication']),selected,target,catalog,max_operations=10000,max_record_bytes=128_000_000)
 record.update(status='INDEPENDENT_PARENT_CHECK_AND_SELECTED_NEW_BODY_PASS_WITH_OPEN',publication=inc['publication'],delta_publication=inc['delta_publication'],retained_parent_bodies=196,normally_admitted_new_bodies=5,total_bodies=201,new_journal_checks=checks,selected_query={'entry_key':selected,'record':checked['record'],'graph_operations':len(checked['body'].graph.operations),'root':checked['body'].graph.root.wire},readonly_activity=[dict(s.counts)for s in archives._stores.values()],old196_sp5_replayed=False,full201_reader=False,source_scope_run=272038,whole_model_complete=False)
except BaseException as error:record['failure']={'type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc()}
finally:
 signal.alarm(0);after={str(p.relative_to(REPO)):sha(p)for p in sorted((REPO/'scar').rglob('*.py'))}
 record.update(elapsed_seconds=time.monotonic()-started,source_unchanged=pins==after,source_sha256=pins,self_maxrss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
 write('RESULT.json',record);print(json.dumps({k:v for k,v in record.items()if k not in('source_sha256','selected_query','new_journal_checks')},sort_keys=True),flush=True)
raise SystemExit(int(record['status']!='INDEPENDENT_PARENT_CHECK_AND_SELECTED_NEW_BODY_PASS_WITH_OPEN'))
