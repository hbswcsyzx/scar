"""One retained focused command; no workload or global regression execution."""
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
PARENT = HERE / 'attempts' / 'codec'
PARENT.mkdir(parents=True, exist_ok=True)
out = next(PARENT / f'attempt{n:03d}' for n in range(1,1000)
           if not (PARENT / f'attempt{n:03d}').exists())
out.mkdir()
fingerprint = runpy.run_path(str(ROOT / 'scripts/run_gate.py'))['fingerprint']
(out/'source.before.json').write_text(json.dumps(fingerprint()[1],indent=2)+'\n')
owned = Path(tempfile.mkdtemp(prefix='scar-protocol-codec-focus-'))
command = [sys.executable, '-m', 'pytest', '-q', 'tests/unit/test_program_protocol_codec.py',
    '--junitxml=' + str(out/'junit.xml'), '--basetemp=' + str(owned), '-p', 'no:cacheprovider']
(out/'command.json').write_text(json.dumps({'command':command,'cwd':str(ROOT),
    'python':sys.version,'activation':'source /home/zyf/miniconda3/etc/profile.d/conda.sh; conda activate lewm',
    'environment':{'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(ROOT)},
    'scope':'Only owned new codec test; development peers may edit disjoint files.'},indent=2)+'\n')
start=time.perf_counter()
result=subprocess.run(command,cwd=ROOT,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(ROOT)),
    capture_output=True,text=True)
(out/'stdout.log').write_text(result.stdout)
(out/'stderr.log').write_text(result.stderr)
(out/'source.after.json').write_text(json.dumps(fingerprint()[1],indent=2)+'\n')
shutil.rmtree(owned)
report={'returncode':result.returncode,'duration_seconds':time.perf_counter()-start,
    'directory':str(out),'owned_basetemp_removed_after_child_exit':str(owned)}
(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
print(result.stdout[-16000:])
print(result.stderr[-2000:])
raise SystemExit(result.returncode)
