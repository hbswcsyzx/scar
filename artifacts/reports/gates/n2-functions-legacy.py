"""Build v1/v2/v3 reports with real archived packages and replay current CLI.

The trace is synthetic compatibility input, not a profiling observation.  The
fixture is parsed/compiled by the tools and must never be executed.  Source
hashes are sampled for provenance; this runner does not assert frozen gate
acceptance while other work can modify the current package.
"""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import time


REVISIONS = ((1, "f21eb53"), (2, "b886e40"), (3, "994f944"))
FIXTURE = """def caller(value):
    return helper(value)
def helper(value):
    return value
def defaults(value=[]):
    return value
raise AssertionError('compatibility fixture must never execute')
"""
PROBE = """import json, sys
from pathlib import Path
import scar
from scar.ir.ids import CodeID
print(json.dumps({
    'package_file': str(Path(scar.__file__).resolve()),
    'code_id': CodeID(sys.argv[1], 'caller', 1, None, 'unknown').key(),
}))
"""


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_stage(name, command, *, cwd, environment, stages):
    started = time.perf_counter()
    run = subprocess.run(command, cwd=cwd, env=environment, capture_output=True, text=True)
    stages.append({
        "name": name, "command": command, "cwd": str(cwd),
        "returncode": run.returncode, "seconds": time.perf_counter() - started,
        "stdout": run.stdout[-6000:], "stderr": run.stderr[-6000:],
        "stdout_characters": len(run.stdout), "stderr_characters": len(run.stderr),
    })
    require(run.returncode == 0, name + " exited with " + str(run.returncode))
    return run


def check_legacy_document(document, version):
    require(document.get("schema") == "scar.program-inventory", "historical schema differs")
    require(document.get("schema_version") == version, "historical package emitted the wrong version")
    require("interfaces" not in document, "historical report unexpectedly contains new interfaces")
    require(("runtime_scope" in document) == (version >= 2), "legacy runtime overlay differs")
    require(("expansion" in document) == (version >= 3), "legacy scheduling overlay differs")
    require(document.get("target_executed") is False, "historical report claims target execution")
    require(document.get("transformation_authorized") is False, "historical authority differs")
    definitions = {definition["id"]["wire"]: definition for file in document["files"]
                   for definition in file["definitions"]}
    bodies = {definitions[body["definition"]["wire"]]["name"]: body
              for file in document["files"] for body in file["bodies"]}
    require(set(bodies) == {"caller", "helper", "defaults"}, "fixture definitions were lost")
    default_body = bodies["defaults"]
    require(default_body["status"] == "UNSUPPORTED" and default_body["graph"] is None,
            "legacy default signature was upgraded")
    require(default_body["metadata"] is not None and any(
        gap["kind"] == "UNSUPPORTED_SIGNATURE" for gap in default_body["metadata"]["gaps"]),
        "legacy default boundary lost its signature gap")
    caller_regions = len(bodies["caller"]["graph"]["regions"])
    helper_regions = len(bodies["helper"]["graph"]["regions"])
    require(caller_regions == (1 if version == 3 else 2), "legacy caller expansion rule differs")
    require(helper_regions == 1, "helper body is not a single region")
    require("function_interfaces" not in document["summary"], "historical summary gained new bindings")
    return {
        "schema_version": version, "default_body_status": default_body["status"],
        "default_signature_gap_preserved": True,
        "caller_regions": caller_regions, "helper_regions": helper_regions,
        "new_interfaces_absent": True,
    }


