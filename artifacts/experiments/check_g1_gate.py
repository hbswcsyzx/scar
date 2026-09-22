"""Run and record the SCAR IR v2 G1 acceptance gate."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "artifacts" / "reports" / "gates"


def run(command: list[str]) -> dict:
    started = time.perf_counter()
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    return {
        "command": command,
        "returncode": result.returncode,
        "duration_seconds": round(time.perf_counter() - started, 6),
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def main() -> int:
    schema_tests = run([
        sys.executable, "-m", "pytest",
        "tests/unit/test_ir_v2.py",
        "tests/unit/test_ir_v2_optimization.py", "-q",
    ])
    compatibility_test = run([
        sys.executable, "-m", "pytest",
        "tests/integration/test_trace.py::test_trace_and_analysis", "-q",
    ])
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
        text=True, check=True).stdout.strip()

    core_files = list((ROOT / "scar" / "ir" / "v2").glob("*.py"))
    workload_specific = [
        str(path.relative_to(ROOT)) for path in core_files
        if "lewm" in path.read_text().lower()
    ]
    forbidden_consumers = []
    for directory in ("analysis", "planner", "backends"):
        for path in (ROOT / "scar" / directory).rglob("*.py"):
            if "scar.ir.v2" in path.read_text() or "ir.v2" in path.read_text():
                forbidden_consumers.append(str(path.relative_to(ROOT)))

    criteria = [
        {
            "id": "typed_id_and_reference_validation",
            "status": "PASS" if schema_tests["returncode"] == 0 else "FAIL",
            "evidence": "test_typed_ids_cannot_be_interchanged and graph validators",
        },
        {
            "id": "report_only_oir_fixtures",
            "status": "PASS" if schema_tests["returncode"] == 0 else "FAIL",
            "evidence": "constant substitution, import residual, loop move, residency fixtures",
        },
        {
            "id": "original_fallback_and_rewrite_proof",
            "status": "PASS" if schema_tests["returncode"] == 0 else "FAIL",
            "evidence": "OIR rejects dangling references and unproven selected rewrites",
        },
        {
            "id": "deterministic_json_round_trip",
            "status": "PASS" if schema_tests["returncode"] == 0 else "FAIL",
            "evidence": "IRBundle canonical JSON decode/encode equality",
        },
        {
            "id": "v1_cli_compatibility",
            "status": "PASS" if compatibility_test["returncode"] == 0 else "FAIL",
            "evidence": "existing trace plus analyze integration test",
        },
        {
            "id": "workload_independence",
            "status": "PASS" if not workload_specific else "FAIL",
            "evidence": {"workload_specific_files": workload_specific},
        },
        {
            "id": "no_detector_or_backend_wiring",
            "status": "PASS" if not forbidden_consumers else "FAIL",
            "evidence": {"v2_consumers": forbidden_consumers},
        },
    ]
    status = "PASS" if all(item["status"] == "PASS" for item in criteria) else "FAIL"
    report = {
        "schema": "scar.gate-report",
        "schema_version": 1,
        "gate": "G1",
        "status": status,
        "revision": revision,
        "python": sys.version,
        "criteria": criteria,
        "commands": {"schema_tests": schema_tests,
                     "compatibility_test": compatibility_test},
        "scope": "IR schema and report-only plan representation",
        "explicitly_not_verified": [
            "source-to-SG frontend",
            "trace-to-EEG normalizer",
            "candidate detection through OIR",
            "backend application",
            "LeWM transformation or speedup",
        ],
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "g1.json").write_text(json.dumps(report, indent=2) + "\n")
    rows = "\n".join(
        f"| `{item['id']}` | {item['status']} | {item['evidence']} |"
        for item in criteria)
    markdown = (
        "# SCAR G1 gate report\n\n"
        f"Status: **{status}**\n\n"
        f"Revision: `{revision}`\n\n"
        "| Criterion | Status | Evidence |\n"
        "| --- | --- | --- |\n"
        f"{rows}\n\n"
        "This gate validates schema and report-only plan representation. It does "
        "not claim source/trace migration, a selected workload transformation, "
        "or a LeWM speedup.\n"
    )
    (REPORT_DIR / "g1.md").write_text(markdown)
    print(json.dumps({"gate": "G1", "status": status,
                      "report": str(REPORT_DIR / "g1.json")}))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
