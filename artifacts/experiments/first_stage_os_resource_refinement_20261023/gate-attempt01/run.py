"""One real 35-port sparse gate; no target, raw importer or fake snapshot."""
import ast
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import time

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
REPO = BASE.parents[3]
R1 = ROOT.parent / "first_stage_os_interface_work_20261023"
START = time.monotonic()


def write(name, value):
    (BASE / name).write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def receipt(path):
    raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def log(event, **fields):
    row = {"event": event, "pid": os.getpid(), "elapsed_seconds": time.monotonic() - START,
           "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, **fields}
    with (BASE / "progress.jsonl").open("a") as stream:
        stream.write(json.dumps(row, sort_keys=True) + "\n")
    print(json.dumps(row, sort_keys=True), flush=True)


def main():
    freeze = json.loads((ROOT / "revised-freeze.json").read_bytes())
    for row in freeze["files"]:
        actual = receipt(REPO / row["path"])
        assert actual["sha256"] == row["sha256"], row["path"]
    manifest = R1 / "result/interfaces/manifest.json"
    assert receipt(manifest)["sha256"] == "cbc6dcfd78ccca0961bdabecce94bc747b7b281fdbc3f49228c8b52b9b3aec14"
    producer = {"revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
        "pid": os.getpid(), "script": receipt(Path(__file__)), "frozen_sources": freeze["files"],
        "revised_freeze": receipt(ROOT / "revised-freeze.json"), "base": receipt(manifest),
        "audit_representatives": receipt(R1 / "audit-attempt03-codec-representatives.json"),
        "scope": "ONE35 real created ports +3 real executor observations + narrow codec boundaries",
        "target_executed": False, "raw_import_replayed": False, "fake_program_snapshot_created": False}
    with (BASE / "producer.json").open("x") as stream:
        stream.write(json.dumps(producer, sort_keys=True, indent=2) + "\n")
    log("START", revision=producer["revision"])
    from scar.trace.os_resource_refinement import OSResourceBase, OSResourceRefinement, build_os_resource_refinement
    from scar.ir.record_codec import decode, encode
    from scar.ir.execution.resources import (HandleBinding, ProviderHandle, ProviderRecordSelector,
        ProviderResourceAccess, ProviderAccessPurpose)
    from scar.ir.execution.work import WorkSubmission
    from scar.ir.execution import codec as execution_codec
    from scar.ir.program import codec as program_codec
    from scar.ir.program.resources import ResourceRole, ResourceKind, ResourceDefinition, ExternalResource
    from scar.ir.program.ids import RegionID, ResourceDefinitionID

    base = OSResourceBase(manifest)
    representatives = json.loads((R1 / "audit-attempt03-codec-representatives.json").read_bytes())
    executor_ordinals = []
    for example in representatives["representatives"].values():
        variant = example["variant"]
        if variant[2:4] != ["KNOWN_PROCESS", "KNOWN_NATIVE_THREAD"]:
            continue
        locator = example["observation"]
        assert locator["manifest_receipt"]["physical_sha256"] == base.artifact.sha256
        ordinal = locator["artifact"]["first_ordinal"] + locator["line"] - 1
        if ordinal not in executor_ordinals:
            executor_ordinals.append(ordinal)
        if len(executor_ordinals) == 3:
            break
    assert len(executor_ordinals) == 3
    write("selected-executors.json", executor_ordinals)
    result = build_os_resource_refinement(base, BASE / "result", executor_observation_ordinals=executor_ordinals,
        progress=lambda row: log("BUILD", **row))
    log("BUILT", counts=result["document"]["counts"], output=result["manifest_receipt"])
    view = OSResourceRefinement.read(base, BASE / "result/manifest.json")
    document = view.document
    assert document["counts"]["created_ports"] == document["counts"]["handle_refinements"] == 35
    assert document["counts"]["executor_refinements"] == 3
    assert len(view.accesses) == 38 and len(view.handles) == 35
    outputs = [access for access in view.accesses.values() if access.purpose is ProviderAccessPurpose.OUTPUT_SELECTOR]
    assert len(outputs) == 35 and len({access.work for access in outputs}) == 22
    assert len({binding.handle.lifetime for _, binding in view.handles.values()}) == 35
    pairs, selected_proofs, codec_counts = {}, [], {"ProviderHandle": 0, "ProviderRecordSelector": 0, "ProviderResourceAccess": 0}
    for binding_id, (ordinal, binding) in view.handles.items():
        selected = view.record("handles", ordinal)
        original = base.resolve(base.selector("handles", ordinal))["record"]
        assert selected["selection"] == "REFINED" and selected["record"]["id"] == original["id"]
        assert {k: v for k, v in selected["record"].items() if k != "handle"} == {k: v for k, v in original.items() if k != "handle"}
        assert encode(decode(ProviderHandle, encode(binding.handle))) == encode(binding.handle)
        codec_counts["ProviderHandle"] += 1
        resolved = base.resolve(binding.handle.selector)
        assert resolved["verification"]["whole_chunk_decoded_sha_verified"]
        assert decode(ProviderRecordSelector, encode(binding.handle.selector)) == binding.handle.selector
        codec_counts["ProviderRecordSelector"] += 1
        row = resolved["record"]
        if len(row["created_handles"]) == 2:
            pairs[row["work_ticket"]] = row["created_handles"]
        selected_proofs.append({"binding": binding_id.as_dict(), "selector": encode(binding.handle.selector),
            "locator": resolved["locator"], "row_sha256": resolved["row_sha256"],
            "original_target": original["target"], "new_lifetime": binding.handle.lifetime.as_dict(),
            "other_fields_unchanged": True})
    assert len(pairs) == 13
    for ports in pairs.values():
        assert ports[0]["target"] != ports[1]["target"] and ports[0]["fd"] != ports[1]["fd"]
    for access in view.accesses.values():
        assert decode(ProviderResourceAccess, encode(access)) == access
        codec_counts["ProviderResourceAccess"] += 1
        assert decode(ProviderRecordSelector, encode(access.selector)) == access.selector
        codec_counts["ProviderRecordSelector"] += 1
    for identity, (ordinal, work) in view.executors.items():
        selected = view.record("submissions", ordinal)
        original = base.resolve(base.selector("submissions", ordinal))["record"]
        assert selected["selection"] == "REFINED" and work.id == identity
        assert {k: v for k, v in selected["record"].items() if k != "executor"} == {k: v for k, v in original.items() if k != "executor"}
        assert work.effects_coverage.value == work.dependencies_coverage.value == work.materializations_coverage.value == "UNKNOWN"
    control_ordinal = next(index for index in range(100) if index not in {item[0] for item in view.handles.values()})
    control = view.record("handles", control_ordinal)
    assert control["selection"] == "BASE" and control["record"] == base.resolve(base.selector("handles", control_ordinal))["record"]
    log("ENDPOINTS_PASS", ports=35, producer_work=22, executors=3, pipe_pairs=13)

    boundary = []
    def rejects(label, callback, expected=None):
        try:
            callback()
        except (TypeError, ValueError) as error:
            if expected is not None:
                assert expected in str(error), (label, str(error))
            boundary.append({"probe": label, "rejected": True, "error": str(error)})
            return
        raise AssertionError(label + " unexpectedly accepted")
    binding = next(iter(view.handles.values()))[1]
    wire9 = execution_codec._encode(binding, HandleBinding, "real_binding", 9)
    assert execution_codec._decode(wire9, HandleBinding, "real_binding", 9) == binding
    rejects("execution8_actual_provider_handle_encode", lambda: execution_codec._encode(binding, HandleBinding, "real_binding", 8))
    rejects("execution8_actual_provider_handle_decode", lambda: execution_codec._decode(wire9, HandleBinding, "real_binding", 8))
    role9 = execution_codec._encode(ResourceRole.HANDLE_TABLE, ResourceRole, "role_boundary", 9)
    rejects("execution8_new_role_encode", lambda: execution_codec._encode(ResourceRole.HANDLE_TABLE, ResourceRole, "role_boundary", 8))
    rejects("execution8_new_role_decode", lambda: execution_codec._decode(role9, ResourceRole, "role_boundary", 8))
    # Negative wire inputs only: no accepted ProgramGraph, ProgramSnapshot or
    # ExecutionModel is manufactured. Reach the shared-enum capability gate.
    region = RegionID("negative-role-wire")
    resource = encode(ResourceDefinition(ResourceDefinitionID("negative-role-wire"), ResourceKind.OTHER,
        ResourceRole.HANDLE_TABLE, ExternalResource(region, "external_handle_table")))
    for version, fields in ((4, program_codec._V4_GRAPH_FIELDS), (27, program_codec._V27_GRAPH_FIELDS)):
        wire = {name: [] for name in fields}
        wire.update(schema=program_codec.SCHEMA, schema_version=version, root=region.as_dict(), resources=[resource])
        rejects("program" + str(version) + "_new_role_negative_wire", lambda wire=wire: program_codec.loads(json.dumps(wire)),
                "historical schema cannot contain handle-table resource role")
    write("selector-proofs.json", selected_proofs)
    write("codec-boundaries.json", boundary)
    summary = {"status": "PASS", "counts": document["counts"], "producer_work": 22, "pipe_pairs": 13,
        "codec_counts": codec_counts, "old_capability_rejections": len(boundary), "executor_observations": executor_ordinals,
        "base_manifest": producer["base"], "refinement": result["manifest_receipt"],
        "all_base_preimages_and_selected_chunks_verified": True, "unresolved_fd_table_containers": 35,
        "base_resource_work_ids_preserved": True, "fake_program_snapshot_created": False,
        "full_execution_model_validation": "OPEN_NOT_PERFORMED", "new_target_or_gpu_execution": False,
        "elapsed_seconds": time.monotonic() - START, "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "whole_model_established": False, "first_stage_complete": False, "transformation_authorized": False}
    write("summary.json", summary)
    log("PASS", summary=summary)


if __name__ == "__main__":
    try:
        main()
    except BaseException as error:
        log("FAILED", error_type=type(error).__name__, detail=str(error))
        raise
