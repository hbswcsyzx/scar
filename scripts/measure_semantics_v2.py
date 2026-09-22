"""Measure explicitly selected source files; never import or execute a target."""
import argparse
from collections import Counter
import gzip
import hashlib
import io
import json
from pathlib import Path
import resource
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scar.analysis.semantics_report_v2 import report_semantics
from run_gate import fingerprint


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.suffix != ".gz":
        parser.error("--out must end in .gz")
    paths = sorted({path.resolve() for path in args.source})
    before = {str(path): digest(path) for path in paths}
    code_hash, tested_files = fingerprint()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    started = time.perf_counter()
    reports = [report_semantics(path) for path in paths]
    seconds = time.perf_counter() - started
    summaries = [{"source": str(path), **report["summary"]} for path, report in zip(paths, reports)]
    statuses = Counter()
    for row in summaries:
        statuses.update(row["constant_statuses"])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as compressed:
        with io.TextIOWrapper(compressed, encoding="utf-8") as text:
            json.dump({"schema": "scar.selected-source-pressure", "schema_version": 1,
                       "reports": reports}, text, sort_keys=True, ensure_ascii=True, allow_nan=False)
            text.write("\n")
    unchanged = before == {str(path): digest(path) for path in paths} and code_hash == fingerprint()[0]
    measurement = {
        "schema": "scar.semantics.pressure", "schema_version": 1,
        "status": "Verified" if unchanged else "Rejected", "revision": revision,
        "command": [sys.executable, *sys.argv], "source_sha256": code_hash, "tested_files": tested_files,
        "input_sha256": before, "source_and_inputs_unchanged": unchanged,
        "analysis_seconds": seconds, "analysis_and_write_seconds": time.perf_counter() - started,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "compressed_bytes": args.out.stat().st_size, "report_sha256": digest(args.out),
        "selection": "Explicit files analyzed independently; no reachability, import closure or whole-project claim.",
        "files": summaries, "constant_statuses": dict(sorted(statuses.items())),
        "selected_transformations": 0,
        "scope": "Offline SCAR analysis with conditional type/content facts; not a target run, rewrite or speedup."
    }
    pressure = args.out.with_suffix("").with_suffix(".pressure.json")
    pressure.write_text(json.dumps(measurement, sort_keys=True, indent=2) + "\n")
    print(json.dumps({key: measurement[key] for key in ("status", "analysis_seconds", "peak_rss_kib", "constant_statuses")}))
    return 0 if unchanged else 1


if __name__ == "__main__":
    raise SystemExit(main())
