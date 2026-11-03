"""Optional raw native-callable facts on existing CALL attempts.

The callback reads a small C record, issues existing reference tokens and
queues plain facts. It does no source expansion, tensor inspection or graph
construction. Source/binary receipts are computed outside the callback.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import struct
import sys


def _receipt(path):
    path = Path(path).absolute()
    before = path.stat()
    if path.is_symlink() or not path.is_file() or before.st_size > 32_000_000:
        raise ValueError('native probe receipt requires a bounded regular file')
    raw = path.read_bytes()
    after = path.stat()
    stamp = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    if stamp(before) != stamp(after) or len(raw) != before.st_size:
        raise ValueError('native probe receipt input changed')
    return {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


class NativeCallableObserver:
    def __init__(self, target, probe_path):
        from scar.trace.native_callable_probe import load_probe
        from scar.analysis.native_callables import build_fields
        from scar.trace.deferred_jsonl import DeferredJsonl, snapshot_transport_enabled

        self.target = target
        self.recorder = target.recorder
        binary = Path(probe_path).absolute()
        self.probe_binary = _receipt(binary)
        self.probe_source = _receipt(binary.with_name('_native_callable_probe.c'))
        self.probe = load_probe(binary).probe
        # The loader cannot change either receipt while this capability is made.
        if _receipt(binary) != self.probe_binary:
            raise ValueError('native probe changed during loading')
        self.build_fields = build_fields
        self.path = self.recorder.out / f'native-callables.{self.recorder.pid}.jsonl'
        self.meta = self.recorder.out / f'native-callable-meta.{self.recorder.pid}.json'
        self.budget = {'max_records': target.budget.max_records,
                       'max_bytes': target.budget.max_bytes, 'max_line_bytes': 2_000_000}
        self.fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        self.deferred = None
        try:
            if snapshot_transport_enabled():
                self.deferred = DeferredJsonl(self.path, max_bytes=self.budget['max_bytes'])
        except BaseException:
            os.close(self.fd)
            raise
        self.rows = self.bytes = self.attempts = 0
        self.digest = hashlib.sha256()
        self.buffer = bytearray()
        self.errors = []
        self.stopped = self.closed = self.io_failed = False

    def on_call(self, callable_object, caller, attempt, call_ref, reference):
        self.attempts += 1
        if self.stopped or self.closed:
            return
        if self.rows >= self.budget['max_records']:
            self.stopped = True
            return
        try:
            facts = self.probe(callable_object)
            row = {'schema': 'scar.native-callables', 'schema_version': 1,
                   'event_index': self.rows + 1, 'caller': dict(caller),
                   'attempt_index': attempt, 'callable_reference': call_ref,
                   'carrier': facts['kind'], 'fields': self.build_fields(facts, reference)}
            if self.deferred is not None:
                if not self.deferred.append(row):
                    self.stopped = True
                    return
                self.bytes = self.deferred.accepted_bytes
            else:
                raw = (json.dumps(row, ensure_ascii=True, separators=(',', ':'),
                                  allow_nan=False) + '\n').encode('ascii')
                if (len(raw) > self.budget['max_line_bytes']
                        or self.bytes + len(raw) > self.budget['max_bytes']):
                    self.stopped = True
                    return
                if len(self.buffer) + len(raw) > 65536:
                    self._flush_buffer()
                self.buffer.extend(raw)
                self.digest.update(raw)
                self.bytes += len(raw)
            self.rows += 1
        except Exception as error:
            # Do not run fallback getters or let a failed optional observation
            # alter application control. The reader rejects this partial channel.
            self.errors.append(type(error).__name__)
            self.stopped = True

    def _flush_buffer(self):
        if os.getpid() != self.recorder.pid:
            raise OSError('child cannot flush parent native callable facts')
        position = 0
        try:
            while position < len(self.buffer):
                written = os.write(self.fd, memoryview(self.buffer)[position:])
                if written <= 0:
                    raise OSError('native callable stream made no write progress')
                position += written
            self.buffer.clear()
        except BaseException:
            self.io_failed = self.stopped = True
            raise

    def close(self):
        if self.closed or os.getpid() != self.recorder.pid:
            return
        try:
            if self.deferred is not None:
                output = self.deferred.finalize()['output']
                self.bytes = output['raw_bytes']
                digest = output['sha256']
            else:
                self._flush_buffer()
                digest = self.digest.hexdigest()
        finally:
            try:
                if self.deferred is not None:
                    self.deferred.close_capture()
            finally:
                os.close(self.fd)
                self.closed = True
        from scar.ir.record_codec import encode
        document = {
            'schema': 'scar.native-callable-collection', 'schema_version': 1,
            'capabilities': ['NATIVE_CALLABLE_FACTS_V1'],
            'process_id': self.recorder.pid, 'project_root': self.recorder.root,
            'abi': {'implementation': sys.implementation.name,
                    'version': list(sys.version_info[:3]),
                    'cache_tag': sys.implementation.cache_tag,
                    'pointer_bits': struct.calcsize('P') * 8},
            'probe_source': self.probe_source, 'probe_binary': self.probe_binary,
            'legacy_inputs': encode(self.target.legacy_inputs),
            'target_meta': _receipt(self.target.meta),
            'scope_policy': 'ALL_CALL_ATTEMPTS_V1', 'budget': self.budget,
            'counts': {'rows': self.rows, 'attempts': self.attempts},
            'stopped': self.stopped, 'errors': self.errors, 'io_failed': self.io_failed,
            'file': {'path': str(self.path), 'bytes': self.bytes,
                     'sha256': digest, 'rows': self.rows}}
        with self.meta.open('x', encoding='utf-8') as stream:
            json.dump(document, stream, ensure_ascii=True, indent=2, allow_nan=False)
            stream.write('\n')
