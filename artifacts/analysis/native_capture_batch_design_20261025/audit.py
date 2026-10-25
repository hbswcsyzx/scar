"""Metadata-only design audit; no SCAR import, raw stream or execution gate."""
from hashlib import sha256
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[3]
PLAN = "docs/NATIVE_CAPTURE_BATCH_PLAN.md"
COORDINATES = "artifacts/experiments/first_stage_native_protocol_bridge_attempt03_20261023/native-coordinates.json"
MODEL = "artifacts/experiments/first_stage_joined_physical_20261023/result/capture-model.json"
MANIFEST = "artifacts/experiments/first_stage_joined_physical_20261023/result/native/bundle-partitions/manifest.json"
SOURCES = (
    "scar/trace/native_protocol.py", "scar/ir/execution/native_port_protocol.py",
    "scar/ir/execution/validation.py", "scar/ir/execution/content_validation.py",
    "scar/trace/native_schema.py", "scar/store/bundle_partitions.py",
    "scar/trace/capture_coordinates.py", "scar/trace/native_import.py",
    "scar/trace/tensor_physical_import.py", "scar/ir/execution/snapshot.py",
    "scar/ir/execution/codec.py", "scar/ir/program/codec.py",
)


def read(path):
    p = Path(path)
    p = p if p.is_absolute() else BASE / p
    return p.read_bytes()


def info(path):
    data = read(path)
    p = Path(path)
    if p.is_absolute():
        p = p.relative_to(BASE)
    return {"path": str(p), "bytes": len(data), "sha256": sha256(data).hexdigest()}


def load(path):
    return json.loads(read(path))


