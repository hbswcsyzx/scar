"""CPython-local temporary bytes journal for collector-owned snapshot rows.

This is an internal transport, not an arbitrary-object serialization API.
Callers must build plain snapshot trees before append; no application object
may be submitted. append performs no recursive Python validation or JSON work.
"""
from __future__ import annotations

from collections import deque
from hashlib import sha256
import json
import marshal
import os
from pathlib import Path
import struct
import sys
import threading

MAGIC = b'SCAR-SNAPSHOT-JOURNAL\x00\x01'
HEADER_LENGTH = struct.Struct('<I')
FRAME = struct.Struct('<cQQ')
RECORD, FOOTER = b'R', b'F'
FORMAT = 'scar.snapshot-journal/1'
HEADER_LIMIT = 65_536
FOOTER_RESERVE = 16_384
_writer_local = threading.local()


def is_journal_writer_thread():
    """Exclude this entire IO-thread stack in collector callbacks."""
    return getattr(_writer_local, 'active', False) is True


def _json(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode('ascii')


def _write_all(fd, payload):
    remaining = memoryview(payload)
    while remaining:
        try:
            count = os.write(fd, remaining)
        except InterruptedError:
            continue
        if count <= 0:
            raise OSError('short snapshot-journal write')
        remaining = remaining[count:]


def _error(error):
    # Never repr/str the snapshot or an arbitrary object from the exception.
    return {'type': type(error).__name__, 'errno': getattr(error, 'errno', None)}


class SnapshotJournal:
    def __init__(self, path, *, max_queue_bytes=8 * 1024 * 1024,
                 max_record_bytes=4 * 1024 * 1024, max_total_bytes=1024 * 1024 * 1024,
                 batch_bytes=64 * 1024, close_timeout=30.0):
        if sys.implementation.name != 'cpython':
            raise ValueError('snapshot journal requires CPython marshal with allow_code=False')
        for value in (max_queue_bytes, max_record_bytes, max_total_bytes, batch_bytes):
            if type(value) is not int or value <= 0:
                raise ValueError('journal byte ceilings must be positive exact integers')
        if type(close_timeout) not in (int, float) or not 0 < close_timeout <= 3600:
            raise ValueError('journal close timeout must be finite and in (0,3600]')
        self.path = Path(path).absolute()
        if self.path != self.path.resolve() or self.path.exists() or self.path.is_symlink():
            raise ValueError('fresh canonical journal path required')
        self._pid = os.getpid()
        self._queue_limit, self._record_limit = max_queue_bytes, max_record_bytes
        self._total_limit, self._batch_limit = max_total_bytes, batch_bytes
        self._close_timeout = close_timeout
        self._condition, self._close_lock = threading.Condition(), threading.Lock()
        self._queue = deque()
        self._queued_bytes = self._queue_highwater = self._inflight_highwater = 0
        self._attempts = self._accepted_records = self._accepted_bytes = self._accepted_frame_bytes = 0
        self._last_record_bytes = self._written_records = self._written_frame_bytes = 0
        self._rejected = {key: 0 for key in ('wrong_root', 'serialization_error', 'record_byte_limit',
            'total_byte_limit', 'queue_full', 'closing_or_closed', 'writer_unavailable')}
        self._fork_rejections = 0
        self._closing = self._closed = self._timed_out = self._child_closed = False
        self._writer_error = None
        self._receipt = None
        self.header = {'format': FORMAT, 'schema_version': 1, 'owner_pid': self._pid,
            'implementation': sys.implementation.name, 'python': sys.version,
            'python_version': list(sys.version_info), 'cache_tag': sys.implementation.cache_tag,
            'marshal_version': marshal.version, 'allow_code': False,
            'snapshot_contract': 'COLLECTOR_OWNED_PLAIN_SNAPSHOT_TREE',
            'ordering': 'append-lock order; not a cross-thread causal assertion',
            'max_queue_bytes': max_queue_bytes, 'max_record_bytes': max_record_bytes,
            'max_total_bytes': max_total_bytes, 'batch_bytes': batch_bytes}
        header = _json(self.header)
        if len(header) > HEADER_LIMIT or len(MAGIC) + HEADER_LENGTH.size + len(header) + FOOTER_RESERVE >= max_total_bytes:
            raise ValueError('journal total byte ceiling cannot reserve header/footer')
        self._header_bytes = len(MAGIC) + HEADER_LENGTH.size + len(header)
        self._fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
        initial = os.fstat(self._fd)
        self._identity = initial.st_dev, initial.st_ino
        try:
            _write_all(self._fd, MAGIC + HEADER_LENGTH.pack(len(header)) + header)
        except BaseException:
            os.close(self._fd); self._fd = None
            raise
        self._thread = threading.Thread(target=self._writer_main,
            name='SCAR-snapshot-journal-io', daemon=True)
        self._thread.start()

    @property
    def accepted_bytes(self):
        """Accepted marshal payload bytes, never a JSON byte-quota claim."""
        return self._accepted_bytes if os.getpid() == self._pid else 0

    @property
    def accepted_records(self):
        return self._accepted_records if os.getpid() == self._pid else 0

    @property
    def last_record_bytes(self):
        return self._last_record_bytes if os.getpid() == self._pid else 0

    @property
    def writer_thread_id(self):
        return self._thread.ident

    @property
    def writer_native_thread_id(self):
        return self._thread.native_id

    def append(self, row):
        """Synchronously freeze a collector-owned snapshot; never wait for space."""
        if os.getpid() != self._pid:
            # Do not acquire an inherited lock: its owner may not survive fork.
            self._fork_rejections += 1
            return False
        with self._condition:
            self._last_record_bytes = 0
            self._attempts += 1
            if self._writer_error is not None:
                self._rejected['writer_unavailable'] += 1
                return False
            if self._closing or self._closed:
                self._rejected['closing_or_closed'] += 1
                return False
            if type(row) is not dict:
                self._rejected['wrong_root'] += 1
                return False
            try:
                payload = marshal.dumps(row, marshal.version, allow_code=False)
            except Exception:
                self._rejected['serialization_error'] += 1
                return False
            size = len(payload)
            if size > self._record_limit:
                self._rejected['record_byte_limit'] += 1
                return False
            framed_size = FRAME.size + size
            if self._header_bytes + self._accepted_frame_bytes + framed_size + FOOTER_RESERVE > self._total_limit:
                self._rejected['total_byte_limit'] += 1
                return False
            if self._queued_bytes + framed_size > self._queue_limit:
                self._rejected['queue_full'] += 1
                return False
            ordinal = self._accepted_records + 1
            frozen = FRAME.pack(RECORD, ordinal, size) + payload
            self._queue.append(frozen)
            self._accepted_records = ordinal
            self._accepted_bytes += size
            self._accepted_frame_bytes += len(frozen)
            self._last_record_bytes = size
            self._queued_bytes += len(frozen)
            self._queue_highwater = max(self._queue_highwater, self._queued_bytes)
            self._condition.notify()
            return True

    def _writer_main(self):
        _writer_local.active = True
        try:
            while True:
                with self._condition:
                    while not self._queue and not self._closing:
                        self._condition.wait()
                    if not self._queue:
                        return
                    batch, size = [], 0
                    while self._queue:
                        frame = self._queue[0]
                        if batch and size + len(frame) > self._batch_limit:
                            break
                        batch.append(self._queue.popleft())
                        size += len(frame)
                        self._queued_bytes -= len(frame)
                    self._inflight_highwater = max(self._inflight_highwater, size)
                try:
                    # IO batching only. No JSON, marshal decoding, graph work,
                    # payload traversal or checksum computation on this thread.
                    _write_all(self._fd, b''.join(batch))
                except BaseException as error:
                    with self._condition:
                        self._writer_error = _error(error)
                        self._closing = True
                        self._queue.clear(); self._queued_bytes = 0
                    return
                with self._condition:
                    self._written_records += len(batch)
                    self._written_frame_bytes += size
        finally:
            _writer_local.active = False

    def _counts(self):
        return {'append_calls': self._attempts, 'accepted_records': self._accepted_records,
            'accepted_bytes': self._accepted_bytes, 'accepted_frame_bytes': self._accepted_frame_bytes,
            'written_records': self._written_records, 'written_frame_bytes': self._written_frame_bytes,
            'rejected': dict(self._rejected), 'queue_highwater_bytes': self._queue_highwater,
            'inflight_highwater_bytes': self._inflight_highwater, 'queued_bytes': self._queued_bytes,
            'writer_error': self._writer_error, 'close_timed_out': self._timed_out}

    def _hash_source(self):
        before = self.path.stat()
        if self.path.is_symlink() or (before.st_dev, before.st_ino) != self._identity or before.st_size > self._total_limit:
            raise ValueError('closed journal path/identity/byte ceiling differs')
        digest, count = sha256(), 0
        with self.path.open('rb') as stream:
            while chunk := stream.read(1024 * 1024):
                count += len(chunk)
                if count > self._total_limit:
                    raise ValueError('closed journal byte ceiling exceeded during hash')
                digest.update(chunk)
        after = self.path.stat()
        if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                or count != before.st_size):
            raise ValueError('closed journal changed during hash')
        return {'uri': str(self.path), 'raw_bytes': count, 'sha256': digest.hexdigest(), 'format': FORMAT,
                'declared_pid': self._pid}

    def close(self):
        if os.getpid() != self._pid:
            if not self._child_closed:
                if self._fd is not None:
                    os.close(self._fd)
                self._fd = None; self._queue.clear(); self._child_closed = True
            return {'status': 'FORK_INVALIDATED_CHILD', 'complete': False, 'owner_pid': self._pid,
                'process_id': os.getpid(), 'fork_rejections': self._fork_rejections,
                'parent_buffer_flushed': False, 'source': None}
        with self._close_lock:
            if self._receipt is not None:
                return dict(self._receipt)
            with self._condition:
                self._closing = True; self._condition.notify()
            self._thread.join(self._close_timeout)
            if self._thread.is_alive():
                self._timed_out = True
                return {'status': 'CLOSE_TIMEOUT', 'complete': False, 'source': None,
                    'counts': self._counts(), 'writer_thread_alive': True,
                    'archive_eligible': False, 'detail': 'IO may still be running; no footer or stable SHA'}
            counts = self._counts()
            complete = (self._writer_error is None and not self._timed_out
                and self._attempts == self._accepted_records == self._written_records)
            footer = {'schema': 'scar.snapshot-journal-footer', 'schema_version': 1,
                      'owner_pid': self._pid, 'complete': complete, 'counts': counts}
            errors, closed_footer = [], False
            try:
                if self._writer_error is None:
                    payload = _json(footer)
                    if len(payload) + FRAME.size > FOOTER_RESERVE:
                        raise ValueError('journal footer reserve exceeded')
                    _write_all(self._fd, FRAME.pack(FOOTER, self._accepted_records + 1, len(payload)) + payload)
                    closed_footer = True
            except BaseException as error:
                complete = False; errors.append(_error(error))
            finally:
                os.close(self._fd); self._fd = None; self._closed = True
            try:
                source = {**self._hash_source(), 'closed_footer': closed_footer}
            except BaseException as error:
                source = None; complete = False; errors.append(_error(error))
            self._receipt = {'status': 'CLOSED' if complete else 'INCOMPLETE', 'complete': complete,
                'source': source, 'counts': counts, 'errors': errors, 'rows_validated': False,
                'json_byte_quota_validated': False, 'writer_thread_alive': False,
                'writer_thread_id': self.writer_thread_id, 'writer_native_thread_id': self.writer_native_thread_id,
                'close_sha_readback_bytes': source['raw_bytes'] if source is not None else 0}
            return dict(self._receipt)
