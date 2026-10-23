"""Freeze receipts, then exec the one public 369749 OS interface CLI."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

BASE = Path(__file__).resolve().parent
REPO = BASE.parents[2]
CAPTURE = BASE.parent / "first_stage_lewm_physical_20261023"
COMMAND = [sys.executable, "-m", "scar.cli", "import-os-resources", str(CAPTURE / "os"),
           "--capture-root", str(CAPTURE), "--interface-work", "--root-tid", "369749",
           "--max-bytes", "2000000000", "--max-lines", "2000000", "--out", str(BASE / "result")]


def receipt(path):
    raw = path.read_bytes()
    return {"path": str(path), "stored_bytes": len(raw), "stored_sha256": hashlib.sha256(raw).hexdigest()}


modules = ["scar/trace/os_resources.py", "scar/cli.py", "scar/trace/capture_import.py",
           "scar/trace/capture_coordinates.py", "scar/store/bundle_partitions.py",
           "scar/ir/execution/work.py", "scar/ir/execution/resources.py", "scar/ir/record_codec.py"]
producer = {"revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
            "pid": os.getpid(), "command": COMMAND, "cwd": str(REPO), "python": sys.version,
            "modules": [receipt(REPO / path) for path in modules], "script": receipt(Path(__file__)),
            "scope": "ONE public CLI over original369749 retained OS raw, no target/native replay",
            "first_stage_complete": False, "transformation_authorized": False}
expected = {"scar/trace/os_resources.py": "c52f45a62693e3e78875b3a23b7c56e0a4cdb48862436981f8d98941a4900c1b",
            "scar/cli.py": "6f786b0fa52b5a8311edac6a8e0233cce038f03fe3257883536ba1db6a726e18",
            "scar/trace/capture_import.py": "c2f101b5e1f7f04981d5f36e87ce4a7a53db7cc77a51747a02898f9b88656356"}
for row in producer["modules"]:
    relative = str(Path(row["path"]).relative_to(REPO))
    if relative in expected:
        assert row["stored_sha256"] == expected[relative], (relative, "frozen module changed")
assert not (BASE / "result").exists()
(BASE / "producer.json").write_text(json.dumps(producer, sort_keys=True, indent=2) + "\n")
(BASE / "command.json").write_text(json.dumps(COMMAND, ensure_ascii=False, indent=2) + "\n")
(BASE / "implementation.patch").write_bytes(subprocess.check_output([
    "git", "diff", "--", "scar/trace/os_resources.py", "scar/cli.py", "scar/trace/capture_import.py"], cwd=REPO))
print(json.dumps({"event": "PUBLIC_CLI_EXEC", "pid": os.getpid(), "time_unix_ns": time.time_ns(),
                  "command": COMMAND, "revision": producer["revision"]}, sort_keys=True), flush=True)
os.chdir(REPO)
os.execv(sys.executable, COMMAND)
