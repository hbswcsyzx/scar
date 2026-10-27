"""Same-process observer calls/actual entry frames; no hooks or LeWM."""
import dis
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace

from scar.trace import python_call_targets as current
from scar.trace.call_operands import _layout
from scar.trace.code_snapshot import code_key, site
from scar.ir.program.python_call_targets import read_target_record, PythonTargetGap

HERE = Path(__file__).resolve().parent
ACTIVE = None
REFERENCE = None
CALL_SITE = None


def method(self):
    ACTIVE.on_frame_enter(sys._getframe())
    return None


class Receiver:
    pass


Receiver.method = method


def caller(observer, callable_object, receiver, attempt, mutate_defaults=False):
    observer.on_call(callable_object, receiver, False, caller.__code__, 1,
                     CALL_SITE, attempt, REFERENCE, _layout)
    if mutate_defaults:
        method.__defaults__ = (None,)
    return receiver.method()


def records(module, root, mode):
    global ACTIVE, REFERENCE, CALL_SITE
    os.environ['SCAR_CAPTURE_TRANSPORT'] = mode
    root.mkdir()
    recorder = SimpleNamespace(out=root, pid=os.getpid(), root=str(HERE), index=10)
    def state(frame):
        if frame.f_code is caller.__code__:
            return 1, code_key(frame.f_code)
        if frame.f_code is method.__code__:
            return 2, code_key(frame.f_code)
    operand = SimpleNamespace(recorder=recorder, _code_inside=lambda code:False,
                              _base_state=state, lean_plan=None)
    observer = module.PythonTargetObserver(operand, module.PythonTargetBudget(64, 100000, 8))
    ACTIVE = observer
    tokens = {}
    REFERENCE = lambda value:tokens.setdefault(id(value),f'weak:{os.getpid()}:{len(tokens)+1}')
    offset = [i.offset for i in dis.get_instructions(caller) if i.opname == 'CALL'][-1]
    CALL_SITE = site(caller.__code__, offset)
    receivers = [Receiver(), Receiver()]
    bound = [receiver.method for receiver in receivers]
    for attempt, function, receiver, defaults, mutate in [
        (1, method, receivers[0], None, False),
        (2, method, receivers[1], (None,), False),
        (3, bound[0], receivers[0], None, False),
        (4, bound[1], receivers[1], None, False),
        (5, method, receivers[0], None, True),
    ]:
        method.__defaults__ = defaults
        caller(observer, function, receiver, attempt, mutate)
    observer.on_call(len, None, True, caller.__code__, 1, CALL_SITE, 6, REFERENCE, _layout)
    observer.gap(6, 'OWNED_WIRE_CHECK')
    observer.emit('GAP', PythonTargetGap(7, 'PUBLIC_TYPED_COMPATIBILITY'))
    observer.close()
    method.__defaults__ = None
    raw = observer.path.read_bytes()
    rows = [json.loads(x) for x in raw.splitlines()]
    typed = [read_target_record(row) for row in rows]
    assert observer.counts == {'TARGET':6,'ENTRY':4,'GAP':3}, observer.counts
    assert [v.receiver_reference for k,v in typed if k=='ENTRY'][:2] == [REFERENCE(receivers[0]),None]
    assert [v.reason for k,v in typed if k=='GAP'][0] == 'CALL_RECEIVER_DEFAULT_STATE_CHANGED'
    return raw, observer.counts


with tempfile.TemporaryDirectory(prefix='raw-target-facts-') as temporary:
    root = Path(temporary)
    baseline_path = root/'before.py'
    baseline_path.write_bytes(subprocess.check_output(['git','show','1d4d681d:scar/trace/python_call_targets.py']))
    spec = importlib.util.spec_from_file_location('_before_raw_targets',baseline_path)
    before = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = before
    spec.loader.exec_module(before)
    result = []
    for mode in ('jsonl','snapshot'):
        old, counts = records(before,root/(mode+'-before'),mode)
        new, observed = records(current,root/(mode+'-after'),mode)
        assert old == new and counts == observed, 'original V2 wire changed'
        result.append(dict(transport=mode,counts=counts,bytes=len(new),
                           sha256=hashlib.sha256(new).hexdigest(),byte_identical=True))
output = dict(status='PASS',base='1d4d681d',transports=result,
    actual_method_entry_frames=4,changed_defaults_gap=True,two_receivers_retained=True,
    normal_typed_reader=True,hook_installed=False,LeWM_or_capture_run=False)
(HERE/'WIRE_RESULT.json').write_text(json.dumps(output,indent=2)+'\n')
print(json.dumps(output))
