"""Root-only, serial, immutable focused attempts on a frozen source tree."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from scripts.run_gate import fingerprint

HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / 'model_async_terminal_semantics'
BASE = 'b2f7e1ec58c5726a61753ffbe8d9ca125c89a162'


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


folder = HERE / sys.argv[1]
folder.mkdir(exist_ok=False)
selectors = sys.argv[2:]
if selectors == ['--selection']:
    selectors = json.loads((HERE / 'focused-selection.json').read_text())['selectors']
assert selectors
baseline = json.loads((PRIOR / 'verified-current/sources.after.json').read_text())
before, sources = fingerprint()
snapshots = {}
for source, digest in sources.items():
    if baseline.get(source) == digest:
        continue
    target = folder / 'source-bytes' / (source.replace('/', '__') + '.txt')
    target.parent.mkdir(parents=True, exist_ok=True)
    data = Path(source).read_bytes()
    assert hashlib.sha256(data).hexdigest() == digest
    target.write_bytes(data)
    snapshots[source] = {'path': str(target.relative_to(HERE)), 'sha256': digest}
write(folder / 'source-bytes.json', snapshots)
command = [sys.executable, '-m', 'pytest', '-q', *selectors,
           '--junitxml=' + str(folder / 'junit.xml')]
write(folder / 'command.json', {'command': command, 'cwd': str(Path.cwd()),
    'python': sys.version, 'base_revision': BASE,
    'activation': 'source /home/zyf/miniconda3/etc/profile.d/conda.sh; conda activate lewm',
    'environment': {key: os.environ.get(key) for key in ('PYTHONPATH', 'PYTHONDONTWRITEBYTECODE')},
    'scope': 'affected supplied-model queries; not full phase, native validation or performance',
    'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
write(folder / 'sources.before.json', sources)
start = time.monotonic()
with (folder / 'stdout.log').open('w') as out, (folder / 'stderr.log').open('w') as err:
    process = subprocess.run(command, stdout=out, stderr=err)
after, final = fingerprint()
result = {'returncode': process.returncode, 'duration_seconds': time.monotonic() - start,
    'source_sha256_before': before, 'source_sha256_after': after,
    'source_unchanged': before == after, 'source_count': len(sources)}
write(folder / 'sources.after.json', final)
write(folder / 'result.json', result)
print(json.dumps(result))
print((folder / 'stdout.log').read_text()[-22000:])
assert before == after, 'source changed during this attempt'
raise SystemExit(process.returncode)
