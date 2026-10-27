"""ONE retained real window. No target execution/source preparation/compilation."""
from pathlib import Path
import ast,builtins,io,gzip,json,hashlib,os,resource,signal,sys,time,traceback
from dataclasses import replace
from functools import lru_cache
BASE=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
CAPTURE=BASE/'artifacts/experiments/first_stage_lewm_physical_20261023'
PARENT=BASE/'artifacts/experiments/first_stage_joined_physical_20261023/result'
START=time.monotonic()
phase='imports'
reads={}
progress=(OUT/'progress.jsonl').open('x')
def emit(row):
 row={'elapsed_s':time.monotonic()-START,**row};progress.write(json.dumps(row,sort_keys=True)+'\n');progress.flush();print(json.dumps(row,sort_keys=True),flush=True)
def timeout(*_):raise TimeoutError('whole gate 300s hard wall budget')
signal.signal(signal.SIGALRM,timeout);signal.alarm(300)
# Count actual source bytes returned by base file APIs. gzip layer is counted
# separately; plain reads are both decoded/stored. Only original capture and
# original selected archive files participate, never imports/output files.
original_open,original_io_open=builtins.open,io.open
original_gread,original_gline=gzip.GzipFile.read,gzip.GzipFile.readline
@lru_cache(maxsize=1024)
def source_path(path):
 try:return Path(path).resolve()
 except (TypeError,ValueError):return None
@lru_cache(maxsize=1024)
def tracked(path):
 p=source_path(path)
 return p is not None and (p.is_relative_to(CAPTURE) or p.is_relative_to(PARENT/'native/bundle-partitions') or p==PARENT/'capture-model.json')
def add(path,kind,n):
 if not n:return
 key=(phase,str(source_path(path)),kind);reads[key]=reads.get(key,0)+n
class FileRead:
 def __init__(self,f):self._f=f
 def __getattr__(self,n):return getattr(self._f,n)
 def __enter__(self):return self
 def __exit__(self,*a):return self._f.__exit__(*a)
 def __iter__(self):return self
 def __next__(self):
  d=self.readline()
  if not d:raise StopIteration
  return d
 def read(self,*a):
  d=self._f.read(*a);add(self.name,'stored',len(d));
  if not str(self.name).endswith('.gz'):add(self.name,'decoded',len(d))
  return d
 def readline(self,*a):
  d=self._f.readline(*a);add(self.name,'stored',len(d));
  if not str(self.name).endswith('.gz'):add(self.name,'decoded',len(d))
  return d
 def readinto(self,b):
  n=self._f.readinto(b);add(self.name,'stored',n or 0)
  if not str(self.name).endswith('.gz'):add(self.name,'decoded',n or 0)
  return n
def fopen(original):
 def opened(path,*a,**kw):
  f=original(path,*a,**kw);mode=a[0] if a else kw.get('mode','r')
  return FileRead(f) if tracked(path) and 'r' in mode and 'b' in mode else f
 return opened
depth={}
def gzread(original):
 def read(self,*a,**kw):
  key=id(self);old=depth.get(key,0);depth[key]=old+1
  try:data=original(self,*a,**kw)
  finally:depth[key]=old
  if old==0 and tracked(self.name):add(self.name,'decoded',len(data))
  return data
 return read
