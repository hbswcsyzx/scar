"""Three retained ordinary source/code consumers; never lower/replay source."""
from pathlib import Path
from dataclasses import replace
import gc,gzip,hashlib,json,time,traceback
ROOT=Path(__file__).resolve().parents[3];HERE=Path(__file__).resolve().parent
CONFIG=Path('/home/zyf/AAA/scar-worktrees/source209-model/artifacts/experiments/source209_resume01_20261026/inputs.json')

def save(p,v):
 with p.open('x')as f:json.dump(v,f,ensure_ascii=False,sort_keys=True,separators=(',',':'));f.write('\n')
def ref(p):
 b=p.read_bytes();return{'path':str(p),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}

def main():
 start=time.monotonic();selection=json.loads((HERE/'selection.json').read_bytes());application=json.loads((HERE/'APPLICATION.json').read_bytes())
 paths=sorted({r['path']for c in application['applied_production_only']for r in c['files']})
 source_pins=[ref(ROOT/p)for p in paths]
 config=json.loads(CONFIG.read_bytes());rows=[];failure=None;archives=catalog=None
 try:
  from scar.analysis.source_attachments import SourceAttachments,SourceAttachmentBudget
  from scar.analysis.code_witness import CodeWitnessBudget
  from scar.analysis.compiler_witness_archives import CompilerWitnessArchives,CompilerArchiveBudget
  from scar.analysis.source_entry_catalog import SourceEntryCatalog
  from scar.analysis.source_language import SourceCodeEvidence,SourceLanguageOptions
  from scar.analysis.program_lowering import SourceProgram
  from scar.analysis.structured_lowering import require_valid_structured_body
  owner=SourceAttachments(config['continuation']['path'],expected_report_sha256=config['continuation']['sha256'],project_root=config['project_root'],budget=SourceAttachmentBudget(max_report_bytes=8_000_000,max_artifact_bytes=1_000_000_000,max_record_bytes=128_000_000,cached_files=2))
  archives=CompilerWitnessArchives(tuple((r['directory'],r['manifest']['sha256'])for r in config['archives']),store_budget=CodeWitnessBudget(max_compile_keys=94,max_source_files=94,max_source_bytes=8_000_000,max_module_bytes=16_000_000,max_archive_bytes=256_000_000,max_manifest_bytes=8_000_000),budget=CompilerArchiveBudget(max_archives=4,max_total_modules=256,max_total_sources=256,max_declared_payload_bytes=256_000_000))
  # Existing genuine entry-evidence API requires this normal metadata owner.
  # No full catalog export/planner/worker runs; only the selected three resolve.
  catalog=SourceEntryCatalog(admissions=(owner,),projects=(),archives=archives,max_groups=8192,max_candidates=8192,max_selected_decode_bytes=512_000_000)
  for item in selection:
   before=time.monotonic();entry=catalog.resolve(item['entry_key']);context=catalog.prepare(entry)
   evidence=SourceCodeEvidence.from_entry(catalog,entry);receipt=item['program'];stored=Path(receipt['uri']).read_bytes()
   assert len(stored)==receipt['physical_bytes']and hashlib.sha256(stored).hexdigest()==receipt['physical_sha256']
   decoded=gzip.decompress(stored);assert len(decoded)==receipt['decoded_bytes']and hashlib.sha256(decoded).hexdigest()==receipt['decoded_sha256']
   document=json.loads(decoded);checked=SourceProgram.read_structure(document,max_operations=10_000,source_texts={entry.reference.snapshot.path:context.text})
   assert checked.interface.definition==entry.reference.definition and checked.metadata.source==entry.reference.snapshot
   require_valid_structured_body(checked.structured,checked.graph,checked.interface,checked.metadata,semantic=checked.semantic,control=checked.control,language=checked.language,source_tree=context.tree,language_options=SourceLanguageOptions(checked.language.capabilities,evidence))
   counts={kind:sum(p.kind.value==kind for p in checked.structured.protocols)for kind in('BUILD_CALL_POSITIONAL_LIST','EXTEND_CALL_POSITIONALS','CALL_POSITIONALS_TO_TUPLE','MAKE_NESTED_FUNCTION')}
   if item['category']=='EXPANDED_CALL':assert counts['BUILD_CALL_POSITIONAL_LIST']>0 and counts['EXTEND_CALL_POSITIONALS']>0 and counts['CALL_POSITIONALS_TO_TUPLE']>0
   if item['category']=='NESTED_FUNCTION':assert counts['MAKE_NESTED_FUNCTION']>0
   row={**item,'status':'ORDINARY_STRUCTURE_AND_INDEPENDENT_SOURCE_CODE_PASS','operations':len(checked.graph.operations),'protocol_counts':counts,'elapsed_s':time.monotonic()-before,'stored_bytes_read':len(stored),'decoded_bytes_read':len(decoded)}
   rows.append(row);print(json.dumps({k:row[k]for k in('category','status','operations','elapsed_s')}),flush=True)
   checked=document=decoded=stored=context=evidence=None;gc.collect()
  catalog.require_unchanged()
  assert [ref(ROOT/p)for p in paths]==source_pins
  protected=application['protected_untracked_catalog'];assert ref(Path(protected['path']))==protected
 except BaseException as error:failure={'type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc()}
 final={'status':'THREE_ORIGINAL_SOURCE_CONSUMERS_PASS_WITH_OPEN'if failure is None else'FAILED_RETAINED_WITH_OPEN','failure':failure,'entries':rows,'elapsed_s':time.monotonic()-start,'source_pins':source_pins,'readonly_counts':[s.counts for s in archives._stores.values()]if archives else[],'normal_owner_initialization':'original metadata guards only; no catalog export or full worker','catalog_measurements':catalog.measurements()if catalog else None,'source_lower':0,'source_replay':0,'source_compile':0,'source_prepare':0,'raw':0,'target':0,'publication':0,'currentRun_binding':0,'whole_model_complete':False,'IO':'selected program exact byte counts plus normal owner counters; cumulative total unmetered OPEN'}
 save(HERE/'readback.json',final);print(json.dumps({'status':final['status'],'elapsed_s':final['elapsed_s'],'failure':failure}),flush=True)
 return 1 if failure else 0
if __name__=='__main__':raise SystemExit(main())
