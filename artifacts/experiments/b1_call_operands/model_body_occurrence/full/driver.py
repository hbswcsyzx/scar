"""Run one frozen full regression and retain its independent evidence."""
from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import runpy
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import traceback
import xml.etree.ElementTree as ET


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def dump(path, document):
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + '\n')


def git(root, *arguments):
    return subprocess.check_output(['git', *arguments], cwd=root, text=True).strip()


def snapshot(root):
    digest, files = runpy.run_path(str(root / 'scripts/run_gate.py'))['fingerprint']()
    return {'revision': git(root, 'rev-parse', 'HEAD'),
            'worktree_status': git(root, 'status', '--porcelain=v1'),
            'source_sha256': digest, 'source_file_count': len(files), 'files': files,
            'fixture_sha256': {
                str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted((root / 'tests/fixtures').rglob('*'))
                if path.is_file() and '__pycache__' not in path.parts}}


def concurrent_processes(root):
    # Only this driver's own PID is inspected; no server-wide process args scan.
    del root
    result = subprocess.run(['ps', '-p', str(os.getpid()), '-o',
                             'pid,ppid,etimes,time,pcpu,rss,comm'],
                            capture_output=True, text=True, check=True)
    return result.stdout


def test_environment(root):
    # Give pytest this complete explicit environment, avoiding unrelated service
    # credentials in both the child and the saved exact-environment evidence.
    names = ('HOME', 'USER', 'LOGNAME', 'SHELL', 'PATH', 'CONDA_DEFAULT_ENV',
             'CONDA_PREFIX', 'CONDA_SHLVL', 'CONDA_PYTHON_EXE', 'LD_LIBRARY_PATH',
             'CUDA_VISIBLE_DEVICES', 'CUDA_HOME', 'CUDA_PATH', 'OMP_NUM_THREADS',
             'XDG_CACHE_HOME', 'HF_HOME', 'TORCH_HOME', 'TMPDIR')
    environment = {name: os.environ[name] for name in names if name in os.environ}
    environment.update({'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8', 'TZ': 'UTC',
                        'PYTHONPATH': str(root), 'PYTHONDONTWRITEBYTECODE': '1',
                        'PYTHONUNBUFFERED': '1'})
    return environment


