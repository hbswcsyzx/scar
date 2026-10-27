"""One actual installed, quota-bound collector fixture; no Torch/LeWM."""
import json, os, sys, tempfile, time
from pathlib import Path
from scar.trace.call_edges import install
from scar.trace.call_operands import CallOperandObserver

HERE=Path(__file__).resolve().parent
started=time.perf_counter()
previous_events={'c_return':0,'c_exception':0}
def previous(frame,event,arg):
    if event in previous_events:
        previous_events[event]+=1

def leaf():
    return 7

def work():
    total=0
    for _ in range(30):
        total+=leaf()
        try:
            int('bad')
        except ValueError:
            pass
    return total

os.environ.update(SCAR_CAPTURE_TRANSPORT='snapshot',SCAR_PYTHON_CAPTURE_PROFILE='SCAR_PROGRAM_PORTS_V2',
 SCAR_CALL_MAX_EVENTS='100',SCAR_CALL_MAX_BYTES='200000',SCAR_CALL_MAX_CODES='32',
 SCAR_CALL_MAX_REFERENCES='256',SCAR_SOURCE_MAX_FILES='4',SCAR_SOURCE_MAX_FILE_BYTES='20000',
 SCAR_SOURCE_MAX_BYTES='40000')
for key in ('SCAR_CALL_TRACE_OWNER_PID','SCAR_CAPTURE_PHASES','SCAR_COLLECTOR_EXECUTION_WITNESS'):
    os.environ.pop(key,None)
sys.setprofile(previous)
with tempfile.TemporaryDirectory(prefix='quota-bound-collector-') as temp:
    recorder=install(temp,HERE)
    operand=CallOperandObserver(recorder,capture='process-ports',max_events=100,max_bytes=18000,
        python_targets=True,stream_interfaces=True)
    targets,env,streams=operand.python_targets,operand.environment_observer,operand.stream_interfaces
    original=recorder._instrumentation_barrier
    calls_after_stop=[0]
    def counted_barrier(frame,event):
        if event=='call' and recorder._entry_stop_reason is not None:
            calls_after_stop[0]+=1
        return original(frame,event)
    recorder._instrumentation_barrier=counted_barrier
    result=work()
    stop_reason=recorder._entry_stop_reason
    during_quota=dict(closing=recorder._closing,closed=recorder.closed,phase_events=recorder.phase_events,
        skipped=recorder._skipped_entries,open_frames=len(recorder.active))
    finish_error=None
    try:
        recorder._collector_finish()
    except Exception as error:
        finish_error=type(error).__name__
    assert sys.getprofile() is previous
    sys.setprofile(None)
    root=Path(temp)
    base=json.loads((root/f'call-meta.{recorder.pid}.json').read_text())
    meta=json.loads((root/f'call-operand-meta.{recorder.pid}.json').read_text())
    small={f.name:json.loads(f.read_text()) for f in root.glob('*.json')}
    rows=[json.loads(line) for line in recorder.event_path.read_bytes().splitlines()]
    source_rows=[json.loads(line) for line in operand._event_path.read_bytes().splitlines()] if operand._event_path.stat().st_size else []
    assert result==210
    assert stop_reason is not None and during_quota['skipped']>0
    assert not during_quota['closing'] and not during_quota['closed'] and during_quota['phase_events'] is None
    assert calls_after_stop==[0]
    assert base['open_invocations']==0
    assert base['events']==len(rows) and base['events']<=100
    assert sum(r['kind']=='call_enter' for r in rows)==sum(r['kind']=='call_exit' for r in rows)
    assert meta['io_failed'] and 'OPERAND_MATERIALIZATION_UNAVAILABLE' in meta['errors']
    assert finish_error!='TypeError'
    assert operand._closed and recorder.closed and env._closed and targets.closed and streams.closed
    assert previous_events['c_return']>0 and previous_events['c_exception']>0
    assert not list(root.glob('capture-phase.*'))
    proof=dict(status='PASS',elapsed_seconds=time.perf_counter()-started,work_result=result,
      recording_stop=base['recording_stop'],during_quota=during_quota,
      fallback_walk_calls_after_stop=calls_after_stop[0],previous_events=previous_events,
      retained_frames=len(rows),retained_returns=sum(r['kind']=='call_exit' for r in rows),
      open_invocations=base['open_invocations'],operand_errors=meta['errors'],
      finish_error=finish_error,all_sidecars_closed=True,exit_phase_events=0,
      target_or_LeWM=False,scope='actual installed own collector; explicit prior hook; tiny operand transport quota; partial evidence remains failed')
    (HERE/'RESULT.json').write_text(json.dumps(proof,indent=2)+'\n')
    (HERE/'SMALL_RECEIPTS.json').write_text(json.dumps(small,indent=2)+'\n')
    print(json.dumps(proof))
