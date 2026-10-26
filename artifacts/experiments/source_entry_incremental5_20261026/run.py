"""Admit five original SP5s; retain the exact196 parent refs, then query one new body."""
from pathlib import Path
from hashlib import sha256
import json,os,resource,signal,threading,time,traceback
ROOT=Path(__file__).resolve().parent;REPO=ROOT.parents[2];started=time.monotonic();phase='preflight';done=threading.Event()
def write(name,value):
 with (ROOT/name).open('x')as stream:json.dump(value,stream,sort_keys=True,separators=(',',':'));stream.write('\n')
def sha(path):return sha256(Path(path).read_bytes()).hexdigest()
def heartbeat():
 while not done.wait(20):print(json.dumps({'pid':os.getpid(),'phase':phase,'elapsed_s':time.monotonic()-started,'closed_admission_rows':len(tuple((ROOT/'result/delta/admissions').glob('*.json'))),'new_cp2_files':len(tuple((ROOT/'result/delta/bodies').glob('*.json.gz')))}),flush=True)
def timeout(*_):raise TimeoutError('single formal incremental gate exceeded1800s wall ceiling')
resource.setrlimit(resource.RLIMIT_AS,(8*1024**3,8*1024**3));resource.setrlimit(resource.RLIMIT_CPU,(1800,1800))
signal.signal(signal.SIGALRM,timeout);signal.alarm(1800)
threading.Thread(target=heartbeat,daemon=True).start()
pins={str(p.relative_to(REPO)):sha(p)for p in sorted((REPO/'scar').rglob('*.py'))}
write('SOURCE_BEFORE.json',{'head':'fe6cf343','source_sha256':pins,'entry_sha256':sha(__file__),'pid':os.getpid()})
print(json.dumps({'pid':os.getpid(),'phase':phase,'frozen_source_count':len(pins),'head':'fe6cf343'}),flush=True)
record={'status':'FAILED_RETAINED_WITH_OPEN','failure':None,'source_scope_run':272038,'lower':0,'compile':0,'target':0,'raw':0,'currentRun_binding':0}
try:
 from scar.analysis.source_entry_incremental import collect_source_entry_deltas,publish_source_entry_deltas,read_source_entry_publication_body
 from scar.ir.program.providers import ProviderArtifact
 from scar.analysis.program_composition import CompositionIndex
 from scar.analysis.source_attachments import SourceAttachments,SourceAttachmentBudget
 from scar.analysis.compiler_witness_archives import CompilerWitnessArchives,CompilerArchiveBudget
 from scar.analysis.code_witness import CodeWitnessBudget
 from scar.analysis.source_entry_catalog import SourceEntryCatalog
 input_doc=json.loads((ROOT/'inputs.json').read_bytes());parent_ref=json.loads((ROOT/'parent-receipt.json').read_bytes())
 parent=ProviderArtifact(parent_ref['uri'],parent_ref['sha256'],parent_ref['size_bytes'],parent_ref['schema'])
 assert sha(parent.uri)==parent.sha256 and parent.sha256=='a124d78bb5e50e4ff96d1af2858357651cb9eda13918c328fd753a3a4bd4650b'
 declaration=json.loads(Path(parent.uri).read_bytes());assert declaration['schema_version']==3 and len(declaration['bodies'])==196
 delta_inputs=tuple(ProviderArtifact(r['delta']['path'],r['delta']['sha256'],r['delta']['bytes'],'scar.source-program-success-delta')for r in input_doc['entries'])
 requests,_=collect_source_entry_deltas(parent,delta_inputs);assert len(requests)==5 and {r['entry_key']for r in requests}=={r['entry_key']for r in input_doc['entries']}
 write('BUDGET.json',{'wall_seconds':1800,'cpu_seconds':1800,'address_space_bytes':8*1024**3,'new_programs':5,'max_operations_per_body':10000,'max_record_bytes':128_000_000,'max_metadata_bytes':32_000_000,'source_attachment_selected_plus_aux_bytes':3_000_000_000,'shared_writer_each_reader_budget_stored_bytes':2*sum(r['source_program']['physical_bytes']for r in requests),'shared_writer_each_reader_budget_decoded_bytes':2*sum(r['source_program']['decoded_bytes']for r in requests),'shared_output_budget_bytes':2*sum(r['source_program']['physical_bytes']for r in requests),'public_source_context_seconds':1800,'budget_roles':'normal public bounded APIs; counters per writer/reader; cumulative whole-process decoded+stored not globally metered'})
 phase='normal-original-owners'
 owner_ref=declaration['catalog_inputs']['admissions'][0]['report']['artifact'];owner_doc=json.loads(Path(owner_ref['uri']).read_bytes())
 owner=SourceAttachments(owner_ref['uri'],expected_report_sha256=owner_ref['sha256'],project_root=owner_doc['program_root'],budget=SourceAttachmentBudget(max_report_bytes=8_000_000,max_artifact_bytes=3_000_000_000,max_record_bytes=128_000_000,cached_files=2))
 archives=CompilerWitnessArchives(tuple((str(Path(r['path']).parent),r['sha256'])for r in declaration['catalog_inputs']['archives']),store_budget=CodeWitnessBudget(max_compile_keys=256,max_source_files=256,max_source_bytes=8_000_000,max_module_bytes=16_000_000,max_archive_bytes=256_000_000,max_manifest_bytes=8_000_000),budget=CompilerArchiveBudget(max_archives=4,max_total_modules=256,max_total_sources=256,max_declared_payload_bytes=256_000_000))
 target=CompositionIndex(declaration['parent_composition']['path'],max_input_bytes=128_000_000,max_record_bytes=128_000_000)
 catalog=SourceEntryCatalog(archives=archives,admissions=(owner,),projects=(target,),max_groups=8192,max_candidates=8192,max_selected_decode_bytes=3_000_000_000)
 phase='normal-five-source-code-cp2-admissions'
 result=publish_source_entry_deltas(parent,delta_inputs,target,catalog,ROOT/'result',max_programs=5,max_operations_per_body=10000,max_record_bytes=128_000_000,max_metadata_bytes=32_000_000)
 assert result['retained_parent_bodies']==196 and result['normally_admitted_new_bodies']==5 and result['total_bodies']==201 and result['parent_bodies_replayed']is False and result['new_bodies_relowered']is False
 publication=result['publication'];new=json.loads(Path(result['delta_publication']['uri']).read_bytes())
 selected=new['bodies'][0]['entry_key'];assert selected in {r['entry_key']for r in requests}
 phase='one-selected-new-body-normal-query'
 checked=read_source_entry_publication_body(ProviderArtifact(publication['uri'],publication['sha256'],publication['size_bytes'],publication['schema']),selected,target,catalog,max_operations=10000,max_record_bytes=128_000_000)
 write('QUERY.json',{'entry_key':selected,'record':checked['record'],'graph_operations':len(checked['body'].graph.operations),'graph_root':checked['body'].graph.root.wire,'qualification':'one selected new body ordinary source/code/CP2 check; no full201 reader/currentRun qualification'})
 assert sha(parent.uri)==parent.sha256 and all(s.counts['compile_attempts']==0 for s in archives._stores.values())
 record.update(status='PUBLISHED_INCREMENTAL5_TO201_WITH_OPEN',publication=result,selected_query=selected,selected_query_operations=len(checked['body'].graph.operations),readonly_activity=[dict(s.counts)for s in archives._stores.values()],catalog_measurements=catalog.measurements(),old196_payload_replayed=False,full201_reader=False,whole_model_complete=False)
except BaseException as error:record['failure']={'phase':phase,'type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc()}
finally:
 signal.alarm(0);done.set();after={str(p.relative_to(REPO)):sha(p)for p in sorted((REPO/'scar').rglob('*.py'))}
 record.update(elapsed_seconds=time.monotonic()-started,pid=os.getpid(),source_unchanged=pins==after,self_maxrss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
 write('SOURCE_AFTER.json',{'source_sha256':after,'unchanged':pins==after})
 if pins!=after:record['status']='FAILED_SOURCE_CHANGED_WITH_OPEN'
 write('RESULT.json',record);print(json.dumps(record,sort_keys=True),flush=True)
raise SystemExit(int(record['status']!='PUBLISHED_INCREMENTAL5_TO201_WITH_OPEN'))
