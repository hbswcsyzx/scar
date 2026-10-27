"""Optional raw snapshot transport for existing owned JSONL collectors.

No JSON encoding occurs in append. Materialization runs in a separate process
after collection stops, before the existing reader metadata is published.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import weakref


def snapshot_transport_enabled():
    mode = os.environ.get('SCAR_CAPTURE_TRANSPORT', 'jsonl')
    if mode not in ('jsonl', 'snapshot'):
        raise ValueError('SCAR_CAPTURE_TRANSPORT must be jsonl or snapshot')
    return mode == 'snapshot'


class DeferredJsonl:
    """An internal collector-owned plain snapshot stream, never application values."""

    def __init__(self, path, *, max_bytes, max_line_bytes=2_000_000):
        from scar.trace.snapshot_journal import SnapshotJournal
        self.path = Path(path)
        # The existing recorder created this empty placeholder with O_EXCL.
        info = self.path.stat(follow_symlinks=False)
        if not self.path.is_file() or info.st_size:
            raise ValueError('snapshot conversion needs the owned empty JSONL placeholder')
        self._placeholder = (info.st_dev, info.st_ino)
        self.pid = os.getpid()
        self.max_bytes, self.max_line_bytes = max_bytes, max_line_bytes
        self.raw_path = Path(str(self.path) + '.snapshot')
        self.receipt_path = Path(str(self.path) + '.snapshot-receipt.json')
        self.result = None
        self._close_receipt = None
        self.journal = SnapshotJournal(self.raw_path,
            max_queue_bytes=int(os.environ.get('SCAR_SNAPSHOT_BUFFER_BYTES', 8 * 1024 * 1024)),
            max_record_bytes=max_line_bytes, max_total_bytes=max_bytes)
        if hasattr(os, 'register_at_fork'):
            reference = weakref.ref(self)
            def after_fork():
                writer = reference()
                if writer is not None and os.getpid() != writer.pid:
                    writer.journal.close()  # child branch takes no inherited lock
            os.register_at_fork(after_in_child=after_fork)

    @property
    def accepted_bytes(self):
        return self.journal.accepted_bytes

    def append(self, row):
        if os.getpid() != self.pid:
            return False
        return self.journal.append(row)

    def close_capture(self):
        """Always drain/stop the writer, including failed sibling streams."""
        if self._close_receipt is None:
            self._close_receipt = self.journal.close()
            if os.getpid() == self.pid:
                with Path(str(self.raw_path) + '-close.json').open('x') as stream:
                    json.dump(self._close_receipt, stream, ensure_ascii=True,
                              separators=(',', ':'), allow_nan=False)
                    stream.write('\n')
        return self._close_receipt

    def finalize(self):
        if os.getpid() != self.pid:
            raise OSError('a child cannot materialize its parent snapshot journal')
        if self.result is not None:
            return self.result
        source = self.close_capture()
        if source.get('complete') is not True or source.get('source') is None:
            raise OSError('snapshot capture incomplete; raw journal retained without legacy evidence')
        info = self.path.stat(follow_symlinks=False)
        if (info.st_dev, info.st_ino) != self._placeholder or info.st_size:
            raise OSError('owned JSONL placeholder changed during capture')
        self.path.unlink()
        environment = os.environ.copy()
        # Do not inject collectors into the offline decoder process.
        for key in tuple(environment):
            if key.startswith('SCAR_'):
                environment.pop(key)
        command = [sys.executable, '-B', '-m', 'scar.analysis.snapshot_materialization',
                   '--journal', str(self.raw_path), '--out', str(self.path),
                   '--sha256', source['source']['sha256'],
                   '--receipt', str(self.receipt_path), '--max-output-bytes', str(self.max_bytes),
                   '--max-line-bytes', str(self.max_line_bytes)]
        completed = subprocess.run(command, env=environment, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False)
        if completed.returncode:
            raise OSError('offline snapshot materialization failed; raw journal and receipt retained')
        result = json.loads(self.receipt_path.read_bytes())
        output = result['output']
        if result.get('complete') is not True or output.get('published') is not True:
            raise OSError('incomplete snapshot cannot publish reader evidence')
        if output['lines'] != self.journal.accepted_records:
            raise OSError('materialized row count differs from accepted snapshot count')
        if output['raw_bytes'] > self.max_bytes:
            raise OSError('materialized JSONL exceeds the original JSON byte quota')
        result['capture_close'] = source
        self.result = result
        return result
