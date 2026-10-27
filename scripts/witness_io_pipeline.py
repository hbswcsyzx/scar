"""Bounded, exclusively owned OS observations for the declared IO model.

These small programs record actual calls, counts, hashes and outcomes. They do
not recover a SCAR program graph or certify IR/native correspondence. The
parent owns the temporary directory and waits for worker termination before
cleanup; the hard subprocess timeout also bounds executor shutdown.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor


CASES = ('file', 'file_raise', 'pending_raise')


class Journal:
    def __init__(self):
        self.rows = []
        self.lock = threading.Lock()

    def record(self, action, phase, **fields):
        with self.lock:
            self.rows.append({'sequence': len(self.rows), 'time_ns': time.monotonic_ns(),
                'thread': threading.get_ident(), 'action': action, 'phase': phase, **fields})


class HostFailure(Exception):
    pass


class PartialWorkFailure(Exception):
    pass


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _load(path, journal):
    journal.record('load', 'enter', requested_bytes=8)
    with io.FileIO(path, 'r') as source:
        value = source.read(8)
    journal.record('load', 'return', returned_bytes=len(value), sha256=_digest(value))
    return value


def _prepare(value, journal):
    journal.record('prepare', 'enter', input_bytes=len(value))
    result = value.upper()
    journal.record('prepare', 'return', output_bytes=len(result), sha256=_digest(result))
    return result


def _compute(value, journal):
    journal.record('compute', 'enter', input_bytes=len(value))
    result = bytes(item + 1 for item in value)
    journal.record('compute', 'return', output_bytes=len(result), sha256=_digest(result))
    return result


def _save(writer, value, journal):
    journal.record('save', 'enter', requested_bytes=len(value))
    count = writer.write(value)
    journal.record('save', 'return', accepted_bytes=count)
    return count


def _close(writer, journal):
    journal.record('close', 'enter')
    writer.close()
    journal.record('close', 'return', closed=writer.closed)


def file_pipeline(workspace, *, fail_after_save=False):
    """Actual buffering visibility; fsync return is not a power-loss test."""
    workspace = Path(workspace)
    source_path, output_path = workspace / 'input.bin', workspace / 'output.bin'
    with source_path.open('xb') as source:
        source.write(b'abcdefgh')
    journal = Journal()
    raw = io.FileIO(output_path, 'x+')
    writer = io.BufferedWriter(raw, buffer_size=4096)
    observations = {'requested_bytes': 8, 'explicit_flush_returned': False,
                    'fsync_returned': False, 'host_exception': None}
    try:
        value = _compute(_prepare(_load(source_path, journal), journal), journal)
        observations['accepted_bytes'] = _save(writer, value, journal)
        before = os.pread(raw.fileno(), 16, 0)
        observations['visible_before_explicit_flush_bytes'] = len(before)
        journal.record('independent_read', 'return', point='before_flush', returned_bytes=len(before))
        if fail_after_save:
            raise HostFailure('save wrapper raised before explicit flush')
        journal.record('flush', 'enter')
        writer.flush()
        observations['explicit_flush_returned'] = True
        after = os.pread(raw.fileno(), 16, 0)
        observations['visible_after_explicit_flush_bytes'] = len(after)
        journal.record('flush', 'return', visible_bytes=len(after), sha256=_digest(after))
        journal.record('fsync', 'enter')
        os.fsync(raw.fileno())
        observations['fsync_returned'] = True
        journal.record('fsync', 'return')
    except HostFailure as error:
        observations['host_exception'] = type(error).__name__
        journal.record('save_wrapper', 'raise', exception=type(error).__name__)
    finally:
        _close(writer, journal)
    final = output_path.read_bytes()
    observations.update(closed=writer.closed, final_bytes=len(final), final_sha256=_digest(final))
    return {'observed': observations, 'events': journal.rows,
            'limitations': ['close may itself flush buffered data; explicit flush is a separate call',
                'fsync return was observed only in the normal case; power-loss durability was not tested',
                'these events do not automatically bind source ports, resource generations or SCAR IR']}


def pending_pipeline():
    """Host RAISE while work is running, followed by partial write and failure."""
    journal, started, release = Journal(), threading.Event(), threading.Event()
    buffer = bytearray(8)
    borrowed = memoryview(buffer)
    executor = ThreadPoolExecutor(max_workers=1)
    future = None
    observations = {'requested_bytes': 8}

    def work():
        journal.record('work', 'start')
        started.set()
        if not release.wait(timeout=2):
            raise TimeoutError('owned worker release deadline exceeded')
        try:
            borrowed[:4] = b'BCDE'
            journal.record('work', 'partial_write', actual_bytes=4)
            raise PartialWorkFailure('failure after the first four bytes')
        finally:
            borrowed.release()
            journal.record('borrow', 'release')

    try:
        try:
            journal.record('submit_wrapper', 'enter')
            future = executor.submit(work)
            if not started.wait(timeout=2):
                raise TimeoutError('owned worker start deadline exceeded')
            raise HostFailure('submit wrapper raised while work was waiting')
        except HostFailure as error:
            observations.update(host_exception=type(error).__name__,
                                work_done_at_host_raise=future.done(),
                                buffer_nonzero_bytes_at_host_raise=sum(item != 0 for item in buffer))
            journal.record('submit_wrapper', 'raise', exception=type(error).__name__,
                           work_done=future.done())
        finally:
            release.set()
        try:
            future.result(timeout=2)
            raise AssertionError('owned partial worker unexpectedly succeeded')
        except PartialWorkFailure as error:
            observations['work_exception'] = type(error).__name__
            journal.record('work_observer', 'terminal', outcome='FAILED', exception=type(error).__name__)
        observations.update(work_done=future.done(), actual_bytes=sum(item != 0 for item in buffer),
                            final_sha256=_digest(buffer))
        try:
            borrowed[0]
            raise AssertionError('borrowed view was not released')
        except ValueError:
            observations['this_view_released'] = True
    finally:
        release.set()
        # The outer parent timeout bounds even unexpected executor-shutdown hangs.
        executor.shutdown(wait=True)
        borrowed.release()
    return {'observed': observations, 'events': journal.rows,
            'limitations': ['one memoryview release does not prove that no other alias or external reader exists',
                'host exception, worker terminal and view release are different observations',
                'Python threads here do not prove GPU work, native coherence, allocation retirement or IR correspondence']}


def run_case(case, *, timeout=10):
    """Run a fixed tiny program in a killable worker; return no file contents."""
    if case not in CASES:
        raise ValueError('unknown IO witness case')
    if type(timeout) not in (int, float) or not 0 < timeout <= 60:
        raise ValueError('witness timeout must be positive and at most 60 seconds')
    command = None
    with tempfile.TemporaryDirectory(prefix='scar-io-pipeline-') as workspace:
        command = [sys.executable, str(Path(__file__).resolve()), '--worker', case,
                   '--workspace', workspace]
        # subprocess.run kills and waits for this child on timeout. All work is
        # in that process's threads, so no owned worker survives directory cleanup.
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            raise RuntimeError(f'owned witness failed ({result.returncode}): {result.stderr}')
        document = json.loads(result.stdout)
    return {'schema': 'scar.io-pipeline-witness', 'schema_version': 1, 'case': case,
        'python': sys.version, 'worker_python': sys.executable,
        'timeout_seconds': timeout, 'worker_returncode': result.returncode,
        'owned_workspace': workspace, 'owned_workspace_removed_after_worker_exit': not Path(workspace).exists(),
        **document, 'source_runtime_verified': False, 'transformation_authorized': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=CASES)
    parser.add_argument('--worker', choices=CASES, help=argparse.SUPPRESS)
    parser.add_argument('--workspace', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        if args.workspace is None:
            parser.error('a worker requires its exclusively owned workspace')
        document = (pending_pipeline() if args.worker == 'pending_raise' else
                    file_pipeline(args.workspace, fail_after_save=args.worker == 'file_raise'))
    elif args.case:
        document = run_case(args.case)
    else:
        parser.error('--case is required')
    print(json.dumps(document, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
