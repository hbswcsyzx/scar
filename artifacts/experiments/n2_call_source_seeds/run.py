"""Measure public compact seed generation/replay on retained raw call records."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import time


def sha(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def files(paths):
    return {str(path): {'bytes': path.stat().st_size, 'sha256': sha(path)}
            for path in sorted(paths) if path.is_file()}


def git_state(project):
    return {name: subprocess.check_output(['git', *arguments], cwd=project, text=True).strip()
            for name, arguments in [('head', ['rev-parse', 'HEAD']), ('status', ['status', '--porcelain'])]}


def main():
    parser = argparse.ArgumentParser()
    for name in ('scar-root', 'project-root', 'trace', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    args.scar_root = args.scar_root.resolve()
    args.project_root = args.project_root.resolve()
    args.trace = args.trace.resolve()
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=False)
    fingerprint = runpy.run_path(str(args.scar_root / 'scripts/run_gate.py'))['fingerprint']
    source_before = fingerprint()
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=args.scar_root, text=True).strip()
    raw_before = files(path for path in args.trace.iterdir() if path.name.startswith('call-'))
    target_before = git_state(args.project_root)
    tracked = subprocess.check_output(['git', 'ls-files', '-z', '--', '*.py'], cwd=args.project_root).decode().split('\0')
    target_files_before = files(args.project_root / name for name in tracked if name)
    environment = dict(os.environ, PYTHONPATH=str(args.scar_root), PYTHONDONTWRITEBYTECODE='1')
    for name in ('SCAR_TRACE_DIR', 'SCAR_TRACE_CALL_EDGES', 'SCAR_CALL_TRACE_OWNER_PID'):
        environment.pop(name, None)
    options = ['--max-call-trace-bytes', '256000000', '--max-call-trace-events', '250000',
               '--max-call-references', '2000000', '--max-call-report-bytes', '8000000']
    report = args.out / 'seeds.json.gz'
    phases = []
    for label, arguments in [('generate', ['seed-calls', str(args.trace), '--project-root', str(args.project_root), '--out', str(report)]),
                             ('replay', ['check-call-seeds', str(report)])]:
        command = [sys.executable, '-m', 'scar.cli', *arguments, *options]
        timing = args.out / (label + '.time')
        started = time.perf_counter()
        process = subprocess.run(['/usr/bin/time', '-v', '-o', str(timing), *command],
                                 cwd=args.scar_root, env=environment, capture_output=True, text=True)
        elapsed = time.perf_counter() - started
        (args.out / (label + '.stdout.json')).write_text(process.stdout)
        (args.out / (label + '.stderr.log')).write_text(process.stderr)
        match = re.search(r'Maximum resident set size \(kbytes\): (\d+)', timing.read_text())
        phases.append({'phase': label, 'command': command, 'returncode': process.returncode,
                       'wall_s': elapsed, 'peak_rss_kib': int(match[1]) if match else None})
        if process.returncode:
            break
    raw_after = files(path for path in args.trace.iterdir() if path.name.startswith('call-'))
    target_after = git_state(args.project_root)
    target_files_after = files(args.project_root / name for name in tracked if name)
    source_after = fingerprint()
    result = {'schema': 'scar.call-source-seed-experiment', 'schema_version': 1,
              'revision': revision, 'source_fingerprint': source_before[0], 'source_sha256': source_before[1],
              'phases': phases, 'trace_files_before': raw_before,
              'raw_inputs_unchanged': raw_before == raw_after,
              'target_before': target_before, 'target_after': target_after,
              'target_source_files_before': target_files_before,
              'target_sources_unchanged': target_files_before == target_files_after,
              'scar_sources_unchanged': source_before == source_after,
              'target_executed': False, 'whole_program_complete': False,
              'inventory_seed_scheduling_implemented': False,
              'actual_formal_provenance_established': False, 'transformation_authorized': False,
              'measurement_scope': 'Offline compact source seed generation/replay; not LeWM execution or speedup.'}
    passed = len(phases) == 2 and all(p['returncode'] == 0 for p in phases)
    if passed:
        with gzip.open(report, 'rt') as stream:
            document = json.load(stream)
        model = document['model']
        eligible_codes = {link['code'] for link in model['code_links']
                          if link['status'] == 'VERIFIED' and link['definition'] is not None
                          and link['source'] is not None and link['snapshot'] is not None}
        result.update(summary=document['summary'],
                      code_source_statuses=dict(Counter(link['status'] for link in model['code_links'])),
                      unique_eligible_definitions=len({json.dumps(link['definition'], sort_keys=True)
                                                       for link in model['code_links'] if link['code'] in eligible_codes}),
                      report_compressed_bytes=report.stat().st_size,
                      report_raw_bytes=len(json.dumps(document, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode()) + 1,
                      report_compressed_sha256=sha(report))
    result['status'] = 'REPLAYED' if (passed and raw_before == raw_after and target_before == target_after
                                      and target_files_before == target_files_after and source_before == source_after) else 'FAIL'
    (args.out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('source_sha256', 'trace_files_before', 'target_source_files_before')}))
    return 0 if result['status'] == 'REPLAYED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
