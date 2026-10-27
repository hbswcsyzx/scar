"""Pure sidecar transport checks; no profile installation/capture or target."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from scar.trace.callable_environment import CallableEnvironmentObserver

HERE = Path(__file__).resolve().parent
BASE = 'fa9adadfa83fc15a303f6ddf501365444cad71bf'
SOURCE = 'scar/trace/callable_environment.py'
old = subprocess.check_output(['git','show',BASE+':'+SOURCE])

with tempfile.TemporaryDirectory(prefix='environment-buffer-') as directory:
    temp = Path(directory)
    previous = temp/'previous.py'; previous.write_bytes(old)
    spec = importlib.util.spec_from_file_location('_previous_environment',previous)
    module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    def produce(cls, path, *, maximum=1_000_000, count=1000):
        observer = cls(path,os.getpid(),max_events=2000,max_bytes=maximum,max_references=16)
        writes = 0
        original = os.write
        def write(fd, data):
            nonlocal writes
            writes += 1
            return original(fd,data)
        os.write = write
        try:
            for _ in range(count):
                observer._gap('TRANSPORT_ONLY_'+'x'*96)
            observer.close(); observer.close()
        finally:
            os.write = original
        raw = observer.event_path.read_bytes()
        meta = json.loads(observer.metadata_path.read_bytes())
        assert raw.endswith(b'\n')
        assert len(raw)==meta['bytes']==meta['file']['raw_bytes']
        assert hashlib.sha256(raw).hexdigest()==meta['file']['raw_sha256']
        assert len([json.loads(x) for x in raw.splitlines()])==meta['events']
        return raw,meta,writes
    before,before_meta,before_writes = produce(module.CallableEnvironmentObserver,temp/'old')
    after,after_meta,after_writes = produce(CallableEnvironmentObserver,temp/'new')
    assert before==after and before_meta['events']==after_meta['events']==1000
    first_bytes = len(before.splitlines(keepends=True)[0])
    limited,meta,_ = produce(CallableEnvironmentObserver,temp/'limited',maximum=first_bytes+1,count=2)
    assert len(limited)==first_bytes and meta['events']==1 and meta['dropped_events']==1
    assert meta['stop_reason']=='BYTE_BUDGET' and meta['io_failed'] is False
    fork = CallableEnvironmentObserver(temp/'fork',os.getpid(),max_events=2,max_bytes=10_000,max_references=16)
    fork._gap('FORK_TRANSPORT_ONLY')
    queued = len(fork._buffer)
    child = os.fork()
    if child == 0:
        os._exit(0 if fork._closed and fork._fd is None and not fork._buffer else 1)
    _,status = os.waitpid(child,0)
    assert os.waitstatus_to_exitcode(status)==0 and len(fork._buffer)==queued
    fork.close()
    assert len(fork.event_path.read_bytes().splitlines())==1

result = dict(status='PURE_TRANSPORT_BYTE_BUDGET_CLOSE_AND_FORK_PASS',
    base_commit=BASE,source=SOURCE,before_sha256=hashlib.sha256(old).hexdigest(),
    after_sha256=hashlib.sha256(Path(SOURCE).read_bytes()).hexdigest(),
    rows=1000,event_bytes=len(after),byte_identical=True,
    write_calls_including_one_metadata_write=dict(before=before_writes,after=after_writes),
    byte_budget=dict(events=meta['events'],dropped=meta['dropped_events'],bytes=len(limited),limit=first_bytes+1),
    child_did_not_flush_parent_buffer=True,normal_close_and_repeat_close_readable=True,
    profile_installed=False,capture_started=False,target_executed=False,
    runtime_speedup_measured=False)
with (HERE/'RESULT.json').open('x') as stream: json.dump(result,stream,indent=2)
print(json.dumps(result))
