"""Generate v3 expected bytes solely with an immutable archived v3 codec."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

root = Path.cwd()
out = root / "artifacts/experiments/b1_call_operands/model_content/codec/v3_golden"
out.mkdir(parents=True, exist_ok=False)
revision = subprocess.run(["git", "rev-parse", "6efbe27^{commit}"], cwd=root, check=True,
                          text=True, stdout=subprocess.PIPE).stdout.strip()
archive_command = ["git", "archive", "--format=tar", revision, "scar", "tests/fixtures"]
archive = subprocess.run(archive_command, cwd=root, check=True, capture_output=True)
(out / "archive.stderr.log").write_bytes(archive.stderr)
script = '''from pathlib import Path
import sys
import scar.ir.execution.codec as codec
import scar.ir.execution.model as model_module
import scar.ir.execution.work as work_module
import scar.ir.execution.order as order_module
import tests.fixtures.execution_order_graphs as fixtures
assert codec.SCHEMA_VERSION == 3
root = Path.cwd().resolve()
for module in (codec, model_module, work_module, order_module, fixtures):
    assert Path(module.__file__).resolve().is_relative_to(root)
program, model = fixtures.event_order_execution(same_queue=False, with_wait=True)
for name, module in tuple(sys.modules.items()):
    if name == 'scar' or name.startswith(('scar.', 'tests.fixtures')):
        path = getattr(module, '__file__', None)
        if path is not None:
            assert Path(path).resolve().is_relative_to(root), (name, path)
assert all(getattr(model, name) for name in ('submissions', 'queue_prefixes',
    'queue_order_profiles', 'event_records', 'queue_waits'))
sys.stdout.write(codec.dumps(model))
'''
with tempfile.TemporaryDirectory(prefix="scar-execution-v3-") as temporary:
    child = Path(temporary)
    with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as source:
        source.extractall(child, filter="data")
    command = [sys.executable, "-c", script]
    names = ("scar/ir/execution/codec.py", "scar/ir/execution/model.py",
             "scar/ir/execution/work.py", "scar/ir/execution/order.py",
             "tests/fixtures/execution_order_graphs.py")
    proof = {"source_revision": revision, "archive_command": archive_command,
             "archive_sha256": hashlib.sha256(archive.stdout).hexdigest(),
             "command": command, "cwd": str(child), "python": sys.version,
             "environment": {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(child)},
             "historical_source_hashes": {
                 name: hashlib.sha256((child / name).read_bytes()).hexdigest() for name in names}}
    (out / "command.json").write_text(json.dumps(proof, indent=2) + "\n")
    result = subprocess.run(command, cwd=child,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(child)),
        capture_output=True)
    (out / "stdout.log").write_bytes(result.stdout)
    (out / "stderr.log").write_bytes(result.stderr)
    (out / "result.json").write_text(json.dumps({"exit_code": result.returncode}, indent=2) + "\n")
    if result.returncode:
        raise SystemExit(result.returncode)
    document = json.loads(result.stdout)
    assert document["schema"] == "scar.execution-model" and document["schema_version"] == 3
    proof.update(codec_schema_version=3, wire_schema_version=3,
        factory="event_order_execution(same_queue=False, with_wait=True)",
        payload_sha256=hashlib.sha256(result.stdout).hexdigest(), payload_size_bytes=len(result.stdout))
    fixture = root / "tests/fixtures/execution_v3_frozen.json"
    fixture.write_bytes(result.stdout)
    fixture.with_suffix(".proof.json").write_text(json.dumps(proof, indent=2) + "\n")
    (out / "proof.json").write_text(json.dumps(proof, indent=2) + "\n")
print(json.dumps({"source_revision": revision, "sha256": proof["payload_sha256"],
                  "size_bytes": proof["payload_size_bytes"]}, indent=2))