builtins.open=fopen(original_open);io.open=fopen(original_io_open)
gzip.GzipFile.read=gzread(original_gread);gzip.GzipFile.readline=gzread(original_gline)
try:
 from scar.trace.capture_coordinates import bind_capture_coordinates
 from scar.trace.native_protocol import bind_native_protocol_window,NativeProtocolWindow,NativeProtocolBudget
 from scar.ir.execution.validation import validate,_analyze
 from scar.ir.execution.content_validation import native_port
 from scar.ir.execution.ids import RunID
 from scar.ir.execution.content import NativeInputRef,ObjectIdentity
 from scar.ir.record_codec import encode
 def cost():
  return {p:{k:sum(n for (ph,_,kind),n in reads.items() if ph==p and kind==k) for k in ('stored','decoded')} for p in sorted({r[0] for r in reads})}
 phase='coordinate_scope'
 emit({'stage':phase,'max_bytes':1200000000,'max_lines':1100000})
 coordinates=bind_capture_coordinates(CAPTURE,max_bytes=1200000000,max_lines=1100000,profile_uri=str(OUT/'native-coordinates.json'))
 (OUT/'native-coordinates.json').write_bytes(coordinates.payload)
 scope_cost=cost()[phase]
 assert scope_cost['decoded']<=1270000000 and scope_cost['stored']<=119000000,scope_cost
 emit({'stage':'coordinate_scope_complete','actual_io':scope_cost,'run':coordinates.run.id.value})
 phase='native_window'
 manifest=PARENT/'native/bundle-partitions/manifest.json';model=PARENT/'capture-model.json'
 result=bind_native_protocol_window(coordinates,CAPTURE,manifest,OUT/'result',
  expected_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),capture_model_path=model,
  expected_capture_model_sha256=hashlib.sha256(model.read_bytes()).hexdigest(),
  window=NativeProtocolWindow(1,16),budget=NativeProtocolBudget(),progress=emit)
 emit({'stage':'native_reference_positive_complete','denotations':len(result.execution.denotations)})
 phase='bounded_negative_checks'
 va=result.report['artifacts']['values_projection'];ea=result.report['artifacts']['evidence_projection']
 kwargs={'value_graphs':{va['sha256']:result.values},'evidence_graphs':{ea['sha256']:result.evidence},
  'native_port_evidence':result.native_port_evidence}
 wrong=replace(result.execution,runs=(replace(result.execution.runs[0],id=RunID('deliberately-wrong-run')),))
 wrong_report=validate(wrong,result.program,**kwargs)
 assert any(i.code=='native_port_scope' for i in wrong_report.issues),'wrong Run borrowed session'
 # Same genuine program/execution context; exchange two actual Tensor inputs
 # of one native operation and independently replay the requested slot.
 valid,ctx=_analyze(result.execution,result.program,**kwargs);assert valid.valid
 by_entry={}
 for d in result.execution.denotations:
  if type(d.basis) is NativeInputRef:by_entry.setdefault(d.basis.entry,[]).append(d)
 pair=next(ds[:2] for ds in by_entry.values() if len(ds)>=2 and ds[0].identity!=ds[1].identity)
 first,second=pair;basis=replace(first.basis,position=second.basis.position)
 resolved=native_port(ctx,basis,'negative-swapped-slot')
 matched=result.native_port_evidence.resolve(ctx,basis,resolved,first.identity,'negative-swapped-slot')
 assert not matched and any(i.code=='native_reference_object' for i in ctx.issues),'swapped actual slot accepted'
 # Missing exact original ObjectInstance in live caller catalog must fail
 # normal ExternalSnapshots canonical/hash/registry checks.
 original=dict(result.values.objects);result.values.objects.pop(first.identity.object.object)
 try:missing=validate(result.execution,result.program,**kwargs)
 finally:result.values.objects.clear();result.values.objects.update(original)
 assert missing.issues,'missing source record accepted'
 # A freshly owned source session must reject an internally legal *new*
 # program/model seal whose boundary/denotation maps are consistently wrong.
 # This uses only the genuine still-live reader owner from this public run;
 # no saved PASS/raw dictionary is restored as authority.
 from order_preflight import make_order_candidate
 from scar.ir.execution.native_port_protocol import _make_evidence,NativePortOrderError
 from scar.ir.program.providers import ProviderArtifact
 from scar.ir.record_codec import decode
 from scar.ir.execution.codec import dumps as execution_dumps
 wrong_program,wrong_order_model=make_order_candidate(result.program,result.execution)
 generic_wrong=validate(wrong_order_model,wrong_program,value_graphs=kwargs['value_graphs'],evidence_graphs=kwargs['evidence_graphs'])
 assert generic_wrong.valid,generic_wrong.issues
 assert wrong_order_model.snapshot.artifact.sha256!=result.execution.snapshot.artifact.sha256
 try:
  _make_evidence(result.native_port_evidence._owned,wrong_program,wrong_order_model,decode(ProviderArtifact,va),decode(ProviderArtifact,ea))
 except NativePortOrderError as error:
  order_failure=str(error)
 else:raise AssertionError('fresh source-owned constructor accepted internally legal wrong port order')
 no_proof=validate(result.execution,result.program,value_graphs=kwargs['value_graphs'],evidence_graphs=kwargs['evidence_graphs'])
 assert any(g.code=='content_native_correspondence_unverified' for g in no_proof.gaps),'legacy no-proof gap suppressed'
 negative={'freshly_sealed_wrong_order':{'rejected':True,'generic_execution_issue_count':len(generic_wrong.issues),
  'own_program_snapshot_sha256':wrong_order_model.snapshot.artifact.sha256,
  'own_execution_sha256':__import__('hashlib').sha256(execution_dumps(wrong_order_model).encode()).hexdigest(),
  'fresh_same_run_owned_constructor_used':True,'failure_kind':'NativePortOrderError','message':order_failure},
  'wrong_run':{'rejected':True,'issues':[encode(i) for i in wrong_report.issues]},
  'swapped_tensor_input_slot':{'rejected':True,'issues':[encode(i) for i in ctx.issues]},
  'missing_original_object':{'rejected':True,'issues':[encode(i) for i in missing.issues]},
  'legacy_without_owned_proof':{'original_gap_retained':True,'gaps':len(no_proof.gaps)}}
 (OUT/'negative-checks.json').write_text(json.dumps(negative,sort_keys=True,indent=2)+'\n')
 summary={'status':'PASS','scope':'bounded actual ATen reference/port/observed physical geometry only',
  'wall_seconds':time.monotonic()-START,'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
  'actual_io_by_phase':cost(),'actual_io_total':{k:sum(n for (_,_,kind),n in reads.items() if kind==k) for k in ('stored','decoded')},
  'reference_report':result.report,'negative_checks':negative,'target_executions':0,'prepare_calls':0,'compiler_witness_calls':0,
  'complete_program_model':False,'transformation_authorized':False}
 (OUT/'summary.json').write_text(json.dumps(summary,sort_keys=True,indent=2)+'\n')
 emit({'stage':'complete','status':'PASS','wall_seconds':summary['wall_seconds'],'actual_io':summary['actual_io_total']})
except BaseException as error:
 failure={'status':'FAILED','phase':phase,'wall_seconds':time.monotonic()-START,'error_type':type(error).__name__,
  'message':str(error),'traceback':traceback.format_exc(),'actual_io':[{'phase':p,'path':q,'kind':k,'bytes':n} for (p,q,k),n in sorted(reads.items())]}
 (OUT/'failure.json').write_text(json.dumps(failure,sort_keys=True,indent=2)+'\n');emit({'stage':'failed','phase':phase,'error':repr(error)});raise
finally:
 signal.alarm(0)
 (OUT/'actual-io.json').write_text(json.dumps([{'phase':p,'path':q,'kind':k,'bytes':n} for (p,q,k),n in sorted(reads.items())],sort_keys=True,indent=2)+'\n')
 progress.close()
