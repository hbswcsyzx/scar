"""Freeze only source/control bytes; bulk digests come from original receipts.

This preparation does not decode or hash any GPU/raw/EEG bulk input.  The real
normal readers verify all declared bulk SHA/bytes during the sole Root-run gate.
"""
from hashlib import sha256
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
TREE = HERE.parents[3]
MAIN = Path("/home/zyf/AAA/scar-worktrees/structured-program-model")
CAP = MAIN / "artifacts/experiments/first_stage_lewm_physical_20261023"
PART = MAIN / "artifacts/experiments/first_stage_joined_physical_20261023/result/native/bundle-partitions"
COORD = MAIN / "artifacts/experiments/first_stage_native_protocol_bridge_attempt03_20261023/native-coordinates.json"
ANALYSIS = TREE / "artifacts/analysis/resource_completion_bridge_20261025"


def receipt(path):
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": sha256(data).hexdigest()}


def write(name, value):
    with (HERE / name).open("xb") as stream:
        stream.write(json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2).encode() + b"\n")


coords = json.loads(COORD.read_bytes())
archive = json.loads((CAP / "archive-index.json").read_bytes())
manifest = json.loads((PART / "manifest.json").read_bytes())
table = manifest["graphs"]["evidence"]["tables"]["instances"]
chunks = table["chunks"]
plain_metadata = sorted(path for path in (CAP / "trace").iterdir()
                        if path.is_file() and path.suffix == ".json")
if any(path.stat().st_size > 2_000_000 for path in plain_metadata):
    raise ValueError("capture control metadata is not small")
controls = [CAP / "archive-index.json", PART / "manifest.json", COORD,
            ANALYSIS / "primary-receipts.json", ANALYSIS / "COMPLETION_CONTRACT.md", *plain_metadata]
sources = [receipt(path) for path in sorted((TREE / "scar").rglob("*.py"))]
runners = [receipt(HERE / name) for name in ("gate.py", "run.sh")]
control_receipts = [receipt(path) for path in dict.fromkeys(controls)]
bulk = []
for row in archive["files"]:
    actual = Path(row["actual_path"])
    if actual.is_symlink() or actual.stat().st_size != row["compressed_bytes"]:
        raise ValueError("declared capture bulk stat differs")
    bulk.append({"path": str(actual), "stored_bytes": row["compressed_bytes"],
                 "stored_sha256": row["gzip_sha256"], "decoded_bytes": row["raw_bytes"],
                 "decoded_sha256": row["raw_sha256"], "authority": "original lossless archive declaration"})
for row in chunks:
    path = PART / row["uri"]
    if path.is_symlink() or path.stat().st_size != row["physical_bytes"]:
        raise ValueError("declared instance chunk stat differs")
    bulk.append({"path": str(path), "stored_bytes": row["physical_bytes"],
                 "stored_sha256": row["physical_sha256"], "decoded_bytes": row["decoded_bytes"],
                 "decoded_sha256": row["decoded_sha256"], "authority": "original partition declaration"})
os_decoded = sum(row["artifact"]["size_bytes"] for row in coords["membership"]
                 if row["artifact"]["schema"] == "strace.syscalls.text.v1")
os_stored = sum(row["compressed_bytes"] for row in archive["files"] if "/os/" in row["logical_path"])
kineto = [row for row in archive["files"] if "/kineto." in row["logical_path"]]
if len(kineto) != 1:
    raise ValueError("capture does not declare exactly one Kineto source")
capture_stored = sum(row["compressed_bytes"] for row in archive["files"])
decoded = coords["counts"]["verified_raw_bytes"] + os_decoded + kineto[0]["raw_bytes"] + sum(c["decoded_bytes"] for c in chunks)
stored = 2 * capture_stored + os_stored + kineto[0]["compressed_bytes"] + sum(c["physical_bytes"] for c in chunks)
budget = {"input_plan_only_not_actual_io": True,
    "binder_verified_decoded_declared": coords["counts"]["verified_raw_bytes"],
    "binder_os_second_parse_decoded": os_decoded, "kineto_second_scan_decoded": kineto[0]["raw_bytes"],
    "all_eeg_instances_chunks": len(chunks), "all_eeg_instances_records": table["records"],
    "all_eeg_instances_decoded": sum(c["decoded_bytes"] for c in chunks),
    "all_eeg_instances_stored": sum(c["physical_bytes"] for c in chunks),
    "decoded_lower_bound": decoded, "stored_read_plan": stored,
    "combined_bulk_read_lower_bound": decoded + stored,
    "control_read_allowance_inside_runtime_input_budget": 16_000_000,
    "runtime_input_max_stored_plus_decoded": 4_000_000_000,
    "runtime_output_max_write_plus_readback": 512_000_000,
    "independent_gate_source_hash_max": 64_000_000, "independent_gate_control_hash_max": 16_000_000,
    "source_preparation_hash_bytes": sum(r["bytes"] for r in sources + runners),
    "source_preparation_bulk_bytes_read": 0,
    "scope": "all provider GPU candidates; only valid fixed kernel/copy end contract qualified",
    "program_snapshot_attachment": "UNATTACHED_TO_PROGRAM_SNAPSHOT",
    "manifest_cannot_identify_gpu_chunks": True,
    "reason_for_all_instances": "manifest has no per-chunk category inventory; no ordinal-range shortcut"}
write("budget-plan.json", budget)
freeze = {"schema": "scar.native-activity-work-gate-freeze", "schema_version": 1,
    "source_tree": str(TREE), "baseline": "isolated frame-entry-routing; based on bc139e19, entry work e01702bf; no main edits",
    "capture": str(CAP), "partitions": str(PART), "sources": sources,
    "runners": runners, "controls": control_receipts,
    "declared_bulk_inputs": bulk, "bulk_freeze_policy": "declarations plus stat only; actual SHA/EOF verified by real ordinary readers",
    "runtime_budget": {"max_input_bytes": 4_000_000_000, "max_output_io_bytes": 512_000_000,
        "max_wall_seconds": 600, "max_rss_kib": 2 * 1024 * 1024,
        "max_record_bytes": 4_000_000, "max_shard_rows": 256, "max_shard_decoded_bytes": 16_000_000},
    "budget_plan": receipt(HERE / "budget-plan.json"), "preflight": receipt(HERE / "syntax-api.json")}
write("freeze.json", freeze)
b = (HERE / "freeze.json").read_bytes()
print(json.dumps({"freeze_sha256": sha256(b).hexdigest(), "freeze_bytes": len(b),
    "source_count": len(sources), "control_count": len(control_receipts),
    "declared_bulk_input_count": len(bulk), "combined_bulk_read_lower_bound": decoded + stored}))
