"""One unmodified LeWM run with the frozen process-scope collector."""
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'collector-source'
LEWM = Path('/home/zyf/AAA/le-wm')


def write(name, value):
    (ROOT / name).write_text(json.dumps(value, indent=2) + '\n')


def check_sources():
    original = json.loads((ROOT / 'COLLECTOR_SOURCE.json').read_text())
    for row in original['files']:
        raw = (SOURCE / row['path']).read_bytes()
        if len(raw) != row['bytes'] or sha256(raw).hexdigest() != row['sha256']:
            raise ValueError('frozen collector source changed: ' + row['path'])
    return original['source_tree_sha256']


def main():
    stamp = check_sources()
    environment = {k: v for k, v in os.environ.items() if not k.startswith('SCAR_')}
    environment.update(
        PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(SOURCE),
        SCAR_COLLECTOR_EXECUTION_WITNESS='1', SCAR_PROCESS_IMAGE_RECEIPTS='1',
        SCAR_NATIVE_TENSOR_INPUTS='1', SCAR_RESOURCE_TOPOLOGY='1',
        LEWM_CHECKPOINT_ROOT='/gpu4-share/data/byx/lewm_data',
        LEWM_DATA_ROOT='/gpu4-share/nfs/gpu4-share/lewm_data',
        LEWM_OUTPUT_ROOT=str(ROOT / 'lewm-output'), LEWM_RUN_NAME='process-ports-20261027',
    )
    command = [
        '/usr/bin/time', '-v', '-o', str(ROOT / 'time.txt'),
        '/usr/bin/timeout', '--signal=INT', '--kill-after=60s', '4500s',
        sys.executable, '-B', '-m', 'scar.cli', 'trace',
        '--capture-profile', 'process-ports',
        '--out', str(ROOT / 'capture' / 'trace'), '--project-root', str(LEWM),
        '--max-call-events', '4000000', '--max-call-bytes', '2400000000',
        '--max-call-codes', '65536',
        '--max-operand-events', '4000000', '--max-operand-bytes', '2400000000',
        '--max-source-files', '4096', '--max-source-file-bytes', '4000000',
        '--max-source-bytes', '256000000',
        '--execution-evidence', '--tensor-physical',
        '--os-capture-root', str(ROOT / 'capture'),
        '--max-os-bytes', '2000000000', '--max-os-lines', '8000000',
        '--max-capture-bytes', '10000000000', '--max-archive-bytes', '6000000000',
        '--max-archive-files', '8192', '--os-timeout', '3600', '--',
        sys.executable, 'run_inference.py', '--config-name=pusht',
        'policy=pusht/weights.pt', 'eval.num_eval=1', 'eval.eval_budget=25',
        'eval.goal_offset_steps=25', 'cache_dir=/gpu4-share/data/byx/lewm_data',
        'hydra.job.chdir=False',
    ]
    write('INPUTS.json', {
        'command': command, 'cwd': str(LEWM), 'collector_source_tree_sha256': stamp,
        'environment': {k: environment[k] for k in environment if k.startswith(('SCAR_', 'LEWM_'))},
        'scope': 'one original pusht configuration; process-ports V2 instrumented modeling run',
        'limits_are_ceilings_not_completeness': True,
        'baseline_or_speedup_measurement': False,
    })
    started = time.monotonic()
    with (ROOT / 'stdout.txt').open('wb') as output, (ROOT / 'stderr.txt').open('wb') as error:
        process = subprocess.Popen(command, cwd=LEWM, env=environment, stdout=output, stderr=error)
        write('RUN_STATUS.json', {'status': 'RUNNING', 'wrapper_pid': process.pid,
                                  'collector_source_tree_sha256': stamp})
        print(json.dumps({'status': 'RUNNING', 'wrapper_pid': process.pid, 'root': str(ROOT)}), flush=True)
        code = process.wait()
    after = {'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=LEWM, text=True).strip(),
             'status': subprocess.check_output(['git', 'status', '--porcelain'], cwd=LEWM, text=True)}
    write('LEWM_AFTER.json', after)
    result = {'status': 'EXITED', 'exit_code': code, 'elapsed_seconds': time.monotonic() - started,
              'wrapper_pid': process.pid, 'collector_source_tree_sha256': check_sources(),
              'lewm_unchanged': after == json.loads((ROOT / 'LEWM_BEFORE.json').read_text()),
              'whole_program_model_complete': False}
    write('ACTUAL_TERMINAL.json', result)
    write('RUN_STATUS.json', result)
    print(json.dumps(result), flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
