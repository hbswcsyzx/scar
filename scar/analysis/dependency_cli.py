"""Public entries for bounded source-port and dependency publications."""
from __future__ import annotations

import gzip
from hashlib import sha256
import json
from pathlib import Path


def _bounds(parser):
    for name, default in (('max-bindings', 64), ('max-queries', 512), ('max-nodes', 128),
                          ('max-depth', 32), ('max-routes', 512), ('max-bodies', 64)):
        parser.add_argument('--' + name, type=int, default=default)


def _query_limits(args):
    return {name: getattr(args, name) for name in
            ('max_bindings', 'max_queries', 'max_nodes', 'max_depth', 'max_routes')}


def build_source_port_shards_cli(args):
    from scar.analysis.retained_source_call_ports import RetainedSourceCallPortSession
    from scar.analysis.retained_source_call_publication import publish_retained_source_call_port_shards
    out = Path(args.out).absolute()
    if out.exists() or out.is_symlink():
        raise ValueError('source-port publication requires a fresh directory')
    session = RetainedSourceCallPortSession(
        source_report_path=args.source_report, bindings_path=args.bindings,
        expected_report_sha256=args.source_report_sha256,
        expected_bindings_sha256=args.bindings_sha256, trace_root=args.trace_root, pid=args.pid,
        max_candidate_pairs=None if args.all_candidates else args.max_candidate_pairs,
        max_live_body_decoded_bytes=args.max_live_body_decoded_bytes)
    result = publish_retained_source_call_port_shards(session, out,
        max_selected_calls_per_shard=args.shard_calls,
        max_candidate_pairs_per_shard=args.shard_candidates, max_shards=args.max_shards)
    print(json.dumps({key: result[key] for key in ('manifest_path', 'manifest_sha256', 'manifest_bytes')}
                     | {'totals': result['manifest']['totals']}, indent=2))
    return 0


def query_source_dependency_batch_cli(args):
    from scar.analysis.source_dependency_batch import SourceDependencyBatchSession
    from scar.analysis.source_return_bindings import SourceReturnBudget
    out = Path(args.out).absolute()
    if out.exists() or out.is_symlink():
        raise ValueError('dependency view requires a fresh output file')
    session = SourceDependencyBatchSession(args.model, expected_sha256=args.sha256,
                                          budget=SourceReturnBudget(max_bodies=args.max_bodies))
    result = session.query_bindings(None if args.binding_index is None else tuple(args.binding_index),
                                   **_query_limits(args))
    payload = (json.dumps(result, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode()
    if len(payload) > args.max_output_bytes:
        raise ValueError('dependency view exceeds decoded output ceiling')
    decoded = len(payload)
    if out.suffix == '.gz':
        payload = gzip.compress(payload, compresslevel=6, mtime=0)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('xb') as stream:
        stream.write(payload)
    print(json.dumps({'uri': str(out), 'sha256': sha256(payload).hexdigest(),
                      'stored_bytes': len(payload), 'decoded_bytes': decoded,
                      'queries': len(result['queries']), 'truncated': result['truncated'],
                      'whole_program_complete': False}, indent=2))
    return 0


def build_source_dependencies_cli(args):
    from scar.analysis.source_dependency_workers import build_source_dependency_workers
    from scar.analysis.source_return_bindings import SourceReturnBudget
    result = build_source_dependency_workers(args.publication, args.out,
        expected_manifest_sha256=args.sha256, max_workers=args.workers, max_inflight=args.max_inflight,
        return_budget=SourceReturnBudget(max_bodies=args.max_bodies),
        view_layout=args.view_layout,
        shard_indices=None if args.shard_index is None else tuple(args.shard_index),
        max_total_output_bytes=args.max_output_bytes, **_query_limits(args))
    print(json.dumps({key: result[key] for key in
                     ('status', 'index', 'worker_pids', 'wall_seconds', 'whole_program_complete')}, indent=2))
    return 0 if result['status'] == 'QUERIED_WITH_OPEN' else 1


def register_dependency_commands(sub):
    build = sub.add_parser('build-source-port-shards', help='read original calls once and publish bounded source-port shards')
    for flag in ('source-report', 'source-report-sha256', 'bindings', 'bindings-sha256'):
        build.add_argument('--' + flag, required=True)
    build.add_argument('--trace-root')
    build.add_argument('--pid', type=int)
    scope = build.add_mutually_exclusive_group()
    scope.add_argument('--max-candidate-pairs', type=int, default=512)
    scope.add_argument('--all-candidates', action='store_true')
    build.add_argument('--shard-calls', type=int, default=32)
    build.add_argument('--shard-candidates', type=int, default=64)
    build.add_argument('--max-shards', type=int)
    build.add_argument('--max-live-body-decoded-bytes', type=int, default=64_000_000)
    build.add_argument('--out', required=True)
    build.set_defaults(func=build_source_port_shards_cli)
    query = sub.add_parser('query-source-dependency-batch', help='query inputs, conditional returns and consumers in one retained body session')
    query.add_argument('--model', required=True)
    query.add_argument('--sha256', required=True)
    query.add_argument('--binding-index', action='append', type=int)
    query.add_argument('--max-output-bytes', type=int, default=64_000_000)
    query.add_argument('--out', required=True)
    _bounds(query)
    query.set_defaults(func=query_source_dependency_batch_cli)
    workers = sub.add_parser('build-source-dependencies', help='derive dependency fragments from closed source-port shards in independent processes')
    workers.add_argument('--publication', required=True)
    workers.add_argument('--sha256', required=True)
    workers.add_argument('--workers', type=int, default=4)
    workers.add_argument('--max-inflight', type=int)
    workers.add_argument('--view-layout', choices=('single', 'queries'), default='single',
                         help='store a complete batch or one bounded file per dependency query')
    workers.add_argument('--shard-index', action='append', type=int,
                         help='process only these original shard ordinals; repeat to select more')
    workers.add_argument('--max-output-bytes', type=int, default=1_000_000_000)
    workers.add_argument('--out', required=True)
    _bounds(workers)
    workers.set_defaults(func=build_source_dependencies_cli)
