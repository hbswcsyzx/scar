"""Preserve small canonical fixture smoke attempts, not a full test gate."""
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path.cwd()
OUT = Path(__file__).resolve().parent
SOURCES = ('tests/fixtures/execution_call_graphs.py', 'scar/ir/execution/call_validation.py',
           'scar/ir/execution/validation.py', 'scar/ir/execution/flow.py',
           'scar/ir/execution/calls.py', 'scar/ir/execution/model.py', 'scar/ir/execution/codec.py')


def child():
    from scar.ir.program.validation import validate as core_validate
    from scar.ir.execution.validation import validate
    from scar.ir.execution.codec import dumps, loads
    from tests.fixtures.execution_call_graphs import shared_calls_execution, invoke_call_execution
    cases = [('shared', shared_calls_execution())]
    cases.extend((f'invoke.raise={raised}.transfer={transfer}',
                  invoke_call_execution(raised=raised, caller_transfer=transfer))
                 for raised in (False, True) for transfer in (True, False))
    for name, (program, model, _details) in cases:
        core, execution = core_validate(program), validate(model, program)
        print(json.dumps({'case':name,
            'core_issues':[(row.code, row.message) for row in core],
            'execution_issues':[(row.code, row.message) for row in execution.issues],
            'gaps':len(execution.gaps), 'links':len(model.call_activations),
            'activations':len(model.activations)}), flush=True)
        assert not core and execution.valid
        assert loads(dumps(model)) == model


def main():
    attempt = next(OUT / f'attempt{number:03d}' for number in range(1, 1000)
                   if not (OUT / f'attempt{number:03d}').exists())
    attempt.mkdir()
    def snapshot():
        return {name:sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCES}
    (attempt / 'source.before.json').write_text(json.dumps(snapshot(), indent=2) + '\n')
    command = [sys.executable, str(Path(__file__).resolve()), '--child']
    (attempt / 'command.json').write_text(json.dumps({'cwd':str(ROOT), 'command':command,
        'python':sys.version, 'environment':{'PYTHONPATH':str(ROOT),'PYTHONDONTWRITEBYTECODE':'1'},
        'activation':'source /home/zyf/miniconda3/etc/profile.d/conda.sh; conda activate lewm'}, indent=2) + '\n')
    started = time.perf_counter()
    result = subprocess.run(command, cwd=ROOT, env=dict(os.environ,
        PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE='1'), capture_output=True, text=True)
    (attempt / 'stdout.log').write_text(result.stdout)
    (attempt / 'stderr.log').write_text(result.stderr)
    (attempt / 'source.after.json').write_text(json.dumps(snapshot(), indent=2) + '\n')
    (attempt / 'report.json').write_text(json.dumps({'returncode':result.returncode,
        'duration_seconds':time.perf_counter()-started}, indent=2) + '\n')
    print(str(attempt))
    print(result.stdout)
    print(result.stderr)
    return result.returncode


if __name__ == '__main__':
    if sys.argv[1:] == ['--child']:
        child()
    else:
        raise SystemExit(main())
