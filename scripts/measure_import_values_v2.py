"""Measure source analysis only; never execute or import the target program."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import time

from scar.analysis.import_report_v2 import report_import_values
from scar.cli import _compressed_document


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    started = time.perf_counter()
    report = report_import_values(args.source.resolve(), project_root=args.project_root)
    output = _compressed_document(args.out, report)
    duration = time.perf_counter() - started
    metadata = {
        "schema": "scar.import-values-measurement", "schema_version": 1,
        "status": "Observed", "revision": revision,
        "recorded_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "One SCAR source analysis and report write; target never executed, no workload speedup measurement.",
        "source": str(args.source.resolve()),
        "project_root": str(args.project_root.resolve()) if args.project_root else None,
        "source_fingerprints": {entry["path"]: entry["fingerprint"] for entry in report["model"]["sources"]},
        "summary": report["summary"], "decision": report["decision"],
        "analysis_seconds": report["measurement"]["analysis_seconds"],
        "seconds_including_write": duration,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "report": str(output), "report_bytes": output.stat().st_size,
        "report_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }
    target = output.with_suffix(".measurement.json")
    target.write_text(json.dumps(metadata, sort_keys=True, indent=2, ensure_ascii=True) + "\n")
    stats = {key: value for key, value in metadata.items() if key not in {"summary", "source_fingerprints"}}
    stats["summary"] = {key: value for key, value in metadata["summary"].items() if key != "targets"}
    print(json.dumps(stats, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
