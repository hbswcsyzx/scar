"""Retain each focused attempt; final gate/full uses independent frozen drivers."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path.cwd()
ARCHIVE = Path(__file__).resolve().parent


def snapshot():
    paths = sorted({*ROOT.joinpath('scar/ir/execution').glob('*.py'),
                    *ROOT.joinpath('tests/unit').glob('test_execution*.py'),
                    *ROOT.joinpath('tests/fixtures').glob('execution*')})
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths if path.is_file()}


def main():
    group, *nodes = sys.argv[1:]
    if not nodes or not group.isidentifier():
        raise ValueError('group identifier and test selectors required')
    parent = ARCHIVE / group
    parent.mkdir(exist_ok=True)
    out = next(parent / f'attempt{n:03d}' for n in range(1, 1000) if not (parent / f'attempt{n:03d}').exists())
    out.mkdir()
    before = snapshot()
    (out / 'source.before.json').write_text(json.dumps(before, indent=2) + '\n')
    owned = Path(tempfile.mkdtemp(prefix='scar-v-focus-'))
    command = [sys.executable, '-m', 'pytest', '-q', *nodes, f'--junitxml={out / "junit.xml"}',
               f'--basetemp={owned}', '-p', 'no:cacheprovider']
    (out / 'command.json').write_text(json.dumps({'cwd': str(ROOT), 'command': command,
        'activation': 'source /home/zyf/miniconda3/etc/profile.d/conda.sh; conda activate lewm',
        'python': sys.version, 'environment': {'PYTHONPATH':str(ROOT),'PYTHONDONTWRITEBYTECODE':'1'},
        'note': 'Focused development; peers may edit other owned files. Full gate freezes all source separately.'}, indent=2) + '\n')
    started = time.perf_counter()
    result = subprocess.run(command, cwd=ROOT, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1',
        PYTHONPATH=str(ROOT)), capture_output=True, text=True)
    (out / 'stdout.log').write_text(result.stdout)
    (out / 'stderr.log').write_text(result.stderr)
    (out / 'source.after.json').write_text(json.dumps(snapshot(), indent=2) + '\n')
    shutil.rmtree(owned)
    report = {'returncode':result.returncode,'duration_seconds':time.perf_counter()-started,
              'owned_basetemp_removed_after_child_exit':str(owned), 'directory':str(out)}
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
    print(result.stdout[-9000:])
    print(result.stderr[-1000:])
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
