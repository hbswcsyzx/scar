"""One actual profile/monitoring behavior check, not a production trace proof."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

from scar.trace.call_edges import CallEdgeRecorder
from scar.trace.call_operands import CallOperandObserver


HERE=Path(__file__).resolve().parent


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def main():
    subject=load('guard_subject',HERE/'project/subject.py')
    foreign=load('guard_foreign',HERE/'outside/foreign.py')
    recorder=CallEdgeRecorder(HERE/'actual',HERE/'project',max_events=1000,max_bytes=1000000)
    observer=CallOperandObserver(recorder,capture='windows',max_events=4000,max_bytes=2000000)
    real_getpid=os.getpid;count={'calls':0}
    def counted_getpid():
        count['calls']+=1
        return real_getpid()
    previous=sys.getprofile();assert previous is None
    def profile(frame,event,arg):
        recorder.profile(frame,event,arg)
        observer.profile(frame,event,arg)
    os.getpid=counted_getpid
    sys.setprofile(profile)
    before=count['calls'];assert foreign.noise(1000)==1000
    ordinary_outside_pid_calls=count['calls']-before
    assert ordinary_outside_pid_calls==0
    assert subject.normal(2)==3
    assert not recorder.active and not observer._frames
    try:subject.exceptional()
    except ValueError:pass
    assert recorder.unknown_exits==1 and not recorder.active and not observer._frames
    read_fd,write_fd=os.pipe();child=os.fork()
    if child==0:
        # Direct constructors install no SCAR at_fork callback: this checks
        # the retained PID guard, rather than relying on hook auto-disarming.
        old_index=recorder.index;old_attempts=observer._event_attempts
        subject.normal(3)
        okay=recorder.index==old_index and observer._event_attempts==old_attempts
        os.write(write_fd,b'PID_GUARD_PRESERVED' if okay else b'FAILED')
        os._exit(0 if okay else 2)
    os.close(write_fd);message=os.read(read_fd,100);os.close(read_fd)
    _,status=os.waitpid(child,0)
    assert os.waitstatus_to_exitcode(status)==0 and message==b'PID_GUARD_PRESERVED'
    foreign.remove_hook()
    assert sys.getprofile() is None and observer._stopped and observer._interfered
    os.getpid=real_getpid
    observer.stop();recorder.close();observer.close()
    report={'schema':'scar.profile-owner-guard-behavior','schema_version':1,'status':'PASS',
        'ordinary_outside_calls':1000,'ordinary_outside_pid_syscalls':ordinary_outside_pid_calls,
        'unknown_exception_returns':recorder.unknown_exits,'retained_frames_after_return':len(observer._frames),
        'fork_pid_guard_preserved':True,'outside_root_visible_hook_mutation_detected':True,
        'scope':'one real profile/monitoring/fork behavior check; no graph or whole-program proof'}
    with (HERE/'summary.json').open('x') as stream:json.dump(report,stream,indent=2,sort_keys=True);stream.write('\n')
    print(json.dumps(report,sort_keys=True))


if __name__=='__main__':main()
