"""Measure source proof models only; no target imports, execution or rewrite."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from scar.analysis.proof_models_report_v2 import report_source_proof_models
from scar.cli import _compressed_document
from scripts.measure_import_values_v2 import process_peak_rss


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    started = time.perf_counter()
    report = report_source_proof_models(args.source, project_root=args.project_root)
    output = _compressed_document(args.out, report)
    duration = time.perf_counter() - started
    peak_rss, rss_source = process_peak_rss()
    metadata = {
        "schema": "scar.source-proof-models-measurement", "schema_version": 1,
        "status": "Observed", "revision": revision,
        "python": sys.version, "executable": sys.executable,
        "recorded_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "One SCAR source model analysis and report write, not target execution, optimization legality or speedup.",
        "source": str(args.source.resolve()),
        "project_root": str(args.project_root.resolve()) if args.project_root else None,
        "source_fingerprints": {entry["path"]: entry["fingerprint"]
                                for entry in report["source_semantics"]["sources"]},
        "summary": report["summary"], "decision": report["decision"],
        "analysis_seconds": report["measurement"]["analysis_seconds"],
        "seconds_including_write": duration,
        "peak_rss_kib": peak_rss, "peak_rss_source": rss_source,
        "report": str(output), "report_bytes": output.stat().st_size,
        "report_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }
    output.with_suffix(".measurement.json").write_text(
        json.dumps(metadata, sort_keys=True, indent=2, ensure_ascii=True) + "\n")
    print(json.dumps(metadata, sort_keys=True))


if __name__ == "__main__":
    main()
