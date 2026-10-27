"""Spawned, bounded query workers over closed original call-model shards.

The parent reads publication metadata only. Children independently use normal
shard/model/body readers; no live owner, ProgramIndex or mutable graph crosses
a process boundary. Outputs are derived query views, not another model graph.
"""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import asdict
import gzip
from hashlib import sha256
import importlib
import json
import multiprocessing
import os
from pathlib import Path
import resource
import time
import traceback

from scar.analysis.source_return_bindings import SourceReturnBudget


def _need(value, detail):
    if not value:
        raise ValueError('source dependency workers: ' + detail)


def _integer(value, maximum, label):
    _need(type(value) is int and 1 <= value <= maximum, 'invalid independent ' + label)


def _canonical(document):
    return json.dumps(document, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False).encode('utf8') + b'\n'


def _write_document(path, document, maximum=1_000_000):
    payload = _canonical(document)
    _need(len(payload) <= maximum, 'metadata output ceiling exceeded')
    with path.open('xb') as stream:
        stream.write(payload)
    return {'uri': str(path), 'stored_sha256': sha256(payload).hexdigest(), 'stored_bytes': len(payload)}


def _implementation():
    modules = ('scar.analysis.source_dependency_workers', 'scar.analysis.source_dependency_batch',
               'scar.analysis.source_dependencies', 'scar.analysis.source_return_bindings',
               'scar.analysis.retained_source_call_publication')
    result = []
    for name in modules:
        path = Path(importlib.import_module(name).__file__).resolve()
        payload = path.read_bytes()
        result.append({'module': name, 'uri': str(path), 'sha256': sha256(payload).hexdigest(),
                       'bytes': len(payload)})
    return result


def _check_implementation(receipts):
    for receipt in receipts:
        path = Path(receipt['uri'])
        _need(not path.is_symlink() and path.is_file(), 'participant source became unavailable')
        payload = path.read_bytes()
        _need(len(payload) == receipt['bytes'] and sha256(payload).hexdigest() == receipt['sha256'],
              'participant source changed during query construction')


class _StoredWriter:
    def __init__(self, stream, limit):
        self.stream, self.limit, self.count, self.digest = stream, limit, 0, sha256()

    def write(self, value):
        _need(self.count + len(value) <= self.limit, 'worker compressed view byte ceiling exceeded')
        count = self.stream.write(value)
        _need(count == len(value), 'short compressed view write')
        self.count += count
        self.digest.update(value)
        return count

    def tell(self):
        return self.count

    def flush(self):
        self.stream.flush()


