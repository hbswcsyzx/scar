"""Read the existing gate fingerprint only; do not execute a gate or tests."""
import json
from pathlib import Path
import sys

from scripts.run_gate import fingerprint


source_sha256, files = fingerprint()
payload = {
    "kind": "read-only bounded-review source snapshot; no tests executed",
    "source_sha256": source_sha256,
    "source_file_count": len(files),
    "files": files,
    "python": sys.version,
    "executable": sys.executable,
}
Path(__file__).with_suffix(".json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
print(json.dumps({key: payload[key] for key in ("kind", "source_sha256", "source_file_count", "python", "executable")}, sort_keys=True))
