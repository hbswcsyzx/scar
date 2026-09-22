"""Record bounded G6 region construction costs and exact input/code revisions."""
import argparse
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
from scar.analysis.region_report_v2 import report_regions
from run_gate import fingerprint


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--root-limit", type=int, default=8)
    parser.add_argument("--max-depth", type=int, default=0)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.suffix != ".gz":
        parser.error("--out must end in .gz to bound report storage")
    trace = args.trace / "events.jsonl" if args.trace.is_dir() else args.trace
    input_hash = digest(trace)
    code_hash, files = fingerprint()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    started = time.perf_counter()
    document = report_regions(args.trace, view="execution", root_limit=args.root_limit,
                              max_depth=args.max_depth)
    analysis_seconds = time.perf_counter() - started
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("wb") as destination, gzip.GzipFile(
            fileobj=destination, mode="wb", mtime=0, filename="") as compressed:
        with io.TextIOWrapper(compressed, encoding="utf-8") as text:
            json.dump(document, text, sort_keys=True, ensure_ascii=False, allow_nan=False)
            text.write("\n")
    unchanged = digest(trace) == input_hash and fingerprint()[0] == code_hash
    measurement = {
        "schema": "scar.regions.pressure", "schema_version": 1,
        "status": "Verified" if unchanged else "Rejected", "revision": revision,
        "source_sha256": code_hash, "tested_files": files, "trace_sha256": input_hash,
        "source_and_trace_unchanged": unchanged, "command": [sys.executable, *sys.argv],
        "analysis_seconds": analysis_seconds, "analysis_and_write_seconds": time.perf_counter() - started,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "compressed_bytes": args.out.stat().st_size, "report_sha256": digest(args.out),
        "selection": document["selection"], "summary": document["summary"],
        "input_records": document["input_coverage"]["raw_records"],
        "scope": "Bounded projection of archived execution; no target run, transformation or speedup measurement.",
    }
    pressure = args.out.with_suffix("").with_suffix(".pressure.json")
    pressure.write_text(json.dumps(measurement, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"status": measurement["status"], "report": str(args.out),
                      "pressure": str(pressure), "analysis_seconds": analysis_seconds,
                      "peak_rss_kib": measurement["peak_rss_kib"], "summary": document["summary"]}))
    return 0 if unchanged else 1


if __name__ == "__main__":
    raise SystemExit(main())
