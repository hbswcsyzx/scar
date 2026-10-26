"""Reject a corrupted private copy despite unchanged copied receipt strings."""
from pathlib import Path
import json,time,traceback
import scar.analysis.source_entry_catalog as module
from scar.analysis.program_composition import CompositionIndex
from scar.analysis.source_attachments import SourceAttachments,SourceAttachmentBudget
from scar.analysis.code_witness import CodeWitnessBudget
from scar.analysis.compiler_witness_archives import CompilerWitnessArchives,CompilerArchiveBudget
HERE=Path(__file__).resolve().parent;started=time.monotonic();result={}
try:
 config=json.loads(Path('/home/zyf/AAA/scar-worktrees/source209-model/artifacts/experiments/source209_resume01_20261026/inputs.json').read_bytes())
 parent=CompositionIndex('/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/first_stage_source_publication_current_20261023/result/composition/index.json.gz',max_input_bytes=128_000_000,max_record_bytes=128_000_000)
 owner=SourceAttachments(config['continuation']['path'],expected_report_sha256=config['continuation']['sha256'],project_root=config['project_root'],budget=SourceAttachmentBudget(max_report_bytes=8_000_000,max_artifact_bytes=3_000_000_000,max_record_bytes=128_000_000,cached_files=2))
 archives=CompilerWitnessArchives(tuple((x['directory'],x['manifest']['sha256'])for x in config['archives']),store_budget=CodeWitnessBudget(max_compile_keys=94,max_source_files=94,max_source_bytes=8_000_000,max_module_bytes=16_000_000,max_archive_bytes=256_000_000,max_manifest_bytes=8_000_000),budget=CompilerArchiveBudget(max_archives=4,max_total_modules=256,max_total_sources=256,max_declared_payload_bytes=256_000_000))
 catalog=module.SourceEntryCatalog(archives=archives,admissions=(owner,),projects=(parent,),max_groups=8192,max_candidates=8192,max_selected_decode_bytes=3_000_000_000)
 normal=module.deepcopy
 def corrupted(value,*args,**kwargs):
  result=normal(value,*args,**kwargs)
  if value is catalog:result._rows[0]['entered_invocations']+=1
  return result
 module.deepcopy=corrupted
 try:
  with catalog._ordinary_read_session(parent):raise AssertionError('inconsistent copied memory accepted')
 except ValueError as e:result['corrupt_copy_rejected']=str(e)
 finally:module.deepcopy=normal
 assert not module._PRIVATE_READ_SESSIONS
 with catalog._ordinary_read_session(parent) as session:
  assert session.catalog is not catalog
  assert session.catalog.metadata()['entered_invocations']==100438
 catalog.require_unchanged();parent.source_inputs()
 result.update(status='COPIED_MEMORY_REJECT_AND_NORMAL_METADATA_PASS',graph_decode=0,CodeType_load=0,compile=0,target=0)
except BaseException as e:result.update(status='FAILED',error=str(e),traceback=traceback.format_exc())
result['elapsed_s']=time.monotonic()-started
(HERE/'copied-memory-result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
raise SystemExit(0 if result['status']=='COPIED_MEMORY_REJECT_AND_NORMAL_METADATA_PASS'else 1)
