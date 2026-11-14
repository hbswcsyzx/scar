"""Owned interpreter boundaries joining persistent resumable activations.

Original call records identify running segments. Actual monitoring events,
not code flags, connect them across yields. No frames or payloads are kept.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import threading

from scar.ir.program.call_edges import InvocationKey, CapturedSite
from scar.ir.record_codec import decode
from scar.trace.code_snapshot import site
from scar.trace.files import open_binary

SCHEMA = 'scar.resumption-boundaries'
KINDS = ('PY_START', 'PY_RESUME', 'PY_THROW', 'PY_YIELD', 'PY_RETURN', 'PY_UNWIND')
ENTRIES = frozenset(KINDS[:3])
LOCAL = frozenset(('PY_START', 'PY_RESUME', 'PY_YIELD', 'PY_RETURN'))
FLAGS = 0x20 | 0x80 | 0x200


@dataclass(frozen=True, slots=True)
class ResumptionBoundary:
    sequence: int
    activation: int
    kind: str
    invocation: InvocationKey
    profile_event_index: int
    position: CapturedSite
    previous: int | None
    origin_observed: bool


def _bytes(value):
    return (json.dumps(value, separators=(',', ':'), sort_keys=True)+'\n').encode()


def _receipt(path):
    digest = sha256(); size = 0
    with open_binary(path) as stream:
        while block := stream.read(65536):
            digest.update(block); size += len(block)
    return dict(uri=str(path), sha256=digest.hexdigest(), size_bytes=size)


class ResumptionObserver:
    """Bounded, optional owner-process channel; frame addresses stay transient.

    A real PY_START always replaces any old address entry with a new ordinal.
    The original profile writer hands off only accepted boundary coordinates.
    Both pending boundaries and suspended activations contain metadata only.
    """
    def __init__(self, recorder):
        self.recorder = recorder; self.pid = recorder.pid; self.monitor = sys.monitoring
        self.name = 'scar-resumptions:'+str(self.pid)
        self.tool = next((i for i in range(6) if self.monitor.get_tool(i) is None), None)
        if self.tool is None: raise RuntimeError('no free monitoring tool for resumptions')
        self.frames = {}; self.pending = {}; self.callbacks = {}
        self.sequence = self.activation = self.size = 0
        self.counts = dict.fromkeys(KINDS, 0); self.frontiers = {}
        self.closed = self.stopped = False; self.digest = sha256()
        self.path = recorder.out/f'resumptions.{self.pid}.jsonl'
        self.stream = self.path.open('xb', buffering=65536)
        self.monitor.use_tool_id(self.tool, self.name)
        try:
            for kind in KINDS:
                callback = self._callback(kind); self.callbacks[kind] = callback
                self.monitor.register_callback(self.tool, getattr(self.monitor.events, kind), callback)
            self.monitor.set_events(self.tool, sum(getattr(self.monitor.events, k) for k in KINDS))
        except BaseException:
            self.monitor.set_events(self.tool, 0); self.monitor.free_tool_id(self.tool)
            self.stream.close(); raise

    def _gap(self, reason):
        self.frontiers[reason] = self.frontiers.get(reason, 0)+1

    def _stop(self, reason):
        self._gap(reason); self.stopped = True

    def profile_event(self, frame, kind, invocation, code, index):
        if self.closed or self.stopped or not frame.f_code.co_flags & FLAGS: return
        key = threading.get_ident(), id(frame)
        if len(self.pending) >= self.recorder.limits['max_references'] and key not in self.pending:
            self._stop('PENDING_PROFILE_BOUNDARY_BUDGET'); return
        if key in self.pending:
            self._stop('PROFILE_BOUNDARY_WITHOUT_MATCHING_MONITOR_EVENT'); return
        self.pending[key] = kind, invocation, code, index

    def _callback(self, kind):
        def callback(code, offset, *unused_payload):
            if not code.co_flags & FLAGS:
                return self.monitor.DISABLE if kind in LOCAL else None
            if self.closed or self.stopped or os.getpid() != self.pid: return
            frame = sys._getframe(1)
            if frame.f_code is not code:
                self._stop('MONITOR_CALLBACK_FRAME_MISMATCH'); return
            with self.recorder.lock:
                try: self._observe(frame, kind, offset)
                except Exception as error: self._stop('MONITOR_BOUNDARY_'+type(error).__name__)
        return callback

    def _observe(self, frame, kind, offset):
        thread = threading.get_ident(); address = id(frame)
        pending = self.pending.pop((thread, address), None); prior = self.frames.get(address)
        if kind == 'PY_START':
            self.frames.pop(address, None); prior = None
        if pending is None:
            if prior is not None:
                self.frames.pop(address, None); self._gap('BOUNDARY_SEGMENT_NOT_RETAINED')
            return
        profile_kind, invocation, code, index = pending
        if profile_kind != ('call' if kind in ENTRIES else 'return'):
            self._stop('PROFILE_MONITOR_ORDER_UNSUPPORTED'); return
        position = site(frame.f_code, offset)
        if position['code'] != code:
            self._stop('PROFILE_MONITOR_CODE_MISMATCH'); return
        if kind in ENTRIES:
            if kind == 'PY_START' or prior is None:
                self.activation += 1
                activation, previous, origin = self.activation, None, kind == 'PY_START'
                if not origin: self._gap('RESUME_ORIGIN_NOT_OBSERVED')
            else:
                activation, previous, origin, old_code, phase, _ = prior
                if old_code != code or phase != 'PY_YIELD':
                    self._stop('RESUME_WITHOUT_MATCHING_SUSPENSION'); return
        else:
            if prior is None:
                self._gap('TERMINAL_WITHOUT_RECORDED_ENTRY'); return
            activation, previous, origin, old_code, phase, segment = prior
            if old_code != code or phase not in ENTRIES or segment != (thread, invocation):
                self._stop('TERMINAL_WITHOUT_MATCHING_SEGMENT'); return
        row = dict(sequence=self.sequence+1, activation=activation, kind=kind,
            invocation=dict(process_id=self.pid, thread_id=thread, invocation_id=invocation),
            profile_event_index=index, position=position, previous=previous, origin_observed=origin)
        data = _bytes(row)
        if self.sequence >= self.recorder.limits['max_events'] or self.size+len(data) > self.recorder.limits['max_bytes']:
            self._stop('RESUMPTION_EVENT_OR_BYTE_BUDGET'); return
        self.stream.write(data); self.digest.update(data); self.size += len(data)
        self.sequence += 1; self.counts[kind] += 1
        if kind in ENTRIES or kind == 'PY_YIELD':
            self.frames[address] = activation, self.sequence, origin, code, kind, (thread, invocation)
            if len(self.frames) > self.recorder.limits['max_references']:
                self._stop('SUSPENDED_ACTIVATION_BUDGET')
        else: self.frames.pop(address, None)

    def close(self):
        if self.closed or os.getpid() != self.pid: return
        self.closed = True; owned = self.monitor.get_tool(self.tool) == self.name
        if owned:
            self.monitor.set_events(self.tool, 0)
            for kind in KINDS: self.monitor.register_callback(self.tool, getattr(self.monitor.events, kind), None)
            self.monitor.free_tool_id(self.tool)
        else: self._gap('MONITOR_TOOL_OWNERSHIP_CHANGED')
        self.stream.close()
        if self.pending: self._gap('PROFILE_BOUNDARIES_PENDING_AT_CLOSE')
        inputs = [_receipt(self.recorder.out/f'call-{family}.{self.pid}.{suffix}')
            for family, suffix in (('events', 'jsonl'), ('codes', 'jsonl'), ('meta', 'json'))]
        report = dict(schema=SCHEMA, schema_version=1, process_id=self.pid, python=sys.version,
            producer_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
            events=dict(uri=str(self.path), sha256=self.digest.hexdigest(), size_bytes=self.size),
            records=self.sequence, activations=self.activation, counts=self.counts,
            stopped=self.stopped, frontiers=self.frontiers, legacy_inputs=inputs,
            open_activations=len(self.frames), monitoring_tool_owned_at_close=owned,
            profile_monitor_order='ACCEPTED_PROFILE_BOUNDARY_THEN_MONITOR_CALLBACK',
            activation_identity='PY_START_GENERATION_AND_EXACT_FRAME_MONITOR_EVENT_CHAIN',
            frame_addresses_persisted=False, frames_or_payloads_retained=False,
            creation_object_or_contents_proven=False, normal_delivery_of_delegation_proven=False)
        (self.recorder.out/f'resumption-meta.{self.pid}.json').write_bytes(_bytes(report))
        self.frames.clear(); self.pending.clear()


def read_resumptions(metadata):
    """Check owned bytes, exact original segment references and event chains."""
    metadata = Path(metadata).absolute(); report = json.loads(metadata.read_bytes())
    pid = report['process_id']; declaration = report['events']; logical = Path(declaration['uri'])
    if ((report['schema'], report['schema_version']) != (SCHEMA, 1)
            or metadata.name != f'resumption-meta.{pid}.json'
            or logical != metadata.parent/f'resumptions.{pid}.jsonl'
            or declaration['size_bytes'] > 128_000_000 or report['stopped']
            or not report['monitoring_tool_owned_at_close']):
        raise ValueError('resumption capture grammar, scope or budget differs')
    if _receipt(logical) != declaration: raise ValueError('resumption event bytes differ')
    for reference in report['legacy_inputs']:
        if Path(reference['uri']).parent != metadata.parent or _receipt(reference['uri']) != reference:
            raise ValueError('resumptions refer to different original call inputs')
    expected = {str(metadata.parent/f'call-{family}.{pid}.{suffix}')
        for family, suffix in (('events', 'jsonl'), ('codes', 'jsonl'), ('meta', 'json'))}
    if {r['uri'] for r in report['legacy_inputs']} != expected or len(report['legacy_inputs']) != 3:
        raise ValueError('resumptions need the exact original call input set')
    original = {}
    with open_binary(metadata.parent/f'call-events.{pid}.jsonl') as stream:
        for raw in stream:
            row = json.loads(raw); original[row['index']] = row
    events = []; latest = {}; seen_segments = set(); counts = dict.fromkeys(KINDS, 0)
    with open_binary(logical) as stream:
        for raw in stream:
            row = decode(ResumptionBoundary, json.loads(raw)); key = row.invocation
            segment = original.get(row.profile_event_index)
            if (row.sequence != len(events)+1 or row.kind not in KINDS
                    or type(row.activation) is not int or not 1 <= row.activation <= report['activations']
                    or segment is None or key.process_id != pid
                    or (key.process_id, key.thread_id, key.invocation_id, row.position.code) !=
                    (segment['process_id'], segment['thread_id'], segment['invocation_id'], segment['code'])
                    or segment['kind'] != ('call_enter' if row.kind in ENTRIES else 'call_exit')):
                raise ValueError('resumption differs from its original call boundary')
            prior = latest.get(row.activation)
            if row.previous != (None if prior is None else prior.sequence):
                raise ValueError('resumption predecessor chain differs')
            if row.kind in ENTRIES:
                if (row.kind == 'PY_START' and prior is not None
                        or prior is not None and (prior.kind != 'PY_YIELD'
                            or prior.position.code != row.position.code or prior.invocation == key)
                        or key in seen_segments):
                    raise ValueError('resumption does not follow one suspended activation')
                seen_segments.add(key)
            elif prior is None or prior.kind not in ENTRIES or prior.invocation != key:
                raise ValueError('terminal does not match its entered segment')
            if (row.origin_observed != (row.kind == 'PY_START' if prior is None else prior.origin_observed)
                    or row.kind == 'PY_YIELD' and row.position.opname != 'YIELD_VALUE'):
                raise ValueError('resumption origin or yield location differs')
            latest[row.activation] = row; counts[row.kind] += 1; events.append(row)
    if len(events) != report['records'] or counts != report['counts']:
        raise ValueError('resumption count denominator differs')
    return report, tuple(events)
