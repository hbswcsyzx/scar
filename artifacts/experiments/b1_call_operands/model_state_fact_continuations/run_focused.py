"""Sequential focused attempts with immutable commands/logs/source registries."""
import json
import hashlib
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
prior = here.parent / 'model_current_async_packet'
baseline_sources = json.loads((prior / 'verified-final/sources.after.json').read_text())
snapshots = {}
for source, digest in sources.items():
    if baseline_sources.get(source) == digest:
        continue
    target = folder / 'source-bytes' / (source.replace('/', '__') + '.txt')
    target.parent.mkdir(parents=True, exist_ok=True)
    data = Path(source).read_bytes()
    assert hashlib.sha256(data).hexdigest() == digest
    target.write_bytes(data)
    snapshots[source] = {'path': str(target.relative_to(here)), 'sha256': digest}
(folder / 'source-bytes.json').write_text(json.dumps(snapshots, indent=2) + '\n')
command = [sys.executable, '-m', 'pytest', '-q', *selectors,
           '--junitxml=' + str(folder / 'junit.xml')]
(folder / 'command.json').write_text(json.dumps({'command': command, 'cwd': str(Path.cwd()),
    'python': sys.version, 'activation': 'source /home/zyf/miniconda3/etc/profile.d/conda.sh; conda activate lewm',
    'environment': {key: os.environ.get(key) for key in ('PYTHONPATH', 'PYTHONDONTWRITEBYTECODE')},
    'scope': 'affected focused only, not complete component/full',
    'base_revision': 'fa7b769e34adf5ef39c27103c11b6cb75f796f7b',
    'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}, indent=2) + '\n')
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
