"""Generate the v11 golden solely from the immutable pre-publication git tree."""
from pathlib import Path
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile

root = Path.cwd().resolve()
archive = Path(__file__).resolve().parent
revision = subprocess.check_output(['git', 'rev-parse', '38d2968'], text=True).strip()
temporary = Path(tempfile.mkdtemp(prefix='scar-publication-v11-'))
output = root / 'tests/fixtures/program_graph_v11_frozen.json'
proof = root / 'tests/fixtures/program_graph_v11_frozen.proof.json'
assert not output.exists() and not proof.exists()
raw = subprocess.check_output(['git', 'archive', revision, 'scar', 'tests/fixtures', 'tests/__init__.py'])
with tarfile.open(fileobj=io.BytesIO(raw)) as bundle:
    bundle.extractall(temporary, filter='data')
child = '''from pathlib import Path
import hashlib, json, sys
import scar.ir.program.codec as codec
from tests.fixtures.program_driver_graphs import driver_program
source, output, proof, revision = map(str, sys.argv[1:])
source, output, proof = Path(source), Path(output), Path(proof)
assert Path(codec.__file__).resolve().is_relative_to(source)
assert codec.SCHEMA_VERSION == 11
wire = codec.dumps(driver_program(target="value", extra_domain=True))
assert json.loads(wire)["schema_version"] == 11
assert codec.dumps(codec.loads(wire)) == wire
output.write_text(wire)
receipt = {"source_revision": revision, "codec_schema_version": codec.SCHEMA_VERSION,
    "wire_schema_version": 11, "factory": "driver_program(target='value', extra_domain=True)",
    "codec_path_inside_immutable_archive": True, "codec_sha256": hashlib.sha256(Path(codec.__file__).read_bytes()).hexdigest(),
    "fixture_bytes": len(wire.encode()), "fixture_sha256": hashlib.sha256(wire.encode()).hexdigest(),
    "python": sys.version}
proof.write_text(json.dumps(receipt, indent=2) + "\\n")
print(json.dumps(receipt))
'''
command = [sys.executable, '-c', child, str(temporary), str(output), str(proof), revision]
environment = {name: os.environ[name] for name in ('PATH', 'HOME', 'CONDA_PREFIX', 'CONDA_DEFAULT_ENV') if name in os.environ}
environment.update(PYTHONPATH=str(temporary), PYTHONDONTWRITEBYTECODE='1')
(archive / 'command.json').write_text(json.dumps({'revision': revision, 'command': command,
    'cwd': str(temporary), 'environment': environment, 'temporary_exclusively_owned': True}, indent=2) + '\n')
result = subprocess.run(command, cwd=temporary, env=environment, capture_output=True, text=True)
(archive / 'generation.log').write_text(result.stdout + result.stderr)
(archive / 'result.json').write_text(json.dumps({'returncode': result.returncode,
    'output_exists': output.exists(), 'proof_exists': proof.exists()}, indent=2) + '\n')
if result.returncode:
    print(result.stdout + result.stderr)
    raise SystemExit(result.returncode)
shutil.rmtree(temporary)
print(result.stdout.strip())
