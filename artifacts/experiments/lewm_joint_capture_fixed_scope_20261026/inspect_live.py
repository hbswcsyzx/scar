"""Bounded live diagnostics only; no claim of EOF or artifact verification."""
from pathlib import Path
import json,time
control=Path(__file__).resolve().parent
command=json.loads((control/'COMMAND.json').read_text())
trace=Path(command['capture_root'])/'trace'
files=[]
for pattern in ('call-operands.*.jsonl','python-call-targets.*.jsonl','call-events.*.jsonl'):
    for path in trace.glob(pattern):
        size=path.stat().st_size
        with path.open('rb') as stream:
            stream.seek(max(0,size-65536));raw=stream.read(65536)
        lines=raw.splitlines()
        if size>65536:lines=lines[1:]
        if raw and not raw.endswith(b'\n'):lines=lines[:-1]
        last=None
        for line in reversed(lines):
            try:last=json.loads(line);break
            except ValueError:pass
        summary={k:last[k] for k in ('index','kind','reason','invocation_id','call_attempt','attempt') if k in last} if last else None
        files.append({'path':str(path),'bytes_visible':size,'last_complete_visible':summary})
metas=[]
for pattern in ('call-meta.*.json','call-operand-meta.*.json','python-call-target-meta.*.json'):
    for path in trace.glob(pattern):
        if path.stat().st_size<1_000_000:
            try:meta=json.loads(path.read_text())
            except ValueError:continue
            metas.append({'path':str(path),'summary':{k:meta[k] for k in ('events','call_attempts','handshakes','gaps','counts','stopped','dropped_events','errors','io_failed') if k in meta}})
record={'utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'qualification':'live buffered tail only; diagnostic, not artifact validation','files':files,'closed_metadata':metas}
with (control/'LIVE_DIAGNOSTICS.jsonl').open('a') as stream:stream.write(json.dumps(record)+'\n')
print(json.dumps(record,indent=2))
with (control/'stderr.txt').open('rb') as stream:
    stream.seek(max(0,stream.seek(0,2)-1500));print(stream.read(1500).decode('utf-8','replace'))
