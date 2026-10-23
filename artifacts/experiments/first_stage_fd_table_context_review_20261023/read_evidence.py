"""Small, read-only follow-up evidence; no producer, target or model is changed."""
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import re
import time

from scar.trace.os_resource_refinement import OSResourceBase


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EXPERIMENTS = ROOT / "artifacts/experiments"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def main():
    started = time.monotonic()
    capture = EXPERIMENTS / "first_stage_lewm_physical_20261023"
    r1 = EXPERIMENTS / "first_stage_os_interface_work_20261023"
    r2 = EXPERIMENTS / "first_stage_os_resource_refinement_20261023/gate-attempt01"
    paths = {"archive": capture / "archive-index.json",
             "coordinates": r1 / "result/capture-coordinates.json",
             "summary": r1 / "result/summary.json",
             "r1_manifest": r1 / "result/interfaces/manifest.json",
             "r2_manifest": r2 / "result/manifest.json"}
    docs = {name: read(path) for name, path in paths.items()}
    files = [row for row in docs["archive"]["files"] if "/os/syscalls." in row["logical_path"]]
    selected = defaultdict(list)
    for row in docs["r2_manifest"]["handle_refinements"]:
        replacement = row["replacement"]
        source = replacement["source"]
        selected[source["artifact"]["uri"].rsplit("/", 1)[1]].append({
            "line": int(source["locator"].rsplit("/", 1)[1]),
            "observation_ordinal": replacement["handle"]["selector"]["ordinal"]})
    small = []
    for tid in (369747, 372874):
        receipt = next(row for row in files if row["logical_path"].endswith("/syscalls." + str(tid)))
        digest, decoded, lines, events = hashlib.sha256(), 0, 0, []
        with gzip.open(receipt["actual_path"], "rb") as stream:
            for raw in stream:
                lines += 1
                decoded += len(raw)
                digest.update(raw)
                match = re.match(rb"\S+\s+(execve|execveat|clone|clone3|fork|vfork|unshare|close_range)\(", raw)
                if match:
                    events.append({"line": lines, "syscall": match[1].decode(),
                                   "rendering": raw.decode().rstrip("\n")})
        assert digest.hexdigest() == receipt["raw_sha256"] and decoded == receipt["raw_bytes"]
        assert sha(Path(receipt["actual_path"])) == receipt["gzip_sha256"]
        small.append({"receipt": receipt, "decoded_bytes": decoded, "lines": lines,
                      "stored_and_raw_sha_verified": True, "identity_relevant_interfaces": events})
    base = OSResourceBase(paths["r1_manifest"], cached_chunks=1)
    selector = base.selector("observations", 867219)
    birth = base.resolve(selector)
    row = birth["record"]
    assert row["source"] == {"artifact": 1, "line": 863883}
    assert row["syscall"] == "clone" and row["result"] == 372874
    assert row["argument_rendering_complete"] and "CLONE_FILES" not in " ".join(row["arguments"])
    assert row["source"]["line"] == int(next(t for t in docs["coordinates"]["threads"] if t["tid"] == 372874)["source"]["locator"].rsplit("/", 1)[1])
    result = {"schema": "scar.fd-table-context-read-review", "schema_version": 1,
        "status": "READ_ONLY_EVIDENCE_REVIEW", "production_changed": False,
        "full_execution_model_semantics": "OPEN", "container_refinements_applied": 0,
        "inputs": {name: {"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size}
                   for name, path in paths.items()},
        "run": docs["coordinates"]["run"]["id"],
        "selector_groups": dict(selected), "small_raw": small,
        "child_birth_r1": {key: value for key, value in birth.items() if key != "value"},
        "child_birth_coordinate": next(t for t in docs["coordinates"]["threads"] if t["tid"] == 372874),
        "target_birth_coordinate": docs["coordinates"]["seed"]["target_birth"],
        "target_exec_coordinate": docs["coordinates"]["seed"]["target_exec"],
        "counts_from_prior_full_scope_r1": {name: docs["summary"]["interface_counts"].get(name, 0)
            for name in ("execve", "execveat", "unshare", "close_range", "clone", "clone3", "fork", "vfork")},
        "budget_for_proposed_non_target_projection": {"files": len(files) - 1,
            "decoded_bytes": sum(row["raw_bytes"] for row in files if not row["logical_path"].endswith(".369749")),
            "performed": False},
        "read_scope": {"small_raw_files": 2, "small_raw_decoded_bytes": sum(row["decoded_bytes"] for row in small),
            "published_r1_chunks": 1, "published_r1_chunk_decoded_bytes": birth["locator"]["artifact"]["decoded_bytes"],
            "main_raw_scanned": False, "all_observations_scanned": False},
        "elapsed_seconds": time.monotonic() - started,
        "script_sha256": sha(Path(__file__))}
    out = HERE / "evidence.json"
    with out.open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"status": result["status"], "evidence": str(out), "sha256": sha(out),
        "selected_ports": sum(map(len, selected.values())), "small_raw_bytes": result["read_scope"]["small_raw_decoded_bytes"],
        "r1_chunks": 1, "elapsed_seconds": result["elapsed_seconds"]}, sort_keys=True))


if __name__ == "__main__":
    main()
