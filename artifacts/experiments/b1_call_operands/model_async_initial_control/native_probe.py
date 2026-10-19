"""Bounded native ASEND observations before model changes; no tests or lowering."""
import hashlib
import inspect
import json
from pathlib import Path
import subprocess
import sys

from scripts.run_gate import fingerprint


HERE = Path(__file__).resolve().parent
destination = HERE / 'native-probe.json'
assert not destination.exists()
before, sources = fingerprint()
prior = HERE.parent / 'model_call_effect_expansions'
assert sources == json.loads((prior / 'verified-final/sources.after.json').read_text())
assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip() == '96b8a322590217151ff6a5e839c7ab17d068f560'
observations = []


def snapshot(body):
    return {'phase': inspect.getasyncgenstate(body), 'active_session': body.ag_running,
            'suspended': body.ag_suspended, 'frame_present': body.ag_frame is not None}


def step(request, body, label, argument=None):
    try:
        result = {'kind': 'RETURN', 'value': request.send(argument)}
    except BaseException as error:
        result = {'kind': 'RAISE', 'type': type(error).__name__, 'message': str(error)}
        if isinstance(error, StopIteration):
            result['value'] = error.value
    row = {'label': label, 'scheduler_argument': argument, 'result': result, 'body': snapshot(body)}
    observations.append(row)
    return row


async def values(events):
    events.append('entry')
    first = yield 10
    events.append(first)
    second = yield first
    events.append(second)
    yield second


events = []
body = values(events)
bad = body.asend(23)
row = step(bad, body, 'created-nonNone-latent-rejected')
assert row['result']['type'] == 'TypeError' and not events
assert row['body']['phase'] == inspect.AGEN_CREATED and not row['body']['active_session']
row = step(bad, body, 'same-rejected-request-cannot-retry')
assert row['result']['type'] == 'RuntimeError' and not events
assert row['body']['phase'] == inspect.AGEN_CREATED
row = step(body.asend(None), body, 'fresh-None-request-starts-same-created-body')
assert row['result'] == {'kind': 'RAISE', 'type': 'StopIteration', 'message': '10', 'value': 10}
assert events == ['entry'] and row['body']['phase'] == inspect.AGEN_SUSPENDED
row = step(body.asend(31), body, 'fresh-nonNone-request-resumes-suspended-body')
assert row['result']['type'] == 'StopIteration' and row['result']['value'] == 31
assert events == ['entry', 31]
row = step(body.asend(61), body, 'initial-nonNone-scheduler-overrides-latent', 77)
assert row['result']['type'] == 'StopIteration' and row['result']['value'] == 77
assert events == ['entry', 31, 77]
step(body.aclose(), body, 'close-first-body')
assert body.ag_frame is None

override_events = []
body = values(override_events)
row = step(body.asend(None), body, 'created-None-latent-nonNone-scheduler-rejected', 43)
assert row['result']['type'] == 'TypeError' and not override_events
assert row['body']['phase'] == inspect.AGEN_CREATED
step(body.aclose(), body, 'close-override-body')
assert body.ag_frame is None


class Gate:
    def __await__(self):
        received = yield 'handoff'
        return received


later_events = []


async def waiting():
    received = await Gate()
    later_events.append(received)
    yield 17


body = waiting()
request = body.asend(None)
row = step(request, body, 'initial-None-reaches-await')
assert row['result'] == {'kind': 'RETURN', 'value': 'handoff'}
assert row['body']['active_session']
row = step(request, body, 'later-scheduler-is-current-input', 'current-S')
assert row['result']['type'] == 'StopIteration' and row['result']['value'] == 17
assert later_events == ['current-S'] and not row['body']['active_session']
step(body.aclose(), body, 'close-waiting-body')
assert body.ag_frame is None
after, final = fingerprint()
assert before == after and sources == final
record = {'python': sys.version, 'python_executable': sys.executable,
          'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'base_revision': '96b8a322590217151ff6a5e839c7ab17d068f560',
          'source_sha256_before': before, 'source_sha256_after': after, 'sources': sources,
          'observations': observations, 'events': events,
          'override_events': override_events, 'later_events': later_events,
          'tests_started': 0, 'automatic_source_recovery': False,
          'reference_source': 'https://raw.githubusercontent.com/python/cpython/3.14/Objects/genobject.c',
          'reference_functions': ['gen_send_ex2', 'async_gen_asend_send', 'async_gen_unwrap_value'],
          'reference_scope': 'Moving3.14 reference reviewed separately; actual installed runtime behavior comes from these observations.'}
destination.write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({'observations': len(observations), 'source_sha256': before,
                  'first_bad_request_reuse': observations[1]['result']['type'],
                  'suspended_override_observed': events[-1], 'tests_started': 0}))
