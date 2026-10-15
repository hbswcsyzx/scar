"""Frozen-source regression receipt, with lossless compressed JUnit output."""
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


def main():
    root = Path.cwd()
    sys.path.insert(0,str(root))
    from scripts.run_gate import fingerprint
    prefix = root/'artifacts/reports/gates/n2-functions-full-regression'
    code_hash = fingerprint()[0]
    git = lambda *args: subprocess.check_output(['git',*args],text=True).strip()
    revision, status = git('rev-parse','HEAD'), git('status','--porcelain')
    xml = Path(str(prefix)+'.xml')
    command = [sys.executable,'-m','pytest','-q','--tb=short','--junitxml='+str(xml)]
    started = time.perf_counter()
    run = subprocess.run(['/usr/bin/time','-v','-o',str(prefix)+'.time.txt',*command],capture_output=True,text=True)
    elapsed = time.perf_counter()-started
    Path(str(prefix)+'.stdout.txt').write_text(run.stdout)
    Path(str(prefix)+'.stderr.txt').write_text(run.stderr)
    raw = xml.read_bytes()
    suite = next(ET.fromstring(raw).iter('testsuite')).attrib
    archive = Path(str(prefix)+'.xml.gz')
    archive.write_bytes(gzip.compress(raw,mtime=0))
    assert gzip.decompress(archive.read_bytes()) == raw
    xml.unlink()
    unchanged = code_hash == fingerprint()[0]
    passed = run.returncode == 0 and unchanged and all(int(suite[k]) == 0 for k in ('failures','errors','skipped'))
    receipt = {'schema':'scar.frozen-regression','status':'PASS' if passed else 'FAIL',
        'revision':revision,'source_sha256':code_hash,'worktree_status':status,
        'source_unchanged':unchanged,'command':command,'returncode':run.returncode,
        'wall_seconds':elapsed,'suite':suite,'xml_sha256':hashlib.sha256(raw).hexdigest()}
    Path(str(prefix)+'.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt),flush=True)
    if not passed:
        print(run.stdout[-12000:])
        print(run.stderr[-2000:])
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
