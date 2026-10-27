"""Finalize saved small gate artifacts; never rescan R1 or rerun its checks."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import resource as process_usage
import time

BASE = Path(__file__).resolve().parent
START = time.monotonic()


def load(name):
    return json.loads((BASE / name).read_bytes())


def receipt(path):
    raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


document = load("result/manifest.json")
proofs, boundaries, producer = load("selector-proofs.json"), load("codec-boundaries.json"), load("producer.json")
assert receipt(BASE / "run.py")["sha256"] == producer["script"]["sha256"]
progress = [json.loads(line) for line in (BASE / "progress.jsonl").read_text().splitlines()]
assert progress[-1]["event"] == "FAILED" and progress[-1]["error_type"] == "AttributeError"
assert progress[-1]["detail"] == "'dict' object has no attribute 'getrusage'"
checks = [row for row in progress if row["event"] == "ENDPOINTS_PASS"]
assert len(checks) == 1 and (checks[0]["ports"], checks[0]["producer_work"], checks[0]["executors"], checks[0]["pipe_pairs"]) == (35, 22, 3, 13)
assert document["counts"] == {"created_ports": 35, "handle_refinements": 35, "executor_refinements": 3,
    "provider_accesses": 38, "observations_scanned": 1067768}
assert len(proofs) == len(document["handle_refinements"]) == 35
assert len(boundaries) == 6 and all(row["rejected"] is True for row in boundaries)
by_binding = {row["binding"]["wire"]: row for row in proofs}
lifetimes, targets = set(), set()
for entry in document["handle_refinements"]:
    row = entry["replacement"]; proof = by_binding[row["id"]["wire"]]
    assert row["id"] == entry["preimage"]["id"] == proof["binding"]
    assert row["target"] == proof["original_target"] and proof["other_fields_unchanged"] is True
    assert row["handle"]["lifetime"] == proof["new_lifetime"]
    assert row["handle"]["selector"] == proof["selector"]
    assert len(proof["row_sha256"]) == 64
    lifetimes.add(row["handle"]["lifetime"]["wire"]); targets.add(row["target"]["instance"]["wire"])
assert len(lifetimes) == len(targets) == 35
outputs, executors, pairs = [], [], defaultdict(list)
for access in document["provider_accesses"]:
    if access["purpose"] == "OUTPUT_SELECTOR":
        outputs.append(access); pairs[access["work"]["wire"]].append(access)
    else:
        assert access["purpose"] == "EXECUTOR"; executors.append(access)
assert len(outputs) == 35 and len(pairs) == 22 and len(executors) == 3
assert sum(len(rows) == 2 for rows in pairs.values()) == 13
for rows in pairs.values():
    if len(rows) == 2:
        assert rows[0]["target"] != rows[1]["target"]
assert len(document["executor_refinements"]) == 3
timing = (BASE / "run.time.txt").read_text()
assert re.search(r"Exit status: 1\b", timing)
summary = {"status": "VERIFIED_SCOPE_WITH_ORIGINAL_GATE_REPORTING_FAILURE",
    "gate_process_exit": 1, "gate_reporting_defect": "local negative-wire variable shadowed resource module in metrics footer",
    "original_gate_script_preserved": True, "gate_or_importer_rerun": False,
    "scope_checks_completed": {"ports": 35, "producer_work": 22, "executors": 3, "pipe_pairs": 13,
        "provider_accesses": 38, "original_target_and_other_fields_preserved": True,
        "all_selected_preimages_chunk_line_ordinal_checks_completed": True},
    "codec_checks_completed_by_original_script": {"ProviderHandle": 35, "ProviderRecordSelector": 73,
        "ProviderResourceAccess": 38, "old_capability_rejections": 6,
        "scope": "existing finite records/negative wire gates, not full ExecutionModel validation"},
    "base_manifest": producer["base"], "refinement": receipt(BASE / "result/manifest.json"),
    "selector_proofs": receipt(BASE / "selector-proofs.json"), "codec_boundaries": receipt(BASE / "codec-boundaries.json"),
    "gate_wall_clock": re.search(r"Elapsed \(wall clock\).*?: (.+)", timing)[1],
    "gate_peak_rss_kib": int(re.search(r"Maximum resident set size \(kbytes\): (\d+)", timing)[1]),
    "finalizer": receipt(Path(__file__)), "finalizer_elapsed_seconds": time.monotonic() - START,
    "finalizer_peak_rss_kib": process_usage.getrusage(process_usage.RUSAGE_SELF).ru_maxrss,
    "unresolved_table_containers": 35, "full_execution_model_validation": "OPEN_NOT_PERFORMED",
    "fake_program_snapshot_created": False, "target_or_gpu_executed": False,
    "whole_model_established": False, "first_stage_complete": False, "transformation_authorized": False}
with (BASE / "finalized-summary.json").open("x") as stream:
    stream.write(json.dumps(summary, sort_keys=True, indent=2) + "\n")
print(json.dumps(summary, sort_keys=True), flush=True)
