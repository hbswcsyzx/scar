"""Before/after actual wrapper body; no installed hooks, Torch or LeWM."""
import ast, hashlib, json, os, statistics, subprocess, sys, tempfile, threading, time, types
from pathlib import Path
from scar.trace.call_edges import CallEdgeRecorder
from scar.trace.call_operands import CallOperandObserver

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'scar/trace/call_edges.py'
BEFORE = subprocess.check_output(['git', 'show', '955d3b57:scar/trace/call_edges.py'], cwd=ROOT)
AFTER = SOURCE.read_bytes()

def wrapper(raw, recorder, previous):
    module = ast.parse(raw)
    install = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == 'install')
    callback = next(n for n in install.body if isinstance(n, ast.FunctionDef) and n.name == 'profile')
    scope = dict(recorder=recorder, threading=threading, previous=previous,
                 previous_thread=previous, main_thread=threading.get_ident())
    exec(compile(ast.Module(body=[callback], type_ignores=[]), str(SOURCE), 'exec'), scope)
    return scope['profile']

def state(previous):
    operand = types.SimpleNamespace(_closed=False)
    operand.profile = types.MethodType(CallOperandObserver.profile, operand)
    recorder = types.SimpleNamespace(_closing=False, process_ports=True, closed=False,
        io_failed=False, _is_capture_writer=None, operand_observer=operand, lock=threading.RLock())
    recorder.profile = types.MethodType(CallEdgeRecorder.profile, recorder)
    return wrapper(BEFORE, recorder, previous), wrapper(AFTER, recorder, previous)

COUNT = 100000
rounds = []
for order in [('before','after'), ('after','before'), ('before','after')]:
    row = {}
    for label in order:
        observed = [0]
        def previous(frame, event, arg):
            observed[0] += 1
        old, new = state(previous)
        callback = old if label == 'before' else new
        start = time.perf_counter_ns()
        for index in range(COUNT):
            callback(None, 'c_return' if index % 2 == 0 else 'c_exception', len)
        row[label] = (time.perf_counter_ns()-start)/1e9
        assert observed[0] == COUNT
    rounds.append(row)

# Existing previous-hook exception is not caught or reordered by the branch.
error = KeyboardInterrupt('owned metadata fixture')
def previous_raises(frame, event, arg):
    raise error
for callback in state(previous_raises):
    try:
        callback(None, 'c_exception', len)
    except BaseException as caught:
        assert caught is error
    else:
        raise AssertionError('previous callback exception lost')

# c_call takes the exact ordinary interference detector, under the original lock.
def interference(raw):
    gaps = []
    recorder = types.SimpleNamespace(_closing=False, process_ports=False, closed=False,
        io_failed=False, _is_capture_writer=None, lock=threading.RLock())
    recorder.profile = types.MethodType(CallEdgeRecorder.profile, recorder)
    operand = types.SimpleNamespace(_closed=False, pid=os.getpid(), _lock=threading.RLock(),
        _stopped=False, _monitoring_interfered=False, program_ports=False,
        lean_plan=None, _base_state=lambda frame:None,
        _gap=lambda *args:gaps.append(args))
    operand._profile_setter = types.MethodType(CallOperandObserver._profile_setter, operand)
    operand._mark_interference = types.MethodType(CallOperandObserver._mark_interference, operand)
    operand.profile = types.MethodType(CallOperandObserver.profile, operand)
    recorder.operand_observer = operand
    wrapper(raw, recorder, None)(None, 'c_call', sys.setprofile)
    assert operand._stopped and operand._interfered
    return gaps
old_gap, new_gap = interference(BEFORE), interference(AFTER)
assert old_gap == new_gap == [('VISIBLE_HOOK_OR_MONITORING_MUTATION', None)]

# Two ordinary real frame rows and code descriptors have identical bytes.
# C completion events add zero rows; no sys.setprofile/monitoring hook is installed.
def frame_rows(callback):
    frame = sys._getframe()
    callback(frame, 'call', None)
    callback(frame, 'c_return', len)
    callback(frame, 'c_exception', len)
    callback(frame, 'return', None)

os.environ['SCAR_CAPTURE_TRANSPORT'] = 'jsonl'
rows = []
with tempfile.TemporaryDirectory(prefix='noop-completion-metadata-') as temp:
    for name, raw in [('before', BEFORE), ('after', AFTER)]:
        # Keep the same one-variable explicit bound, without alias differences
        # from this harness's changing top-level before/after byte strings.
        recorder = CallEdgeRecorder(Path(temp)/name, HERE, max_values=1)
        frame_rows(wrapper(raw, recorder, None))
        recorder.close()
        events, codes = recorder.event_path.read_bytes(), recorder.code_path.read_bytes()
        rows.append(dict(events=events, codes=codes))
    assert rows[0] == rows[1], 'ordinary frame metadata changed'
    event_kinds = [json.loads(line)['kind'] for line in rows[1]['events'].splitlines()]
    assert event_kinds == ['call_enter', 'call_exit']
result = dict(status='PASS', base='955d3b57', source_uri=str(SOURCE),
    before_sha256=hashlib.sha256(BEFORE).hexdigest(), after_sha256=hashlib.sha256(AFTER).hexdigest(),
    events_per_timing=COUNT, event_types=['c_return','c_exception'], rounds=rounds,
    before_median_seconds=statistics.median(r['before'] for r in rounds),
    after_median_seconds=statistics.median(r['after'] for r in rounds),
    previous_calls_each_timing=COUNT, previous_exception_same_object=True,
    c_call_interference_ordinary_detector=list(new_gap[0]),
    ordinary_frame_events=event_kinds, ordinary_frame_bytes=len(rows[1]['events']),
    ordinary_frame_sha256=hashlib.sha256(rows[1]['events']).hexdigest(),
    ordinary_code_bytes=len(rows[1]['codes']),
    ordinary_code_sha256=hashlib.sha256(rows[1]['codes']).hexdigest(), metadata_bytes_equal=True,
    hooks_installed=False, native_os_collectors=False, fixture_only=True,
    LeWM_speedup_not_measured=True,
    scope='current extracted wrapper bodies; real domain early-return methods and ordinary frame rows; not a full capture or attribution of the old prefix')
(HERE/'RESULT.json').write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps(result))
