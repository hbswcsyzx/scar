"""One previously slow real context, two smallest retained bodies; observe CFG calls."""
from pathlib import Path
import json,sys,importlib.util,hashlib,time,collections,traceback,resource
import scar.analysis,scar.store
ISO=Path('/home/zyf/AAA/scar-worktrees/source-entry-project');MAIN=Path('/home/zyf/AAA/scar-worktrees/structured-program-model');ROOT=Path(__file__).resolve().parent
for name in ('program_lowering','structured_lowering'):
 key='scar.analysis.'+name;spec=importlib.util.spec_from_file_location(key,ISO/'scar/analysis'/(name+'.py'));m=importlib.util.module_from_spec(spec);sys.modules[key]=m;spec.loader.exec_module(m)
key='scar.store.source_fragments';spec=importlib.util.spec_from_file_location(key,ISO/'scar/store/source_fragments.py');m=importlib.util.module_from_spec(spec);sys.modules[key]=m;spec.loader.exec_module(m)
for name in ('source_entry_catalog','source_program_publication'):
 key='scar.analysis.'+name;spec=importlib.util.spec_from_file_location(key,ISO/'scar/analysis'/(name+'.py'));m=importlib.util.module_from_spec(spec);sys.modules[key]=m;spec.loader.exec_module(m)
from scar.analysis.program_composition import CompositionIndex
from scar.analysis.source_attachments import SourceAttachments,SourceAttachmentBudget
from scar.analysis.compiler_witness_archives import CompilerWitnessArchives,CompilerArchiveBudget
from scar.analysis.code_witness import CodeWitnessBudget
from scar.analysis.source_entry_catalog import SourceEntryCatalog
from scar.analysis.source_program_publication import plan_source_entry_publication,publish_source_entries
from scar.ir.control_flow_v2 import SourceControlFlowGraph
from scar.ir.record_codec import encode
import gzip
start=time.monotonic()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(name,value):(ROOT/name).write_text(json.dumps(value,indent=2)+'\n')
try:
 p=MAIN/'artifacts/experiments/source_entry_integration_20261026/attempt03/result/publication/manifest.json';old=json.loads(p.read_text());refs=json.loads((ISO/'artifacts/experiments/source_entry_incremental35_shared02_20261026/INPUTS.json').read_text())['requests']
 # Exact completed CP2 metadata from the stopped scope selects a formerly slow source, not a name.
 groups=collections.defaultdict(list)
 for cp in (ISO/'artifacts/experiments/source_entry_incremental35_shared02_20261026/result/delta/bodies').glob('*.gz'):
  row=json.loads(gzip.decompress(cp.read_bytes()));groups[json.dumps(row['context'],sort_keys=True)].append(row)
 candidates=[rows for rows in groups.values() if len(rows)>=2]
 chosen=max(candidates,key=lambda rows:min(r['source_program']['decoded_bytes'] for r in rows))
 chosen=sorted(chosen,key=lambda row:(row['source_program']['decoded_bytes'],row['source_program']['uri']))[:2]
 programs={r['source_program']['uri'] for r in chosen};requests=tuple(r for r in refs if r['source_program']['uri'] in programs)
 assert len(requests)==2
 save('selection.json',{'requests':requests,'previous_context':chosen[0]['context'],'reason':'largest formerly slow completed context with at least two bodies; smallest retained pair within it'})
 owner_ref=old['catalog_inputs']['admissions'][0]['report']['artifact'];owner_doc=json.loads(Path(owner_ref['uri']).read_text())
 owner=SourceAttachments(owner_ref['uri'],expected_report_sha256=owner_ref['sha256'],project_root=owner_doc['program_root'],budget=SourceAttachmentBudget(max_report_bytes=8_000_000,max_artifact_bytes=3_000_000_000,max_record_bytes=128_000_000,cached_files=2))
 archives=CompilerWitnessArchives(tuple((str(Path(r['path']).parent),r['sha256']) for r in old['catalog_inputs']['archives']),store_budget=CodeWitnessBudget(max_compile_keys=256,max_source_files=256,max_source_bytes=8_000_000,max_module_bytes=16_000_000,max_archive_bytes=256_000_000,max_manifest_bytes=8_000_000),budget=CompilerArchiveBudget(max_archives=4,max_total_modules=256,max_total_sources=256,max_declared_payload_bytes=256_000_000))
 target=CompositionIndex(old['parent_composition']['path'],max_input_bytes=128_000_000,max_record_bytes=128_000_000)
 catalog=SourceEntryCatalog(archives=archives,admissions=(owner,),projects=(target,),max_groups=8192,max_candidates=8192,max_selected_decode_bytes=3_000_000_000)
 original_validate=SourceControlFlowGraph.validate;observed=collections.defaultdict(lambda:{'calls':0,'elapsed_seconds':0.,'callers':collections.Counter()})
 def watched(self,*args,**kwargs):
  caller=sys._getframe(1).f_code.co_name;t=time.perf_counter()
  try:return original_validate(self,*args,**kwargs)
  finally:
   row=observed[id(self)];row['calls']+=1;row['elapsed_seconds']+=time.perf_counter()-t;row['callers'][caller]+=1
 phase_start=time.monotonic()
 with catalog._ordinary_read_session(target,controls=(requests,),share_source_context=True) as session:
  plan=plan_source_entry_publication(session.target,session.catalog,requests,max_programs=2,publication_version=3)
  SourceControlFlowGraph.validate=watched
  try:
   publication=publish_source_entries(session.target,session.catalog,requests,ROOT/'publication',max_programs=2,max_record_bytes=128_000_000,max_operations_per_body=10000,plan=plan)
   reader=session.program_reader;owned=reader.reader._context(reader.reference);identity=id(owned.control);costs=reader.measurements()
  finally:SourceControlFlowGraph.validate=original_validate
 result={'status':'PASS_REAL_LARGE_CONTEXT_SHARED_NORMAL_PUBLISHER','published_bodies':publication['body_count'],'publication':publication,
  'source_context_costs':costs,'owned_cfg_validate':observed[identity],
  'all_cfg_validate':dict(observed),'original_sp5_stored_bytes':sum(r['source_program']['physical_bytes'] for r in requests),'original_sp5_decoded_bytes':sum(r['source_program']['decoded_bytes'] for r in requests),
  'normal_publisher_including_plan_elapsed_seconds':time.monotonic()-phase_start,'elapsed_seconds':time.monotonic()-start,'maxrss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
  'readonly_activity':[dict(x.counts) for x in archives._stores.values()],'new_lower':0,'new_target':0,
  'instrumentation':'analysis-only wrapper calls original CFG.validate and preserves return/exception; restored in finally','whole_program_complete':False}
 assert costs['contexts']['context_validations']==1 and costs['contexts']['body_reads']==2
 assert not observed[identity]['callers'].get('_require_valid_structured_body')
 save('result.json',result);print(json.dumps(result,indent=2))
except BaseException as error:
 save('FAILURE.json',{'type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc(),'elapsed_seconds':time.monotonic()-start});raise
