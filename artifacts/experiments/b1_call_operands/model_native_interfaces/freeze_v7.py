"""Generate the v7 golden using its original, isolated program codec."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[4]
REVISION = "126d56eccf9a1b3d20e09af342e729b053193af1"
archive = subprocess.check_output(["git", "archive", REVISION, "scar", "tests"], cwd=ROOT)
with tempfile.TemporaryDirectory(prefix="scar-original-v7-") as scratch:
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        bundle.extractall(scratch, filter="data")
    env = dict(os.environ, PYTHONPATH=scratch, PYTHONDONTWRITEBYTECODE="1")
    payload = subprocess.check_output([
        sys.executable, "-c",
        "from scar.ir.program.codec import dumps; "
        "from tests.fixtures.program_provider_graphs import definition_provider_graph; "
        "print(dumps(definition_provider_graph()), end='')",
    ], cwd=scratch, env=env)
    assert json.loads(payload)["schema_version"] == 7
    codec_hash = hashlib.sha256(Path(scratch, "scar/ir/program/codec.py").read_bytes()).hexdigest()

fixture = ROOT / "tests/fixtures/program_graph_v7_frozen.json"
assert not fixture.exists(), "do not overwrite a frozen fixture"
fixture.write_bytes(payload + b"\n")
proof = {
    "revision": REVISION,
    "origin": "git archive scar tests; isolated original code, not the new dataclasses",
    "archive_sha256": hashlib.sha256(archive).hexdigest(),
    "original_codec_sha256": codec_hash,
    "fixture": str(fixture.relative_to(ROOT)),
    "factory": "tests.fixtures.program_provider_graphs.definition_provider_graph",
    "wire_sha256": hashlib.sha256(payload).hexdigest(),
    "wire_bytes": len(payload),
    "file_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
    "temporary_directory_removed": True,
}
fixture.with_suffix(".proof.json").write_text(json.dumps(proof, indent=2) + "\n")
print(json.dumps(proof))