def _write_view(directory, document, decoded_limit, stored_limit):
    partial, final = directory / 'view.partial.json.gz', directory / 'view.json.gz'
    decoded, digest = 0, sha256()
    with partial.open('xb') as raw:
        stored = _StoredWriter(raw, stored_limit)
        with gzip.GzipFile(filename='', fileobj=stored, mode='wb', mtime=0) as compressed:
            encoder = json.JSONEncoder(sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
            for token in encoder.iterencode(document):
                payload = token.encode('utf8')
                decoded += len(payload)
                _need(decoded <= decoded_limit, 'worker decoded view byte ceiling exceeded')
                digest.update(payload)
                compressed.write(payload)
    partial.rename(final)
    return {'uri': str(final), 'stored_sha256': stored.digest.hexdigest(), 'stored_bytes': stored.count,
            'decoded_sha256': digest.hexdigest(), 'decoded_bytes': decoded, 'representation': 'gzip-json-mtime0-v1'}


def _run_shard(task):
    """A spawn-safe top-level entry receiving paths, receipts and ceilings only."""
    from scar.analysis.retained_source_call_publication import (
        read_retained_source_call_publication, read_retained_source_call_shard)
    from scar.analysis.source_dependency_batch import SourceDependencyBatchSession
    start = time.monotonic()
    directory = Path(task['directory'])
    directory.mkdir()
    started = {'shard_index': task['shard_index'], 'worker_pid': os.getpid(),
               'parent_pid': os.getppid(), 'start_method': multiprocessing.get_start_method(),
               'manifest_path': task['manifest_path'], 'manifest_sha256': task['manifest_sha256']}
    _write_document(directory / 'started.json', started)
    record = dict(started)
    try:
        _check_implementation(task['implementation'])
        index = read_retained_source_call_publication(task['manifest_path'],
                    expected_manifest_sha256=task['manifest_sha256'], max_bytes=task['max_manifest_bytes'])
        shard = read_retained_source_call_shard(index, task['shard_index'],
                    max_stored_bytes=task['return_budget']['max_model_stored_bytes'],
                    max_decoded_bytes=task['return_budget']['max_model_decoded_bytes'])
        budget = SourceReturnBudget(**task['return_budget'])
        session = SourceDependencyBatchSession(shard.path, expected_sha256=shard.stored_sha256, budget=budget)
        # Both ordinary readers must refer to exactly the same closed model.
        _need(session._model.to_dict() == shard.model.to_dict(), 'normal shard/query model differs')
        view = session.query_bindings(**task['query_limits'])
        view['publication_scope'] = {'manifest_path': index.manifest_path,
            'manifest_sha256': index.manifest_sha256, 'shard_index': shard.shard_index,
            'candidate_scope': shard.candidate_scope, 'namespace_refs': list(shard.namespace_refs),
            'cross_shard_scope': index.manifest.get('cross_shard_scope'),
            'cross_shard_paths_selected': False}
        output = _write_view(directory, view, task['max_view_decoded_bytes'], task['max_view_stored_bytes'])
        _check_implementation(task['implementation'])
        read_retained_source_call_publication(task['manifest_path'],
            expected_manifest_sha256=task['manifest_sha256'], max_bytes=task['max_manifest_bytes'])
        session._check()
        record.update(status='QUERIED_WITH_OPEN', output=output, candidate_scope=shard.candidate_scope,
            namespace_refs=list(shard.namespace_refs), query_count=len(view['queries']),
            query_truncated=view['truncated'], body_query_costs=view['costs'],
            normal_metadata_reads={'manifest_reads': 2, 'manifest_bytes_per_read': Path(index.manifest_path).stat().st_size,
                'shard_reader_stored_bytes': Path(shard.path).stat().st_size,
                'shard_reader_decoded_bytes': index.shard_refs[shard.shard_index].decoded_bytes},
            cross_shard_paths_selected=False, runtime_occurrence_selected=False,
            reference_identity_established=False, whole_program_complete=False)
    except BaseException as error:
        record.update(status='FAILED_PARTIAL_RETAINED', failure={'type': type(error).__name__,
            'detail': str(error), 'traceback': traceback.format_exc()})
    record.update(wall_seconds=time.monotonic() - start,
                  process_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  output_before_terminal_bytes=sum(p.stat().st_size for p in directory.iterdir() if p.is_file()))
    terminal = _write_document(directory / 'result.json', record)
    record['terminal'] = terminal
    record['output_stored_bytes'] = sum(p.stat().st_size for p in directory.iterdir() if p.is_file())
    return record


def build_source_dependency_workers(publication_path, output_dir, *, expected_manifest_sha256=None,
        max_workers=4, max_inflight=None, return_budget=SourceReturnBudget(max_bodies=64),
        max_bindings=64, max_queries=512, max_nodes=128, max_depth=32, max_routes=512,
        max_shards=4096, max_manifest_bytes=32_000_000, max_view_decoded_bytes=64_000_000,
        max_view_stored_bytes=64_000_000, max_total_output_bytes=1_000_000_000,
        max_index_bytes=16_000_000, progress=None):
    """Read closed metadata, then independently query every published model shard.

    Failed/missing shard results are retained, never automatically retried. A
    fully queried publication still has its original candidate/coverage debt;
    this operation proves no runtime branch, identity, content or ready state.
    """
    from scar.analysis.retained_source_call_publication import read_retained_source_call_publication
    _integer(max_workers, 8, 'worker count')
    max_inflight = 2 * max_workers if max_inflight is None else max_inflight
    _integer(max_inflight, 2 * max_workers, 'inflight count')
    for value, ceiling, name in ((max_bindings, 1024, 'bindings'), (max_queries, 4096, 'queries'),
        (max_nodes, 100_000, 'nodes'), (max_depth, 1024, 'depth'), (max_routes, 100_000, 'routes'),
        (max_shards, 100_000, 'shards'), (max_manifest_bytes, 128_000_000, 'manifest bytes'),
        (max_view_decoded_bytes, 1_000_000_000, 'decoded view bytes'),
        (max_view_stored_bytes, 1_000_000_000, 'stored view bytes'),
        (max_total_output_bytes, 1_000_000_000_000, 'total output bytes'),
        (max_index_bytes, 128_000_000, 'index bytes')):
        _integer(value, ceiling, name)
    _need(type(return_budget) is SourceReturnBudget, 'typed independent body reader budget required')
    return_budget.__post_init__()
    _need(progress is None or callable(progress), 'progress must be a metadata callback')
    index = read_retained_source_call_publication(publication_path,
        expected_manifest_sha256=expected_manifest_sha256, max_bytes=max_manifest_bytes)
    _need(index.publication_closed and len(index.shard_refs) <= max_shards, 'closed publication/shard ceiling required')
    root = Path(output_dir).absolute()
    _need(root == root.resolve() and not root.exists() and not root.is_symlink(), 'fresh canonical output directory required')
    root.mkdir(parents=True)
    (root / 'shards').mkdir()
    implementation = _implementation()
    parent_pid, start = os.getpid(), time.monotonic()
    # Each inflight worker gets a disjoint reservation. The metadata reserve
    # includes its terminal and the final index, not an unbounded success log.
    per_shard_reserve = max_view_stored_bytes + 1_100_000
    _need(max_total_output_bytes > max_index_bytes + per_shard_reserve, 'output budget cannot reserve one shard')
    query_limits = dict(max_bindings=max_bindings, max_queries=max_queries, max_nodes=max_nodes,
                        max_depth=max_depth, max_routes=max_routes)
    _write_document(root / 'started.json', {'manifest_path': index.manifest_path,
        'manifest_sha256': index.manifest_sha256, 'parent_pid': parent_pid, 'max_workers': max_workers,
        'max_inflight': max_inflight, 'start_method': 'spawn', 'shards': len(index.shard_refs),
        'query_limits': query_limits, 'return_budget': asdict(return_budget), 'implementation': implementation})
    results, pending, cursor, pool_failure = {}, {}, 0, None
    completed_output, reserved_index = (root / 'started.json').stat().st_size, max_index_bytes
    def emit(value):
        if progress is not None:
            progress(value)
    with ProcessPoolExecutor(max_workers=max_workers, mp_context=multiprocessing.get_context('spawn')) as executor:
        while cursor < len(index.shard_refs) or pending:
            while pool_failure is None and cursor < len(index.shard_refs) and len(pending) < max_inflight:
                if completed_output + reserved_index + (len(pending) + 1) * per_shard_reserve > max_total_output_bytes:
                    break
                ref = index.shard_refs[cursor]
                task = {'manifest_path': index.manifest_path, 'manifest_sha256': index.manifest_sha256,
                    'shard_index': ref.shard_index, 'directory': str(root / 'shards' / f'{ref.shard_index:06d}'),
                    'return_budget': asdict(return_budget), 'query_limits': query_limits,
                    'max_manifest_bytes': max_manifest_bytes, 'max_view_decoded_bytes': max_view_decoded_bytes,
                    'max_view_stored_bytes': max_view_stored_bytes, 'implementation': implementation}
                try:
                    future = executor.submit(_run_shard, task)
                except BaseException as error:
                    pool_failure = {'type': type(error).__name__, 'detail': str(error)}
                    break
                pending[future] = ref.shard_index
                cursor += 1
            if not pending:
                break
            done, _ = wait(pending, timeout=20, return_when=FIRST_COMPLETED)
            if not done:
                emit({'phase': 'WORKERS_ACTIVE', 'inflight_shards': sorted(pending.values()),
                      'finished_shards': len(results), 'parent_pid': parent_pid})
            for future in done:
                ordinal = pending.pop(future)
                try:
                    record = future.result()
                    _need(record['worker_pid'] != parent_pid and record['start_method'] == 'spawn', 'query did not run in an independent spawned process')
                except BaseException as error:
                    directory = root / 'shards' / f'{ordinal:06d}'
                    directory.mkdir(exist_ok=True)
                    record = {'shard_index': ordinal, 'status': 'FAILED_PARTIAL_RETAINED',
                              'failure': {'type': type(error).__name__, 'detail': str(error)}}
                    record['terminal'] = _write_document(directory / 'parent-failure.json', record)
                    record['output_stored_bytes'] = sum(p.stat().st_size for p in directory.iterdir() if p.is_file())
                results[ordinal] = record
                completed_output += record['output_stored_bytes']
                emit({'phase': 'SHARD_TERMINAL', 'shard_index': ordinal, 'status': record['status'],
                      'worker_pid': record.get('worker_pid'), 'finished_shards': len(results)})
    for ref in index.shard_refs[cursor:]:
        results[ref.shard_index] = {'shard_index': ref.shard_index,
            'status': 'NOT_ATTEMPTED_PROCESS_POOL_FAILURE' if pool_failure else 'NOT_ATTEMPTED_OUTPUT_BUDGET',
            'candidate_scope': ref.candidate_scope, 'failure': pool_failure}
    _check_implementation(implementation)
    read_retained_source_call_publication(index.manifest_path,
        expected_manifest_sha256=index.manifest_sha256, max_bytes=max_manifest_bytes)
    ordered = [results[ref.shard_index] for ref in index.shard_refs]
    report = {'schema': 'scar.source-dependency-worker-publication', 'schema_version': 1,
        'status': ('NO_MODEL_SHARDS_WITH_OPEN' if not ordered else
                   'QUERIED_WITH_OPEN' if all(r['status'] == 'QUERIED_WITH_OPEN' for r in ordered) else 'PARTIAL_WITH_OPEN'),
        'manifest_path': index.manifest_path, 'manifest_sha256': index.manifest_sha256,
        'expected_manifest_sha256_supplied': expected_manifest_sha256 is not None,
        'parent_pid': parent_pid, 'worker_pids': sorted({r['worker_pid'] for r in ordered if 'worker_pid' in r}),
        'max_workers': max_workers, 'max_inflight': max_inflight, 'start_method': 'spawn',
        'capture_denominators': index.manifest.get('capture_denominators'),
        'candidate_funnel': index.manifest.get('candidate_funnel'), 'candidate_scope': index.manifest.get('candidate_scope'),
        'publication_totals': index.manifest.get('totals'), 'windows': index.manifest.get('windows'),
        'cross_shard_scope': index.manifest.get('cross_shard_scope'), 'candidate_coverage_complete': index.candidate_coverage_complete,
        'shards': ordered, 'wall_seconds': time.monotonic() - start,
        'parent_peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'parent_graphs_loaded': 0, 'implementation': implementation,
        'query_limits': query_limits, 'return_budget': asdict(return_budget),
        'output_stored_bytes_before_index': completed_output, 'max_total_output_bytes': max_total_output_bytes,
        'max_view_decoded_bytes': max_view_decoded_bytes, 'max_view_stored_bytes': max_view_stored_bytes,
        'cross_shard_paths_selected': False, 'runtime_occurrence_selected': False,
        'producer_inputs_replayed': False, 'whole_program_complete': False,
        'reference_identity_established': False, 'content_or_ready_established': False,
        'transformation_authorized': False}
    report['index'] = _write_document(root / 'index.json', report, max_index_bytes)
    return report
