"""Measure read-only source/runtime/effect inspection with reproducible inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import sys
import time
import tokenize

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scar.analysis.inspection_v2 import inspect_program
from run_gate import fingerprint


def file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--runtime-sources", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    source_hash, hashes = fingerprint()
    trace = args.trace / "events.jsonl" if args.trace.is_dir() else args.trace
    trace_hash = file_digest(trace)
    started = time.perf_counter()
    report = inspect_program(args.source, args.trace, project_root=args.project_root,
                             runtime_sources=args.runtime_sources)
    elapsed = time.perf_counter() - started
    observed_source_hashes = {}
    for path in report["source_text_fingerprints"]:
        with tokenize.open(path) as handle:
            observed_source_hashes[path] = "sha256:" + hashlib.sha256(handle.read().encode()).hexdigest()
    target_unchanged = observed_source_hashes == report["source_text_fingerprints"]
    unchanged = fingerprint()[0] == source_hash and trace_hash == file_digest(trace) and target_unchanged
    measurement = {
        "schema": "scar.inspection.pressure", "schema_version": 1,
        "status": "Verified" if unchanged else "Rejected",
        "revision": revision, "source_sha256": source_hash, "tested_files": hashes,
        "command": [sys.executable, *sys.argv], "source_and_trace_unchanged": unchanged,
        "trace_sha256": trace_hash,
        "target_source_unchanged": target_unchanged,
        "source_text_fingerprints": report["source_text_fingerprints"],
        "source_files_sha256": {path: file_digest(path) for path in report["source_coverage"]["files"]},
        "wall_seconds": elapsed, "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "source_coverage": report["source_coverage"], "trace_counts": report["trace_coverage"]["status_counts"],
        "correspondence_counts": report["correspondence"]["status_counts"],
        "runtime_effects": report["runtime_effects"], "summary": report["summary"],
        "scope": "Offline G5 analysis only. No target execution, optimization or workload speedup measurement.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
    pressure = args.out.with_name(args.out.stem + ".pressure.json")
    pressure.write_text(json.dumps(measurement, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"status": measurement["status"], "report": str(args.out),
                      "pressure": str(pressure), "wall_seconds": elapsed,
                      "peak_rss_kib": measurement["peak_rss_kib"],
                      "correspondence_counts": measurement["correspondence_counts"],
                      "decisions": report["summary"]["dispositions"]}))
    return 0 if unchanged else 1


if __name__ == "__main__":
    raise SystemExit(main())
