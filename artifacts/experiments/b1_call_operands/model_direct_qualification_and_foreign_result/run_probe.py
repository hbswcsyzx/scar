"""Root-only serial diagnostic, retaining immutable command/source evidence."""
import hashlib
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
script = here / sys.argv[2]
before, sources = fingerprint()
command = [sys.executable, str(script)]
(folder / 'command.json').write_text(json.dumps({'command': command,
    'cwd': str(Path.cwd()), 'python': sys.version,
    'activation': 'source /home/zyf/miniconda3/etc/profile.d/conda.sh; conda activate lewm',
    'environment': {key: os.environ.get(key) for key in ('PYTHONPATH', 'PYTHONDONTWRITEBYTECODE')},
    'script_sha256': hashlib.sha256(script.read_bytes()).hexdigest(),
    'scope': 'source diagnosis only, not acceptance or native execution'}, indent=2) + '\n')
(folder / 'sources.before.json').write_text(json.dumps(sources, indent=2) + '\n')
started = time.monotonic()
with (folder / 'stdout.log').open('w') as out, (folder / 'stderr.log').open('w') as err:
    result = subprocess.run(command, stdout=out, stderr=err)
after, final_sources = fingerprint()
(folder / 'sources.after.json').write_text(json.dumps(final_sources, indent=2) + '\n')
record = {'returncode': result.returncode, 'duration_seconds': time.monotonic() - started,
    'source_sha256_before': before, 'source_sha256_after': after,
    'source_unchanged': before == after, 'source_count': len(sources)}
(folder / 'result.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record))
print((folder / 'stdout.log').read_text())
print((folder / 'stderr.log').read_text())
raise SystemExit(result.returncode)
