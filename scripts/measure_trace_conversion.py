"""Measure offline v1-to-v2 normalization and save reproducible G3 evidence.

Usage: python scripts/measure_trace_conversion.py TRACE --out REPORT.json
TRACE is an events.jsonl file or its directory. The target program is not run,
and the large normalized graph/value payload is not serialized.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scar.ir.v2 import EvidenceKind, EvidenceRelation  # noqa: E402
from scar.trace.normalize_v2 import normalize_trace  # noqa: E402


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sources():
    paths = sorted([*ROOT.joinpath("scar").rglob("*.py"), Path(__file__).resolve()])
    files = {str(path.relative_to(ROOT)): _file_sha256(path) for path in paths}
    combined = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    return combined, files


def _git(*arguments: str) -> str | None:
    result = subprocess.run(["git", *arguments], cwd=ROOT, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.stdout.strip() if result.returncode == 0 else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path, help="events.jsonl or its directory")
    parser.add_argument("--out", required=True, type=Path, help="small measurement report JSON")
    args = parser.parse_args()
    trace = args.trace.resolve()
    if trace.is_dir():
        trace = trace / "events.jsonl"
    if not trace.is_file():
        parser.error(f"trace file does not exist: {trace}")

    source_sha, measured_files = _sources()
    report = {
        "schema": "scar.gate.g3.runtime_pressure", "schema_version": 2,
        "status": "Rejected", "source": str(trace),
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "revision": _git("rev-parse", "HEAD"),
        "worktree_status": _git("status", "--porcelain"),
        "source_sha256": source_sha, "measured_files": measured_files,
        "command": [sys.executable, str(Path(__file__).resolve()), str(trace),
                    "--out", str(args.out.resolve())],
        "environment": {"python": sys.version, "executable": sys.executable,
                        "platform": platform.platform()},
        "measurement_scope": "normalize_trace including input hashing, graph construction and validation; excludes report writing and graph serialization",
        "errors": [],
    }
    rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    started = time.perf_counter()
    try:
        result = normalize_trace(trace)
    except Exception as error:
        report["errors"].append(f"{type(error).__name__}: {error}")
        report["valid"] = False
    else:
        elapsed = time.perf_counter() - started
        coverage = result.coverage
        instances = result.bundle.evidence.instances.values()
        edges = result.bundle.evidence.edges.values()
        report.update({
            "raw_sha256": coverage["source_sha256"],
            "raw_records": coverage["raw_records"],
            "accounted_records": coverage["accounted_records"],
            "coverage_status_counts": coverage["status_counts"],
            "kind_counts": coverage["kind_counts"],
            "graph_counts": coverage["graph_counts"],
            "valid": coverage["valid"],
            "physical_copies": sum(i.metadata.get("physical_copy") is True for i in instances),
            "host_transfer_calls": sum(i.metadata["raw_kind"] == "transfer" for i in instances),
            "physical_false_host_calls": sum(i.metadata.get("physical_copy") is False for i in instances),
            "aggregate_rows": sum(r.get("aggregate", False) for r in coverage["records"]),
            "same_stream_order_edges": sum(e.relation is EvidenceRelation.HAPPENS_BEFORE for e in edges),
            "same_stream_observed_claims": sum(
                e.relation is EvidenceRelation.HAPPENS_BEFORE and e.evidence.kind is EvidenceKind.OBSERVED
                for e in edges),
            "paired_python_calls": sum(i.metadata["raw_kind"] == "python_call" and i.metadata["completion"] == "paired_return" for i in instances),
            "incomplete_python_calls": sum(i.metadata["raw_kind"] == "python_call" and i.metadata["completion"] == "missing_return" for i in instances),
            "scope": coverage["scope"],
        })
        unchanged = (coverage["namespace"] == "trace:" + coverage["source_sha256"]
                     and _file_sha256(trace) == coverage["source_sha256"])
        report["input_unchanged"] = unchanged
        if not unchanged:
            report["errors"].append("trace changed during measurement")
        if coverage["raw_records"] != coverage["accounted_records"] or not coverage["valid"]:
            report["errors"].append("graph validity or raw-record accounting failed")
        report["normalization_wall_seconds"] = elapsed
    finally:
        report.setdefault("normalization_wall_seconds", time.perf_counter() - started)
        # ru_maxrss is a process high-water mark, not an incremental allocation
        # measurement. Linux reports KiB; macOS reports bytes.
        scale = 1 / 1024 if sys.platform == "darwin" else 1
        report["process_peak_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * scale
        report["process_peak_rss_before_kib"] = rss_before * scale
        report["source_unchanged"] = _sources()[0] == source_sha
        if not report["source_unchanged"]:
            report["errors"].append("SCAR source changed during measurement")

    report["limits"] = [
        "Offline conversion cost, not workload latency or an optimization speedup.",
        "RSS is the peak for this script process, including imports and validation.",
        "Valid records can retain incomplete observations or unresolved semantics.",
        "Snapshot identities do not prove logical equivalence across captures.",
        "Host and GPU clock domains are not aligned by this adapter.",
    ]
    if report["valid"] and not report["errors"]:
        report["status"] = "Verified"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"status": report["status"], "report": str(args.out.resolve()),
                      "raw_records": report.get("raw_records"),
                      "wall_seconds": report["normalization_wall_seconds"],
                      "peak_rss_kib": report["process_peak_rss_kib"]}))
    return 0 if report["status"] == "Verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
