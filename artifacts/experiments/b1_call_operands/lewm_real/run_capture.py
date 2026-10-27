"""Capture the unchanged external LeWM command with bounded operand evidence."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import time


HERE = Path(__file__).resolve().parent
SCAR = Path('/tmp/scar-call-operands-fe9ytsud')
PROJECT = Path('/home/zyf/AAA/le-wm')
EXPECTED = '33d92b1635ac614ab817388dbeb45cda5fe6f71a6af99b115193e473582d1933'


def save(path, document):
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + '\n')


def state():
    return {name: subprocess.check_output(['git', *args], cwd=PROJECT, text=True).strip()
            for name, args in [('head', ['rev-parse', 'HEAD']),
                               ('status', ['status', '--porcelain=v1'])]}


def source_hashes():
    names = subprocess.check_output(['git', 'ls-files', '-z', '*.py'], cwd=PROJECT).split(b'\0')
    return {os.fsdecode(name): hashlib.sha256((PROJECT / os.fsdecode(name)).read_bytes()).hexdigest()
            for name in names if name}


def main():
    trace = HERE / 'trace'
    if trace.exists():
        raise ValueError('refusing to reuse a capture directory')
    fingerprint = runpy.run_path(str(SCAR / 'scripts/run_gate.py'))['fingerprint']
    before_fp, _ = fingerprint()
    if before_fp != EXPECTED:
        raise ValueError('source fingerprint differs from frozen component')
    before = state()
    if before['status']:
        raise ValueError('target status differs from the clean baseline')
    hashes = source_hashes()
    env = dict(os.environ, PYTHONPATH=str(SCAR), PYTHONDONTWRITEBYTECODE='1',
               LEWM_CHECKPOINT_ROOT='/gpu4-share/data/byx/lewm_data',
               LEWM_OUTPUT_ROOT=str(HERE / 'workload_output'), LEWM_RUN_NAME='b1')
    for name in list(env):
        if name.startswith('SCAR_'):
            env.pop(name)
    command = [sys.executable, '-m', 'scar.cli', 'trace', '--call-operands',
               '--project-root', str(PROJECT), '--out', str(trace),
               '--max-call-events', '250000', '--max-call-bytes', '256000000',
               '--max-operand-events', '2000000', '--max-operand-bytes', '1200000000',
               '--resources', '--resource-interval', '0.5', '--', sys.executable,
               'run_inference.py', '--config-name=pusht', 'policy=pusht/weights.pt',
               'eval.num_eval=1', 'eval.eval_budget=25', 'eval.goal_offset_steps=25',
               'cache_dir=/gpu4-share/data/byx/lewm_data', 'hydra.job.chdir=False']
    invocation = {'schema': 'scar.b1-lewm-capture', 'schema_version': 1,
                  'command': command, 'cwd': str(PROJECT), 'source_sha256_before': before_fp,
                  'scar_revision': subprocess.check_output(['git','rev-parse','HEAD'],cwd=SCAR,text=True).strip(),
                  'target_before': before, 'source_files_before': hashes,
                  'environment': {name: env[name] for name in ('PYTHONPATH','PYTHONDONTWRITEBYTECODE',
                      'LEWM_CHECKPOINT_ROOT','LEWM_OUTPUT_ROOT','LEWM_RUN_NAME')},
                  'measurement_scope': 'instrumented run; concurrent validation; not a clean benchmark'}
    save(HERE / 'invocation.json', invocation)
    started = time.perf_counter()
    with (HERE / 'capture.stdout.log').open('w') as stdout, (HERE / 'capture.stderr.log').open('w') as stderr:
        result = subprocess.run(['/usr/bin/time','-v','-o',str(HERE/'capture.time'),*command],
                                cwd=PROJECT, env=env, stdout=stdout, stderr=stderr)
    elapsed = time.perf_counter() - started
    after_fp, _ = fingerprint()
    after = state()
    report = {'schema': 'scar.b1-lewm-capture-result', 'schema_version': 1,
              'returncode': result.returncode, 'wall_seconds': elapsed,
              'target_after': after, 'target_git_unchanged': before == after,
              'target_tracked_python_unchanged': hashes == source_hashes(),
              'source_sha256_after': after_fp, 'scar_source_unchanged': before_fp == after_fp,
              'files': {path.name: path.stat().st_size for path in sorted(trace.iterdir()) if path.is_file()},
              'whole_program_complete': False, 'transformation_authorized': False}
    save(HERE / 'capture-result.json', report)
    print(json.dumps(report), flush=True)
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
