"""Optional plain exit-phase events for the owned launcher's time budget.

These are lifecycle observations, not a graph, GPU-ready claim, or proof that
daemon threads/external actors ended. Only the first qualified atexit boundary
can start one bounded postprocessing interval.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import threading
import time
from types import CodeType, FrameType

from scar.ir.record_codec import loads
from scar.trace.code_snapshot import code_key

PROFILE = 'SCAR_EXIT_PHASES_V1'
SCHEMA = 'scar.capture-phase-event'


def _need(value, message):
    if not value:
        raise ValueError('capture phases: ' + message)


def _source(path):
    path = Path(path).absolute()
    _need(not path.is_symlink() and path.is_file(), 'producer source absent/symlinked')
    raw = path.read_bytes()
    _need(len(raw) <= 2_000_000, 'producer source exceeds bound')
    return {'uri': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw)}


def _producer(code):
    return {'entrypoint': code.co_qualname, 'code_key': code_key(code), 'source': _source(code.co_filename)}


def phase_request(postprocess_seconds):
    """Pin this ordinary collector's source/code before its child starts."""
    _need(type(postprocess_seconds) is int and postprocess_seconds > 0, 'positive postprocessing seconds required')
    from scar.trace.execution_evidence import ExecutionEvidence
    from scar.trace.call_edges import install
    codes = [ExecutionEvidence.close_at_exit.__code__]
    codes += [c for c in install.__code__.co_consts if type(c) is CodeType
              and c.co_name in ('finish', 'finish_at_exit')]
    _need(len(codes) == 3, 'known collector exit callbacks required')
    return {'profile': PROFILE, 'postprocess_seconds': postprocess_seconds,
            'helper_source': _source(__file__), 'producers': {c.co_qualname: _producer(c) for c in codes},
            'boundary': 'owner main-thread C atexit entry; not all actors ended or GPU ready'}


def _process(pid):
    # Bounded kernel process identity only: no memory, locals, FD table or attach.
    text = (Path('/proc') / str(pid) / 'stat').read_text()
    _need(len(text) <= 16_384 and ') ' in text, 'process stat exceeds bound')
    fields = text.rsplit(') ', 1)[1].split()
    return {'pid': pid, 'parent_pid': int(fields[1]), 'start_ticks': int(fields[19])}


def _stamp(path):
    s = path.stat(follow_symlinks=False)
    return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns


class CapturePhases:
    """Live recorder-owned emitter. No JSON-to-owner constructor exists."""

    @classmethod
    def from_environment(cls, recorder):
        if os.environ.get('SCAR_CAPTURE_PHASES') is None:
            return None
        try:
            from scar.trace.os_capture_launch import _document
            _need(os.environ['SCAR_CAPTURE_PHASES'] == PROFILE, 'unknown exit-phase profile')
            nonce = os.environ['SCAR_OS_CAPTURE_NONCE']
            expected = recorder.out.parent / ('os-capture-intent.' + nonce + '.json')
            _need(Path(os.environ['SCAR_OS_CAPTURE_INTENT']).absolute() == expected, 'intent path differs')
            intent, receipt = _document(expected)
            _need(receipt['sha256'] == os.environ['SCAR_OS_CAPTURE_INTENT_SHA256']
                  and intent['nonce'] == nonce and intent['trace_directory'] == str(recorder.out)
                  and intent['phase_budget']['profile'] == PROFILE, 'phase intent differs')
            self = cls()
            self.owner = _process(recorder.pid)
            self.owner.update(python_ident=threading.get_ident(), native_tid=threading.get_native_id())
            self.recorder, self.nonce, self.intent_sha = recorder, nonce, receipt['sha256']
            self.request, self.stop = intent['phase_budget'], None
            return self
        except Exception:
            return None  # Optional budget evidence missing: retain the old wall limit.

    def _emit(self, phase, frame, previous=None):
        _need(os.getpid() == self.owner['pid'] and threading.get_ident() == self.owner['python_ident']
              and threading.get_native_id() == self.owner['pid']
              and threading.current_thread() is threading.main_thread(), 'not original main-thread owner')
        producer = _producer(frame.f_code)
        _need(producer == self.request['producers'].get(frame.f_code.co_qualname)
              and _source(__file__) == self.request['helper_source'], 'phase producer source/code changed')
        event = {'schema': SCHEMA, 'schema_version': 1, 'phase': phase,
            'nonce': self.nonce, 'intent_sha256': self.intent_sha, 'owner': self.owner,
            'clock': 'time.monotonic_ns', 'monotonic_ns': time.monotonic_ns(),
            'producer': producer, 'helper_source': self.request['helper_source'], 'previous': previous}
        raw = (json.dumps(event, separators=(',', ':'), allow_nan=False) + '\n').encode()
        path = self.recorder.out / f'capture-phase.{self.nonce}.{self.owner["pid"]}.{phase}.json'
        from scar.trace.os_capture_launch import publish_bytes
        publish_bytes(path, raw)
        return {'uri': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw), 'schema': SCHEMA}

    def begin_atexit(self, frame):
        try:
            _need(type(frame) is FrameType and frame.f_back is None and not self.recorder.closed,
                  'only original C atexit entry can declare main execution ended')
            if self.stop is None:
                self.stop = self._emit('ATEXIT_STOPPING', frame)
            return True
        except Exception:
            return False

    def converting(self, frame):
        try:
            if self.stop is not None and self.recorder._closing:
                self._emit('CONVERTING', frame, self.stop)
        except Exception:
            pass  # No budget renewal or target retry on missing evidence.


