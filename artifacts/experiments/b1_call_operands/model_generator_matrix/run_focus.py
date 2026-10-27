"""Record bounded focused tests during shared development; never a full gate."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from scripts.run_gate import fingerprint

root = Path.cwd()
here = Path(__file__).resolve().parent
out = here / sys.argv[1]
selectors = sys.argv[2:]
assert selectors and all(item.startswith('tests/unit/test_program_') for item in selectors)
assert out.is_relative_to(here) and not out.exists()
out.mkdir(parents=True)
command = [sys.executable, '-m', 'pytest', '-q', *selectors,
           '--junitxml=' + str(out / 'junit.xml')]
before_digest, before = fingerprint()
(out / 'command.json').write_text(json.dumps({
    'command': command, 'cwd': str(root), 'python': sys.version,
    'activation': 'source /home/zyf/miniconda3/etc/profile.d/conda.sh; conda activate lewm',
    'environment': {key: os.environ.get(key) for key in ('PYTHONPATH', 'PYTHONDONTWRITEBYTECODE')},
    'scope': 'Focused test attempt during shared development; not a component or full acceptance',
}, indent=2) + '\n')
(out / 'sources.before.json').write_text(json.dumps(before, indent=2) + '\n')
started = time.monotonic()
result = subprocess.run(command, cwd=root, capture_output=True, text=True)
elapsed = time.monotonic() - started
after_digest, after = fingerprint()
(out / 'stdout.log').write_text(result.stdout)
(out / 'stderr.log').write_text(result.stderr)
(out / 'sources.after.json').write_text(json.dumps(after, indent=2) + '\n')
report = {'returncode': result.returncode, 'duration_seconds': elapsed,
          'source_sha256_before': before_digest, 'source_sha256_after': after_digest,
          'source_unchanged': before_digest == after_digest,
          'changed_paths': sorted(key for key in before.keys() | after.keys()
                                  if before.get(key) != after.get(key))}
(out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(result.stdout)
print(result.stderr)
print(json.dumps(report))
raise SystemExit(result.returncode)
