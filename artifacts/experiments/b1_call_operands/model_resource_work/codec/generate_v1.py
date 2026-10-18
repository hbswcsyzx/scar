"""Generate the historical fixture using only an isolated immutable archive."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path.cwd()
REVISION = "6fcac0f778d56d7fe4fdb90e546b23e545f86f96"
OUT = ROOT / "artifacts/experiments/b1_call_operands/model_resource_work/codec/historical"
OUT.mkdir(parents=True, exist_ok=False)
fixture = ROOT / "tests/fixtures/execution_v1_frozen.json"
proof = fixture.with_suffix(".proof.json")
archive_command = ["git", "archive", "--format=tar", REVISION, "scar", "tests/fixtures"]
archive = subprocess.run(archive_command, cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
(OUT / "archive.stderr.log").write_bytes(archive.stderr)
script = """from pathlib import Path
import sys
import scar.ir.execution.codec as codec
from tests.fixtures.execution_resource_graphs import resource_execution_program
assert codec.SCHEMA_VERSION == 1
assert Path(codec.__file__).resolve().is_relative_to(Path.cwd().resolve())
assert Path(sys.path[0] or '.').resolve() == Path.cwd().resolve()
program, model = resource_execution_program(native_handles=True)
assert len(model.activations) == 2
sys.stdout.write(codec.dumps(model))
"""
with tempfile.TemporaryDirectory(prefix="scar-execution-v1-") as temporary:
    child = Path(temporary)
    with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as source:
        source.extractall(child, filter="data")
    command = [sys.executable, "-c", script]
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(child))
    metadata = {"archive_command": archive_command, "command": command, "cwd": str(child),
                "environment": {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(child)},
                "source_revision": REVISION, "python": sys.version,
                "historical_codec_sha256": hashlib.sha256((child/"scar/ir/execution/codec.py").read_bytes()).hexdigest(),
                "historical_fixture_sha256": hashlib.sha256((child/"tests/fixtures/execution_resource_graphs.py").read_bytes()).hexdigest()}
    (OUT / "command.json").write_text(json.dumps(metadata, indent=2) + "\n")
    result = subprocess.run(command, cwd=child, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (OUT / "stderr.log").write_bytes(result.stderr)
    (OUT / "result.json").write_text(json.dumps({"exit_code": result.returncode}, indent=2) + "\n")
    if result.returncode:
        (OUT / "failed.stdout.log").write_bytes(result.stdout)
        raise SystemExit(result.returncode)
    document = json.loads(result.stdout)
    assert document["schema"] == "scar.execution-model" and document["schema_version"] == 1
    fixture.write_bytes(result.stdout)
    metadata.update(codec_schema_version=1, wire_schema_version=1,
                    factory="resource_execution_program(native_handles=True)",
                    payload_sha256=hashlib.sha256(result.stdout).hexdigest(),
                    payload_size_bytes=len(result.stdout))
    proof.write_text(json.dumps(metadata, indent=2) + "\n")
print(json.dumps({"fixture": str(fixture), "sha256": metadata["payload_sha256"],
                  "size_bytes": metadata["payload_size_bytes"]}, indent=2))
