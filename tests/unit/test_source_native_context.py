"""Tiny saved declarations; no raw producer, Torch, DB or real capture input."""
from dataclasses import replace
import gzip
from hashlib import sha256
import json

import pytest

from scar.analysis.source_native_composition import (
    ContextRelationship, NativeContextInputs, NativeContextIndex,
    NativeContextQueryBudget, NativeContextStatus, NavigationBudget,
    _BudgetExceeded, build_native_context_navigation,
)
from scar.ir.execution.common import EvidencePoint, MissingEvidence
from scar.ir.execution.coordinates import (
    BlockVisit, ControlTransfer, ExecutionRun, ExecutionSegment, InitialEntry,
    HostThreadInstance, OperationOccurrence, ProcessInstance, ProgramSnapshot, RegionActivation,
)
from scar.ir.execution.ids import (
    BlockVisitID, ExecutionSegmentID, HostThreadInstanceID, OperationOccurrenceID, ProcessInstanceID,
    RegionActivationID, RunID,
)
from scar.ir.execution.model import ExecutionModel, LegacyOperationRef, OccurrenceEvidenceBinding
from scar.ir.execution.codec import dumps as execution_dumps
from scar.ir.modeling_scope import (
    AnalysisScope, Coverage, CoverageGap, Domain, Encoding, Observability,
    RecordLocator, RetainedArtifact, ScopeField, ScopeFieldKind, digest,
)
from scar.ir.modeling_scope_codec import to_dict
from scar.ir.program.codec import dumps as program_dumps
from scar.ir.program.ids import BlockID, OperationID, RegionID
from scar.ir.program.model import (
    Behavior, Block, CompletionSignature, CompletionSuccessor, ExitKind,
    ExitPort, Operation, ProgramGraph, Region, Terminator, TerminatorKind,
)
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.record_codec import encode
from scar.ir.v2.evidence import OperationInstance
from scar.ir.v2.ids import OperationDefinitionID, OperationInstanceID
from scar.store.bundle_partitions import TABLES