def main():
    root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path,
                        default=root / "artifacts/reports/gates/n2-functions-legacy")
    parser.add_argument("--require-stable-source", action="store_true",
                        help="fail if sampled current source hashes differ during this run")
    args = parser.parse_args()
    prefix = args.prefix.resolve()
    prefix.parent.mkdir(parents=True, exist_ok=True)
    inputs = Path(str(prefix) + "-input")
    inputs.mkdir(exist_ok=True)
    entry = inputs / "entry.py"
    entry.write_text(FIXTURE, encoding="utf-8")

    sys.path.insert(0, str(root))
    from scripts.run_gate import fingerprint
    source_before = fingerprint()[0]
    current_environment = dict(os.environ, PYTHONPATH=str(root))
    receipt = {
        "schema": "scar.historical-function-interface-compatibility", "schema_version": 1,
        "current_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "current_source_sha256_before": source_before,
        "fixture": {"path": str(entry), "sha256": sha256(entry), "target_executed": False,
                    "module_execution_sentinel": "raises AssertionError if executed"},
        "trace_evidence": "synthetic compatibility input; no real profiling observation",
        "historical_packages": [], "target_executed": False,
        "frozen_acceptance": False,
        "scope": "historical public CLI generation and current public CLI strict replay only",
    }
    for version, short_revision in REVISIONS:
        row = {"expected_schema_version": version, "requested_revision": short_revision, "stages": []}
        receipt["historical_packages"].append(row)
        try:
            revision = subprocess.check_output(
                ["git", "rev-parse", short_revision], cwd=root, text=True).strip()
            archive = subprocess.check_output(
                ["git", "archive", revision, "scar", "pyproject.toml"], cwd=root)
            row.update({"historical_revision": revision,
                        "archive_sha256": hashlib.sha256(archive).hexdigest(),
                        "archived_paths": ["scar", "pyproject.toml"]})
            output = Path(str(prefix) + "-v" + str(version) + ".json.gz")
            output.unlink(missing_ok=True)
            with tempfile.TemporaryDirectory(prefix="scar-functions-legacy-v" + str(version) + "-") as folder:
                archive_root = Path(folder)
                with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
                    stream.extractall(archive_root, filter="data")
                historical_environment = dict(os.environ, PYTHONPATH=str(archive_root))
                probe_run = run_stage(
                    "historical_package_probe", [sys.executable, "-c", PROBE, str(entry)],
                    cwd=archive_root, environment=historical_environment, stages=row["stages"],
                )
                probe = json.loads(probe_run.stdout)
                require(Path(probe["package_file"]).is_relative_to(archive_root),
                        "historical command imported outside the Git archive")
                row["package_file"] = probe["package_file"]
                command = [sys.executable, "-m", "scar.cli", "inventory-program", str(entry),
                           "--project-root", str(inputs), "--max-lowered-bodies", "3",
                           "--out", str(output)]
                if version >= 2:
                    trace = inputs / ("events-v" + str(version) + ".jsonl")
                    trace.write_text(json.dumps({
                        "kind": "python_call", "index": 1, "invocation_id": 1,
                        "code_id": probe["code_id"], "metadata": {"process_id": 1},
                    }) + "\n", encoding="utf-8")
                    command.extend(["--trace", str(trace)])
                    row["synthetic_trace"] = {"path": str(trace), "sha256": sha256(trace)}
                run_stage("historical_public_cli_build", command, cwd=archive_root,
                          environment=historical_environment, stages=row["stages"])
            with gzip.open(output, "rt", encoding="utf-8") as stream:
                document = json.load(stream)
            row["legacy_checks"] = check_legacy_document(document, version)
            row["report"] = {"path": str(output), "sha256": sha256(output),
                             "bytes": output.stat().st_size}
            replay = run_stage(
                "current_public_cli_strict_replay",
                [sys.executable, "-m", "scar.cli", "check-inventory", str(output)],
                cwd=root, environment=current_environment, stages=row["stages"],
            )
            replay_document = json.loads(replay.stdout)
            require(replay_document.get("status") == "REPLAYED", "current CLI did not confirm replay")
            require("function_interfaces" not in replay_document["summary"],
                    "current replay retroactively added function bindings")
            require(sha256(output) == row["report"]["sha256"], "current replay changed the historical report")
            row["status"] = "PASS"
        except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
            row["status"] = "FAIL"
            row["error"] = type(error).__name__ + ": " + str(error)

    source_after = fingerprint()[0]
    receipt["current_source_sha256_after"] = source_after
    receipt["current_source_unchanged_between_samples"] = source_before == source_after
    receipt["require_stable_source"] = args.require_stable_source
    passed = all(row["status"] == "PASS" for row in receipt["historical_packages"])
    if args.require_stable_source and source_before != source_after:
        passed = False
    receipt["status"] = "PASS" if passed else "FAIL"
    receipt_path = Path(str(prefix) + "-receipt.json")
    receipt_path.write_text(json.dumps(receipt, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": receipt["status"], "receipt": str(receipt_path),
        "versions": {str(row["expected_schema_version"]): row["status"]
                     for row in receipt["historical_packages"]},
        "current_source_unchanged_between_samples": receipt["current_source_unchanged_between_samples"],
        "frozen_acceptance": False,
    }))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
