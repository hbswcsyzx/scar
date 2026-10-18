from __future__ import annotations
import hashlib
import json
import platform
import sys
from pathlib import Path

attempt = Path(sys.argv[1]).resolve()
fixture = Path(sys.argv[2]).resolve()
archive_hash = (attempt / "archive-sha256.txt").read_text().split()[0]
module_hashes = json.loads((attempt / "imported-source-hashes.json").read_text())
payload = fixture.read_bytes()
proof = {
    "source_revision": "5ab22f8d8fcbabbc59d494b571651d480468f3d5",
    "archive_command": ["git", "archive", "--format=tar",
                        "5ab22f8d8fcbabbc59d494b571651d480468f3d5",
                        "scar", "tests/fixtures"],
    "archive_sha256": archive_hash,
    "command": [
        "/home/zyf/miniconda3/envs/lewm/bin/python",
        str(attempt / "generate_v4_golden.py"),
        str(attempt / "archive"), str(attempt / "execution_v4_frozen.json"),
        str(attempt / "imported-source-hashes.json"),
    ],
    "cwd": "/tmp/scar-structured-model-280qf4mi",
    "python": sys.version,
    "environment": {"PYTHONDONTWRITEBYTECODE": "1",
                     "PYTHONPATH": str(attempt / "archive")},
    "historical_source_hashes": module_hashes["loaded_modules"],
    "codec_schema_version": 4,
    "wire_schema_version": 4,
    "factory": "content_connection_fixture(consumer='work', duplicate_use=True, observation=True)",
    "payload_sha256": hashlib.sha256(payload).hexdigest(),
    "payload_size_bytes": len(payload),
    "independent_oracle": "old codec and fixture loaded only from git archive; archived output compared byte-for-byte with checked-in fixture",
    "attempt001_note": "generation succeeded; wrapper stopped on cp of a file onto itself before checksums/proof; its raw output is preserved separately",
}
fixture.with_suffix(fixture.suffix + ".proof.json").write_text(
    json.dumps(proof, sort_keys=True, indent=2) + "\n")
