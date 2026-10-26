"""Retained relation reader plus independent public static codec; no producer."""
from pathlib import Path
import argparse,hashlib,json,os,resource,signal,subprocess,sys,threading,time,traceback
BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[3]
def raw(v):return (json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode()
def sha(v):return hashlib.sha256(v).hexdigest()
def verify(expected):
 data=(BASE/'freeze.json').read_bytes()
 if sha(data)!=expected:raise ValueError('postflight freeze differs')
 f=json.loads(data)
 for r in f['sources']+f['tools']:
  data=Path(r['path']).read_bytes()
  if (len(data),sha(data))!=(r['bytes'],r['sha256']):raise ValueError('frozen source/reader/runner changed '+r['path'])
 for r in f['inputs']:
  s=Path(r['path']).stat()
  if (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)!=(r['device'],r['inode'],r['bytes'],r['mtime_ns'],r['ctime_ns']):raise ValueError('selected input changed '+r['path'])
 return f

def worker(expected):
 start=time.monotonic();attempt=BASE/'attempt01';phase={'phase':'START'};stop=threading.Event();meter=None
 counters={'producer_or_index_attempts':0,'lower_attempts':0,'prepare_attempts':0,'target_exec_attempts':0,'target_compile_attempts':0}
 progress=(attempt/'progress.jsonl').open('xb')
 def event(kind,**kw):
  value={**phase,'event':kind,'elapsed_s':time.monotonic()-start,'rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,**kw}
  progress.write(raw(value));progress.flush()
 def beat():
  while not stop.wait(20):event('HEARTBEAT')
 threading.Thread(target=beat,daemon=True).start();signal.signal(signal.SIGALRM,lambda *x:(_ for _ in ()).throw(TimeoutError('reader180s')));signal.setitimer(signal.ITIMER_REAL,180)
 def save(name,value):
  data=raw(value)
  if len(data)>4_000_000:raise ValueError('report4MB')
  with (attempt/name).open('xb') as stream:stream.write(data)
 try:
  f=verify(expected);sel=json.loads((BASE/'selection.json').read_bytes())
  def audit(name,args):
   if name=='import' and str(args[0]).split('.')[0] in ('torch','torchvision','stable_worldmodel'):
    counters['target_exec_attempts']+=1;raise RuntimeError('target import forbidden')
   if name in ('subprocess.Popen','os.system','os.exec'):
    counters['target_exec_attempts']+=1;raise RuntimeError('target subprocess forbidden')
   if name=='compile' and isinstance(args[1],(str,bytes)) and os.fsdecode(args[1]).startswith('/home/zyf/AAA/le-wm/'):
    counters['target_compile_attempts']+=1;raise RuntimeError('target compile forbidden')
  sys.addaudithook(audit)
  from scar.ir.record_codec import decode,encode
  from scar.ir.execution.fragment_relations import RuntimeScope,WorkTicketRef,canonical
  from scar.store.fragment_relations import RelationPartitions,Meter,RelationBudgets
  from scar.analysis.fragment_relations import FragmentRelationProducer,_source_locator_value
  from scar.ir.program.codec import loads as program_loads
  def forbidden_producer(*a,**k):counters['producer_or_index_attempts']+=1;raise RuntimeError('production forbidden')
  FragmentRelationProducer.produce=forbidden_producer
  import scar.analysis.program_lowering as source_api
  def forbidden_lower(*a,**k):counters['lower_attempts']+=1;raise RuntimeError('lower forbidden')
  def forbidden_prepare(*a,**k):counters['prepare_attempts']+=1;raise RuntimeError('prepare forbidden')
  source_api.prepare_source=forbidden_prepare;source_api.lower_source=forbidden_lower;source_api._lower_prepared=forbidden_lower
  budget=RelationBudgets(**f['limits']);meter=Meter(budget)
  # Constructor reads this small already-pinned root; charge its actual plain bytes.
  meter.charge(stored=sel['manifest']['bytes'],decoded=sel['manifest']['bytes'])
  reader=RelationPartitions(sel['manifest']['path'],expected_sha256=sel['manifest']['sha256'],budgets=budget)
  phase['phase']='NORMAL_RETAINED_RELATION_READER';event('BEGIN')
  chosen=sel['selected_work'];result=reader.work(decode(RuntimeScope,chosen['scope']),decode(WorkTicketRef,chosen['work']),meter=meter)
  row=result['record']
  if row is None or not row.source_contexts or not row.static_bindings:raise ValueError('actual complete retained chain absent')
  body=decode(__import__('scar.ir.execution.fragment_relations',fromlist=['StaticEntityRef']).StaticEntityRef,sel['static_reference'])
  if not any(s.body==body for s in row.static_bindings):raise ValueError('static endpoint is not from same retained chain')
  phase['phase']='INDEPENDENT_PUBLIC_STATIC_CODEC';event('BEGIN')
  document=_source_locator_value(body.graph,meter,{})
  graph=program_loads(canonical(document).decode())
  members=[r for r in graph.regions if r.id==body.identity]
  if len(members)!=1:raise ValueError('original static Region membership differs')
  phase['phase']='FINAL_SELECTED_INPUT_SOURCE_CHECK';event('BEGIN');verify(expected)
  if any(counters.values()):raise ValueError('forbidden activity attempted')
  save('worker-result.json',{'status':'RETAINED_RELATIONS_AND_INDEPENDENT_STATIC_MEMBERSHIP_WITH_OPEN','original_window_exit_code':1,'original_public_static_member_helper':'FAILED_UNFIXED_IN_PRESERVED_PRODUCER_SOURCE','normal_relation_reader':result['validation'],'selected_work':chosen,'relation_id':row.id,'host_relations':len(row.hosts),'source_contexts':len(row.source_contexts),'static_bindings':len(row.static_bindings),'static_membership':{'reference':encode(body),'reader':'scar.ir.program.codec.loads','region_present':True,'graph_operations':len(graph.operations),'graph_regions':len(graph.regions),'graph_values':len(graph.values),'graph_locations':len(graph.locations),'scope':'STATIC_CORE_MEMBERSHIP_ONLY; NO_DYNAMIC_EXECUTION_OR_AST_REPLAY'},'complete_work_count_from_unchanged_publication':reader.manifest['report']['visited_work_count'],'whole_program_complete':False,'public_helper_passed':False,'runtime_participant_identity_fully_requalified':False,'counts':counters,'io':meter.receipt(),'elapsed_s':time.monotonic()-start,'rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss});event('FINISHED');return 0
 except BaseException as e:
  save('failure.json',{'phase':phase['phase'],'type':type(e).__name__,'detail':str(e),'traceback':traceback.format_exc(),'counts':counters,'io':meter.receipt() if meter else None});event('FAILED',detail=str(e));return 1
 finally:stop.set();signal.setitimer(signal.ITIMER_REAL,0);progress.close()
def main():
 p=argparse.ArgumentParser();p.add_argument('--read-inputs',action='store_true');p.add_argument('--worker',action='store_true');p.add_argument('--approved-freeze-sha256');a=p.parse_args()
 if not a.read_inputs and not a.worker:print('NOT_RUN');return 0
 if not a.approved_freeze_sha256:raise ValueError('approved freeze required')
 if a.worker:return worker(a.approved_freeze_sha256)
 verify(a.approved_freeze_sha256);attempt=BASE/'attempt01';attempt.mkdir(exist_ok=False);start=time.monotonic()
 with (attempt/'stdout.log').open('xb') as out,(attempt/'stderr.log').open('xb') as err:
  cmd=['/usr/bin/time','-v','-o',str(attempt/'gnu-time.txt'),sys.executable,'-B',str(Path(__file__).resolve()),'--worker','--approved-freeze-sha256',a.approved_freeze_sha256]
  try:code=subprocess.run(cmd,stdout=out,stderr=err,timeout=240,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(ROOT)}).returncode
  except subprocess.TimeoutExpired:code=124
 (attempt/'result.json').write_bytes(raw({'actual_exit_code':code,'elapsed_s':time.monotonic()-start,'original_window_exit_code':1,'freeze_sha256':a.approved_freeze_sha256,'whole_program_complete':False}));return code
if __name__=='__main__':raise SystemExit(main())
