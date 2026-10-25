"""Small synthetic cost receipt; not a real-archive benchmark."""
from dataclasses import replace
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import resource
import runpy
import tempfile
import time

from scar.analysis.modeling_scope import produce_scope_ledger

BASE = Path(__file__).resolve().parent

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(BASE / "small-cost-next.json"), help="fresh cost receipt, never overwrite prior measurements")
    args = parser.parse_args()
    output = Path(args.out)
    if output.exists():
        raise ValueError("cost receipt must be fresh")
    fixture_api = runpy.run_path(str(BASE / "check_small.py"))
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        catalog = fixture_api["fixture"](root)
        calls = root / "calls"
        report = json.loads((calls / "report.json").read_bytes())
        sample = json.loads(gzip.decompress((calls / "invocations.jsonl.gz").read_bytes()).splitlines()[0])
        rows = []
        for i in range(64):
            row = json.loads(json.dumps(sample))
            row["invocation"]["invocation_id"] = i + 1
            row["anchor"]["index"] = i
            rows.append(fixture_api["raw_json"](row))
        raw = b"".join(rows)
        (calls / "invocations.jsonl.gz").write_bytes(gzip.compress(raw, mtime=0))
        report["summary"]["invocations"] = 64
        report["invocations"].update(rows=64, raw_bytes=len(raw), raw_sha256=hashlib.sha256(raw).hexdigest())
        fixture_api["write_json"](calls / "report.json", report)
        catalog = replace(catalog, source_invocations=fixture_api["input_file"](calls / "report.json"))
        started = time.monotonic()
        result = produce_scope_ledger(catalog, str(root / "ledger"))
        elapsed = time.monotonic() - started
        record = {"scope": "synthetic retained metadata only; no original archives", "calls": 64,
            "source_definitions": 5, "wall_seconds": elapsed,
            "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "output": result["totals"], "aggregate": result["aggregate"],
            "producer": json.loads((root / "ledger/manifest.json").read_bytes())["producer"],
            "target_executions": 0, "raw_capture_reads": 0}
        with output.open("x") as stream:
            stream.write(json.dumps(record, indent=2, sort_keys=True) + "\n")
        print(json.dumps(record, sort_keys=True))

if __name__ == "__main__":
    main()
