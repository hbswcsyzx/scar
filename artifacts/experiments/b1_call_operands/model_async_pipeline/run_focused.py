"""Sequential focused attempts with immutable commands/logs/source registries."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from scripts.run_gate import fingerprint

here = Path(__file__).resolve().parent
folder = here / sys.argv[1]
folder.mkdir(exist_ok=False)
selectors = sys.argv[2:]
if selectors == ['--selection']:
    selectors = json.loads((here / 'focused-selection.json').read_text())['selectors']
before, sources = fingerprint()
command = [sys.executable, '-m', 'pytest', '-q', *selectors,
           '--junitxml=' + str(folder / 'junit.xml')]
(folder / 'command.json').write_text(json.dumps({'command': command, 'cwd': str(Path.cwd()),
    'python': sys.version, 'activation': 'source /home/zyf/miniconda3/etc/profile.d/conda.sh; conda activate lewm',
    'environment': {key: os.environ.get(key) for key in ('PYTHONPATH', 'PYTHONDONTWRITEBYTECODE')},
    'scope': 'affected focused only, not complete component/full'}, indent=2) + '\n')
(folder / 'sources.before.json').write_text(json.dumps(sources, indent=2) + '\n')
started = time.monotonic()
with (folder / 'stdout.log').open('w') as out, (folder / 'stderr.log').open('w') as err:
    result = subprocess.run(command, stdout=out, stderr=err)
after, final_sources = fingerprint()
record = {'returncode': result.returncode, 'duration_seconds': time.monotonic() - started,
          'source_sha256_before': before, 'source_sha256_after': after,
          'source_unchanged': before == after, 'source_count': len(sources)}
(folder / 'sources.after.json').write_text(json.dumps(final_sources, indent=2) + '\n')
(folder / 'result.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record))
print((folder / 'stdout.log').read_text()[-10000:])
raise SystemExit(result.returncode)
