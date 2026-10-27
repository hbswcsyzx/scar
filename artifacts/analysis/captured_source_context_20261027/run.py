"""One retained project source through normal source matcher and CodeWitness."""
from pathlib import Path,PurePosixPath
from hashlib import sha256
import ast,json,sys,time,traceback,resource
from scar.analysis.captured_source_owner import CapturedSourceOwner,CapturedSourceBudget
from scar.analysis.call_trace_reader import scan_call_trace,CollectingCallSink
from scar.analysis.call_edges import _link_call_model,CallEdgeReport
from scar.analysis.code_witness import CodeWitnessStore,CodeWitnessBudget
from scar.ir.program.call_edges import CallEdgeBudget,CallLinkStatus
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.compilation import CallCompilationProfile
from scar.ir.record_codec import encode,decode
from scar.trace.code_snapshot import describe_code

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];started=time.monotonic()
TRACE=Path('/home/zyf/AAA/scar-worktrees/program-ports-capture/artifacts/experiments/program_ports_cpu_20261027/capture/trace')
meta=json.loads((TRACE/'call-meta.2026697.json').read_bytes());decl=decode(ProviderArtifact,meta['captured_sources'])
source_meta=json.loads(Path(decl.uri).read_bytes());project=meta['project_root']
blocked={r['path']for r in source_meta['files']if PurePosixPath(r['path']).is_absolute()};attempted=[]
def guard(event,args):
 if event=='open' and args and isinstance(args[0],(str,bytes)):
  name=args[0].decode()if isinstance(args[0],bytes)else args[0]
  if name in blocked:
   attempted.append(name);raise RuntimeError('static archive path attempted live source open: '+name)
sys.addaudithook(guard)
names=('scar/analysis/program_lowering.py','scar/analysis/call_edges.py','scar/analysis/control_flow_v2.py','scar/ir/frontend_v2.py')
pins={name:sha256((ROOT/name).read_bytes()).hexdigest()for name in names}
record={'schema':'scar.captured-source-context-actual','schema_version':1,'status':'FAILED_RETAINED',
        'new_capture':0,'target_exec':0,'body_lower':0,'failure':None}
try:
 budget=CallEdgeBudget(max_raw_bytes=2_000_000,max_lines=10000,max_codes=256,max_events=2000,
                       max_source_files=1,max_source_bytes=1_000_000)
 sink=CollectingCallSink();scan=scan_call_trace(TRACE,project,budget,sink=sink)
 with CapturedSourceOwner(TRACE,project_root=project,metadata=decl,frame_scan=scan,
      budget=CapturedSourceBudget(max_metadata_bytes=1_000_000,max_rows_bytes=1_000_000,
       max_row_bytes=1_000_000,max_files=32,max_source_bytes=1_000_000,max_codes=256,max_code_bytes=1_000_000)) as owner:
  # Same normal factory as public link_calls, retaining its in-process owner
  # only so this receipt can inspect generated original layers/provenance.
  model,sources=_link_call_model(TRACE,project,budget=budget,frame_scan=scan,
      entries=tuple(sink.entries),exits=tuple(sink.exits),
      compilation_profile=CallCompilationProfile.RECORDED_FUTURE_FLAGS,
      captured_source_owner=owner,captured_source_root_is_package=False)
  assert len(model.edges)==len(sink.entries)==177 and len(sources.contexts)==1
  selected=sorted((c for c in owner.captured_codes()if PurePosixPath(c.filename).is_absolute()
      and PurePosixPath(c.filename).is_relative_to(PurePosixPath(project))and c.qualname!='<module>'),
      key=lambda c:(c.filename,c.first_line,c.qualname,c.key))[0]
  link=sources.links[selected.key];assert link.status is CallLinkStatus.VERIFIED and link.definition is not None
  original=owner.archived_source(link.snapshot);context=sources.contexts[selected.filename]
  assert context.text==original.text and context.snapshot==original.snapshot
  assert selected.key in sources.objects and describe_code(sources.objects[selected.key])==encode(selected)
  assert link.definition in sources.signatures
  limits=CodeWitnessBudget(max_compile_keys=1,max_source_files=1,max_source_bytes=1_000_000,
       max_module_bytes=2_000_000,max_archive_bytes=4_000_000,max_manifest_bytes=1_000_000)
  writer=CodeWitnessStore(HERE/'archive',budget=limits,create=True,compile_missing=True,
      producer={'profile':'ARCHIVE_SOURCE_NORMAL_CONTEXT_SINGLE_CPU_V1','input':encode(decl)})
  admission=writer.admit_captured_source(link.snapshot,captured=selected,source_owner=owner)
  code,proof=writer.resolve(selected,link.snapshot,link.optimize_levels,allow_compile=True)
  readonly=CodeWitnessStore(HERE/'archive',budget=limits);restored,check=readonly.resolve(selected,link.snapshot,link.optimize_levels)
  assert check==proof and describe_code(restored)==describe_code(code)==encode(selected)
  assert readonly.text(link.snapshot)==original.text
  owner.require_unchanged()
  (HERE/'call-model.json').write_text(json.dumps(CallEdgeReport(model).to_dict(),sort_keys=True,indent=2)+'\n')
  record.update(status='NORMAL_ARCHIVED_SOURCE_CONTEXT_CODELINK_WITNESS_WITH_OPEN',
       original_frame_entries=len(sink.entries),original_frame_exits=len(sink.exits),source_context_files=len(sources.contexts),
       selected=encode(selected),code_link=encode(link),source=encode(original.source),source_declaration=encode(original.declaration),
       source_snapshot=encode(context.snapshot),namespace_root=project,root_is_package=False,
       namespace_policy_basis='retained original CPU project script namespace; explicit static policy, not inferred from uncaptured __init__ absence',
       ast_nodes=sum(1 for _ in ast.walk(context.tree)),source_index_definitions=len(sources.indexes[selected.filename].definitions),
       source_index_calls=len(sources.indexes[selected.filename].calls),signature_definitions=len(sources.signatures),
       source_match_compile_variants=len(sources.compiled),code_statuses=CallEdgeReport(model).summary()['code_source_statuses'],
       writer_activity=writer.counts,readonly_activity=readonly.counts,owner_activity=owner.counts,
       archive=writer.receipt(),source_admission=admission,normal_proof=proof,
       non_filesystem_frontiers=owner.frontiers(),loader_bytes_observed=False,whole_model_established=False)
except BaseException as error:
 record['failure']={'type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc()}
finally:
 record.update(elapsed_seconds=time.monotonic()-started,max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
      live_source_open_attempts=attempted,audit_denied_source_filenames=sorted(blocked),source_sha256=pins,
      source_unchanged=all(sha256((ROOT/name).read_bytes()).hexdigest()==h for name,h in pins.items()))
 (HERE/'RESULT.json').write_text(json.dumps(record,sort_keys=True,indent=2)+'\n')
 print(json.dumps({k:v for k,v in record.items()if k not in('source_admission','normal_proof','audit_denied_source_filenames')},indent=2))
raise SystemExit(int(record['failure']is not None or attempted or not record['source_unchanged']))
