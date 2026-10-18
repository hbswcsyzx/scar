"""Generate a v7 wire golden only while running from an immutable source archive."""
import hashlib
import json
from pathlib import Path
import platform
import sys

from scar.ir.execution.codec import SCHEMA_VERSION, dumps
from tests.fixtures.execution_call_graphs import shared_calls_execution


REVISION = "a740661bdf5ed34676d65e6c8eb5f15b890e0084"
SOURCE_FILES = (
    "scar/ir/execution/codec.py",
    "scar/ir/execution/model.py",
    "scar/ir/execution/calls.py",
    "scar/ir/execution/coordinates.py",
    "scar/ir/execution/common.py",
    "scar/ir/execution/snapshot.py",
    "tests/fixtures/execution_call_graphs.py",
    "tests/fixtures/program_graphs.py",
)


def main():
    output = Path(sys.argv[1]).resolve()
    proof_path = Path(sys.argv[2]).resolve()
    if SCHEMA_VERSION != 7:
        raise SystemExit(f"oracle schema must be v7, got {SCHEMA_VERSION}")
    program, model, details = shared_calls_execution()
    if not model.call_activations or len(model.call_activations) != 2:
        raise SystemExit("v7 oracle fixture must contain two populated CallActivation rows")
    payload = dumps(model, schema_version=7).encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    immutable_blobs = {
        path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
        for path in SOURCE_FILES
    }
    proof = {
        "revision": REVISION,
        "schema": "scar.execution-model",
        "schema_version": 7,
        "encoder": "scar.ir.execution.codec.dumps(model, schema_version=7)",
        "codec_sha256": immutable_blobs["scar/ir/execution/codec.py"],
        "fixture_source": "tests/fixtures/execution_call_graphs.py",
        "fixture_sha256": immutable_blobs["tests/fixtures/execution_call_graphs.py"],
        "program_fixture_sha256": immutable_blobs["tests/fixtures/program_graphs.py"],
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "payload_bytes": len(payload),
        "call_activations": [row.id.value for row in model.call_activations],
        "call_activation_count": len(model.call_activations),
        "program_root": program.root.value,
        "factory_details": sorted(details),
        "python": sys.version,
        "platform": platform.platform(),
        "immutable_blobs": immutable_blobs,
    }
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    proof_path.write_text(json.dumps(proof, sort_keys=True, indent=2) + "\n")
    print(json.dumps({key: proof[key] for key in (
        "revision", "schema_version", "payload_sha256", "payload_bytes",
        "call_activation_count", "call_activations", "codec_sha256")}, sort_keys=True))


if __name__ == "__main__":
    main()
