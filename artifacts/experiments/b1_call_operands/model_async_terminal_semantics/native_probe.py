"""Finite local async terminal/close observations; no SCAR graph or permissions."""
import hashlib
import inspect
import json
from pathlib import Path
import sys

from scripts.run_gate import fingerprint


HERE = Path(__file__).resolve().parent
BASE = '54118247d4ff4c764dbe6f66493bc8609041f24b'


def state(body):
    return {'phase': inspect.getasyncgenstate(body), 'active_session': body.ag_running,
            'suspended': body.ag_suspended, 'frame_present': body.ag_frame is not None,
            'native_ag_closed_bit': 'NOT_EXPOSED_BY_THIS_PROBE'}


def observe(rows, label, body, request, *, argument=None, source=None, marks=None):
    before = state(body)
    try:
        result = {'kind': 'YIELD', 'value': request.send(argument)}
    except BaseException as error:
        result = {'kind': 'RAISE', 'type': type(error).__name__, 'message': str(error),
            'cause_type': None if error.__cause__ is None else type(error.__cause__).__name__,
            'context_type': None if error.__context__ is None else type(error.__context__).__name__,
            'same_source_exception': error is source if source is not None else None,
            'cause_is_source': error.__cause__ is source if source is not None else None,
            'context_is_source': error.__context__ is source if source is not None else None}
        if isinstance(error, StopIteration):
            result['value'] = error.value
    rows.append({'label': label, 'before': before, 'result': result,
                 'after': state(body), 'marks': None if marks is None else tuple(marks)})


async def natural():
    yield 'item'


async def active(error):
    yield 'item'
    raise error


async def ignored_close(marks):
    try:
        yield 'item'
    finally:
        marks.append('finally-entered')
        yield 'illegal-during-close'
        marks.append('finally-resumed')


class Pause:
    def __await__(self):
        yield 'cleanup-handoff'
        return None


async def awaited_close(marks):
    try:
        yield 'item'
    finally:
        marks.append('finally-entered')
        await Pause()
        marks.append('finally-resumed')


before, sources = fingerprint()
rows, bodies, compile_rows = [], [], []
body = natural()
bodies.append(body)
observe(rows, 'natural-first-item', body, body.__anext__())
observe(rows, 'natural-terminal-anext', body, body.__anext__())
observe(rows, 'finished-frame-new-anext', body, body.__anext__())
observe(rows, 'finished-frame-new-asend', body, body.asend(17))
request = body.athrow(ValueError('closed frame input'))
observe(rows, 'finished-frame-new-athrow', body, request)
observe(rows, 'finished-frame-same-athrow-retry', body, request)
observe(rows, 'finished-frame-new-aclose', body, body.aclose())

for category in (StopIteration, StopAsyncIteration, ValueError):
    error = category('active terminal')
    body = active(error)
    bodies.append(body)
    observe(rows, category.__name__ + '-prime', body, body.__anext__())
    observe(rows, category.__name__ + '-escapes', body, body.__anext__(), source=error)

marks = []
body = ignored_close(marks)
bodies.append(body)
observe(rows, 'ignored-close-prime', body, body.__anext__(), marks=marks)
request = body.aclose()
observe(rows, 'ignored-close-first-request-error', body, request, marks=marks)
observe(rows, 'ignored-close-same-request-retry', body, request, marks=marks)
observe(rows, 'ignored-close-new-aclose-with-continuation', body, body.aclose(), marks=marks)
observe(rows, 'ignored-close-new-athrow-with-continuation', body,
        body.athrow(ValueError('input after native close bit')), marks=marks)
observe(rows, 'ignored-close-new-anext-resumes-continuation', body, body.__anext__(), marks=marks)

marks = []
body = awaited_close(marks)
bodies.append(body)
observe(rows, 'awaited-close-prime', body, body.__anext__(), marks=marks)
request = body.aclose()
observe(rows, 'awaited-close-handoff-keeps-active-request', body, request, marks=marks)
observe(rows, 'awaited-close-resume-completes-body-and-request', body, request,
        argument='scheduler-ack', marks=marks)

for label, text in (
    ('nonempty-asyncgen-return', 'async def invalid():\n    yield 1\n    return 2\n'),
    ('bare-asyncgen-return', 'async def valid():\n    yield 1\n    return\n')):
    try:
        compile(text, '<scar-native-terminal-probe>', 'exec')
    except SyntaxError as error:
        compile_rows.append({'label': label, 'accepted': False, 'kind': 'SyntaxError',
                             'message': error.msg, 'line': error.lineno})
    else:
        compile_rows.append({'label': label, 'accepted': True})

assert all(body.ag_frame is None and not body.ag_running for body in bodies)
after, final = fingerprint()
assert before == after and sources == final
record = {'base_revision': BASE, 'python': sys.version, 'python_executable': sys.executable,
    'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'source_sha256_before': before, 'source_sha256_after': after, 'sources': sources,
    'observations': rows, 'compile_observations': compile_rows,
    'all_bodies_finished': True, 'tests_started': 0,
    'source_runtime_verified': False, 'transformation_authorized': False}
assert not (HERE / 'native-probe.json').exists()
(HERE / 'native-probe.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({'source_sha256': before, 'observations': rows,
                  'compile_observations': compile_rows}, indent=2))
