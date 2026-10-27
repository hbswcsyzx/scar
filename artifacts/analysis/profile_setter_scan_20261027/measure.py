"""Bounded method comparison; never installs a profile/monitoring hook."""
from pathlib import Path
import importlib.util,json,os,statistics,subprocess,sys,threading,time
from scar.trace.call_operands import CallOperandObserver

root=Path(__file__).resolve().parent
old_path=root/'before.py'
old_path.write_bytes(subprocess.check_output(['git','show','d12d62bd:scar/trace/call_operands.py']))
spec=importlib.util.spec_from_file_location('_scar_before_profile_setter',old_path)
before=importlib.util.module_from_spec(spec);sys.modules[spec.name]=before;spec.loader.exec_module(before)
old=before.CallOperandObserver._profile_setter
new=CallOperandObserver._profile_setter
obj=object.__new__(CallOperandObserver)
callbacks=[len,hash,os.getpid,{}.get,[].append,sys.setprofile,sys.settrace,threading.setprofile,threading.settrace,threading.setprofile_all_threads,threading.settrace_all_threads]
callbacks += [getattr(sys.monitoring,n) for n in ('set_events','set_local_events','register_callback','use_tool_id','free_tool_id','restart_events')]
assert [old(obj,c) for c in callbacks]==[new(obj,c) for c in callbacks]
held=sys.setprofile
try:
    sys.setprofile=len
    assert old(obj,len)==new(obj,len)=='profile'
finally:sys.setprofile=held
rounds=[]
for pair in range(3):
    values={}
    for name,method in ((('old',old),('new',new)) if pair%2==0 else (('new',new),('old',old))):
        start=time.perf_counter_ns()
        for index in range(100000):method(obj,callbacks[index%5])
        values[name]=(time.perf_counter_ns()-start)/1e9
    rounds.append(values)
result={'status':'SCOPED_METHOD_PASS','ordinary_C_callbacks_per_timing':100000,'rounds':rounds,'old_median':statistics.median(r['old'] for r in rounds),'new_median':statistics.median(r['new'] for r in rounds),'classifications_equal':True,'checked_interfaces':len(callbacks),'live_binding_replacement_checked':True,'profile_hooks_installed':False,'target_executed':False,'whole_program_complete':False}
(root/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
