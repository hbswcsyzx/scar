"""One root-owned complete-work retained relation gate; no target or lowering."""
import argparse, ast, gzip, hashlib, importlib, json, os, pickle, _compat_pickle, uuid, _uuid
from pathlib import Path
import resource, signal, sqlite3, subprocess, sys, threading, time, traceback
BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[3]

def wire(value):return (json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)+'\n').encode()
def sha(data):return hashlib.sha256(data).hexdigest()
def preload():
    for folder in ('program','execution'):
        for p in sorted((ROOT/'scar/ir'/folder).glob('*.py')):
            if p.stem!='__init__':importlib.import_module('scar.ir.'+folder+'.'+p.stem)
    for name in ('scar.analysis.fragment_relations','scar.analysis.source_native_composition','scar.analysis.program_lowering',
                 'scar.store.fragment_relations','scar.ir.program.codec','scar.ir.execution.codec'):
        importlib.import_module(name)
    return {str(Path(m.__file__).resolve()) for n,m in tuple(sys.modules.items())
            if n!='__main__' and not n.startswith('scar') and getattr(m,'__file__',None)}
def verify(expected):
    raw=(BASE/'freeze.json').read_bytes()
    if sha(raw)!=expected:raise ValueError('approved relation freeze differs')
    f=json.loads(raw)
    if Path(f['attempt'])!=BASE/'attempt01':raise ValueError('attempt path differs')
    count=0
    for row in f['source_and_runtime']+f['tools']:
        p=Path(row['path']);data=p.read_bytes();count+=len(data)
        if p.is_symlink() or (len(data),sha(data))!=(row['bytes'],row['sha256']):raise ValueError('frozen source/runner/runtime changed: '+str(p))
    if count>32_000_000:raise ValueError('per-pass source/runtime guard budget')
    for r in f['inputs']:
        s=Path(r['path']).stat()
        if (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)!=(r['device'],r['inode'],r['bytes'],r['mtime_ns'],r['ctime_ns']):raise ValueError('input stat changed: '+r['path'])
    return f,count

