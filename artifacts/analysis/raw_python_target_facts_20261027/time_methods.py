"""One same-process bounded metadata-method timing, not an inference A/B."""
import dis, hashlib, importlib.util, json, os, subprocess, sys, tempfile
from pathlib import Path
from time import perf_counter_ns as now
from types import SimpleNamespace
from scar.trace import python_call_targets as after
from scar.trace.call_operands import _layout
from scar.trace.code_snapshot import code_key,site
from scar.ir.program.python_call_targets import read_target_record,PythonCallTarget,PythonEntryBinding,BoundReceiver,PythonTargetGap
from scar.ir.program.call_edges import InvocationKey

HERE=Path(__file__).resolve().parent
ACTIVE=REFERENCE=CALL_SITE=None
ENTRY_NS=0
CHECKS={}
os.sched_setaffinity(0,{54,55})
os.environ['SCAR_CAPTURE_TRANSPORT']='snapshot'

def method(self):
    global ENTRY_NS
    start=now()
    ACTIVE.on_frame_enter(sys._getframe())
    ENTRY_NS+=now()-start

class Receiver:pass
Receiver.method=method

def caller(observer,receiver,index):
    start=now()
    observer.on_call(method,receiver,False,caller.__code__,1,CALL_SITE,index,REFERENCE,_layout)
    elapsed=now()-start
    receiver.method()
    return elapsed

def run(module,directory,count):
    global ACTIVE,REFERENCE,CALL_SITE,ENTRY_NS
    directory.mkdir();tokens={}
    REFERENCE=lambda x:tokens.setdefault(id(x),f'weak:{os.getpid()}:{len(tokens)+1}')
    def state(frame):
        return ((1,code_key(frame.f_code))if frame.f_code is caller.__code__ else
                (2,code_key(frame.f_code))if frame.f_code is method.__code__ else None)
    recorder=SimpleNamespace(out=directory,pid=os.getpid(),root=str(HERE),index=10)
    operand=SimpleNamespace(recorder=recorder,_base_state=state,_code_inside=lambda c:False,lean_plan=None)
    observer=module.PythonTargetObserver(operand,module.PythonTargetBudget(count*2+8,32000000,8))
    ACTIVE=observer;ENTRY_NS=0;CHECKS.clear()
    receiver=[Receiver(),Receiver()]
    CALL_SITE=site(caller.__code__,[i.offset for i in dis.get_instructions(caller)if i.opname=='CALL'][-1])
    total=0;start=now()
    for index in range(1,count+1):
        method.__defaults__=None if index%3 else (index,)
        total+=caller(observer,receiver[index%2],index)
    g=now();observer.gap(None,'METHOD_MICRO_END');gap=now()-g
    wall=now()-start;checks=dict(CHECKS)
    observer.close();raw=observer.path.read_bytes()
    # The ordinary typed validation stays outside the measured callback window.
    for line in raw.splitlines():read_target_record(json.loads(line))
    return dict(on_call_ns=total,on_frame_enter_ns=ENTRY_NS,gap_ns=gap,loop_wall_ns=wall,
                callback_IR_post_init_calls=checks,rows=observer.records,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())

with tempfile.TemporaryDirectory(prefix='target-method-timing-')as temp:
    root=Path(temp);p=root/'before.py'
    p.write_bytes(subprocess.check_output(['git','show','1d4d681d:scar/trace/python_call_targets.py']))
    spec=importlib.util.spec_from_file_location('_before_target_method_timing',p)
    before=importlib.util.module_from_spec(spec);sys.modules[spec.name]=before;spec.loader.exec_module(before)
    originals=[]
    for cls in (InvocationKey,PythonCallTarget,PythonEntryBinding,BoundReceiver,PythonTargetGap):
        original=cls.__post_init__;originals.append((cls,original))
        def counted(self,_original=original,_name=cls.__name__):
            CHECKS[_name]=CHECKS.get(_name,0)+1
            return _original(self)
        cls.__post_init__=counted
    try:
        old=run(before,root/'before',5000)
        new=run(after,root/'after',5000)
    finally:
        for cls,original in originals:cls.__post_init__=original
    assert (old['rows'],old['bytes'],old['sha256'])==(new['rows'],new['bytes'],new['sha256'])
    assert not new['callback_IR_post_init_calls']

r=dict(status='PASS',count=5000,before=old,after=new,wire_byte_identical=True,
       ordinary_typed_readback=True,clock='perf_counter_ns',inclusive_times_overlap=False,
       scope='only actual observer on_call/entry/gap methods; no profile hooks, source capture, native/OS or target episode',
       diagnostic_overhead='two clocks/call and IR-post-init counters; single paired run, not LeWM speedup')
(HERE/'METHOD_TIMINGS.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))
