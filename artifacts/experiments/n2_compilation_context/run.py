"""Measure versioned source matching on retained calls, never execute target."""
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


def raw_files(trace):
    return {str(path): {"bytes": path.stat().st_size, "sha256": sha(path)}
            for path in sorted(trace.glob("call-*")) if path.is_file()}


def git_state(root):
    return {name: subprocess.check_output(["git", *command], cwd=root, text=True).strip()
            for name, command in (("head", ["rev-parse", "HEAD"]), ("status", ["status", "--porcelain"]))}


def main():
    parser = argparse.ArgumentParser()
    for name in ("scar-root", "project-root", "trace", "legacy-seeds", "out"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    for name in vars(args):
        setattr(args, name, getattr(args, name).resolve())
    args.out.mkdir(parents=True, exist_ok=False)
    fingerprint = runpy.run_path(str(args.scar_root / "scripts/run_gate.py"))["fingerprint"]
    before = fingerprint()
    raw_before, target_before = raw_files(args.trace), git_state(args.project_root)
    with gzip.open(args.legacy_seeds, "rt") as stream:
        legacy = json.load(stream)
    if legacy.get("schema_version") != 1 or "compilation_profile" in legacy:
        raise ValueError("comparison input must be the retained legacy v1 source-seed report")
    snapshot_before = {link["snapshot"]["path"]: sha(Path(link["snapshot"]["path"]))
        for link in legacy["model"]["code_links"] if link["snapshot"] is not None}
    environment = dict(os.environ, PYTHONPATH=str(args.scar_root), PYTHONDONTWRITEBYTECODE="1")
    for name in ("SCAR_TRACE_DIR", "SCAR_TRACE_CALL_EDGES", "SCAR_CALL_TRACE_OWNER_PID"):
        environment.pop(name, None)
    options = ["--max-call-trace-bytes", "256000000", "--max-call-trace-events", "250000",
               "--max-call-references", "2000000", "--max-call-report-bytes", "8000000"]
    report = args.out / "seeds.json.gz"
    phases = []
    for phase, arguments in (("generate", ["seed-calls", str(args.trace), "--project-root",
                                         str(args.project_root), "--out", str(report)]),
                             ("replay", ["check-call-seeds", str(report)])):
        command = [sys.executable, "-m", "scar.cli", *arguments, *options]
        timing = args.out / (phase + ".time")
        started = time.perf_counter()
        result = subprocess.run(["/usr/bin/time", "-v", "-o", str(timing), *command],
            cwd=args.scar_root, env=environment, capture_output=True, text=True)
        (args.out / (phase + ".stdout.json")).write_text(result.stdout)
        (args.out / (phase + ".stderr.log")).write_text(result.stderr)
        match = re.search(r"Maximum resident set size \(kbytes\): (\d+)", timing.read_text())
        phases.append({"phase": phase, "command": command, "returncode": result.returncode,
            "wall_s": time.perf_counter() - started, "peak_rss_kib": int(match[1]) if match else None})
        print(json.dumps(phases[-1]), flush=True)
        (args.out / "progress.json").write_text(json.dumps(phases, indent=2) + "\n")
        if result.returncode:
            break
    receipt = {"schema": "scar.compilation-context-experiment", "schema_version": 1,
        "source_fingerprint": before[0], "source_sha256": before[1], "phases": phases,
        "scar_sources_unchanged": before == fingerprint(), "raw_inputs_unchanged": raw_before == raw_files(args.trace),
        "target_git_before": target_before, "target_git_after": git_state(args.project_root),
        "matched_source_files_unchanged": snapshot_before == {path: sha(Path(path)) for path in snapshot_before},
        "target_executed": False, "whole_program_complete": False, "transformation_authorized": False,
        "measurement_scope": "Offline source correspondence; no target execution or A/B speedup.",
        "analysis_overlap": "Mapped/full regression may overlap; timings are not a clean analysis speedup benchmark."}
    passed = len(phases) == 2 and all(phase["returncode"] == 0 for phase in phases)
    if passed:
        with gzip.open(report, "rt") as stream:
            current = json.load(stream)
        old_links = {link["code"]: link for link in legacy["model"]["code_links"]}
        new_links = {link["code"]: link for link in current["model"]["code_links"]}
        mismatched = {key for key, link in old_links.items() if link["status"] == "MISMATCH"}
        changed = {key for key in old_links if old_links[key] != new_links.get(key)}
        retained = {key: value for key, value in legacy["model"].items() if key != "code_links"}
        rebuilt = {key: value for key, value in current["model"].items() if key != "code_links"}
        receipt.update(summary=current["summary"], profile=current.get("compilation_profile"),
            old_mismatches=len(mismatched), changed_links=len(changed),
            code_link_keys_unchanged=old_links.keys() == new_links.keys(),
            changed_exactly_old_mismatches=changed == mismatched,
            all_old_mismatches_now_verified=all(new_links[key]["status"] == "VERIFIED" for key in mismatched),
            other_model_fields_unchanged=retained == rebuilt,
            changed_code_links=[{"before": old_links[key], "after": new_links[key]} for key in sorted(changed)],
            report_compressed_bytes=report.stat().st_size, report_sha256=sha(report))
        passed = (current["schema_version"] == 2 and changed == mismatched
                  and receipt["code_link_keys_unchanged"]
                  and receipt["all_old_mismatches_now_verified"] and retained == rebuilt)
    passed = (passed and receipt["scar_sources_unchanged"] and receipt["raw_inputs_unchanged"]
              and receipt["matched_source_files_unchanged"] and target_before == receipt["target_git_after"])
    receipt["status"] = "REPLAYED" if passed else "FAIL"
    (args.out / "result.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({key: value for key, value in receipt.items()
                     if key not in ("source_sha256", "changed_code_links")}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
