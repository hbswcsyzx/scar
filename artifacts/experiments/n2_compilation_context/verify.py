"""Regenerate retained seed output from raw inputs through the public verifier.

The initial CLI generation is retained with its own source fingerprint. Reusing
that output avoids a redundant second generation: check-call-seeds recomputes
the complete report from raw/source before comparing the canonical document.
"""
import argparse
import gzip
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    for name in ("scar-root", "project-root", "trace", "legacy-seeds",
                 "generated-report", "initial-result", "out"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    for name in vars(args):
        setattr(args, name, getattr(args, name).resolve())
    args.out.mkdir(parents=True, exist_ok=False)
    helpers = runpy.run_path(str(Path(__file__).with_name("run.py")))
    sha, raw_files, git_state = (helpers[name] for name in ("sha", "raw_files", "git_state"))
    fingerprint = runpy.run_path(str(args.scar_root / "scripts/run_gate.py"))["fingerprint"]
    before = fingerprint()
    initial = json.loads(args.initial_result.read_text())
    assert initial["phases"][0]["phase"] == "generate"
    assert initial["phases"][0]["returncode"] == 0
    raw_before, target_before = raw_files(args.trace), git_state(args.project_root)
    assert raw_before
    report_before = sha(args.generated_report)
    with gzip.open(args.legacy_seeds, "rt") as stream:
        legacy = json.load(stream)
    with gzip.open(args.generated_report, "rt") as stream:
        current = json.load(stream)
    assert legacy["schema_version"] == 1 and "compilation_profile" not in legacy
    assert Path(current["model"]["trace_directory"]) == args.trace
    assert Path(current["model"]["project_root"]) == args.project_root
    source_before = {link["snapshot"]["path"]: sha(Path(link["snapshot"]["path"]))
                     for link in current["model"]["code_links"] if link["snapshot"] is not None}
    environment = dict(os.environ, PYTHONPATH=str(args.scar_root), PYTHONDONTWRITEBYTECODE="1")
    for name in ("SCAR_TRACE_DIR", "SCAR_TRACE_CALL_EDGES", "SCAR_CALL_TRACE_OWNER_PID"):
        environment.pop(name, None)
    command = [sys.executable, "-m", "scar.cli", "check-call-seeds", str(args.generated_report),
               "--max-call-trace-bytes", "256000000", "--max-call-trace-events", "250000",
               "--max-call-references", "2000000", "--max-call-report-bytes", "8000000"]
    timing = args.out / "replay.time"
    started = time.perf_counter()
    result = subprocess.run(["/usr/bin/time", "-v", "-o", str(timing), *command],
                            cwd=args.scar_root, env=environment, capture_output=True, text=True)
    (args.out / "replay.stdout.json").write_text(result.stdout)
    (args.out / "replay.stderr.log").write_text(result.stderr)
    match = re.search(r"Maximum resident set size \(kbytes\): (\d+)", timing.read_text())
    old_links = {link["code"]: link for link in legacy["model"]["code_links"]}
    new_links = {link["code"]: link for link in current["model"]["code_links"]}
    mismatched = {key for key, link in old_links.items() if link["status"] == "MISMATCH"}
    changed = {key for key in old_links if old_links[key] != new_links.get(key)}
    checks = {
        "public_independent_regeneration_passed": result.returncode == 0,
        "scar_sources_unchanged": before == fingerprint(),
        "raw_inputs_unchanged": raw_before == raw_files(args.trace),
        "target_git_unchanged": target_before == git_state(args.project_root),
        "matched_sources_unchanged": source_before == {path: sha(Path(path)) for path in source_before},
        "generated_report_unchanged": report_before == sha(args.generated_report),
        "code_link_keys_unchanged": old_links.keys() == new_links.keys(),
        "changed_exactly_old_mismatches": changed == mismatched,
        "all_old_mismatches_now_verified": all(new_links.get(key, {}).get("status") == "VERIFIED" for key in mismatched),
        "other_model_fields_unchanged": ({key: value for key, value in legacy["model"].items() if key != "code_links"}
                                        == {key: value for key, value in current["model"].items() if key != "code_links"}),
        "expected_versioned_policy": (current["schema_version"] == 2
                                      and current.get("compilation_profile") == "RECORDED_FUTURE_FLAGS_V1"),
    }
    receipt = {
        "schema": "scar.compilation-context-final-verification", "schema_version": 1,
        "source_fingerprint": before[0], "source_sha256": before[1],
        "command": command, "returncode": result.returncode,
        "wall_s": time.perf_counter() - started,
        "peak_rss_kib": int(match[1]) if match else None,
        "initial_generation_source_fingerprint": initial["source_fingerprint"],
        "initial_result_sha256": sha(args.initial_result),
        "report_compressed_bytes": args.generated_report.stat().st_size,
        "report_sha256": report_before, "summary": current["summary"],
        "old_mismatches": len(mismatched), "changed_links": len(changed), "checks": checks,
        "target_git_before": target_before, "target_git_after": git_state(args.project_root),
        "raw_inputs": raw_before, "matched_source_sha256": source_before,
        "changed_code_links": [{"before": old_links[key], "after": new_links[key]} for key in sorted(changed)],
        "target_executed": False, "whole_program_complete": False, "transformation_authorized": False,
        "measurement_scope": "Offline full regeneration by public verifier from original raw/source. No target execution or speedup.",
        "analysis_overlap": "May overlap regression; not a clean analysis speedup benchmark.",
        "status": "VERIFIED_R1_ONLY" if all(checks.values()) else "FAIL",
    }
    (args.out / "result.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({key: value for key, value in receipt.items() if key not in
                     ("source_sha256", "command", "changed_code_links", "raw_inputs", "matched_source_sha256")}))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
