"""Root-run single navigation gate; default is prepared-only, never execution."""
import argparse
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import threading
import time
import traceback

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]
CAPTURE = ROOT / 'artifacts/experiments/first_stage_lewm_physical_20261023'


def raw(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + '\n').encode()


def read(path, maximum=128_000_000):
    path = Path(path)
    if not path.is_file() or path.is_symlink() or path.resolve() != path or path.stat().st_size > maximum:
        raise ValueError('frozen file path/size differs: ' + str(path))
    return path.read_bytes()


def verify(expected, *, stat_only=False):
    payload = read(BASE / 'freeze.json', 4_000_000)
    if sha256(payload).hexdigest() != expected: raise ValueError('root-approved freeze SHA differs')
    frozen = json.loads(payload); total = 0
    if frozen['fixed_attempt'] != str(BASE / 'attempt01'): raise ValueError('attempt path differs')
    if not stat_only:
        for row in frozen['source_files'] + frozen['runtime_files'] + frozen['metadata_files'] + frozen['runner_files']:
            data = read(row['path']); total += len(data)
            if (len(data), sha256(data).hexdigest()) != (row['bytes'], row['sha256']):
                raise ValueError('frozen current bytes differ: ' + row['path'])
            if 'snapshot' in row:
                data = read(row['snapshot']); total += len(data)
                if (len(data), sha256(data).hexdigest()) != (row['bytes'], row['sha256']):
                    raise ValueError('frozen snapshot differs: ' + row['snapshot'])
    for row in frozen['stream_stats'] + frozen['native_inventory_stats']:
        s = Path(row['path']).stat()
        if (s.st_size, s.st_ino, s.st_dev, s.st_mtime_ns, s.st_ctime_ns) != (
                row['bytes'], row['inode'], row['device'], row['mtime_ns'], row['ctime_ns']):
            raise ValueError('stat-only stream changed: ' + row['path'])
    return frozen, total


