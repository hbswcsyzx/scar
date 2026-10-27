"""Serial immutable attempts; snapshot every actual override before running."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from scripts.run_gate import fingerprint


HERE = Path(__file__).resolve().parent
folder = HERE / sys.argv[1]
folder.mkdir(exist_ok=False)
selectors = sys.argv[2:]
if selectors == ['--selection']:
    selectors = json.loads((HERE / 'focused-selection.json').read_text())['selectors']
baseline = json.loads((HERE.parent / 'model_async_session_ownership/verified-final/sources.after.json').read_text())
before, sources = fingerprint()
snapshots = {}
for source, digest in sources.items():
    if baseline.get(source) == digest:
        continue
    destination = folder / 'source-bytes' / (source.replace('/', '__') + '.txt')
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = Path(source).read_bytes()
    assert hashlib.sha256(data).hexdigest() == digest
    destination.write_bytes(data)
    snapshots[source] = {'path': str(destination.relative_to(HERE)), 'sha256': digest}
(folder / 'source-bytes.json').write_text(json.dumps(snapshots, indent=2) + '\n')
command = [sys.executable, '-m', 'pytest', '-q', *selectors,
           '--junitxml=' + str(folder / 'junit.xml')]
(folder / 'command.json').write_text(json.dumps({'command': command, 'cwd': str(Path.cwd()),
    'python': sys.version, 'base_revision': '51a6eb3354eb05f7c02c9ff189239166f2cd4081',
    'activation': 'source /home/zyf/miniconda3/etc/profile.d/conda.sh; conda activate lewm',
    'environment': {key: os.environ.get(key) for key in ('PYTHONPATH', 'PYTHONDONTWRITEBYTECODE')},
    'scope': 'affected focused only; not full component/native/automatic source recovery',
    'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}, indent=2) + '\n')
(folder / 'sources.before.json').write_text(json.dumps(sources, indent=2) + '\n')
start = time.monotonic()
with (folder / 'stdout.log').open('w') as out, (folder / 'stderr.log').open('w') as err:
    process = subprocess.run(command, stdout=out, stderr=err)
after, final = fingerprint()
record = {'returncode': process.returncode, 'duration_seconds': time.monotonic() - start,
    'source_sha256_before': before, 'source_sha256_after': after,
    'source_unchanged': before == after, 'source_count': len(sources)}
(folder / 'sources.after.json').write_text(json.dumps(final, indent=2) + '\n')
(folder / 'result.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record))
print((folder / 'stdout.log').read_text()[-22000:])
raise SystemExit(process.returncode)
