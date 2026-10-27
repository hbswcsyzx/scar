import json,os
from pathlib import Path
from scar.trace.call_edges import CallEdgeRecorder
from scar.trace.call_operands import CallOperandObserver
root=Path(__file__).resolve().parent/'negative02'
root.mkdir()

rec=CallEdgeRecorder(root/'fork',root/'project')
obs=CallOperandObserver(rec,capture='windows',python_targets=True)
obs._buffer.extend(b'parent operand\n');obs.python_targets._buffer.extend(b'parent target\n')
pid=os.fork()
if pid==0:
    blocked=0
    for writer in (obs,obs.python_targets):
        try:writer._flush()
        except OSError:blocked+=1
    os._exit(0 if blocked==2 else 1)
_,status=os.waitpid(pid,0)
assert os.waitstatus_to_exitcode(status)==0
assert obs._event_path.stat().st_size==0 and obs.python_targets.path.stat().st_size==0
obs._buffer.clear();obs.python_targets._buffer.clear()
obs.stop();rec.close();obs.close()

rec=CallEdgeRecorder(root/'operand-failed',root/'project')
obs=CallOperandObserver(rec,capture='windows')
obs._buffer.extend(b'pending\n')
def fail(data):raise OSError('injected owned operand flush failure')
obs._write_all=fail
obs.stop();rec.close();obs.close()
meta=json.loads(obs._metadata_path.read_text())
assert meta['io_failed']

rec=CallEdgeRecorder(root/'target-failed',root/'project')
obs=CallOperandObserver(rec,capture='windows',python_targets=True)
target=obs.python_targets;target._buffer.extend(b'pending\n');target._write_all=fail
obs.stop();rec.close()
try:obs.close()
except OSError:pass
else:raise AssertionError('failed target flush accepted')
assert target.closed and not target.meta.exists()
report={'forked_child_cannot_flush_either_parent_buffer':True,'operand_flush_failure_marks_io_failed':True,
        'target_flush_failure_prevents_final_manifest':True,'uses_application_values':False}
(root/'negative-result.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