def audit():
    fingerprints = [info(p) for p in SOURCES]
    freeze = load("artifacts/experiments/first_stage_native_protocol_bridge_attempt03_20261023/freeze.json")
    for row in freeze["production"]:
        assert info(row["path"]) == row
    coordinates = load(COORDINATES)
    schemas = {"scar.execution-evidence-collection", "scar.dispatch-observation-trace", "scar.tensor-physical-trace"}
    metadata = {}
    metadata_inputs = []
    for row in coordinates["membership"]:
        artifact = row["artifact"]
        if artifact["schema"] in schemas:
            assert artifact["size_bytes"] <= 4_000_000
            raw = read(row["local_path"])
            assert len(raw) == artifact["size_bytes"] and sha256(raw).hexdigest() == artifact["sha256"]
            document = json.loads(raw)
            assert document["schema"] == artifact["schema"]
            metadata[artifact["schema"]] = document
            metadata_inputs.append(info(row["local_path"]))
    assert set(metadata) == schemas
    native = metadata["scar.execution-evidence-collection"]
    dispatch = metadata["scar.dispatch-observation-trace"]
    physical = metadata["scar.tensor-physical-trace"]
    assert native["status"] == "CLOSED" and native["failures"] == []
    assert dispatch["dropped_events"] == 0 and dispatch["errors"] == []
    assert physical["traversal_completed"] and physical["allocation_receipt_traversal_complete"]
    manifest = load(MANIFEST)
    model = load(MODEL)
    tables = []
    for graph, table in (("evidence", "instances"), ("values", "objects"), ("values", "regions"), ("values", "allocations")):
        desc = manifest["graphs"][graph]["tables"][table]
        tables.append({"graph": graph, "table": table, "records": desc["records"],
                       "chunks": len(desc["chunks"]),
                       "decoded_bytes": sum(c["decoded_bytes"] for c in desc["chunks"]),
                       "stored_bytes": sum(c["physical_bytes"] for c in desc["chunks"])})
    totals = {key: sum(t[key] for t in tables) for key in ("records", "chunks", "decoded_bytes", "stored_bytes")}
    assert totals == {"records": 686872, "chunks": 95, "decoded_bytes": 1490910199, "stored_bytes": 91044471}
    counts = physical["counts"]
    denominator = dispatch["dispatch_attempts"]
    raw_bytes = native["artifacts"]["execution_trace"]["size_bytes"] + dispatch["file"]["raw_bytes"] + physical["file"]["raw_bytes"]
    assert denominator == 39796 and raw_bytes == 546619922
    cost = load("artifacts/experiments/first_stage_native_protocol_bridge_attempt03_20261023/cost-audit.json")
    assert all(info(row["path"]) == row for row in fingerprints), "source changed during metadata audit"
    return {
        "status": "DESIGN_ONLY_METADATA_AND_SOURCE_AUDIT_COMPLETE",
        "plan": info(PLAN), "source_fingerprints": fingerprints,
        "original_metadata_inputs": metadata_inputs,
        "other_input_fingerprints": [info(p) for p in (COORDINATES, MODEL, MANIFEST)],
        "delivered_six_sources_match_attempt03_freeze": True,
        "source_fingerprints_unchanged_during_audit": True,
        "metadata_declared_domain": {"dispatch_attempts": denominator, "dispatch_rows": dispatch["file"]["lines"],
                                     "eto_nodes": model["native"]["inventory"]["eto_nodes"], "physical_rows": physical["file"]["lines"],
                                     "physical_argument_slots": counts["marker_argument_slots"],
                                     "physical_slots_with_epoch_reference": counts["marker_slots_with_epoch_reference"],
                                     "physical_slots_without_epoch_reference": counts["marker_argument_slots"] - counts["marker_slots_with_epoch_reference"]},
        "metadata_declared_native_raw_bytes": raw_bytes,
        "archive_four_table_upper_bounds": {"tables": tables, "totals": totals},
        "planning_estimates_inferred_not_measured": {
            "combined_decoded_input_representation_bytes_excluding_spool_and_codec": cost["coordinate_scope_actual_IO"]["decoded"] + raw_bytes + totals["decoded_bytes"],
            "minimum_256_attempt_shards_for_fixture": (denominator + 255) // 256,
            "execution_bytes_if_13_call_prefix_average_extrapolated": 736486 * denominator / 13,
            "extrapolation_is_not_an_upper_bound": True,
            "proposed_rss_limit_bytes": 2 * 1024**3, "proposed_whole_run_seconds": 1800,
            "proposed_private_spool_bytes": 4_000_000_000,
            "proposed_published_output_bytes": 8_000_000_000,
            "proposed_free_working_space_bytes": 16_000_000_000,
        },
        "minimal_existing_modules_requiring_future_edit": ["scar/trace/native_protocol.py", "scar/ir/execution/native_port_protocol.py"],
        "new_generic_batch_orchestrator_proposed": True,
        "bundle_partitions_native_schema_generic_validation_changes_required": False,
        "implementation_waits_for_root_dependency_freeze_window": True,
        "invariants": ["one ordinary coordinate bind plus one live native acquisition per batch run",
                       "shared immutable complete static catalog and identical ProgramSnapshot artifact for every shard",
                       "independent full-static and shard-actual order domains",
                       "freshly sealed generic-valid wrong-order candidate rejects as NativePortOrderError using genuine live owner",
                       "complete original parent closure and qualified projection artifact namespaces",
                       "qualified plus explicit frontier equals original full dispatch denominator; unvisited zero only after actual full accounting",
                       "reference correspondence does not establish contents, complete world/state, alias completeness or readiness",
                       "no workload-name selection and no saved report or index restores runtime authority"],
        "raw_sources_read_by_this_design_audit": 0,
        "archive_chunks_read_by_this_design_audit": 0,
        "production_imports": 0, "production_writes": 0, "history_writes": 0,
        "new_gates_run": 0, "target_executions": 0, "git_commands": 0,
        "full_domain_semantics_newly_verified": False,
        "whole_program_model_established": False,
    }


if __name__ == "__main__":
    print(json.dumps(audit(), ensure_ascii=False, sort_keys=True, indent=2))
