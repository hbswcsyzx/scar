"""Capture only the new Created/Running unit file; never component/full."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from scripts.run_gate import fingerprint

here = Path(__file__).resolve().parent
attempt = here / sys.argv[1]
attempt.mkdir(parents=True, exist_ok=False)
command = [sys.executable, '-m', 'pytest', '-q',
           'tests/unit/test_program_generator_reentry.py',
           '--junitxml=' + str(attempt / 'junit.xml')]
before, source_before = fingerprint()
(attempt / 'command.json').write_text(json.dumps({
    'command': command, 'cwd': str(Path.cwd()), 'python': sys.version,
    'activation': 'source /home/zyf/miniconda3/etc/profile.d/conda.sh; conda activate lewm',
    'PYTHONPATH': os.environ.get('PYTHONPATH'),
    'PYTHONDONTWRITEBYTECODE': os.environ.get('PYTHONDONTWRITEBYTECODE'),
    'scope': 'single owned file, shared development, not a frozen component',
}, indent=2) + '\n')
(attempt / 'sources.before.json').write_text(json.dumps(source_before, indent=2) + '\n')
started = time.monotonic()
result = subprocess.run(command, capture_output=True, text=True)
after, source_after = fingerprint()
(attempt / 'stdout.log').write_text(result.stdout)
(attempt / 'stderr.log').write_text(result.stderr)
(attempt / 'sources.after.json').write_text(json.dumps(source_after, indent=2) + '\n')
report = {'returncode': result.returncode, 'duration_seconds': time.monotonic() - started,
          'before': before, 'after': after, 'source_unchanged': before == after,
          'changed_paths': [path for path in set(source_before) | set(source_after)
                            if source_before.get(path) != source_after.get(path)]}
(attempt / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(result.stdout)
print(result.stderr)
print(json.dumps(report))
raise SystemExit(result.returncode)
