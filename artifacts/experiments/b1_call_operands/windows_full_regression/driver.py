"""Run one frozen B1 windows full regression, retaining independent test evidence."""
from __future__ import annotations

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
import subprocess
import sys
import tempfile
import time
import traceback
import xml.etree.ElementTree as ET


ROOT = Path('/tmp/scar-call-windows-qx_qw6dk')
OUT = Path(__file__).resolve().parent
EXPECTED_REVISION = '8a300eb068d992b3737eee0bdf43fa2bf8c8aea1'
EXPECTED_SOURCE = '38dfe6c34545b405fa5e8f08e2828f7357c862527500a6a1f2b3d97072796574'


def write(name, document):
    (OUT / name).write_text(json.dumps(document, indent=2, ensure_ascii=False) + '\n')


def git(*arguments):
    return subprocess.check_output(['git', *arguments], cwd=ROOT, text=True).strip()


def fingerprint():
    # Execute the frozen gate helper's exact algorithm without its CLI main.
    return runpy.run_path(str(ROOT / 'scripts/run_gate.py'))['fingerprint']()


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def main():
    if (OUT / 'before.json').exists():
        raise RuntimeError('Evidence already exists; this driver must not repeat the run')
    revision, status = git('rev-parse', 'HEAD'), git('status', '--porcelain=v1')
    source, files = fingerprint()
    if revision != EXPECTED_REVISION or source != EXPECTED_SOURCE or status:
        raise RuntimeError('Frozen revision/source/clean-worktree precondition failed')
    basetemp = Path(tempfile.mkdtemp(prefix='scar-b1-windows-full-8a300eb-'))
    command = [sys.executable, '-m', 'pytest', '-q', 'tests',
               f'--junitxml={OUT / "results.xml"}', f'--basetemp={basetemp}',
               '-o', f'cache_dir={basetemp / ".pytest_cache"}']
    timed_command = ['/usr/bin/time', '-v', '-o', str(OUT / 'time.txt'), *command]
    environment = {
        'python_executable': sys.executable, 'python_version': sys.version,
        'platform': platform.platform(), 'pytest_version': importlib.metadata.version('pytest'),
        'torch_version': importlib.metadata.version('torch'),
        'numpy_version': importlib.metadata.version('numpy'),
        'CONDA_DEFAULT_ENV': os.environ.get('CONDA_DEFAULT_ENV'),
        'CONDA_PREFIX': os.environ.get('CONDA_PREFIX'),
        'PYTHONPATH': os.environ.get('PYTHONPATH'),
        'PYTHONDONTWRITEBYTECODE': os.environ.get('PYTHONDONTWRITEBYTECODE'),
    }
    before = {
        'schema': 'scar.b1-windows-full-regression', 'schema_version': 1,
        'revision': revision, 'worktree_status': status, 'source_sha256': source,
        'tested_files': files, 'cwd': str(ROOT), 'command': command,
        'timed_command': timed_command, 'environment': environment,
        'basetemp': str(basetemp), 'driver_pid': os.getpid(), 'started_at': utc(),
        'measurement_note': 'Concurrent root LeWM and generic GPU tasks may compete for resources; elapsed time is not a benchmark.',
    }
    write('before.json', before)
    (OUT / 'command.json').write_text(json.dumps({'cwd': str(ROOT), 'command': timed_command,
        'activation': 'source /home/zyf/miniconda3/etc/profile.d/conda.sh; conda activate lewm',
        'environment': {'PYTHONPATH': '.', 'PYTHONDONTWRITEBYTECODE': '1'}}, indent=2) + '\n')
    started = time.perf_counter()
    returncode, error = None, None
    try:
        with (OUT / 'stdout.log').open('wb') as stdout, (OUT / 'stderr.log').open('wb') as stderr:
            process = subprocess.Popen(timed_command, cwd=ROOT, stdout=stdout, stderr=stderr)
            write('process.json', {'driver_pid': os.getpid(), 'time_pid': process.pid,
                                   'basetemp': str(basetemp), 'started_at': before['started_at']})
            returncode = process.wait()
    except BaseException:
        error = traceback.format_exc()
    duration = time.perf_counter() - started
    source_after, files_after = fingerprint()
    cases = []
    if (OUT / 'results.xml').exists():
        for case in ET.parse(OUT / 'results.xml').iter('testcase'):
            failure = case.find('failure')
            failure = case.find('error') if failure is None else failure
            skipped = case.find('skipped')
            outcome = 'failed' if failure is not None else 'skipped' if skipped is not None else 'passed'
            cases.append({'class': case.get('classname', ''), 'name': case.get('name', ''),
                          'outcome': outcome, 'seconds': case.get('time'),
                          'detail': None if failure is None and skipped is None else
                                    (failure if failure is not None else skipped).attrib})
    counts = {name: sum(case['outcome'] == name for case in cases) for name in ('passed', 'failed', 'skipped')}
    counts['total'] = len(cases)
    timing = (OUT / 'time.txt').read_text() if (OUT / 'time.txt').exists() else ''
    rss = re.search(r'Maximum resident set size \(kbytes\):\s*(\d+)', timing)
    cleanup = None
    try:
        # Ownership is the exact mkdtemp returned to this run, never a global
        # pytest root or another worker's temporary directory.
        shutil.rmtree(basetemp)
        cleanup = 'removed exclusively owned basetemp'
    except OSError as exc:
        cleanup = repr(exc)
    report = {
        **before, 'finished_at': utc(), 'returncode': returncode,
        'duration_seconds': duration, 'max_rss_kib': int(rss[1]) if rss else None,
        'source_sha256_after': source_after,
        'source_unchanged_during_test': source == source_after and files == files_after,
        'revision_after': git('rev-parse', 'HEAD'), 'worktree_status_after': git('status', '--porcelain=v1'),
        'counts': counts, 'nonpassing_cases': [case for case in cases if case['outcome'] != 'passed'],
        'driver_error': error, 'basetemp_cleanup': cleanup,
        'junit': str(OUT / 'results.xml'), 'stdout': str(OUT / 'stdout.log'),
        'stderr': str(OUT / 'stderr.log'), 'time_log': str(OUT / 'time.txt'),
    }
    report['status'] = 'PASS' if returncode == 0 and not error and counts['total'] and not counts['failed'] and report['source_unchanged_during_test'] else 'FAIL'
    write('report.json', report)
    (OUT / 'report.md').write_text(
        '# B1 windows frozen full regression\n\n'
        f"Status: **{report['status']}**\n\nRevision: `{revision}`\n\n"
        f"Source before/after: `{source}` / `{source_after}`\n\n"
        f"Cases: {counts}; return code: {returncode}.\n\n"
        f"Wall time: {duration:.3f} seconds; peak RSS: {report['max_rss_kib']} KiB.\n\n"
        + before['measurement_note'] + '\n\n'
        + f'JUnit: `{OUT / "results.xml"}`\n\nCleanup: {cleanup}.\n')
    print(json.dumps({name: report[name] for name in ('status', 'returncode', 'counts',
        'duration_seconds', 'max_rss_kib', 'source_unchanged_during_test')}), flush=True)
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
