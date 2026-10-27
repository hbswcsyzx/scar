"""Freeze v5 bytes using only an immutable pre-V checkout and its fixture."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path.cwd()
OUT = Path(__file__).resolve().parent
REVISION = 'f2b4672d9555348dcd05da62a8cd126711ef22f9'


def main():
    attempt = next(OUT / f'attempt{number:03d}' for number in range(1, 1000)
                   if not (OUT / f'attempt{number:03d}').exists())
    attempt.mkdir(exist_ok=False)
    command = ['git', 'archive', REVISION, 'scar', 'tests/fixtures',
               'tests/unit/test_execution_production_codec.py']
    (attempt / 'archive-command.json').write_text(json.dumps(command, indent=2) + '\n')
    archive_result = subprocess.run(command, cwd=ROOT, capture_output=True)
    (attempt / 'archive-stderr.log').write_bytes(archive_result.stderr)
    (attempt / 'archive-exit.txt').write_text(str(archive_result.returncode) + '\n')
    if archive_result.returncode:
        raise RuntimeError('immutable git archive failed')
    archive = archive_result.stdout
    (attempt / 'source.tar').write_bytes(archive)
    directory = Path(tempfile.mkdtemp(prefix='scar-v5-immutable-'))
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        source.extractall(directory, filter='data')
    child = '''import hashlib, importlib.util, json
from pathlib import Path
import scar.ir.execution.codec as codec
spec = importlib.util.spec_from_file_location("old_fixture", "tests/unit/test_execution_production_codec.py")
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
model = fixture.production_model.__wrapped__()
payload = codec.dumps(model).encode("utf-8")
Path("v5.json").write_bytes(payload)
assert codec.SCHEMA_VERSION == 5
assert codec.loads(payload.decode()) == model
print(json.dumps({"codec_file":str(Path(codec.__file__).resolve()),
 "codec_sha256":hashlib.sha256(Path(codec.__file__).read_bytes()).hexdigest(),
 "fixture_file":str(Path(fixture.__file__).resolve()),
 "fixture_sha256":hashlib.sha256(Path(fixture.__file__).read_bytes()).hexdigest(),
 "schema_version":5,"payload_sha256":hashlib.sha256(payload).hexdigest(),
 "payload_bytes":len(payload),"p_table_counts":{k:len(getattr(model,k)) for k in
 ("source_inventories","source_bridges","writes","produced")}},sort_keys=True))
'''
    (attempt / 'child.py').write_text(child)
    environment = {key: os.environ[key] for key in ('PATH', 'HOME', 'CONDA_PREFIX') if key in os.environ}
    environment.update(PYTHONPATH=str(directory), PYTHONDONTWRITEBYTECODE='1')
    child_command = [sys.executable, '-c', child]
    (attempt / 'child-command.json').write_text(json.dumps(child_command, indent=2) + '\n')
    result = subprocess.run(child_command, cwd=directory, env=environment, capture_output=True, text=True)
    (attempt / 'stdout.log').write_text(result.stdout)
    (attempt / 'stderr.log').write_text(result.stderr)
    (attempt / 'exit.txt').write_text(str(result.returncode) + '\n')
    if result.returncode:
        raise RuntimeError('immutable v5 generation failed; original evidence retained')
    proof = json.loads(result.stdout)
    payload = (directory / 'v5.json').read_bytes()
    proof.update(revision=REVISION, archive_sha256=hashlib.sha256(archive).hexdigest(),
                 archive_bytes=len(archive), fixture_scope='old codec-only rich declaration fixture; not a validated physical execution')
    for source, key in [('scar/ir/execution/codec.py', 'codec_sha256'),
                        ('tests/unit/test_execution_production_codec.py', 'fixture_sha256')]:
        blob = subprocess.check_output(['git', 'show', REVISION + ':' + source], cwd=ROOT)
        assert hashlib.sha256(blob).hexdigest() == proof[key]
    fixture = ROOT / 'tests/fixtures/execution_v5_frozen.json'
    if fixture.exists():
        raise RuntimeError('refusing to overwrite an existing independent golden')
    fixture.write_bytes(payload)
    fixture.with_name(fixture.name + '.proof.json').write_text(json.dumps(proof, indent=2) + '\n')
    (attempt / 'proof.json').write_text(json.dumps(proof, indent=2) + '\n')
    shutil.rmtree(directory)
    (attempt / 'source.tar').unlink()
    (attempt / 'cleanup.json').write_text(json.dumps({'owned_extraction_removed': str(directory),
        'source_tar_removed_after_size_sha_and_blob_check': True}, indent=2) + '\n')
    print(json.dumps(proof))


if __name__ == '__main__':
    main()
