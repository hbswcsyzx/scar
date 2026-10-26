"""Normally admit only35 retained real source bodies and combine original refs."""
from pathlib import Path
import hashlib,json,resource,sys,time,threading,traceback
import scar.analysis
ISO=Path('/home/zyf/AAA/scar-worktrees/source-entry-project')
scar.analysis.__path__.append(str(ISO/'scar/analysis'))
from scar.analysis.source_entry_incremental import collect_source_entry_deltas,publish_source_entry_deltas,read_source_entry_publication_body
from scar.ir.program.providers import ProviderArtifact
from scar.analysis.program_composition import CompositionIndex
from scar.analysis.source_attachments import SourceAttachments,SourceAttachmentBudget
from scar.analysis.compiler_witness_archives import CompilerWitnessArchives,CompilerArchiveBudget
from scar.analysis.code_witness import CodeWitnessBudget
from scar.analysis.source_entry_catalog import SourceEntryCatalog
from scar.analysis.program_region_view import ProgramRegionView
ROOT=Path(__file__).resolve().parent
MAIN=Path('/home/zyf/AAA/scar-worktrees/structured-program-model')
DATA=Path('/home/zyf/AAA/scar-worktrees/source-try-model/artifacts/analysis')
start=time.monotonic();phase='metadata';done=threading.Event()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(name,value):(ROOT/name).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
def heartbeat():
 while not done.wait(20):print(json.dumps({'phase':phase,'elapsed_s':time.monotonic()-start,'checkpoint_files_present':len(list((ROOT/'result/delta/bodies').glob('*.json.gz')))}),flush=True)
threading.Thread(target=heartbeat,daemon=True).start()
try:
 parent_path=MAIN/'artifacts/experiments/source_entry_integration_20261026/attempt03/result/publication/manifest.json'
 parent=ProviderArtifact(str(parent_path),'e61120885b52e48810d4033975d82bece570b80c8251606df2ae7ae9634a734b',parent_path.stat().st_size,'scar.source-entry-publication')
 declaration=json.loads(parent_path.read_text())
 delta_paths=[DATA/p for p in ('call_expansion_delivery_20261026/successful-programs-delta18.json','nested_function_delivery_20261026/successful-programs-delta7.json','function_import_implementation_20261026/successful-programs-delta4.json','function_with_implementation_20261026/successful-programs-delta2.json','genexpr_creation_delivery_20261026/successful-programs-delta1.json','set_display_delivery_20261026/successful-programs-delta3.json')]
 inputs=tuple(ProviderArtifact(str(p),sha(p),p.stat().st_size,json.loads(p.read_text())['schema']) for p in delta_paths)
 requests,origins=collect_source_entry_deltas(parent,inputs)
 assert len(requests)==35
 write('INPUTS.json',{'parent_publication':parent.__dict__ if hasattr(parent,'__dict__') else {'uri':parent.uri,'sha256':parent.sha256,'size_bytes':parent.size_bytes,'schema':parent.schema},
     'requests':requests,'by_input':{str(p):len(json.loads(p.read_text())['entries']) for p in delta_paths},
     'stored_sp5_bytes':sum(r['source_program']['physical_bytes'] for r in requests),'decoded_sp5_bytes':sum(r['source_program']['decoded_bytes'] for r in requests),
     'all_original_paths_exist':all(Path(r['source_program']['uri']).is_file() for r in requests),
     'old_bodies_not_opened':161,'max_record_bytes':128_000_000,'max_selected_source_decode_bytes':3_000_000_000,'max_elapsed_seconds':1800})
 sources=[ISO/'scar/analysis/source_entry_incremental.py']+[MAIN/'scar/analysis'/p for p in ('source_program_publication.py','source_entry_catalog.py','program_lowering.py','program_composition.py')]
 before={str(p):sha(p) for p in sources};write('SOURCE_RECEIPTS.json',before)
 phase='normal-owners'
 project_root=json.loads(Path(declaration['catalog_inputs']['admissions'][0]['report']['artifact']['uri']).read_text())['program_root']
 ref=declaration['catalog_inputs']['admissions'][0]['report']['artifact']
 attachment_budget=SourceAttachmentBudget(max_report_bytes=8_000_000,max_artifact_bytes=3_000_000_000,max_record_bytes=128_000_000,cached_files=2)
 owner=SourceAttachments(ref['uri'],expected_report_sha256=ref['sha256'],project_root=project_root,budget=attachment_budget)
 archives=CompilerWitnessArchives(tuple((str(Path(r['path']).parent),r['sha256']) for r in declaration['catalog_inputs']['archives']),
    store_budget=CodeWitnessBudget(max_compile_keys=256,max_source_files=256,max_source_bytes=8_000_000,max_module_bytes=16_000_000,max_archive_bytes=256_000_000,max_manifest_bytes=8_000_000),
    budget=CompilerArchiveBudget(max_archives=4,max_total_modules=256,max_total_sources=256,max_declared_payload_bytes=256_000_000))
 target=CompositionIndex(declaration['parent_composition']['path'],max_input_bytes=128_000_000,max_record_bytes=128_000_000)
 catalog=SourceEntryCatalog(archives=archives,admissions=(owner,),projects=(target,),max_groups=8192,max_candidates=8192,max_selected_decode_bytes=3_000_000_000)
 phase='normal-publication35'
 result=publish_source_entry_deltas(parent,inputs,target,catalog,ROOT/'result',max_programs=35)
 phase='normal-selected-query1'
 # Mechanical first new entry in publication order; no business name policy.
 delta=json.loads(Path(result['delta_publication']['uri']).read_text());selected=delta['bodies'][0]['entry_key']
 p=result['publication'];publication=ProviderArtifact(p['uri'],p['sha256'],p['size_bytes'],p['schema'])
 checked=read_source_entry_publication_body(publication,selected,target,catalog)
 view=ProgramRegionView(checked['body'].graph,metadata=checked['body'].metadata,structured=checked['program'].structured,interface=checked['program'].interface).region()
 write('QUERY.json',{'entry_key':selected,'record':checked['record'],'graph_operations':len(checked['body'].graph.operations),'region':view,
     'qualification':'selected normal source/code/CP2 read; no full196 reader or runtime bind'})
 assert len(json.loads(Path(publication.uri).read_text())['bodies'])==196
 assert before=={str(p):sha(p) for p in sources}
 assert sha(parent_path)==parent.sha256
 assert all(store.counts['compile_attempts']==0 for store in archives._stores.values())
 phase='finished'
 write('RESULT.json',{'status':'PASS_INCREMENTAL35_PUBLICATION196_AND_SELECTED_NORMAL_QUERY','publication':result,
      'normal_selected_query':selected,'selected_graph_operations':len(checked['body'].graph.operations),
      'catalog_measurements':catalog.measurements(),'readonly_activity':[dict(store.counts) for store in archives._stores.values()],
      'old161_full_reader_replayed':False,'old161_original_exit1_preserved':True,'new_source_lower':0,'target_exec':0,'runtime_binding':False,
      'elapsed_seconds':time.monotonic()-start,'self_maxrss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})
 print((ROOT/'RESULT.json').read_text(),flush=True)
except BaseException as error:
 write('FAILURE.json',{'phase':phase,'type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc(),'elapsed_seconds':time.monotonic()-start});raise
finally:done.set()
