"""Offline inventory generation/replay; does not execute the target program."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import time


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def manifest(paths):
    return {str(path): {"bytes": path.stat().st_size, "sha256": sha(path)}
            for path in sorted(paths) if path.is_file()}


def git_state(root):
    return {name: subprocess.check_output(["git", *command], cwd=root, text=True).strip()
            for name, command in (("head", ["rev-parse", "HEAD"]),
                                  ("status", ["status", "--porcelain"]))}


def main():
    parser = argparse.ArgumentParser()
    for name in ("scar-root", "project-root", "entry", "trace", "expected-seeds", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    for name in vars(args):
        setattr(args, name, getattr(args, name).resolve())
    args.out.mkdir(parents=True, exist_ok=False)
    fingerprint = runpy.run_path(str(args.scar_root / "scripts/run_gate.py"))["fingerprint"]
    before = fingerprint()
    raw_before = manifest(args.trace.glob("call-*"))
    target_before = git_state(args.project_root)
    tracked = subprocess.check_output(["git", "ls-files", "-z", "--", "*.py"],
                                     cwd=args.project_root).decode().split("\0")
    source_before = manifest(args.project_root / name for name in tracked if name)
    environment = dict(os.environ, PYTHONPATH=str(args.scar_root), PYTHONDONTWRITEBYTECODE="1")
    for name in ("SCAR_TRACE_DIR", "SCAR_TRACE_CALL_EDGES", "SCAR_CALL_TRACE_OWNER_PID"):
        environment.pop(name, None)
    options = ["--max-files", "256", "--max-lowered-bodies", "256", "--max-operations", "10000",
               "--max-call-trace-bytes", "256000000", "--max-call-trace-events", "250000",
               "--max-call-references", "2000000"]
    report = args.out / "inventory.json.gz"
    phases = []
    for phase, arguments in (("generate", ["inventory-program", str(args.entry),
            "--project-root", str(args.project_root), "--calls", str(args.trace), "--out", str(report)]),
            ("replay", ["check-inventory", str(report)])):
        command = [sys.executable, "-m", "scar.cli", *arguments, *options]
        timing = args.out / (phase + ".time")
        started = time.perf_counter()
        completed = subprocess.run(["/usr/bin/time", "-v", "-o", str(timing), *command],
            cwd=args.scar_root, env=environment, capture_output=True, text=True)
        (args.out / (phase + ".stdout.json")).write_text(completed.stdout)
        (args.out / (phase + ".stderr.log")).write_text(completed.stderr)
        rss = re.search(r"Maximum resident set size \(kbytes\): (\d+)", timing.read_text())
        phases.append({"phase": phase, "command": command, "returncode": completed.returncode,
            "wall_s": time.perf_counter() - started, "peak_rss_kib": int(rss[1]) if rss else None})
        (args.out / "progress.json").write_text(json.dumps(phases, indent=2) + "\n")
        print(json.dumps(phases[-1]), flush=True)
        if completed.returncode:
            break
    result = {"schema": "scar.call-demand-experiment", "schema_version": 1,
        "phases": phases, "source_fingerprint": before[0], "source_sha256": before[1],
        "scar_sources_unchanged": fingerprint() == before,
        "raw_inputs_unchanged": manifest(args.trace.glob("call-*")) == raw_before,
        "target_git_before": target_before, "target_git_after": git_state(args.project_root),
        "target_sources_unchanged": manifest(args.project_root / name for name in tracked if name) == source_before,
        "target_executed": False, "whole_program_complete": False,
        "actual_formal_provenance_established": False, "transformation_authorized": False,
        "measurement_scope": "Offline source/trace analysis; not LeWM wall-clock speedup or clean A/B benchmark.",
        "analysis_overlap": "Mapped gate/full regression may overlap; do not interpret timings as a speedup benchmark."}
    passed = len(phases) == 2 and all(phase["returncode"] == 0 for phase in phases)
    if passed:
        with gzip.open(report, "rt") as stream:
            document = json.load(stream)
        with gzip.open(args.expected_seeds, "rt") as stream:
            expected = json.load(stream)
        result.update(summary=document["summary"],
            exact_frozen_d0_seed_report=document["call_sources"] == expected,
            report_bytes=report.stat().st_size, report_sha256=sha(report))
        passed = result["exact_frozen_d0_seed_report"]
    passed = (passed and result["scar_sources_unchanged"] and result["raw_inputs_unchanged"]
              and result["target_sources_unchanged"] and result["target_git_before"] == result["target_git_after"])
    result["status"] = "REPLAYED" if passed else "FAIL"
    (args.out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "source_sha256"}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
