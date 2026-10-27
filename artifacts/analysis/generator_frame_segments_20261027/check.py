"""One generator, three yields: original profile + ordinary collector/reader."""
import dis, hashlib, json, os, sys, tempfile
from pathlib import Path
from time import perf_counter
from scar.trace.call_edges import install
from scar.trace.code_snapshot import code_key
from scar.analysis.call_trace_reader import scan_call_trace, CollectingCallSink
from scar.ir.program.call_edges import CallEdgeBudget

HERE=Path(__file__).resolve().parent
EXPECTED=None
raw=[]

def source_generator():
    yield 1
    yield 2
    yield 3
    return 4

instructions={i.offset:dict(opname=i.opname,arg=i.arg) for i in dis.get_instructions(source_generator)}
def original_profile(frame,event,arg):
    if frame.f_code is source_generator.__code__ and event in ('call','return'):
        owner=frame.f_generator
        raw.append(dict(event=event,frame_id=id(frame),code_id=id(frame.f_code),lasti=frame.f_lasti,
            instruction=instructions.get(frame.f_lasti),f_generator_id=None if owner is None else id(owner),
            f_generator_type=type(owner).__name__,f_generator_is_original=owner is EXPECTED,
            profile_arg_type=type(arg).__name__))

for key in tuple(os.environ):
    if key.startswith('SCAR_'):
        os.environ.pop(key)
os.environ.update(SCAR_CAPTURE_TRANSPORT='jsonl',SCAR_CALL_MAX_EVENTS='500',SCAR_CALL_MAX_BYTES='2000000')
started=perf_counter()
sys.setprofile(original_profile)
with tempfile.TemporaryDirectory(prefix='generator-frame-segments-') as temp:
    recorder=install(temp,HERE)
    EXPECTED=source_generator()
    at_creation=len(raw)
    for index in range(4):
        try:
            next(EXPECTED)
        except StopIteration:
            pass
    recorder._collector_finish()
    assert sys.getprofile() is original_profile
    sys.setprofile(None)
    paths=Path(temp)
    records=[json.loads(line) for line in recorder.event_path.read_bytes().splitlines()]
    key=code_key(source_generator.__code__)
    selected=[r for r in records if r['code']==key]
    sink=CollectingCallSink()
    scan=scan_call_trace(paths,HERE,CallEdgeBudget(max_raw_bytes=2000000,max_lines=1000,max_codes=100,max_events=500),sink=sink)
    entries=[e for e in sink.entries if e.code==key]
    exits=[e for e in sink.exits if e.code==key]
    assert at_creation==0 and len(raw)==8 and len(entries)==len(exits)==4
    assert len({r['frame_id'] for r in raw})==len({r['f_generator_id'] for r in raw})==1
    assert all(r['f_generator_is_original'] for r in raw)
    assert len({e.invocation.invocation_id for e in entries})==4
    assert len({e.code for e in entries})==1
    assert [r['instruction']['opname'] for r in raw if r['event']=='return']==['YIELD_VALUE']*3+['RETURN_VALUE']
    metadata=json.loads((paths/f'call-meta.{recorder.pid}.json').read_text())
    source=Path(sys.modules['scar.trace.call_edges'].__file__)
    result=dict(status='OBSERVED_GENERATOR_SEGMENT_GAP',elapsed_seconds=perf_counter()-started,
        python=sys.version,collector_source=dict(uri=str(source),sha256=hashlib.sha256(source.read_bytes()).hexdigest()),
        source_key=key,raw_generator_events=raw,collector_generator_rows=selected,
        source_creation_frame_events=at_creation,retained_entries=len(entries),
        distinct_invocation_keys=len({e.invocation for e in entries}),single_raw_frame_and_generator=True,
        collector_completions=[e.completion.value for e in exits],
        original_return_opcodes=[r['instruction']['opname'] for r in raw if r['event']=='return'],
        typed_reader_consumed=True,reader_issues=[i.kind.value for i in scan.issues],
        metadata=dict(suspended_exits=metadata['suspended_exits'],dropped_events=metadata['dropped_events'],
                      errors=metadata['errors'],open_invocations=metadata['open_invocations']),
        no_production_change=True,LeWM_run=False)
    (HERE/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('raw_generator_events','collector_generator_rows')}))
