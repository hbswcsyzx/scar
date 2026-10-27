"""Create v2 expected bytes in an independent immutable archive, never current code."""
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
revision = subprocess.run(["git", "rev-parse", "bb1b402^{commit}"], cwd=ROOT,
                          check=True, text=True, stdout=subprocess.PIPE).stdout.strip()
OUT = ROOT / "artifacts/experiments/b1_call_operands/model_resource_order/codec/historical"
OUT.mkdir(parents=True, exist_ok=False)
fixture = ROOT / "tests/fixtures/execution_v2_frozen.json"
archive_command = ["git", "archive", "--format=tar", revision, "scar", "tests/fixtures"]
archive = subprocess.run(archive_command, cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
(OUT / "archive.stderr.log").write_bytes(archive.stderr)
script = """from pathlib import Path
import sys
import scar.ir.execution.codec as codec
import scar.ir.execution.model as model_module
import scar.ir.execution.work as work_module
import tests.fixtures.execution_work_graphs as fixtures
assert codec.SCHEMA_VERSION == 2
root = Path.cwd().resolve()
for module in (codec, model_module, work_module, fixtures):
    assert Path(module.__file__).resolve().is_relative_to(root)
program, model, value_graphs = fixtures.ordinary_work_execution(queued=True, two_tickets=True, retained='allocation')
for name, module in tuple(sys.modules.items()):
    if name == 'scar' or name.startswith(('scar.', 'tests.fixtures')):
        path = getattr(module, '__file__', None)
        if path is not None:
            assert Path(path).resolve().is_relative_to(root), (name, path)
assert all(getattr(model, name) for name in ('submissions','outcomes','quiescences','retentions','queue_prefixes'))
sys.stdout.write(codec.dumps(model))
"""
with tempfile.TemporaryDirectory(prefix="scar-execution-v2-") as temporary:
    child = Path(temporary)
    with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as source:
        source.extractall(child, filter="data")
    command = [sys.executable, "-c", script]
    names = ("scar/ir/execution/codec.py", "scar/ir/execution/model.py", "scar/ir/execution/work.py",
             "tests/fixtures/execution_work_graphs.py")
    metadata = {"source_revision": revision, "archive_command": archive_command, "command": command,
                "cwd": str(child), "environment": {"PYTHONDONTWRITEBYTECODE":"1", "PYTHONPATH":str(child)},
                "python": sys.version, "historical_source_hashes": {
                    name:hashlib.sha256((child/name).read_bytes()).hexdigest() for name in names}}
    (OUT/"command.json").write_text(json.dumps(metadata, indent=2)+"\n")
    result = subprocess.run(command, cwd=child,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(child)),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (OUT/"stderr.log").write_bytes(result.stderr)
    (OUT/"result.json").write_text(json.dumps({"exit_code":result.returncode}, indent=2)+"\n")
    if result.returncode:
        (OUT/"failed.stdout.log").write_bytes(result.stdout)
        raise SystemExit(result.returncode)
    document = json.loads(result.stdout)
    assert document["schema"] == "scar.execution-model" and document["schema_version"] == 2
    fixture.write_bytes(result.stdout)
    metadata.update(codec_schema_version=2, wire_schema_version=2,
        factory="ordinary_work_execution(queued=True, two_tickets=True, retained='allocation')",
        payload_sha256=hashlib.sha256(result.stdout).hexdigest(), payload_size_bytes=len(result.stdout))
    fixture.with_suffix(".proof.json").write_text(json.dumps(metadata, indent=2)+"\n")
print(json.dumps({"source_revision":revision,"sha256":metadata["payload_sha256"],
                  "size_bytes":metadata["payload_size_bytes"]}, indent=2))
