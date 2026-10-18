"""Capture every bounded owned-file pytest attempt; no component/full execution."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from scripts.run_gate import fingerprint

root = Path.cwd()
here = Path(__file__).resolve().parent
attempt = here / sys.argv[1]
attempt.mkdir(parents=True, exist_ok=False)
selectors = sys.argv[2:]
assert selectors and all(selector in (
    'tests/unit/test_program_admission_records.py',
    'tests/unit/test_program_admission_codec.py',
) for selector in selectors)
command = [sys.executable, '-m', 'pytest', '-q', *selectors,
           '--junitxml=' + str(attempt / 'junit.xml')]
before, before_files = fingerprint()
(attempt / 'command.json').write_text(json.dumps({
    'command': command, 'cwd': str(root), 'python': sys.version,
    'activation': 'source /home/zyf/miniconda3/etc/profile.d/conda.sh; conda activate lewm',
    'environment': {'PYTHONPATH': os.environ.get('PYTHONPATH'),
                    'PYTHONDONTWRITEBYTECODE': os.environ.get('PYTHONDONTWRITEBYTECODE')},
    'scope': 'Owned constructor/codec tests only; active shared development, not final frozen gate',
}, indent=2) + '\n')
(attempt / 'sources.before.json').write_text(json.dumps(before_files, indent=2) + '\n')
started = time.monotonic()
result = subprocess.run(command, cwd=root, capture_output=True, text=True)
elapsed = time.monotonic() - started
after, after_files = fingerprint()
(attempt / 'stdout.log').write_text(result.stdout)
(attempt / 'stderr.log').write_text(result.stderr)
(attempt / 'sources.after.json').write_text(json.dumps(after_files, indent=2) + '\n')
report = {'returncode': result.returncode, 'duration_seconds': round(elapsed, 3),
          'registered_sources_before': before, 'registered_sources_after': after,
          'source_unchanged': before == after,
          'changed_paths': [path for path in set(before_files) | set(after_files)
                            if before_files.get(path) != after_files.get(path)]}
(attempt / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(result.stdout)
print(result.stderr)
print(json.dumps(report))
raise SystemExit(result.returncode)