def worker(expected):
    started = time.monotonic(); frozen, initial_freeze_bytes = verify(expected)
    attempt = BASE / 'attempt01'
    log = (attempt / 'progress.jsonl').open('x')
    stopped, lock = threading.Event(), threading.Lock()
    state = {'phase': 'IMPORTS', 'navigation_published': False}; opens = Counter(); queries = []
    def event(kind, **values):
        with lock:
            row = {**state, **values, 'event': kind, 'elapsed_s': time.monotonic() - started,
                   'self_peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
            log.write(json.dumps(row, sort_keys=True) + '\n'); log.flush()
            print(json.dumps(row, sort_keys=True), flush=True)
    def heartbeat():
        while not stopped.wait(frozen['heartbeat_seconds']):
            closed = {}
            for family in ('source', 'native', 'index'):
                directory = attempt / 'navigation' / family
                files = list(directory.glob('*.jsonl.gz')) if directory.exists() else []
                closed[family] = {'chunks': len(files), 'stored_bytes': sum(p.stat().st_size for p in files)}
            event('HEARTBEAT', closed_transport=closed, progress_is_not_semantic_coverage=True)
    thread = threading.Thread(target=heartbeat, daemon=True); thread.start()
    def terminated(signum, _frame): raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, terminated); signal.signal(signal.SIGINT, terminated)
    def write(name, value):
        with (attempt / name).open('x') as output: output.write(raw(value).decode())
    try:
        from scar.analysis.source_native_composition import (NativeContextInputs, NavigationBudget, NativeContextQueryBudget,
            NativeContextIndex, NativeContextStatus, build_native_context_navigation)
        from scar.ir.record_codec import decode, encode
        inputs = decode(NativeContextInputs, frozen['inputs'])
        build_budget = decode(NavigationBudget, frozen['build_budget'])
        query_budget = decode(NativeContextQueryBudget, frozen['query_budget'])
        def check_imports():
            allowed = {r['path']: r for r in frozen['source_files']}
            imported = []
            for name, module in tuple(sys.modules.items()):
                if name not in ('scar', 'sitecustomize') and not name.startswith('scar.'): continue
                filename = getattr(module, '__file__', None)
                if filename is None: continue
                p = Path(filename).resolve()
                if p.suffix == '.pyc':
                    from importlib.util import source_from_cache
                    p = Path(source_from_cache(str(p))).resolve()
                if str(p) not in allowed or not p.is_relative_to(ROOT): raise ValueError('import escaped frozen main: ' + name)
                data = read(p)
                if sha256(data).hexdigest() != allowed[str(p)]['sha256']: raise ValueError('import bytes changed: ' + name)
                imported.append(str(p))
            return sorted(set(imported))
        check_imports()
        association = Path(frozen['stream_stats'][0]['path'])
        native_chunks = {r['path'] for r in frozen['native_inventory_stats']}
        forbidden_source = Path(inputs.source_report.uri).parent / 'invocations.jsonl.gz'
        def audit(event_name, args):
            if event_name != 'open' or not isinstance(args[0], (str, bytes, os.PathLike)): return
            try: path = Path(os.fsdecode(args[0])).absolute()
            except (ValueError, TypeError): return
            mode = args[1]
            if isinstance(mode, str) and any(x in mode for x in 'wax+'): return
            if path.is_relative_to(CAPTURE) or path == forbidden_source or path.suffix in ('.sqlite', '.db'):
                raise PermissionError('navigation gate prohibits raw/DB input: ' + str(path))
            if path == association or str(path) in native_chunks:
                if state['phase'] != 'BUILD_NAVIGATION': raise PermissionError('original indexed data reopened outside builder: ' + str(path))
                opens[str(path)] += 1
                if opens[str(path)] > 1: raise PermissionError('original indexed data reopened: ' + str(path))
        sys.addaudithook(audit)
        state['phase'] = 'BUILD_NAVIGATION'; event('STAGE_BEGIN')
        navigation = build_native_context_navigation(inputs, attempt / 'navigation', budgets=build_budget)
        state['navigation_published'] = True
        if opens[str(association)] != 1 or any(opens[p] != 1 for p in native_chunks):
            raise ValueError('original source/native inventory open conservation failed')
        state['phase'] = 'OPEN_PUBLIC_READER'; event('STAGE_BEGIN')
        reader = NativeContextIndex.open(navigation, expected_inputs=inputs, budgets=query_budget)
        for sample in frozen['samples']:
            state.update(phase='QUERY_SAMPLE', sequence=sample['sequence']); event('STAGE_BEGIN', roles=sample['roles'])
            result = reader.native_context(sample['sequence'])
            encoded = encode(result)
            queries.append({'selection': sample, 'result': encoded})
            write('query-' + str(sample['sequence']) + '.json', queries[-1])
            if result.navigation != navigation or result.inputs != inputs: raise ValueError('query lost exact navigation/inputs')
            if result.status is NativeContextStatus.BUDGET_EXHAUSTED: raise ValueError('sample query exhausted its frozen budget')
            if 'UNRESOLVED' in sample['roles']:
                if result.relationship is not None: raise ValueError('unresolved source falsely claims context relationship')
            elif any(role.startswith('RETAINED_') for role in sample['roles']):
                if result.status is not NativeContextStatus.RETAINED_CONTEXT: raise ValueError('saved linked source sample failed context query')
            event('QUERY_COMPLETE', status=result.status.value, relationship=None if result.relationship is None else result.relationship.value,
                  costs=result.costs, frontier_count=len(result.frontiers))
        state['phase'] = 'FINAL_FREEZE_CHECK'; event('STAGE_BEGIN')
        imported = check_imports(); _, final_freeze_bytes = verify(expected)
        m = json.loads(read(navigation.uri, 4_000_000))
        footer = {'status': 'PUBLISHED_RETAINED_CONTEXT_SAMPLES_MODEL_OPEN', 'navigation': encode(navigation),
            'navigation_counts': m['counts'], 'navigation_build_costs': m['costs'], 'sample_queries': len(queries),
            'actual_imported_SCAR_sources': imported, 'freeze_sha256': expected,
            'freeze_verification_bytes': {'initial': initial_freeze_bytes, 'final': final_freeze_bytes},
            'original_source_association_opens': opens[str(association)], 'native_inventory_chunk_opens': {p: opens[p] for p in sorted(native_chunks)},
            'raw_capture_reads': 0, 'sqlite_reads': 0, 'target_executions': 0, 'native_or_source_producer_runs': 0,
            'historical_collector_assumption_retained': True, 'old_scope_obligations_closed': False,
            'object_identity_established': False, 'whole_program_model': 'OPEN', 'queries_are_samples': True,
            'wall_seconds': time.monotonic() - started, 'self_peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
        write('result.json', footer); state['phase'] = 'FINISHED_OPEN'; event('STAGE_END')
        return 0
    except BaseException as error:
        write('failure.json', {'status': 'FAILED_RETAINED', 'exception': type(error).__name__, 'message': str(error),
            'phase': state, 'completed_queries': len(queries), 'opens': dict(opens), 'automatic_retry': False,
            'wall_seconds': time.monotonic() - started, 'self_peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})
        traceback.print_exc(); event('FAILED', exception=type(error).__name__, message=str(error))
        return 1
    finally:
        stopped.set(); thread.join(timeout=1); log.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--freeze-sha256')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        return worker(args.freeze_sha256)
    if not args.execute:
        print(json.dumps({'status': 'PREPARED_NOT_RUN', 'freeze': str(BASE / 'freeze.json'), 'attempt': str(BASE / 'attempt01'),
            'streams_opened': False, 'requires_root_execution': True})); return 0
    frozen, _ = verify(args.freeze_sha256)
    attempt = BASE / 'attempt01'; attempt.mkdir(exist_ok=False)
    (attempt / 'BUILDING.json').write_bytes(raw({'freeze_sha256': args.freeze_sha256, 'status': 'BUILDING'}))
    command = ['/usr/bin/time', '-v', '-o', str(attempt / 'time.txt'), sys.executable, '-B', str(Path(__file__).resolve()),
               '--worker', '--freeze-sha256', args.freeze_sha256]
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE='1')
    started, parent_stop = time.monotonic(), None
    def stop_parent(signum, _frame): raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, stop_parent)
    with (attempt / 'stdout.log').open('x') as stdout, (attempt / 'stderr.log').open('x') as stderr:
        child = subprocess.Popen(command, cwd=ROOT, env=env, stdout=stdout, stderr=stderr, start_new_session=True)
        try: code = child.wait(timeout=frozen['outer_wall_seconds'])
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGTERM)
            try: code = child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL); code = child.wait()
        except (KeyboardInterrupt, SystemExit) as stopped:
            parent_stop = 130 if isinstance(stopped, KeyboardInterrupt) else int(stopped.code)
            os.killpg(child.pid, signal.SIGTERM)
            try: code = child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL); code = child.wait()
    launch = {'status': 'EXIT0_RETAINED_CONTEXT_MODEL_OPEN' if code == 0 and parent_stop is None else 'FAILED_RETAINED', 'exit_code': code,
        'parent_stop_exit': parent_stop,
        'wall_seconds': time.monotonic() - started, 'command': command, 'automatic_retry': False, 'attempt': str(attempt)}
    (attempt / 'launch-result.json').write_bytes(raw(launch)); print(json.dumps(launch, sort_keys=True))
    return parent_stop if parent_stop is not None else 0 if code == 0 else 1


if __name__ == '__main__': raise SystemExit(main())
