"""Small closed-V2 wire and mutable CALL association check; no hooks/capture."""
import dataclasses
import dis
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace

from scar.ir.program.call_edges import InvocationKey
from scar.ir.program.python_call_targets import (
    PythonEntryBinding, PythonTargetGap, read_target_record, target_record)
from scar.trace.call_operands import _layout, _layout_record
from scar.trace.code_snapshot import code_key, site
from scar.trace.python_call_targets import PythonTargetObserver, PythonTargetBudget, _target_record

HERE = Path(__file__).resolve().parent


def function(self, value=None):
    return value


class Receiver:
    method = function


def caller(receiver):
    return receiver.method(1)


def packed(value):
    return json.dumps(value, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode('ascii')


receivers = [Receiver(), Receiver()]
methods = [receiver.method for receiver in receivers]
offset = next(i.offset for i in dis.get_instructions(caller) if i.opname == 'CALL')
call_site = site(caller.__code__, offset)
tokens = {}
def reference(value):
    return tokens.setdefault(id(value), f'weak:{os.getpid()}:{len(tokens)+1}')

with tempfile.TemporaryDirectory(prefix='scar-wire-') as temporary:
    operand = SimpleNamespace(recorder=SimpleNamespace(out=Path(temporary), pid=os.getpid(), root=str(HERE)),
                              _code_inside=lambda code: False)
    observer = PythonTargetObserver(operand, PythonTargetBudget(32, 100_000, 8))
    # Different mutable defaults and two live receiver objects at the same
    # static code/site. Only the first is a normalized finite receiver ABI.
    calls = [(function, receivers[0], None), (function, receivers[0], (7,)),
             (methods[0], receivers[0], None), (methods[1], receivers[1], None),
             (len, receivers[0], None), (receivers[0].__str__, receivers[0], None),
             (receivers[0], receivers[0], None)]
    for attempt, (callable_object, receiver, defaults) in enumerate(calls, 1):
        function.__defaults__ = defaults
        observer.on_call(callable_object, receiver, False, caller.__code__, 1,
                         call_site, attempt, reference, _layout)
        observer.pending.clear()
    observer.emit('ENTRY', PythonEntryBinding(1, InvocationKey(os.getpid(), 1, 1),
        InvocationKey(os.getpid(), 1, 2), 1, code_key(function.__code__), 0, reference(receivers[0])))
    observer.emit('GAP', PythonTargetGap(2, 'OWNED_MICRO_GAP'))
    observer.close()
    raw = observer.path.read_bytes()
    documents = [json.loads(row) for row in raw.splitlines()]
    for document in documents:
        kind, typed = read_target_record(document)
        assert packed(_target_record(kind, typed)) == packed(target_record(kind, typed))
    targets = [row['value'] for row in documents if row['kind'] == 'TARGET']
    assert targets[0]['kind'] == 'NORMALIZED_RECEIVER_FUNCTION'
    assert targets[1]['kind'] == 'FUNCTION' and targets[1]['receiver'] is None
    assert targets[2]['receiver']['reference'] != targets[3]['receiver']['reference']
    first = _layout_record(_layout(function.__code__))
    first['parameters'].append('caller mutation')
    assert _layout_record(_layout(function.__code__))['parameters'] == ['self', 'value']
    kind, value = read_target_record(documents[0])
    object.__setattr__(value, 'attempt_index', 0)
    for encoder in (target_record, _target_record):
        try:
            encoder(kind, value)
        except ValueError:
            pass
        else:
            raise AssertionError('typed invalid target must still be rejected')
    function.__defaults__ = (None,)

result = dict(status='PASS', rows=len(documents), bytes=len(raw),
    sha256=hashlib.sha256(raw).hexdigest(), target_kinds=[row['kind'] for row in targets],
    ordinary_typed_readback=True, all_three_record_variants_byte_equal=True,
    changed_defaults_and_two_receivers_retained=True, fresh_layout_wire=True,
    invalid_typed_record_still_rejected=True, hooks_installed=False, capture_started=False)
(HERE / 'wire-check.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
