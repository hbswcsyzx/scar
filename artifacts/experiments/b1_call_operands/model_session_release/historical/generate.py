"""Generate the v13 golden solely from the immutable pre-publication git tree."""
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
revision = subprocess.check_output(['git', 'rev-parse', '817cc0b'], text=True).strip()
temporary = Path(tempfile.mkdtemp(prefix='scar-session-v13-'))
output = root / 'tests/fixtures/program_graph_v13_frozen.json'
proof = root / 'tests/fixtures/program_graph_v13_frozen.proof.json'
assert not output.exists() and not proof.exists()
raw = subprocess.check_output(['git', 'archive', revision, 'scar', 'tests/fixtures'])
with tarfile.open(fileobj=io.BytesIO(raw)) as bundle:
    bundle.extractall(temporary, filter='data')
child = '''from pathlib import Path
import hashlib, json, sys
import scar.ir.program.codec as codec
from tests.fixtures.program_no_body_graphs import no_body_program
source, output, proof, revision = map(str, sys.argv[1:])
source, output, proof = Path(source), Path(output), Path(proof)
assert Path(codec.__file__).resolve().is_relative_to(source)
assert codec.SCHEMA_VERSION == 13
wire = codec.dumps(no_body_program(target="value", extra_domain=True, strict_subset=True))
assert json.loads(wire)["schema_version"] == 13
assert codec.dumps(codec.loads(wire)) == wire
output.write_text(wire)
receipt = {"source_revision": revision, "codec_schema_version": codec.SCHEMA_VERSION,
    "wire_schema_version": 13, "factory": "no_body_program(target='value', extra_domain=True, strict_subset=True)",
    "codec_path_inside_immutable_archive": True, "codec_sha256": hashlib.sha256(Path(codec.__file__).read_bytes()).hexdigest(),
    "fixture_bytes": len(wire.encode()), "fixture_sha256": hashlib.sha256(wire.encode()).hexdigest(),
    "python": sys.version}
proof.write_bytes(json.dumps(receipt, indent=2).encode() + bytes([10]))
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
