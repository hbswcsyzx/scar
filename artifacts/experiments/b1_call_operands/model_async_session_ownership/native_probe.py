"""A bounded native observation, not automatic program lowering or a proof."""
import hashlib
import inspect
import json
from pathlib import Path
import sys

from scripts.run_gate import fingerprint

HERE = Path(__file__).resolve().parent
before, sources = fingerprint()
observations = []


class Gate:
    def __init__(self, token):
        self.token = token

    def __await__(self):
        yield self.token
        return None


def snapshot(body):
    return {'inspect_state': inspect.getasyncgenstate(body), 'suspended': body.ag_suspended,
            'active_session': body.ag_running, 'awaiting': body.ag_await is not None,
            'frame_present': body.ag_frame is not None}


def step(request, body, label):
    try:
        result = request.send(None)
    except BaseException as error:
        result = {'kind': 'RAISE', 'type': type(error).__name__, 'message': str(error)}
        if isinstance(error, StopIteration):
            result['value'] = error.value
    else:
        result = {'kind': 'RETURN', 'value': result}
    row = {'label': label, 'result': result, 'body': snapshot(body)}
    observations.append(row)
    return row


events = []


async def two_awaits():
    events.append('entry')
    await Gate('handoff-1')
    events.append('resume-1')
    await Gate('handoff-2')
    events.append('resume-2')
    yield 17


body = two_awaits()
first, second = body.__anext__(), body.__anext__()
distinct_requests = first is not second
assert distinct_requests
row = step(first, body, 'R1.first-await')
assert row['result'] == {'kind': 'RETURN', 'value': 'handoff-1'}
assert row['body']['suspended'] and row['body']['active_session']
saved_events = list(events)
row = step(second, body, 'R2.competing-initial-attempt')
assert row['result']['type'] == 'RuntimeError' and events == saved_events
assert row['body']['active_session'] and row['body']['awaiting']
row = step(first, body, 'R1.continues-through-second-await')
assert row['result'] == {'kind': 'RETURN', 'value': 'handoff-2'}
row = step(first, body, 'R1.item-completes')
assert row['result']['type'] == 'StopIteration' and row['result']['value'] == 17
assert not row['body']['active_session']
row = step(second, body, 'R2.retry-after-original-owner-completes')
assert row['result']['type'] == 'RuntimeError'
step(body.aclose(), body, 'body.close')
assert body.ag_frame is None

initial = []
for value in (None, 23):
    body = two_awaits()
    request = body.asend(value)
    row = step(request, body, 'initial-ASEND-' + ('None' if value is None else 'nonNone'))
    initial.append(row)
    if value is None:
        assert row['result']['kind'] == 'RETURN' and row['body']['active_session']
        step(request, body, 'initial-None-resume-1')
        step(request, body, 'initial-None-item')
    else:
        assert row['result']['type'] == 'TypeError'
        assert row['body']['inspect_state'] == inspect.AGEN_CREATED
        assert not row['body']['active_session']
    step(body.aclose(), body, 'initial-body-close')
    assert body.ag_frame is None

after, final_sources = fingerprint()
assert before == after and sources == final_sources
destination = HERE / 'native-probe.json'
assert not destination.exists()
record = {'python': sys.version, 'python_executable': sys.executable,
          'command': [sys.executable, str(Path(__file__).relative_to(Path.cwd()))],
          'activation': 'source /home/zyf/miniconda3/etc/profile.d/conda.sh; conda activate lewm',
          'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'source_sha256_before': before, 'source_sha256_after': after,
          'sources': sources, 'distinct_live_requests_observed': distinct_requests,
          'observations': observations, 'events': events,
          'tests_started': 0, 'automatic_source_recovery': False,
          'reference_source': 'https://raw.githubusercontent.com/python/cpython/3.14/Objects/genobject.c',
          'reference_functions': ['async_gen_asend_send', 'async_gen_unwrap_value']}
record['inspect_state_implementation_sha256'] = hashlib.sha256(
    inspect.getsource(inspect.getasyncgenstate).encode()).hexdigest()
destination.write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({'status': 'OBSERVED_NATIVE_BOUNDARY', 'observations': len(observations),
                  'source_sha256': before, 'tests_started': 0}))
