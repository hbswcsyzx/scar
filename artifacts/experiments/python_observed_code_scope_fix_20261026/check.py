"""Normal readers over the one direct/opaque/sentinel CPU example."""
from pathlib import Path
import hashlib,json
from scar.analysis.call_operand_reader import read_call_operands
from scar.analysis.python_call_targets import read_python_call_targets

ROOT=Path(__file__).resolve().parent
project=ROOT/'example/project'
result={}
for name in ('before-with-call','after-with-call','default-with-call'):
    trace=read_call_operands(ROOT/name,project)
    codes={c.code.key:c.code.qualname for c in trace.frame_scan.captures}
    selected=[e for e in trace.entries if codes[e.code]=='selected']
    sentinel=[e for e in trace.attempts if codes.get(e.dispatch.code)=='sentinel']
    summary={'frame_entries':len(trace.entries),'selected_entries':len(selected),
        'attempts':len(trace.attempts),'sentinel_attempts':len(sentinel),
        'gaps':[g.reason for g in trace.gaps],
        'collector_errors':[e for m in trace.metadata for e in m.errors]}
    if name=='before-with-call':
        assert summary['gaps']==['INSTRUCTION_FRAME_UNAVAILABLE'] and len(selected)==1 and not sentinel
    elif name=='after-with-call':
        observed=read_python_call_targets(trace)
        assert not trace.gaps and len(selected)==2 and len(sentinel)==1
        # Code-scope observation is separate from immediate callable proof.
        bound=[e for e in observed.entries if codes[e.code]=='selected']
        assert len(bound)==1 and bound[0].callee==selected[0].invocation
        assert all(e.callee!=selected[1].invocation for e in observed.entries)
        summary['exact_selected_target_entry_relations']=len(bound)
        summary['indirect_entry_fabricated_handshake']=False
        summary['observed']=observed.summary()
    else:
        assert not trace.gaps and len(selected)==1 and len(sentinel)==1
        assert not tuple((ROOT/name).glob('python-call-target-meta.*.json'))
    result[name]=summary
result['source_sha256']={name:hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in
    ('scar/trace/call_edges.py','scar/trace/call_operands.py','scar/trace/python_call_targets.py')}
(ROOT/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
