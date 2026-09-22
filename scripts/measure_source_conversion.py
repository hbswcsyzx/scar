"""Measure nonexecuting SG construction without serializing the full graph."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scar.ir.frontend_v2 import build_semantic
from run_gate import fingerprint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    source_hash, _ = fingerprint()
    started = time.perf_counter()
    result = build_semantic(args.source, project_root=args.project_root)
    elapsed = time.perf_counter() - started
    coverage = {key: value for key, value in result.coverage.items()
                if key not in ("owners", "diagnostics")}
    coverage["diagnostic_counts"] = {}
    for diagnostic in result.coverage["diagnostics"]:
        kind = diagnostic.get("kind", "unspecified")
        coverage["diagnostic_counts"][kind] = coverage["diagnostic_counts"].get(kind, 0) + 1
    files = result.coverage["files"]
    # Record the exact source inputs; reading them does not execute the target.
    digests = {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in files}
    report = {
        "schema": "scar.source-conversion-pressure", "schema_version": 1,
        "revision": revision, "source_sha256": source_hash,
        "source_unchanged": source_hash == fingerprint()[0],
        "command": [sys.executable, *sys.argv],
        "source": str(args.source.resolve()),
        "project_root": str(args.project_root.resolve()) if args.project_root else None,
        "input_files": digests, "coverage": coverage,
        "wall_seconds": elapsed,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "scope": "Whole selected source tree, including unreachable files; no target execution, transformation or workload speedup measurement.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"out": str(args.out), "wall_seconds": elapsed,
                      "peak_rss_kib": report["peak_rss_kib"], "files": len(files)}))


if __name__ == "__main__":
    main()
