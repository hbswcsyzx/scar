"""Read-only stacks from this task's live analysis process; no remote execution."""
import _remote_debugging
import json
from pathlib import Path
import sys
import time

HERE=Path(__file__).resolve().parent
pid=int(sys.argv[1])
command=Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\x00',b' ').decode()
assert 'first_stage_source_publication_current_attempt02_20261023/run.py' in command
samples=[]
started=time.monotonic()
try:
 unwinder=_remote_debugging.RemoteUnwinder(pid,all_threads=True)
 for _ in range(3):
  samples.append({'elapsed_s':time.monotonic()-started,'stacks':unwinder.get_stack_trace()})
  time.sleep(0.15)
 status='READ_ONLY_STACKS_OBSERVED'
 error=None
except (PermissionError,OSError,RuntimeError,UnicodeDecodeError) as exc:
 status='READ_ONLY_STACK_UNAVAILABLE'
 error=type(exc).__name__+': '+str(exc)
report={'status':status,'target_pid':pid,'target_command':command,'samples':samples,'error':error,
 'remote_code_executed':False,'target_stopped_or_restarted':False,'global_configuration_changed':False,
 'elapsed_s':time.monotonic()-started,'first_stage_complete':False,
 'api_basis':'CPython v3.14.7 Modules/clinic/_remote_debugging_module.c.h RemoteUnwinder.get_stack_trace'}
with (HERE/'result.json').open('x') as stream:json.dump(report,stream,indent=2,default=str)
print(json.dumps(report,default=str))
