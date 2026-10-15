"""Use the actual historical package, then check its report with current code."""
import argparse
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import time


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--revision', default='b886e40')
    args = p.parse_args()
    root = Path.cwd()
    prefix = root / 'artifacts/reports/gates/n2-schedule-legacy'
    inputs = Path(str(prefix) + '-input')
    inputs.mkdir(exist_ok=True)
    entry = inputs / 'entry.py'
    entry.write_text('def unused(x):\n    return x\ndef observed(x):\n    return child(x)\ndef child(x):\n    return x\n')
    sys.path.insert(0, str(root))
    from scar.ir.ids import CodeID
    from scripts.run_gate import fingerprint
    frozen_hash = fingerprint()[0]
    trace = inputs / 'events.jsonl'
    trace.write_text(json.dumps({'kind':'python_call', 'index':1, 'invocation_id':1,
        'code_id':CodeID(str(entry), 'observed', 3, None, 'unknown').key(),
        'metadata':{'process_id':1}}) + '\n')
    output = Path(str(prefix) + '-v2.json.gz')
    old_revision = subprocess.check_output(['git','rev-parse',args.revision],text=True).strip()
    archive = subprocess.check_output(['git','archive',old_revision,'scar','pyproject.toml'])
    stages = []
    with tempfile.TemporaryDirectory(prefix='scar-legacy-package-') as folder:
        with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
            stream.extractall(folder, filter='data')
        environment = dict(os.environ, PYTHONPATH=folder)
        command = [sys.executable,'-m','scar.cli','inventory-program',str(entry),
            '--project-root',str(inputs),'--trace',str(trace),'--max-lowered-bodies','2','--out',str(output)]
        start = time.perf_counter()
        run = subprocess.run(command,cwd=folder,env=environment,capture_output=True,text=True)
        stages.append({'name':'historical_build','command':command,'returncode':run.returncode,
                       'seconds':time.perf_counter()-start,'stdout':run.stdout,'stderr':run.stderr})
    if run.returncode:
        raise RuntimeError(stages)
    import gzip
    with gzip.open(output,'rt') as stream:
        document = json.load(stream)
    assert document['schema_version'] == 2 and 'expansion' not in document
    body = next(b for f in document['files'] for b in f['bodies']
                if b['metadata'] and b['metadata']['entry'] == 'observed')
    assert len(body['graph']['regions']) == 2
    start = time.perf_counter()
    command = [sys.executable,'-m','scar.cli','check-inventory',str(output)]
    run = subprocess.run(command,cwd=root,capture_output=True,text=True)
    stages.append({'name':'current_replay','command':command,'returncode':run.returncode,
                   'seconds':time.perf_counter()-start,'stdout':run.stdout,'stderr':run.stderr})
    receipt = {'schema':'scar.historical-inventory-compatibility','historical_revision':old_revision,
        'current_revision':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'source_sha256':frozen_hash,'source_unchanged':fingerprint()[0] == frozen_hash,
        'target_executed':False,'stages':stages,
        'status':'PASS' if run.returncode == 0 and fingerprint()[0] == frozen_hash else 'FAIL'}
    Path(str(prefix) + '-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt))
    return 0 if receipt['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
