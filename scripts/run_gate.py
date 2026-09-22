"""Execute gate criteria from a manifest and write evidence for each test case.

Usage: conda run -n lewm python scripts/run_gate.py gates/g1.json
Reports bind both the Git revision and the tested source hashes. A missing or
skipped test fails its criterion; one successful suite cannot fill every row.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def fingerprint():
    paths = [*ROOT.joinpath("scar").rglob("*.py"),
             *ROOT.joinpath("tests").rglob("*.py"),
             *ROOT.joinpath("scripts").rglob("*.py"),
             *ROOT.joinpath("gates").glob("*.json"), ROOT / "pyproject.toml"]
    digests = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
               for path in sorted(paths)}
    combined = hashlib.sha256(json.dumps(digests, sort_keys=True).encode()).hexdigest()
    return combined, digests


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    criteria = manifest["criteria"]
    nodes = sorted({node for row in criteria for node in row["tests"]})
    code_hash, hashes = fingerprint()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="scar-gate-") as temp:
        junit = Path(temp) / "results.xml"
        command = [sys.executable, "-m", "pytest", "-q", *nodes, f"--junitxml={junit}"]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        cases = []
        if junit.exists():
            for case in ET.parse(junit).iter("testcase"):
                cases.append({"class": case.get("classname", ""), "name": case.get("name", ""),
                              "status": "FAIL" if any(case.find(tag) is not None
                                                       for tag in ("failure", "error", "skipped")) else "PASS"})
    rows = []
    for row in criteria:
        evidence = []
        for node in row["tests"]:
            file, _, test = node.partition("::")
            classname = file.removesuffix(".py").replace("/", ".")
            matched = [case for case in cases if case["class"] == classname
                       and (not test or case["name"] == test or case["name"].startswith(test + "["))]
            evidence.append({"node": node, "cases": matched,
                             "status": "PASS" if matched and all(case["status"] == "PASS"
                                                                  for case in matched) else "FAIL"})
        rows.append({**row, "evidence": evidence,
                     "status": "PASS" if evidence and all(item["status"] == "PASS"
                                                           for item in evidence) else "FAIL"})
    unchanged = fingerprint()[0] == code_hash
    passed = result.returncode == 0 and unchanged and all(row["status"] == "PASS" for row in rows)
    report = {"schema": "scar.gate-report", "schema_version": 2,
              "gate": manifest["gate"], "status": "PASS" if passed else "FAIL",
              "revision": revision, "worktree_status": dirty, "source_sha256": code_hash,
              "tested_files": hashes, "source_unchanged_during_test": unchanged,
              "scope": manifest["scope"], "limitations": manifest.get("limitations", []),
              "criteria": rows, "command": command[:-1], "returncode": result.returncode,
              "duration_seconds": round(time.monotonic() - started, 3),
              "stdout": result.stdout, "stderr": result.stderr, "python": sys.version}
    out = args.out or ROOT / "artifacts/reports/gates" / f"{manifest['gate'].lower()}-verified.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    out.with_suffix(".md").write_text(
        f"# {manifest['gate']} independent criteria report\n\n"
        f"Status: **{report['status']}**\n\nRevision: `{revision}`\n\n"
        f"Source digest: `{code_hash}`\n\n"
        "| Criterion | Status |\n| --- | --- |\n" +
        "".join(f"| {row['id']} | {row['status']} |\n" for row in rows) +
        "\nScope: " + manifest["scope"] + "\n\n" +
        "\n".join("- " + text for text in manifest.get("limitations", [])) + "\n")
    print(json.dumps({"gate": manifest["gate"], "status": report["status"],
                      "report": str(out), "tests": len(cases)}))
    if not passed:
        print(result.stdout)
        print(result.stderr)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
