"""Bounded parallel reads of existing, sealed source production plans.

Tasks carry only store coordinates and the expected root receipt. Every task
uses the original strict reader; no target module is imported or executed and
no source operation, graph node, or port is created by this adapter.
"""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from contextlib import contextmanager
from hashlib import sha256
import importlib.abc
import multiprocessing
import os
from pathlib import Path
import re
import sys
from threading import RLock
import time

from scar.ir.program import source_productions as P
from scar.ir.program.source_template_links import SourceTemplateKey


class _NoTorch(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'torch' or fullname.startswith('torch.'):
            raise ImportError('torch import is forbidden in static template workers')
        return None


def _check_no_torch():
    if any(name == 'torch' or name.startswith('torch.') for name in sys.modules):
        raise RuntimeError('static template reader process has imported torch')


@contextmanager
def _torch_guard():
    _check_no_torch()
    finder = _NoTorch()
    sys.meta_path.insert(0, finder)
    try:
        yield
        _check_no_torch()
    finally:
        if finder in sys.meta_path:
            sys.meta_path.remove(finder)


def _initialize_worker():
    _check_no_torch()
    sys.meta_path.insert(0, _NoTorch())


def _check_root(root, expected):
    if sha256((Path(root) / 'result.json').read_bytes()).hexdigest() != expected:
        raise ValueError('sealed template root differs from the expected receipt')


def _read_batch(root, unit_id, keys, expected_root_sha256):
    """Spawn-safe task over trusted tool code and original source coordinates."""
    started, cpu = time.monotonic(), time.process_time()
    with _torch_guard():
        _check_root(root, expected_root_sha256)
        from scar.analysis.source_template_batch import read_template_bodies
        plans = read_template_bodies(root, unit_id, keys)
        _check_root(root, expected_root_sha256)
        if set(plans) != set(keys) or any(type(plan) is not P.SourceProductionPlan
                or plan.source != P.ProductionOccurrence(key.occurrence)
                or plan.purpose is not key.purpose for key,plan in plans.items()):
            raise ValueError('strict template reader returned another source plan')
    return plans, os.getpid(), time.monotonic() - started, time.process_time() - cpu


def _default_jobs():
    try:
        count = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        count = getattr(os, 'process_cpu_count', os.cpu_count)() or 1
    return min(48, max(1, count))


class TemplatePlanPool:
    """Reusable spawn pool with an explicit, waiting close operation.

    One-key batches run in the caller. A multi-key batch has at most
    ``min(jobs, key_count)`` submitted tasks; spawn starts workers lazily, so
    small batches do not eagerly create the configured maximum process count.
    ``stats`` reports completed-task worker time, including strict validation.
    """
    def __init__(self, jobs=None):
        jobs = _default_jobs() if jobs is None else jobs
        if type(jobs) is not int or jobs < 1:
            raise ValueError('template jobs must be a positive exact integer')
        self.jobs = jobs
        self._executor = None
        self._closed = False
        self._lock = RLock()
        self._worker_pids = set()
        self._counts = dict(read_many_calls=0, tasks=0, completed_tasks=0, failed_tasks=0,
                            cancelled_tasks=0, serial_tasks=0, parallel_tasks=0,
                            failed_batches=0, peak_inflight=0,worker_batches=0,completed_worker_batches=0)
        self._wall_seconds = self._worker_seconds = self._worker_cpu_seconds = self._close_seconds = 0.0

    @property
    def stats(self):
        with self._lock:
            return dict(self._counts, jobs=self.jobs, plans_per_batch=8,parent_pid=os.getpid(),
                        worker_pids=sorted(self._worker_pids), start_method='spawn',
                        wall_seconds=self._wall_seconds, worker_seconds=self._worker_seconds,
                        worker_cpu_seconds=self._worker_cpu_seconds, close_seconds=self._close_seconds,
                        pool_created=self._executor is not None, closed=self._closed)

    def _accept(self, result, *, parallel):
        plans, pid, seconds, cpu_seconds = result
        if type(plans) is not dict or any(type(plan) is not P.SourceProductionPlan for plan in plans.values()):
            raise ValueError('template worker did not return a typed source plan')
        self._counts['completed_tasks'] += len(plans)
        self._counts['completed_worker_batches'] += 1
        self._worker_seconds += seconds
        self._worker_cpu_seconds += cpu_seconds
        if parallel:
            if pid == os.getpid():
                raise RuntimeError('parallel template task ran in the caller process')
            self._worker_pids.add(pid)
        return plans

    def read_many(self, root, unit_id, keys, expected_root_sha256):
        with self._lock:
            if self._closed:
                raise RuntimeError('template plan pool is closed')
            if type(unit_id) is not str or not unit_id:
                raise ValueError('template reader requires an original unit ID')
            if (type(expected_root_sha256) is not str
                    or re.fullmatch(r'[0-9a-f]{64}', expected_root_sha256) is None):
                raise ValueError('template root SHA must be lowercase SHA256')
            keys = tuple(keys)
            if any(type(key) is not SourceTemplateKey for key in keys):
                raise TypeError('template reader requires original SourceTemplateKey records')
            keys = tuple(dict.fromkeys(keys))
            root = str(Path(root).absolute())
            started = time.monotonic()
            self._counts['read_many_calls'] += 1
            try:
                _check_no_torch()
                _check_root(root, expected_root_sha256)
                if not keys:
                    result = {}
                elif len(keys) == 1 or self.jobs == 1:
                    result = {}
                    self._counts['tasks'] += len(keys)
                    self._counts['serial_tasks'] += len(keys)
                    self._counts['worker_batches'] += 1
                    try:
                        result = self._accept(_read_batch(root, unit_id, keys, expected_root_sha256), parallel=False)
                    except BaseException:
                        self._counts['failed_tasks'] += len(keys)
                        raise
                else:
                    result = self._read_parallel(root, unit_id, keys, expected_root_sha256)
                _check_root(root, expected_root_sha256)
                _check_no_torch()
                return {key: result[key] for key in keys}
            except BaseException:
                self._counts['failed_batches'] += 1
                raise
            finally:
                self._wall_seconds += time.monotonic() - started

    def _read_parallel(self, root, unit_id, keys, expected):
        if self._executor is None:
            self._executor = ProcessPoolExecutor(max_workers=self.jobs,
                mp_context=multiprocessing.get_context('spawn'), initializer=_initialize_worker)
        remaining = iter(tuple(keys[i:i+8]) for i in range(0,len(keys),8))
        pending, results = {}, {}
        window = min(self.jobs, (len(keys)+7)//8)

        def submit():
            batch = next(remaining, None)
            if batch is None:
                return
            future = self._executor.submit(_read_batch, root, unit_id, batch, expected)
            pending[future] = batch
            self._counts['tasks'] += len(batch)
            self._counts['parallel_tasks'] += len(batch)
            self._counts['worker_batches'] += 1
            self._counts['peak_inflight'] = max(self._counts['peak_inflight'], len(pending))

        try:
            for _ in range(window):
                submit()
            while pending:
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    batch = pending.pop(future)
                    try:
                        received = self._accept(future.result(), parallel=True)
                        if set(received)!=set(batch):raise ValueError('template batch selection differs')
                        results.update(received)
                    except BaseException:
                        self._counts['failed_tasks'] += len(batch)
                        raise
                    submit()
        except BaseException:
            # Drain running tasks before propagating the first failure. No
            # partial dictionary escapes and no old batch remains in flight.
            for future in pending:
                future.cancel()
            for future in pending:
                if future.cancelled():
                    self._counts['cancelled_tasks'] += len(pending[future])
                    continue
                try:
                    self._accept(future.result(), parallel=True)
                except BaseException:
                    self._counts['failed_tasks'] += len(pending[future])
            raise
        return results

    def close(self):
        with self._lock:
            if self._closed:
                return
            started = time.monotonic()
            self._closed = True
            try:
                if self._executor is not None:
                    self._executor.shutdown(wait=True, cancel_futures=True)
            finally:
                self._close_seconds += time.monotonic() - started

    def __enter__(self):
        if self._closed:
            raise RuntimeError('template plan pool is closed')
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()


__all__ = ['TemplatePlanPool']