def worker(expected):
    start=time.monotonic();attempt=BASE/'attempt01';stop=threading.Event();lock=threading.Lock()
    phase={'phase':'PRELOAD'};producer=None;guard_bytes=[]
    counts={'target_executable_compile_attempts':0,'target_exec_attempts':0,'source_prepare_attempts':0,'lower_attempts':0,'subprocess_attempts':0,'non_target_compile_events':0}
    progress=(attempt/'progress.jsonl').open('xb')
    def event(name,**more):
        with lock:
            item={**phase,'event':name,'elapsed_s':time.monotonic()-start,'self_peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,**more}
            if producer is not None:item.update(producer_phase=getattr(producer,'phase',None),io=getattr(producer,'_meter',None).receipt() if getattr(producer,'_meter',None) is not None else None)
            progress.write(wire(item));progress.flush();print(wire(item).decode(),end='',flush=True)
    def beat():
        while not stop.wait(20):event('HEARTBEAT')
    threading.Thread(target=beat,daemon=True).start()
    signal.signal(signal.SIGALRM,lambda *x:(_ for _ in ()).throw(TimeoutError('worker1500s')));signal.setitimer(signal.ITIMER_REAL,1500)
    resource.setrlimit(resource.RLIMIT_AS,(2*1024**3,2*1024**3))
    def save(name,value):
        raw=wire(value)
        if len(raw)>4_000_000:raise ValueError('gate record4MB')
        with (attempt/name).open('xb') as stream:stream.write(raw)
    try:
        def bootstrap_guard(event,args):
            if event=='import' and str(args[0]).split('.')[0] in ('torch','torchvision','stable_worldmodel'):
                counts['target_exec_attempts']+=1;raise RuntimeError('target import forbidden during preload')
        sys.addaudithook(bootstrap_guard)
        preload();f,n=verify(expected);guard_bytes.append(n)
        known={r['path'] for r in f['source_and_runtime']+f['tools']+f['inputs']}|{str(BASE/'freeze.json')}
        raw_members=set(f['raw_capture_paths'])
        def audit(name,args):
            if name=='open' and isinstance(args[0],(str,bytes,os.PathLike)):
                p=Path(os.fsdecode(args[0])).absolute();s=str(p);mode=args[1] or '';flags=args[2] or 0
                writing=any(c in mode for c in 'wax+') or bool(flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
                if writing and not p.is_relative_to(attempt):raise PermissionError('write outside new attempt')
                if not writing and s in raw_members:raise PermissionError('raw collector input forbidden')
                if not writing and (p.is_relative_to(ROOT/'artifacts') or '/scar-worktrees/' in s) and not p.is_relative_to(attempt) and s not in known:
                    raise PermissionError('unfrozen retained input '+s)
            elif name in ('subprocess.Popen','os.system','os.exec'):
                counts['subprocess_attempts']+=1;raise RuntimeError('target/subprocess forbidden')
            elif name=='import' and str(args[0]).split('.')[0] in ('torch','torchvision','stable_worldmodel'):
                counts['target_exec_attempts']+=1;raise RuntimeError('target package import forbidden')
            elif name=='compile':
                filename=os.fsdecode(args[1]) if isinstance(args[1],(str,bytes,os.PathLike)) else ''
                if filename.startswith('/home/zyf/AAA/le-wm/'):
                    counts['target_executable_compile_attempts']+=1;raise RuntimeError('target compile forbidden')
                counts['non_target_compile_events']+=1
            elif name=='exec':
                filename=getattr(args[0],'co_filename','')
                if filename.startswith('/home/zyf/AAA/le-wm/'):
                    counts['target_exec_attempts']+=1;raise RuntimeError('target exec forbidden')
        sys.addaudithook(audit)
        from scar.ir.record_codec import decode,encode
        from scar.analysis.fragment_relations import FragmentInputs,FragmentRelationProducer,static_member
        from scar.ir.execution.fragment_relations import RuntimeScope,WorkTicketRef,stable_key
        from scar.store.fragment_relations import RelationBudgets,publish_fragment_relations,RelationPartitions
        import scar.analysis.program_lowering as source_api
        def forbidden_prepare(*a,**k):counts['source_prepare_attempts']+=1;raise RuntimeError('source prepare forbidden')
        def forbidden_lower(*a,**k):counts['lower_attempts']+=1;raise RuntimeError('source lower forbidden')
        source_api.prepare_source=forbidden_prepare;source_api.lower_source=forbidden_lower;source_api._lower_prepared=forbidden_lower
        selection=json.loads((BASE/'selection.json').read_bytes());inputs=decode(FragmentInputs,selection['inputs'])
        budget=RelationBudgets(**f['limits']);producer=FragmentRelationProducer(inputs,schema_version=2)
        phase['phase']='FULL_WORK_PRODUCER';event('BEGIN')
        publication=publish_fragment_relations(producer,attempt/'result',budgets=budget)
        manifest_raw=(attempt/'result/manifest.json').read_bytes();m=json.loads(manifest_raw)
        if m['report']['declared_work_count']!=selection['expected_work_count'] or m['report']['visited_work_count']!=selection['expected_work_count']:raise ValueError('complete24082 denominator differs')
        if m['schema_version']!=2 or m['report']['missing_relations'].get('STATE_CONTENT_READY_UNPROVED')!=selection['expected_work_count']:raise ValueError('v2/state-ready debt differs')
        phase['phase']='NORMAL_RELATION_CONSUMER';event('BEGIN')
        reader=RelationPartitions(attempt/'result/manifest.json',expected_sha256=publication['sha256'],budgets=budget)
        representative=m['report']['first_unique_connected_work']
        if representative is None:raise ValueError('full inventory has no unique real native/source/CodeVersion chain')
        samples={};queries=[];static_result=None
        selected=[representative,m['report'].get('first_static_body_work')]
        selected.extend(v for _,v in sorted(m['report']['first_enclosing_work_by_depth'].items(),key=lambda x:int(x[0])))
        if len(selected)>6:raise ValueError('normal query6 budget')
        for chosen in selected:
            if chosen is None:continue
            scope=decode(RuntimeScope,chosen['scope']);ref=decode(WorkTicketRef,chosen['work']);key=stable_key((scope,ref))
            if key not in samples:
                result=reader.work(scope,ref,meter=producer._meter);samples[key]=result
                if result['record'] is None:raise ValueError('published representative missing')
                queries.append({'work':chosen,'id':result['record'].id,'hosts':len(result['record'].hosts),'enclosing_native':len(result['record'].enclosing_native),'enclosing_depths':[len(r.parents) for r in result['record'].enclosing_native],'contexts':len(result['record'].source_contexts),'static_bindings':len(result['record'].static_bindings),'validation':result['validation']})
            row=samples[key]['record']
            if static_result is None:
                bodies=[s.body for s in row.static_bindings if s.body is not None and s.body.graph.decoded_bytes<=budget.max_metadata_bytes]
                if bodies:
                    checked=static_member(bodies[0],meter=producer._meter)
                    static_result={'reference':encode(checked['reference']),'member_type':type(checked['member']).__name__,'qualification':checked['qualification'],'runtime_occurrence_implied':False}
        phase['phase']='FINAL_FROZEN_INPUT_RUNTIME_CHECK';event('BEGIN')
        producer.finish();final,n=verify(expected);guard_bytes.append(n)
        runtime=preload();allowed={r['path'] for r in final['source_and_runtime']}
        if not runtime<=allowed:raise ValueError('runtime participant missing '+repr(sorted(runtime-allowed)))
        if any(counts[k] for k in ('target_executable_compile_attempts','target_exec_attempts','source_prepare_attempts','lower_attempts','subprocess_attempts')):raise ValueError('forbidden activity attempted')
        save('worker-result.json',{'status':'COMPLETE_WORK_DENOMINATOR_V2_ENCLOSING_RELATIONS_WITH_OPEN','publication':publication,'report':m['report'],'queries':queries,'static_member':static_result,'static_body_debt':static_result is None,'activity':counts,'source_runtime_guard_bytes':guard_bytes,'io':producer._meter.receipt(),'runtime_participants':sorted(runtime),'elapsed_s':time.monotonic()-start,'self_peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'whole_program_complete':False,'published_as_whole_program':False,'target_episode_created':False})
        event('FINISHED');return 0
    except BaseException as error:
        save('failure.json',{'phase':phase['phase'],'type':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc(),'activity':counts,'io':producer._meter.receipt() if producer is not None and getattr(producer,'_meter',None) is not None else None,'elapsed_s':time.monotonic()-start})
        event('FAILED',error=str(error));return 1
    finally:stop.set();signal.setitimer(signal.ITIMER_REAL,0);progress.close()

def main():
    p=argparse.ArgumentParser();p.add_argument('--read-inputs',action='store_true');p.add_argument('--worker',action='store_true');p.add_argument('--approved-freeze-sha256');a=p.parse_args()
    if not a.read_inputs and not a.worker:print('FROZEN_NOT_RUN: root owns actual handle');return 0
    if not a.approved_freeze_sha256:raise ValueError('approved freeze required')
    if a.worker:return worker(a.approved_freeze_sha256)
    preload();f,n=verify(a.approved_freeze_sha256);attempt=Path(f['attempt']);attempt.mkdir(exist_ok=False);start=time.monotonic()
    with (attempt/'stdout.log').open('xb') as out,(attempt/'stderr.log').open('xb') as err:
        cmd=['/usr/bin/time','-v','-o',str(attempt/'gnu-time.txt'),sys.executable,'-B',str(Path(__file__).resolve()),'--worker','--approved-freeze-sha256',a.approved_freeze_sha256]
        try:code=subprocess.run(cmd,stdout=out,stderr=err,timeout=1560,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(ROOT),'PYTHONPYCACHEPREFIX':str(attempt/'unused-pycache')}).returncode
        except subprocess.TimeoutExpired:code=124
    (attempt/'result.json').write_bytes(wire({'actual_worker_exit_code':code,'elapsed_s':time.monotonic()-start,'freeze_sha256':a.approved_freeze_sha256,'outer_guard_bytes':n,'whole_program_complete':False}))
    return code
if __name__=='__main__':raise SystemExit(main())
