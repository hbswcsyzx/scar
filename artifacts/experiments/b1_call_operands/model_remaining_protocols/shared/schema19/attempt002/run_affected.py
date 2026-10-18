import json
import os
from pathlib import Path
import subprocess
import sys
import time

from scripts.run_gate import fingerprint


ROOT = Path.cwd()
OUT = ROOT / "artifacts/experiments/b1_call_operands/model_remaining_protocols/shared/schema19/attempt002"
TESTS = [
    "tests/unit/test_program_state_address_codec.py",
    "tests/unit/test_program_literal_codec.py",
    "tests/unit/test_program_admission_codec.py",
    "tests/unit/test_program_no_body_codec.py",
    "tests/unit/test_program_protocol_codec.py",
    "tests/unit/test_program_session_release_codec.py",
    "tests/unit/test_program_driver_codec.py",
    "tests/unit/test_program_publication_codec.py",
    "tests/unit/test_program_resumption_codec.py",
    "tests/unit/test_lifecycle_composition_codec.py",
    "tests/unit/test_program_protocol_connection_records.py",
    "tests/unit/test_program_protocol_connections_codec.py",
    "tests/unit/test_program_protocol_connection_records.py::test_package_port_aliases_match_closed_model_unions_in_fresh_process",
]


def main():
    command = [sys.executable, "-m", "pytest", "-q", *TESTS,
               f"--junitxml={OUT / 'junit.xml'}"]
    before_digest, before = fingerprint()
    (OUT / "command.json").write_text(json.dumps({
        "command": command,
        "cwd": str(ROOT),
        "python": sys.version,
        "activation": "source /home/zyf/miniconda3/etc/profile.d/conda.sh; conda activate lewm",
        "environment": {key: os.environ.get(key) for key in ("PYTHONPATH", "PYTHONDONTWRITEBYTECODE")},
        "scope": "One affected focused selection after package-alias export fix",
    }, indent=2) + "\n")
    (OUT / "sources.before.json").write_text(json.dumps(before, indent=2) + "\n")
    started = time.monotonic()
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    elapsed = time.monotonic() - started
    after_digest, after = fingerprint()
    (OUT / "stdout.log").write_text(result.stdout)
    (OUT / "stderr.log").write_text(result.stderr)
    (OUT / "sources.after.json").write_text(json.dumps(after, indent=2) + "\n")
    report = {
        "returncode": result.returncode,
        "duration_seconds": elapsed,
        "source_sha256_before": before_digest,
        "source_sha256_after": after_digest,
        "source_unchanged": before_digest == after_digest,
        "changed_paths": sorted(key for key in before.keys() | after.keys()
                                 if before.get(key) != after.get(key)),
        "tests": TESTS,
    }
    (OUT / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(result.stdout)
    print(result.stderr)
    print(json.dumps(report))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