def cases_from(path):
    if not path.exists():
        return []
    cases = []
    for case in ET.parse(path).iter('testcase'):
        failure, error, skipped = (case.find(name) for name in ('failure', 'error', 'skipped'))
        node = failure if failure is not None else error if error is not None else skipped
        outcome = ('failed' if failure is not None else 'error' if error is not None
                   else 'skipped' if skipped is not None else 'passed')
        cases.append({'class': case.get('classname', ''), 'name': case.get('name', ''),
                      'outcome': outcome, 'seconds': case.get('time'),
                      'detail': None if node is None else {'attributes': node.attrib, 'text': node.text}})
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scar-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--source-files', type=int, required=True)
    args = parser.parse_args()
    root, out = args.scar_root.resolve(), args.out.resolve()
    if out != Path(__file__).resolve().parent:
        raise RuntimeError('The driver and all evidence must share the fresh output directory')
    if any(path.name != 'driver.py' for path in out.iterdir()):
        raise RuntimeError('Output directory contains prior evidence; no repeat run is permitted')
    before = snapshot(root)
    dump(out / 'source.before.json', before)
    if (before['revision'] != args.revision or before['source_sha256'] != args.source_sha
            or before['source_file_count'] != args.source_files or before['worktree_status']):
        dump(out / 'precondition.failure.json', {'expected': vars(args) | {
            'scar_root': str(root), 'out': str(out)}, 'actual': before})
        raise RuntimeError('Frozen HEAD, source hashes, file count or clean status failed')
    basetemp = Path(tempfile.mkdtemp(prefix='scar-structured-full-' + args.revision[:8] + '-'))
    command = [sys.executable, '-m', 'pytest', '-q', 'tests',
               f'--junitxml={out / "results.xml"}', f'--basetemp={basetemp}',
               '-o', f'cache_dir={basetemp / ".pytest_cache"}']
    timed = ['/usr/bin/time', '-v', '-o', str(out / 'time-v.txt'), '--', *command]
    environment = test_environment(root)
    receipt = {'schema': 'scar.frozen-full-regression', 'schema_version': 1,
               'scope': 'One complete pytest tests run; no automatic retry or source changes.',
               'scar_root': str(root), 'cwd': str(root), 'expected_revision': args.revision,
               'expected_source_sha256': args.source_sha, 'expected_source_files': args.source_files,
               'command': command, 'timed_command': timed, 'environment': environment,
               'activation': 'source /home/zyf/miniconda3/etc/profile.d/conda.sh; conda activate lewm',
               'driver_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'python_executable': sys.executable, 'python_version': sys.version,
               'platform': platform.platform(),
               'package_versions': {name: importlib.metadata.version(name)
                                    for name in ('pytest', 'torch', 'numpy')},
               'basetemp': str(basetemp), 'driver_pid': os.getpid(), 'started_at': utc(),
               'measurement_note': 'Component checks and focused reviews completed before this run. '
                 'This driver starts no other SCAR job. External server load is not measured; '
                 'wall time is acceptance cost, not a workload benchmark.'}
    dump(out / 'command.json', receipt)
    dump(out / 'progress.json', {'status': 'RUNNING', 'started_at': receipt['started_at'],
                               'driver_pid': os.getpid(), 'basetemp': str(basetemp)})
    (out / 'concurrency.before.txt').write_text(concurrent_processes(root))
    started, process, returncode, errors = time.perf_counter(), None, None, []
    try:
        with (out / 'stdout.log').open('wb') as stdout, (out / 'stderr.log').open('wb') as stderr:
            process = subprocess.Popen(timed, cwd=root, env=environment, stdout=stdout,
                                       stderr=stderr, start_new_session=True)
            dump(out / 'process.json', {'driver_pid': os.getpid(), 'time_pid': process.pid,
                 'process_group': process.pid, 'basetemp': str(basetemp), 'started_at': receipt['started_at']})
            returncode = process.wait()
    except BaseException:
        errors.append(traceback.format_exc())
    finally:
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                returncode = process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                returncode = process.wait()
    duration = time.perf_counter() - started
    after = snapshot(root)
    dump(out / 'source.after.json', after)
    (out / 'concurrency.after.txt').write_text(concurrent_processes(root))
    try:
        cases = cases_from(out / 'results.xml')
    except BaseException:
        cases = []
        errors.append(traceback.format_exc())
    dump(out / 'cases.json', cases)
    counts = {name: sum(case['outcome'] == name for case in cases)
              for name in ('passed', 'failed', 'error', 'skipped')}
    counts['total'] = len(cases)
    timing = (out / 'time-v.txt').read_text() if (out / 'time-v.txt').exists() else ''
    rss = re.search(r'Maximum resident set size \(kbytes\):\s*(\d+)', timing)
    source_unchanged = before == after
    cleanup = 'not attempted'
    try:
        # No process from this driver remains alive. Only its exact mkdtemp is
        # removed; no shared pytest/cache/temp directory is traversed for cleanup.
        shutil.rmtree(basetemp)
        cleanup = 'removed exclusively owned basetemp after child termination'
    except OSError:
        cleanup = traceback.format_exc()
    passed = (returncode == 0 and not errors and counts['total'] > 0
              and not counts['failed'] and not counts['error'] and source_unchanged)
    report = {**receipt, 'status': 'PASS' if passed else 'FAIL', 'returncode': returncode,
              'finished_at': utc(), 'duration_seconds': duration,
              'max_rss_kib': int(rss[1]) if rss else None, 'counts': counts,
              'source_unchanged_during_test': source_unchanged,
              'source_sha256_before': before['source_sha256'],
              'source_sha256_after': after['source_sha256'],
              'revision_before': before['revision'], 'revision_after': after['revision'],
              'worktree_status_before': before['worktree_status'],
              'worktree_status_after': after['worktree_status'],
              'nonpassing_cases': [case for case in cases if case['outcome'] != 'passed'],
              'driver_errors': errors, 'basetemp_cleanup': cleanup,
              'junit': str(out / 'results.xml'), 'stdout': str(out / 'stdout.log'),
              'stderr': str(out / 'stderr.log'), 'time_v': str(out / 'time-v.txt')}
    dump(out / 'report.json', report)
    dump(out / 'progress.json', {'status': report['status'], 'returncode': returncode,
             'finished_at': report['finished_at'], 'duration_seconds': duration, 'counts': counts})
    (out / 'report.md').write_text('# Frozen structured-model full regression\n\n'
        f"Status: **{report['status']}**; pytest return code: {returncode}.\n\n"
        f"Cases: {counts}.\n\nWall time: {duration:.3f}s; peak RSS: {report['max_rss_kib']} KiB.\n\n"
        f"HEAD before/after: `{before['revision']}` / `{after['revision']}`.\n\n"
        f"Source before/after: `{before['source_sha256']}` / `{after['source_sha256']}`.\n\n"
        f"All {before['source_file_count']} per-file hashes unchanged: {source_unchanged}.\n\n"
        + receipt['measurement_note'] + '\n\n' + f'Owned temporary directory cleanup: {cleanup}.\n')
    files = {str(path.relative_to(out)): {'bytes': path.stat().st_size,
              'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
             for path in sorted(out.rglob('*')) if path.is_file()}
    dump(out / 'manifest.json', {'schema': 'scar.frozen-full-regression-manifest',
                                'schema_version': 1, 'files': files})
    print(json.dumps({name: report[name] for name in ('status', 'returncode', 'counts',
          'duration_seconds', 'max_rss_kib', 'source_unchanged_during_test')}), flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