class PhaseDeadline:
    """Own-launch budget consumer; source, nonce and live ancestry are checked."""

    def __init__(self, root, nonce, intent_sha, request, provider_pid, started_ns, recording_seconds):
        self.root, self.nonce, self.intent_sha, self.request = root, nonce, intent_sha, request
        self.provider_pid, self.started_ns = provider_pid, started_ns
        self.recording_deadline = started_ns + recording_seconds * 1_000_000_000
        self.stop, self.events, self.cache, self.frontiers = None, {}, {}, []
        self.invalid = False

    def _read(self, path):
        stamp = _stamp(path)
        _need(not path.is_symlink() and stamp[2] <= 32_000, 'invalid phase marker file')
        if path in self.cache:
            _need(self.cache[path][0] == stamp, 'published phase marker changed')
            return self.cache[path][1:]
        raw = path.read_bytes()
        _need(_stamp(path) == stamp and len(raw) == stamp[2], 'phase marker changed during read')
        doc = loads(raw.decode('utf-8'))
        receipt = {'uri': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw), 'schema': SCHEMA}
        self.cache[path] = stamp, doc, receipt
        return doc, receipt

    def _validate(self, path, event, now):
        owner = event['owner']
        _need(event['schema'] == SCHEMA and type(event['schema_version']) is int and event['schema_version'] == 1
              and event['nonce'] == self.nonce and event['intent_sha256'] == self.intent_sha
              and event['phase'] in ('ATEXIT_STOPPING', 'CONVERTING')
              and event['clock'] == 'time.monotonic_ns' and type(event['monotonic_ns']) is int
              and self.started_ns <= event['monotonic_ns'] <= now, 'phase namespace/clock differs')
        _need(type(owner['pid']) is int and owner['pid'] > 0 and owner['native_tid'] == owner['pid']
              and path.name == f'capture-phase.{self.nonce}.{owner["pid"]}.{event["phase"]}.json', 'phase owner/path differs')
        producer = event['producer']
        _need(event['helper_source'] == self.request['helper_source']
              and producer == self.request['producers'].get(producer['entrypoint']), 'unrecognized phase producer')
        allowed = ('ExecutionEvidence.close_at_exit', 'install.<locals>.finish_at_exit')
        _need(producer['entrypoint'] in allowed if event['phase'] == 'ATEXIT_STOPPING'
              else producer['entrypoint'] == 'install.<locals>.finish', 'wrong phase callback')

    def deadline(self, now):
        try:
            paths = sorted((self.root/'trace').glob(f'capture-phase.{self.nonce}.*.json'))
            _need(len(paths) <= 2, 'conflicting phase event inventory')
            found = {}
            for path in paths:
                event, receipt = self._read(path)
                self._validate(path, event, now)
                _need(event['phase'] not in found, 'ambiguous phase owner')
                found[event['phase']] = event, receipt
            _need(all(name in found for name in ('ATEXIT_STOPPING','CONVERTING') if name in self.events),
                  'accepted phase marker disappeared')
            if 'ATEXIT_STOPPING' in found:
                event, receipt = found['ATEXIT_STOPPING']
                _need(event['previous'] is None and event['monotonic_ns'] <= self.recording_deadline,
                      'atexit occurred after the original recording deadline')
                if self.stop is None:
                    live = _process(event['owner']['pid'])
                    _need(all(live[k] == event['owner'][k] for k in ('pid','parent_pid','start_ticks')),
                          'phase owner incarnation differs')
                    ancestry, pid = [], live['pid']
                    for _ in range(16):
                        _need(pid > 1, 'phase owner is not provider descendant')
                        ancestry.append(pid)
                        pid = _process(pid)['parent_pid']
                        if pid == self.provider_pid:
                            break
                    _need(pid == self.provider_pid and live['pid'] != self.provider_pid,
                          'phase owner is outside this live provider tree')
                    self.stop = event
                    self.events['owner_binding'] = {'kernel_sources': ['/proc/'+str(p)+'/stat' for p in ancestry],
                        'observed_parent_chain': ancestry + [self.provider_pid], 'owner': live}
                _need(event == self.stop, 'first atexit boundary changed')
                self.events['ATEXIT_STOPPING'] = receipt
            if 'CONVERTING' in found:
                event, receipt = found['CONVERTING']
                _need(self.stop is not None and event['owner'] == self.stop['owner']
                      and event['previous'] == self.events['ATEXIT_STOPPING']
                      and event['monotonic_ns'] >= self.stop['monotonic_ns'], 'conversion has no exact exit predecessor')
                self.events['CONVERTING'] = receipt
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.invalid = True
            if len(self.frontiers) < 8 and str(error) not in self.frontiers:
                self.frontiers.append(str(error))
        if self.stop is None or self.invalid:
            return self.recording_deadline
        return self.stop['monotonic_ns'] + self.request['postprocess_seconds'] * 1_000_000_000

    def report(self):
        return {'profile': PROFILE, 'requested_postprocess_seconds': self.request['postprocess_seconds'],
            'qualified_atexit': self.stop is not None and not self.invalid, 'events': self.events,
            'frontiers': self.frontiers, 'recording_deadline_monotonic_ns': self.recording_deadline,
            'postprocess_deadline_monotonic_ns': None if self.stop is None or self.invalid else
                self.stop['monotonic_ns'] + self.request['postprocess_seconds'] * 1_000_000_000,
            'basis': 'pinned collector code/source, exact nonce/intent and live owned provider ancestry; not hostile-process authentication',
            'scope': 'main atexit and collector shutdown only; daemon/external completion and GPU ready remain unknown'}