def _bytes(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def _save(path, value, schema):
    raw = value if type(value) is bytes else _bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return ProviderArtifact(str(path), sha256(raw).hexdigest(), len(raw), schema)


def _fixture(root, *, wrong=None):
    pid, nonce = 123, "a" * 32
    original = root / "original"
    eto = ProviderArtifact(str(original / "eto.json"), "1" * 64, 10, "pytorch.execution-trace.v1")
    kineto = ProviderArtifact(str(original / "kineto.json"), "2" * 64, 10, "pytorch.kineto.chrome-trace.v1")
    dispatch = ProviderArtifact(str(original / "dispatch.jsonl"), "3" * 64, 10, "scar.dispatch-observation.events.v1")
    native_scope = "native:" + sha256(_bytes({"eto": eto.sha256, "kineto": kineto.sha256,
        "revision": "cf30153c4c131c8164ee7798e5022d810682e2cb", "pid": pid}).rstrip(b"\n")).hexdigest()
    ids = {i: OperationInstanceID(native_scope + ":eto:" + str(i)) for i in (1, 10, 11, 12)}
    instances = []
    for ordinal, node in enumerate((1, 10, 11, 12)):
        parent = 1 if node == 10 else 10
        instances.append(OperationInstance(ids[node], OperationDefinitionID("tiny"), pid, 1,
            None if node == 1 else ids[parent], metadata={"provider": "ETO", "node_id": node,
                "ctrl_deps": 1 if node == 1 else parent, "raw_tid": 1, "rf_id": ordinal,
                "raw_reference": "sha256:" + eto.sha256 + "#/nodes/" + str(ordinal)}).as_dict())
    raw = b"".join(_bytes({"ordinal": n, "record": r}) for n, r in enumerate(instances))
    stored = gzip.compress(raw, mtime=0)
    chunk = {"uri": "evidence/instances/000000.jsonl.gz", "compression": "gzip", "lines": 4,
        "first_ordinal": 0, "last_ordinal": 3, "physical_bytes": len(stored), "physical_sha256": sha256(stored).hexdigest(),
        "decoded_bytes": len(raw), "decoded_sha256": sha256(raw).hexdigest()}
    _save(original / chunk["uri"], stored, "retention")
    graphs = {}
    for name, tables in TABLES.items():
        if name == "correspondence": graphs[name] = None; continue
        counts = {t: (4 if (name, t) == ("evidence", "instances") else 0) for t in tables}
        graphs[name] = {"schema": "scar.ir.v2." + name, "schema_version": 6 if name == "evidence" else 2,
            "tables": {t: {"records": counts[t], "chunks": [chunk] if counts[t] else []} for t in tables},
            "counts": counts, "validation": {"valid": True, "schema": "scar.ir.v2." + name,
                "schema_version": 6 if name == "evidence" else 2, "counts": counts}}
    bundle = _save(original / "manifest.json", {"schema": "scar.partitioned-ir-bundle", "schema_version": 1,
        "status": "PUBLISHED", "bundle": {"schema": "scar.ir.v2.bundle", "schema_version": 2},
        "optimization": None, "source_semantics": None, "public_bundle_validation_performed": True,
        "graphs": graphs, "totals": {"records": 4, "chunks": 1, "stored_bytes": len(stored), "decoded_bytes": len(raw)}},
        "scar.partitioned-ir-bundle")
    run = ExecutionRun(RunID("tiny"), MissingEvidence("synthetic execution"))
    process = ProcessInstance(ProcessInstanceID("process"), run.id, pid, run.source)
    thread = HostThreadInstance(HostThreadInstanceID("thread"), process.id, pid, run.source)
    declaration = {"process_id": pid, "nonce": nonce, "provider_revision": "cf30153c4c131c8164ee7798e5022d810682e2cb",
        "file": {"path": dispatch.uri, "raw_sha256": dispatch.sha256, "raw_bytes": dispatch.size_bytes}}
    coordinates = {"schema": "scar.capture-coordinates", "schema_version": 1, "run": encode(run),
        "target_process": encode(process.id), "processes": [encode(process)], "dispatch_collector_declaration": declaration,
        "membership": [{"artifact": encode(a)} for a in (eto, kineto, dispatch)]}
    sc = _save(root / "source-coordinates.json", coordinates, "scar.capture-coordinates")
    nc = _save(root / "native-coordinates.json", coordinates, "scar.capture-coordinates")
    bindings = _save(root / "source/bindings.json", {}, "scar.source-invocation-bindings")
    source_inventory = _save(root / "source/inventory.json", {}, "scar.partitioned-program-inventory")
    inv = {"path": "invocations.jsonl.gz", "rows": 1, "raw_sha256": "7" * 64, "raw_bytes": 100}
    source = _save(root / "source/report.json", {"schema": "scar.source-invocations", "schema_version": 3,
        "current_capture_raw_scan_verified": True, "old_capture_dynamic_facts_used_for_current_run": False,
        "transformation_authorized": False, "inventory": {"path": source_inventory.uri,
            "raw_sha256": source_inventory.sha256, "raw_bytes": source_inventory.size_bytes, "decoded_bytes": source_inventory.size_bytes},
        "run": encode(run), "coordinate_binding": encode(sc), "bindings": {"path": "bindings.json",
        "raw_sha256": bindings.sha256, "raw_bytes": bindings.size_bytes}, "invocations": inv}, "scar.source-invocations")
    invocation_artifact = ProviderArtifact(str(root / "source/invocations.jsonl.gz"), inv["raw_sha256"], inv["raw_bytes"],
                                          "scar.source-invocations.events.v3")
    rows = []
    for phase, node, ordinal in (("span", 10, 1), ("output", 12, 3)):
        if wrong == "phase": phase = "output" if phase == "span" else "span"
        rows.append({"sequence": 1, "phase": phase, "marker_instance": ids[node].wire,
            "marker_reference": encode(ProviderFactReference(eto, "#/nodes/" + str(ordinal))),
            "relationship": "RETAINED_ANCESTOR_CONTEXT", "direct_callsite_established": False,
            "invocation": {"process_id": pid, "thread_id": 1, "invocation_id": 1}, "definition": None,
            "source_invocation_reference": encode(ProviderFactReference(invocation_artifact, "#/lines/1")),
            "source_binding_reference": encode(ProviderFactReference(bindings, "#/bindings/0")),
            "source_invocation_line_sha256": "8" * 64, "frontiers": [], "status": "RETAINED_INVOCATION_LINKED"})
    lines = [_bytes(r) for r in rows]; assoc_raw = b"".join(lines)
    assoc_path = root / "dispatch/associations.jsonl.gz"
    _save(assoc_path, gzip.compress(assoc_raw, mtime=0), "retention")
    marker_index = _bytes({"schema": "scar.dispatch-source-index", "schema_version": 1,
        "markers": {r["marker_instance"]: {"line": n, "line_sha256": sha256(line).hexdigest()}
                    for n, (r, line) in enumerate(zip(rows, lines), 1)}})
    marker_path = root / "dispatch/marker-index.json.gz"
    _save(marker_path, gzip.compress(marker_index, mtime=0), "retention")
    source_dispatch = _save(root / "dispatch/report.json", {"schema": "scar.dispatch-source-associations", "schema_version": 3,
        "run": encode(run), "coordinate_binding": encode(sc), "source_report": encode(source), "source_bindings": encode(bindings),
        "source_invocations": encode(invocation_artifact), "observations": {"path": assoc_path.name, "rows": 2,
        "raw_sha256": sha256(assoc_raw).hexdigest(), "raw_bytes": len(assoc_raw)},
        "index": {"path": marker_path.name, "raw_sha256": sha256(marker_index).hexdigest(), "raw_bytes": len(marker_index)}},
        "scar.dispatch-source-associations")
    region, entry, normal = RegionID("native"), BlockID("entry"), BlockID("normal")
    call, ret = OperationID("invoke"), OperationID("return")
    body_region = Region(region, "native", entry,
        (Block(entry, (), (call,)), Block(normal, (), (ret,))), (ExitPort("normal", ExitKind.NORMAL, ()),))
    operations = (Operation(call, "native", (Behavior.CONTROL,), terminator=Terminator(TerminatorKind.INVOKE,
            successors=(CompletionSuccessor(ExitKind.NORMAL, normal, ()),)),
            completions=(CompletionSignature(ExitKind.NORMAL, ()),), invoke_arguments=()),
         Operation(ret, "return", (Behavior.CONTROL,), terminator=Terminator(TerminatorKind.RETURN, exit="normal")))
    program = ProgramGraph(region, (body_region,), operations, ())
    shared = _save(root / "native/program.json", program_dumps(program).encode(), "scar.program-graph")
    projected = _save(root / "native/shards/000000/source-evidence.json",
        {"schema": "scar.ir.v2.evidence", "schema_version": 6, "instances": instances}, "scar.ir.v2.evidence")
    activation, segment = RegionActivationID("activation"), ExecutionSegmentID("segment")
    ev, nv = BlockVisitID("entry"), BlockVisitID("normal")
    invoke, returned = OperationOccurrenceID("invoke"), OperationOccurrenceID("return")
    point = EvidencePoint(run.id, process.id, ProviderFactReference(dispatch, "#line/1"))
    source_ordinal = 1 if wrong == "ordinal" else 2
    source_fact = ProviderFactReference(eto, "#/nodes/" + str(source_ordinal))
    return_fact = ProviderFactReference(eto, source_fact.locator + ("" if wrong == "return" else "/outputs"))
    legacy = LegacyOperationRef(projected, ids[11])
    execution = ExecutionModel(ProgramSnapshot(shared, 15), runs=(run,), processes=(process,), threads=(thread,),
        activations=(RegionActivation(activation, region, process.id, point),),
        segments=(ExecutionSegment(segment, activation, thread.id, InitialEntry(point)),),
        visits=(BlockVisit(ev, segment, entry), BlockVisit(nv, segment, normal)),
        operations=(OperationOccurrence(invoke, ev, call), OperationOccurrence(returned, nv, ret)),
        transfers=(ControlTransfer(invoke, 0, nv),), evidence_bindings=(
            OccurrenceEvidenceBinding(invoke, legacy, source_fact), OccurrenceEvidenceBinding(returned, legacy, return_fact)))
    execution_artifact = _save(root / "native/shards/000000/execution.json", execution_dumps(execution).encode(), "scar.execution-model")
    shard = {"execution": encode(execution_artifact), "sequences": [1], "evidence_projection": encode(projected),
             "program_snapshot": encode(execution.snapshot)}
    inventory_rows = [{"sequence": 1, "outcome": "RETURNED", "begin_count": 1, "end_count": 1,
        "source_rows": {"DISPATCH_BEGIN": [{"artifact": encode(dispatch), "locator": "#line/1", "index": 1}],
                        "DISPATCH_END": [{"artifact": encode(dispatch), "locator": "#line/3", "index": 3}]},
        "state": "MODELED_COMPLETE_REFERENCE", "activation_id": activation.value, "execution": encode(execution_artifact)},
        {"sequence": 3, "source_rows": {}, "state": "FRONTIER", "reason": "ORIGINAL_ETO_SPAN_UNAVAILABLE"}]
    inv_raw = b"".join(_bytes(row) for row in inventory_rows)
    inv_chunk = _save(root / "native/inventory/000000.jsonl", inv_raw, "scar.native-capture-row-chunk")
    inventory = _save(root / "native/inventory/manifest.json", {"schema": "scar.native-capture-table-chunks", "schema_version": 1,
        "row_schema_version": 2, "profile": "PINNED_TORCH_NATIVE_PORT_HELD_SUBSET_V2", "rows": 2,
        "chunks": [{"artifact": encode(inv_chunk), "rows": 2, "first_row_ordinal": 0, "last_row_ordinal": 1}]},
        "scar.native-capture-table-chunks")
    native = _save(root / "native/report.json", {"schema": "scar.native-capture-batch", "schema_version": 2,
        "profile": "PINNED_TORCH_NATIVE_PORT_HELD_SUBSET_V2", "status": "SOURCE_DOMAIN_ACCOUNTED_WITH_PORT_GAPS",
        "unvisited_actual_groups": 0, "run": run.id.value, "coordinates": encode(nc),
        "source_manifest": {"path": bundle.uri, "physical_bytes": bundle.size_bytes, "physical_sha256": bundle.sha256},
        "actual_sequence_ids": [1, 3], "enumerated_dispatch_groups": 2, "dispatch_inventory": encode(inventory),
        "modeled_complete_reference_dispatches": 1, "modeled_partial_reference_dispatches": 0, "unmodeled_frontier_dispatches": 1,
        "shards": [shard], "shared_program": encode(shared)}, "scar.native-capture-batch")
    def locator(artifact, encoding=Encoding.JSON):
        return RecordLocator(RetainedArtifact(artifact, artifact.sha256, artifact.size_bytes, encoding), "#")
    policy = tuple(locator(_save(root / ("policy" + str(i)), b"synthetic", "text/x-python"), Encoding.TEXT) for i in range(4))
    source_ref, native_ref, inventory_ref = locator(source), locator(bundle), locator(source_inventory)
    gap = CoverageGap("OPEN", "scope", source_ref, "synthetic retained scope")
    payload = dict(id="scope:" + "a" * 64, parent=None, contract=source_ref, policy=policy[0], source=source_ref,
        run=run.id, fields=tuple(ScopeField(k, (source_ref,), (gap,)) for k in ScopeFieldKind),
        observability=tuple(Observability(d, (source_ref, native_ref, inventory_ref), Coverage.UNKNOWN, (gap,)) for d in Domain),
        denominators=tuple(Domain), policy_sources=policy)
    scope = AnalysisScope(revision="scope_revision:" + digest(payload), **payload)
    ledger = _save(root / "scope/manifest.json", {"schema": "scar.partitioned-modeling-scope-ledger", "schema_version": 2,
        "status": "PUBLISHED", "scope": to_dict(scope)}, "scar.partitioned-modeling-scope-ledger")
    inputs = NativeContextInputs(source, source_dispatch, native, bundle, sc, nc, ledger, scope.revision)
    nav = build_native_context_navigation(inputs, root / "navigation")
    return inputs, nav, (assoc_path, marker_path)


def test_context_is_bound_to_navigation_and_queries_never_open_original_gzip(tmp_path):
    inputs, manifest, original_streams = _fixture(tmp_path)
    for path in original_streams: path.unlink()
    reader = NativeContextIndex.open(manifest, expected_inputs=inputs)
    result = reader.native_context(1)
    assert result.status is NativeContextStatus.RETAINED_CONTEXT
    assert result.relationship is ContextRelationship.RETAINED_SOURCE_CONTEXT
    assert result.navigation == manifest and result.inputs == inputs
    assert result.invoke and result.normal_return
    assert result.assumptions == ("HISTORICAL_SCAR_COLLECTOR_EXECUTION_SOURCE_UNRECORDED",)
    assert result.costs["index_chunks"] == 1 and result.costs["data_chunks"] == 2 and result.costs["archive_chunks"] == 1
    frontier = reader.native_context(3)
    assert frontier.status is NativeContextStatus.NATIVE_FRONTIER and frontier.relationship is None
    assert reader.native_context(2).status is NativeContextStatus.SEQUENCE_NOT_OBSERVED


@pytest.mark.parametrize("wrong", ["phase", "ordinal", "return"])
def test_wrong_phase_ordinal_and_normal_return_reject(tmp_path, wrong):
    inputs, manifest, _ = _fixture(tmp_path, wrong=wrong)
    reader = NativeContextIndex.open(manifest, expected_inputs=inputs)
    with pytest.raises(ValueError, match="source/native context"):
        reader.native_context(1)


def test_wrong_scope_partial_root_and_query_budget_are_explicit(tmp_path):
    inputs, manifest, _ = _fixture(tmp_path)
    with pytest.raises(ValueError, match="navigation inputs"):
        NativeContextIndex.open(manifest, expected_inputs=replace(inputs, scope_revision="scope_revision:" + "f" * 64))
    reader = NativeContextIndex.open(manifest, expected_inputs=inputs)
    reader._budgets = NativeContextQueryBudget(max_decoded_bytes=1)
    result = reader.native_context(1)
    assert result.status is NativeContextStatus.BUDGET_EXHAUSTED and result.relationship is None and result.cursor
    partial = _save(tmp_path / "partial.json", {"schema": "scar.native-capture-execution-shard", "schema_version": 2},
                    "scar.native-capture-batch")
    with pytest.raises(ValueError, match="final native batch root"):
        build_native_context_navigation(replace(inputs, native_final_batch_report=partial), tmp_path / "rejected")


def test_builder_output_ceiling_is_independent_of_input_stored_budget(tmp_path):
    inputs, _, _ = _fixture(tmp_path)
    output = tmp_path / "over-output"
    with pytest.raises(_BudgetExceeded, match="output_bytes"):
        build_native_context_navigation(inputs, output,
            budgets=NavigationBudget(max_stored_bytes=256_000_000, max_output_bytes=1))
    assert not list(output.iterdir())
