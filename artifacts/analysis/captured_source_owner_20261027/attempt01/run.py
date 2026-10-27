"""One retained CPU source -> normal compile/descriptor/readonly witness."""
from pathlib import Path,PurePosixPath
from hashlib import sha256
import sys,json,time,traceback,resource
from scar.analysis.captured_source_owner import CapturedSourceOwner,CapturedSourceBudget
from scar.analysis.code_witness import CodeWitnessStore,CodeWitnessBudget
from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import decode,encode
from scar.trace.code_snapshot import describe_code

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];started=time.monotonic()
TRACE=Path('/home/zyf/AAA/scar-worktrees/program-ports-capture/artifacts/experiments/program_ports_cpu_20261027/capture/trace')
call_meta=json.loads((TRACE/'call-meta.2026697.json').read_bytes());decl=decode(ProviderArtifact,call_meta['captured_sources'])
raw=Path(decl.uri).read_bytes();assert sha256(raw).hexdigest()==decl.sha256 and len(raw)==decl.size_bytes
metadata=json.loads(raw);project=call_meta['project_root']
blocked={item['path']for item in metadata['files']if PurePosixPath(item['path']).is_absolute()}
attempted=[]
def guard(event,args):
 if event=='open' and args and isinstance(args[0],(str,bytes)):
  name=args[0].decode()if isinstance(args[0],bytes)else args[0]
  if name in blocked:
   attempted.append(name);raise RuntimeError('offline source witness attempted original live source open: '+name)
sys.addaudithook(guard)
source_names=('scar/analysis/captured_source_owner.py','scar/analysis/code_witness.py')
pins={name:sha256((ROOT/name).read_bytes()).hexdigest()for name in source_names}
result={'schema':'scar.captured-source-owner-actual','schema_version':1,'status':'FAILED_RETAINED',
        'new_capture':0,'target_exec':0,'source_body_lower':0,'selected_sources':1,'failure':None}
try:
 with CapturedSourceOwner(TRACE,project_root=project,metadata=decl,
        budget=CapturedSourceBudget(max_metadata_bytes=1_000_000,max_rows_bytes=1_000_000,
            max_row_bytes=1_000_000,max_files=32,max_source_bytes=1_000_000,max_codes=256,max_code_bytes=1_000_000)) as owner:
  candidates=sorted((c for c in owner.captured_codes()if PurePosixPath(c.filename).is_absolute()
      and PurePosixPath(c.filename).is_relative_to(PurePosixPath(project))),key=lambda c:(c.filename,c.first_line,c.qualname,c.key))
  assert candidates
  captured=candidates[0];snapshot=owner.snapshot(captured);source=owner.archived_source(snapshot)
  limits=CodeWitnessBudget(max_compile_keys=1,max_source_files=1,max_source_bytes=1_000_000,
      max_module_bytes=2_000_000,max_archive_bytes=4_000_000,max_manifest_bytes=1_000_000)
  writer=CodeWitnessStore(HERE/'archive',budget=limits,create=True,compile_missing=True,
      producer={'profile':'CAPTURED_CPU_SOURCE_SINGLE_OFFLINE_MATCH_V1','source':encode(decl)})
  admission=writer.admit_captured_source(snapshot,captured=captured,source_owner=owner)
  # optimize=0 is a candidate, not a claim that per-code optimization was
  # observed. Only the actual full-descriptor comparison can accept it.
  code,proof=writer.resolve(captured,snapshot,(0,),allow_compile=True)
  assert describe_code(code)==encode(captured)
  receipt=writer.receipt();readonly=CodeWitnessStore(HERE/'archive',budget=limits)
  restored,ordinary=readonly.resolve(captured,snapshot,(0,),allow_compile=False)
  assert ordinary==proof and describe_code(restored)==encode(captured)
  assert readonly.text(snapshot)==source.text and readonly.receipt()==receipt
  owner.require_unchanged()
  result.update(status='ACTUAL_CAPTURED_SOURCE_DESCRIPTOR_READBACK_WITH_OPEN',captured=encode(captured),
      snapshot=encode(snapshot),source=encode(source.source),source_declaration=encode(source.declaration),
      original_encoding=source.original_encoding,original_raw_bytes=source.raw_bytes,original_raw_sha256=source.raw_sha256,
      observed_python=source.observed_python,source_admission=admission,archive=receipt,proof=proof,
      compiler_match='COMPLETE_DESCRIPTOR_MATCHED_BY_ACTUAL_COMPILE',original_capture_compiler_match='NOT_CHECKED',
      writer_activity=writer.counts,readonly_activity=readonly.counts,owner_activity=owner.counts,
      owner_receipts=owner.receipts(),non_filesystem_frontiers=owner.frontiers(),loader_bytes_observed=False)
except BaseException as error:
 result['failure']={'type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc()}
finally:
 result.update(elapsed_seconds=time.monotonic()-started,max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
      audit_live_open_attempts=attempted,audit_denied_source_filenames=sorted(blocked),source_sha256=pins,
      source_unchanged=all(sha256((ROOT/name).read_bytes()).hexdigest()==digest for name,digest in pins.items()))
 (HERE/'RESULT.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
 print(json.dumps({k:v for k,v in result.items()if k not in('source_admission','owner_receipts','audit_denied_source_filenames','proof')},indent=2))
raise SystemExit(int(result['failure']is not None or attempted or not result['source_unchanged']))
