"""ONE automatic witness to retained 35-port gate; no manual actor or ordinal input."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import sys
import time


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
EXP = ROOT / "artifacts/experiments"


def digest(path):
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode()


def write(name, value):
    with (HERE / name).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")


def progress(value):
    print(json.dumps(value, sort_keys=True), flush=True)


def imported_sources():
    rows = []
    for name, module in sorted(sys.modules.items()):
        filename = getattr(module, "__file__", None)
        if name.startswith("scar") and filename and filename.endswith(".py"):
            rows.append({"module": name, **digest(Path(filename).resolve())})
    return rows


def main():
    started = time.monotonic()
    freeze = json.loads((HERE.parent / "static-freeze.json").read_text())
    frozen = [row for row in freeze["files"] if row["path"].endswith(".py")]
    assert len(frozen) == 11
    for row in frozen:
        assert digest(ROOT / row["path"])["sha256"] == row["sha256"], row["path"]
    write("producer.json", {"schema": "scar.fd-table-context-gate-producer", "schema_version": 1,
        "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "frozen_python_modules": frozen, "script": digest(Path(__file__)),
        "freeze": digest(HERE.parent / "static-freeze.json"), "scope": "ONE builder/public-reader/35 retained endpoints",
        "target_runs": 0, "full_execution_model_semantics": "OPEN"})
    with (HERE / "frozen-implementation.py").open("xb") as stream:
        stream.write((ROOT / "scar/trace/os_fd_table_contexts.py").read_bytes())
    with (HERE / "frozen-lookup-implementation.py").open("xb") as stream:
        stream.write((ROOT / "scar/trace/os_source_lookup.py").read_bytes())
    from scar.ir.execution.ids import ResourceInstanceID
    from scar.ir.execution.resources import HandleBinding, ImportedAt, InstanceTarget, ProviderHandle, ResourceInstance, RunRealm
    from scar.ir.program.resources import ResourceKind, ResourceRole
    from scar.ir.record_codec import decode, encode
    from scar.trace.os_resource_refinement import OSResourceBase
    from scar.trace.os_fd_table_contexts import FDTableContextInputs, OSFDTableContexts, build_os_fd_table_contexts
    from scar.trace.os_source_lookup import prepare_fd_context_evidence
    imports = imported_sources()
    write("imported-sources-before.json", imports)
    capture = EXP / "first_stage_lewm_physical_20261023"
    r1 = EXP / "first_stage_os_interface_work_20261023"
    r2_manifest = EXP / "first_stage_os_resource_refinement_20261023/gate-attempt01/result/manifest.json"
    projection = EXP / "first_stage_fd_table_projection_20261023"
    base = OSResourceBase(r1 / "result/interfaces/manifest.json", cached_chunks=2)
    progress({"phase": "AUTOMATIC_WITNESS_PREPARE_BEGIN"})
    preparation = prepare_fd_context_evidence(base, r2_manifest, archive=capture / "archive-index.json",
        coordinates=r1 / "result/capture-coordinates.json", r1_summary=r1 / "result/summary.json",
        projection_summary=projection / "summary.json", projection_files=projection / "file-receipts.json",
        context_events=projection / "context-events.json", fresh_out=HERE / "automatic-witness", progress=progress)
    assert preparation["status"] == "PUBLISHED_WITNESS" and preparation["producer"] == "AUTOMATIC_SOURCE_LOOKUP"
    assert preparation["all_needs_reported"] is True
    lookup = json.loads(Path(preparation["lookup_receipt"]["path"]).read_text())
    assert lookup["counts"]["selected_ports"] == 35 and lookup["counts"]["groups"] == 3
    assert lookup["counts"]["birth_needs"] == lookup["counts"]["positive_matches"] == 2
    assert lookup["counts"]["preexec_birth_needs"] == 1
    assert all(any(match["need"] == need for match in lookup["matches"]) for need in lookup["needs"])
    assert lookup["counts"]["queries"] <= 8 and lookup["counts"]["lookup_decoded_bytes_charged"] <= 64000000
    assert lookup["source_order_proved"] is False and lookup["source_uniqueness_proved"] is False
    evidence_path = Path(preparation["context_evidence"]["path"])
    evidence = json.loads(evidence_path.read_text())
    assert evidence["producer"]["kind"] == "AUTOMATIC_SOURCE_LOOKUP"
    assert evidence["producer"]["lookup_receipt"] == preparation["lookup_receipt"]
    inputs = FDTableContextInputs(capture, capture / "archive-index.json", r1 / "result/capture-coordinates.json",
        r1 / "result/summary.json", r1 / "audit-attempt03-summary.json", projection / "summary.json",
        projection / "file-receipts.json", projection / "context-events.json", evidence_path)
    progress({"phase": "AUTOMATIC_WITNESS_PUBLISHED", "receipt": preparation["context_evidence"]})
    progress({"phase": "BUILD_BEGIN"})
    result = build_os_fd_table_contexts(base, r2_manifest, inputs, HERE / "result",
        progress=lambda row: progress({"stage": "build", **row}))
    progress({"phase": "BUILD_PUBLISHED", "receipt": result["manifest_receipt"]})
    view = OSFDTableContexts.read(base, r2_manifest, inputs, HERE / "result/manifest.json",
        progress=lambda row: progress({"stage": "public_read", **row}))
    progress({"phase": "PUBLIC_READ_VALIDATED"})
    original = json.loads(r2_manifest.read_text())
    assert view.r2.document == original
    assert encode(tuple(view.r2.accesses.values())) == original["provider_accesses"]
    expected_ids = set(view.r2.handles)
    assert len(expected_ids) == len(view.handles) == 35
    assert len(view.context_resources) == 3
    changes = {decode(HandleBinding, entry["replacement"]).id: entry for entry in view.document["handle_refinements"]}
    grouped, receipts = defaultdict(list), []
    for identity, (ordinal, old) in view.r2.handles.items():
        previous = view.r2.record("handles", ordinal)
        selected = view.record("handles", ordinal)
        new = decode(HandleBinding, selected["record"])
        assert new.id == identity and type(new.handle) is ProviderHandle
        assert type(new.handle.container) is InstanceTarget
        assert new.handle.container.instance in view.context_resources
        assert previous["record"] == encode(old)
        assert changes[identity]["r2_record_sha256"] == hashlib.sha256(canonical(previous["record"])).hexdigest()
        before, after = previous["record"], selected["record"]
        assert {k:v for k,v in before.items() if k!="handle"} == {k:v for k,v in after.items() if k!="handle"}
        assert {k:v for k,v in before["handle"].items() if k!="container"} == {k:v for k,v in after["handle"].items() if k!="container"}
        source = base.resolve(new.handle.selector)
        grouped[new.handle.selector.ordinal].append((new, source["record"]))
        receipts.append({"id": encode(identity), "ordinal": ordinal,
            "r1_preimage": changes[identity]["r1_preimage"],
            "r2_record_sha256": changes[identity]["r2_record_sha256"],
            "new_record_sha256": hashlib.sha256(canonical(after)).hexdigest(),
            "container": encode(new.handle.container), "original_target": encode(new.target),
            "native_lifetime_unchanged": new.handle.lifetime == old.handle.lifetime,
            "other_fields_unchanged": True, "selector": encode(new.handle.selector),
            "original_selector_locator": source["locator"], "original_row_sha256": source["row_sha256"]})
    pipe_pairs = []
    for ordinal, rows in grouped.items():
        if rows[0][1]["syscall"] == "pipe2":
            assert len(rows) == 2
            left, right = rows[0][0], rows[1][0]
            assert left.target != right.target and left.handle.container == right.handle.container
            pipe_pairs.append({"observation_ordinal": ordinal, "left": encode(left.id), "right": encode(right.id),
                "distinct_original_ofds": True, "same_container": encode(left.handle.container)})
    assert len(grouped) == 22 and len(pipe_pairs) == 13
    resource_receipts = []
    for identity, typed in view.context_resources.items():
        assert decode(ResourceInstance, encode(typed)) == typed
        assert typed.kind is ResourceKind.OTHER and typed.role is ResourceRole.HANDLE_TABLE
        assert typed.realm == RunRealm(base.run.id) and type(typed.origin) is ImportedAt
        uses = [handle for handle in view.handles.values() if handle.handle.container.instance == identity]
        assert any(typed.origin.point == handle.start and typed.source == handle.source for handle in uses)
        assert view.selected_resource(identity)["coverage"] == "SELECTED_CONTEXT"
        resource_receipts.append({"resource": encode(typed), "selected_handles": len(uses)})
    work_receipts = []
    for entry in original["base_references"]["submissions"]:
        ordinal = entry["selector"]["ordinal"]
        selected = view.record("submissions", ordinal)
        assert selected == view.r2.record("submissions", ordinal)
        work_receipts.append({"ordinal": ordinal, "r1_preimage": entry,
            "selected_record_sha256": hashlib.sha256(canonical(selected["record"])).hexdigest()})
    assert len(work_receipts) == 25
    accepted_contexts = json.loads((EXP / "first_stage_fd_table_contexts_20261023/gate-attempt01/result/manifest.json").read_text())
    assert view.document["context_resources"] == accepted_contexts["context_resources"]
    assert [x["replacement"] for x in view.document["handle_refinements"]] == [x["replacement"] for x in accepted_contexts["handle_refinements"]]
    known_unselected = None
    for envelope in base.reader.iter_records("resources"):
        identity = decode(ResourceInstanceID, envelope["record"]["id"])
        if identity not in view.r2.resources:
            query = view.selected_resource(identity)
            assert query["coverage"] == "NOT_IN_SELECTED_REGISTRY" and query["record"] is None
            assert query["complete_registry"] is False and query["base_total"] == 12683
            known_unselected = {"id": encode(identity), "original_base_locator": envelope["locator"], "query": query,
                "base_presence_verified": True, "query_does_not_claim_absence": True}
            break
    assert known_unselected is not None
    for identity in view.r2.resources:
        query = view.selected_resource(identity)
        assert query["coverage"] == "R2_SELECTED_BASE" and query["record"] == encode(view.r2.resources[identity])
    after_imports = imported_sources()
    write("imported-sources-after.json", after_imports)
    after_by_name = {row["module"]: row for row in after_imports}
    imported_file_drift = [row for row in imports if row != after_by_name[row["module"]]]
    for row in frozen:
        assert digest(ROOT / row["path"])["sha256"] == row["sha256"]
    write("selected-handle-proofs.json", receipts)
    write("pipe-pairs.json", pipe_pairs)
    write("resources.json", resource_receipts)
    write("work-receipts.json", work_receipts)
    write("unselected-query.json", known_unselected)
    report = {"schema": "scar.fd-table-context-gate-report", "schema_version": 1,
        "status": "PASS_SELECTED_CONTAINER_SCOPE", "actual_gate_exit_expected": 0,
        "manifest": result["manifest_receipt"], "counts": view.document["counts"],
        "handles_typed_verified": len(receipts), "contexts_typed_verified": len(resource_receipts),
        "original_producer_works": len(grouped), "pipe_pairs": len(pipe_pairs),
        "selected_works_unchanged": len(work_receipts), "provider_accesses_unchanged": len(view.r2.accesses),
        "eleven_frozen_modules_sha": "PASS", "source_file_drift_after_import": imported_file_drift, "fresh_actual_scar_import_sources": len(after_imports),
        "not_selected_means_not_in_this_registry_not_absence": True,
        "same_selected_model_as_accepted_witness_gate": True,
        "upstream_child_birth_selector_discovery": "VERIFIED_AUTOMATIC_POSITIVE_EXACT_LOOKUP",
        "automatic_lookup_counts": lookup["counts"], "automatic_lookup_frontiers": lookup["frontiers"],
        "preparation": preparation,
        "full_execution_model_semantics": "OPEN: no fake ProgramSnapshot; selected typed/FK checks only",
        "first_stage_complete": False, "transformation_authorized": False,
        "elapsed_seconds": time.monotonic()-started, "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    write("summary.json", report)
    progress({"phase": "GATE_COMPLETE", "status": report["status"], "handles": len(receipts), "contexts": len(resource_receipts)})


if __name__ == "__main__":
    main()
