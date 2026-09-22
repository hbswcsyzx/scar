"""The v1 adapter must preserve observations without strengthening claims."""
import hashlib
import json

import scar.ir.v2 as ir
from scar.trace.normalize_v2 import normalize_records, normalize_trace


def _event(kind, index, *, invocation=None, ts=None, duration=None,
           metadata=None, resource=None, inputs=(), outputs=(), code="fn:sha256:1"):
    return {"index": index, "kind": kind, "invocation_id": invocation,
            "ts_ns": index * 100 if ts is None else ts, "duration_ns": duration,
            "code_id": code, "labels": [], "effect": {},
            "inputs": list(inputs), "outputs": list(outputs), "resource": resource or {},
            "metadata": {"process_id": 1, "thread_id": 2, "clock_domain": "perf_counter",
                         **(metadata or {})}}


def _tensor(**overrides):
    return {"object_id": "python:address", "storage_id": "storage:address",
            "logical_version": "storage:address@0:v0", "type": "Tensor",
            "shape": [2, 3], "strides": [3, 1], "offset": 0,
            "dtype": "torch.float32", "device": "cpu", **overrides}


def _gpu(kind, index, *, stream=7, device=0, context=1, process=1,
         clock="kineto", ts=None, duration=10):
    return _event(kind, index, ts=ts, duration=duration,
                  metadata={"clock_domain": clock, "process_id": process,
                            "physical": kind == "cuda_memcpy"},
                  resource={"device": device, "stream": stream, "context": context})


def test_aggregate_profile_rows_are_measurements_not_invocations_or_allocations():
    result = normalize_records([_event(
        "torch_op", 1, duration=30, code="aten::empty",
        metadata={"aggregate": True},
        resource={"count": 20, "cpu_memory_usage": 4096,
                  "device_memory_usage": -1024, "cuda_time_total_us": 4.5})])
    assert not result.bundle.evidence.instances
    assert not result.bundle.values.allocations
    measurements = {m.metric: m for m in result.bundle.evidence.measurements.values()}
    assert measurements["count"].value == 20
    assert measurements["self_cpu_time_total"].value == 30
    assert measurements["device_memory_usage"].value == -1024
    assert all(m.instrumented and m.samples == 20 for m in measurements.values())
    assert result.coverage["raw_records"] == result.coverage["accounted_records"] == 1


def test_python_pairing_namespaces_process_thread_and_invocation():
    records = [
        _event("python_call", 0, invocation=1),
        _event("python_call", 1, invocation=1, metadata={"process_id": 3}),
        _event("python_call", 2, invocation=1, metadata={"thread_id": 4}),
        _event("python_return", 3, invocation=1, metadata={"thread_id": 4}),
        _event("python_return", 4, invocation=1, metadata={"process_id": 3}),
        _event("python_return", 5, invocation=1),
    ]
    first = normalize_records(records, namespace="one")
    second = normalize_records(records, namespace="two")
    calls = list(first.bundle.evidence.instances.values())
    assert len(calls) == 3
    assert {(c.process_id, c.thread_id, c.start_ns, c.end_ns) for c in calls} == {
        (1, 2, 0, 500), (3, 2, 100, 400), (1, 4, 200, 300)}
    assert all(c.metadata["completion"] == "paired_return" for c in calls)
    assert not set(first.bundle.evidence.instances) & set(second.bundle.evidence.instances)


def test_missing_duplicate_and_orphan_calls_remain_unmatched():
    records = [
        _event("python_call", 0, invocation=1),
        _event("python_call", 1, invocation=1),
        _event("python_return", 2, invocation=1),
        _event("python_return", 3, invocation=99),
        _event("python_call", 4, invocation=2),
    ]
    result = normalize_records(records)
    assert result.coverage["status_counts"]["unmatched"] == 5
    calls = [c for c in result.bundle.evidence.instances.values()
             if c.metadata["raw_kind"] == "python_call"]
    assert len(calls) == 3 and all(c.end_ns is None for c in calls)
    assert len(result.bundle.evidence.instances) == 5


def test_mismatched_return_code_or_clock_never_closes_a_call():
    for change in ({"code_id": "different"}, {"metadata": {"process_id": 1, "thread_id": 2, "clock_domain": "other"}}):
        returned = _event("python_return", 1, invocation=1)
        returned.update(change)
        result = normalize_records([_event("python_call", 0, invocation=1), returned])
        call = next(iter(result.bundle.evidence.instances.values()))
        assert call.end_ns is None
        assert result.coverage["status_counts"]["unmatched"] == 2


def test_parent_edges_and_control_observations_do_not_invent_extra_calls():
    result = normalize_records([
        _event("python_call", 0, invocation=1),
        _event("python_line", 1, invocation=1, metadata={"line": 8}),
        _event("loop_iteration", 2, invocation=1, metadata={"iteration": 2}),
        _event("python_call", 3, invocation=2, metadata={"parent_invocation_id": 1}),
        _event("python_return", 4, invocation=2),
        _event("python_return", 5, invocation=1),
    ])
    evidence = result.bundle.evidence
    assert len(evidence.instances) == 2
    assert len(evidence.control_events) == 2
    parent, child = list(evidence.instances.values())
    assert child.parent == parent.id
    assert len(parent.metadata["control_observations"]) == 2
    edges = [e for e in evidence.edges.values() if e.relation is ir.EvidenceRelation.CONTROLS_INSTANCE]
    assert len(edges) == 1
    assert edges[0].relation is ir.EvidenceRelation.CONTROLS_INSTANCE
    assert edges[0].source.reference == parent.id and edges[0].target.reference == child.id
    observed_control = [e for e in evidence.edges.values() if e.relation is ir.EvidenceRelation.OBSERVED_CONTROL]
    assert len(observed_control) == 2
    assert all(e.source.reference == parent.id for e in observed_control)


def test_host_completed_spans_and_kineto_start_times_keep_separate_clocks():
    result = normalize_records([
        _event("module_call", 0, ts=100, duration=30),
        _gpu("cuda_kernel", 1, ts=50, duration=10),
        _event("cuda_barrier", 2, ts=70, duration=5,
               metadata={"clock_domain": "kineto", "host_tid": 8}),
    ])
    module, kernel, barrier = list(result.bundle.evidence.instances.values())
    assert (module.start_ns, module.end_ns) == (70, 100)
    assert (kernel.start_ns, kernel.end_ns) == (50, 60)
    assert (barrier.start_ns, barrier.end_ns) == (70, 75)
    assert module.metadata["clock_domain"] == "perf_counter"
    assert barrier.thread_id == 8
    assert not any(e.relation is ir.EvidenceRelation.HAPPENS_BEFORE
                   for e in result.bundle.evidence.edges.values())


def test_same_stream_order_requires_matching_process_clock_device_context_stream():
    result = normalize_records([
        _gpu("cuda_kernel", 1), _gpu("cuda_memcpy", 2),
        _gpu("cuda_kernel", 3, stream=8),
        _gpu("cuda_kernel", 4, device=1),
        _gpu("cuda_kernel", 5, process=2),
        _gpu("cuda_kernel", 6, clock="other"),
        _gpu("cuda_kernel", 7, context=2),
    ])
    edges = [e for e in result.bundle.evidence.edges.values()
             if e.relation is ir.EvidenceRelation.HAPPENS_BEFORE]
    assert len(edges) == 1
    instances = list(result.bundle.evidence.instances)
    assert (edges[0].source.reference, edges[0].target.reference) == (instances[0], instances[1])
    assert edges[0].evidence.kind is ir.EvidenceKind.INFERRED


def test_overlapping_or_tied_gpu_timestamps_do_not_invent_stream_order():
    result = normalize_records([
        _gpu("cuda_kernel", 1, ts=100, duration=50),
        _gpu("cuda_kernel", 2, ts=100, duration=40),
        _gpu("cuda_kernel", 3, ts=120, duration=10),
    ])
    assert not any(e.relation is ir.EvidenceRelation.HAPPENS_BEFORE
                   for e in result.bundle.evidence.edges.values())
    assert result.coverage["status_counts"]["ambiguous"] == 2


def test_to_and_expand_are_not_physical_copy_or_allocation_events():
    same = _tensor(shape=[1024, 3], strides=[0, 1])
    result = normalize_records([
        _event("transfer", 1, duration=10, inputs=[same], outputs=[same],
               metadata={"physical": False, "same_object": True}),
        _event("torch_dispatch", 2, duration=10, code="aten.expand.default",
               inputs=[same], outputs=[same]),
        _gpu("cuda_memcpy", 3),
    ])
    operations = list(result.bundle.evidence.instances.values())
    assert operations[0].metadata["physical_copy"] is False
    assert sum(op.metadata.get("physical_copy") is True for op in operations) == 1
    assert all(a.nbytes is None and a.metadata["allocation_event"] is False
               for a in result.bundle.values.allocations.values())
    assert all(r.strides == (0, 1) for r in result.bundle.values.regions.values())


def test_legacy_version_alias_and_content_hash_do_not_prove_logical_equality():
    cpu = _tensor(content_fingerprint="sha256:same", values=list(range(1000)))
    gpu = _tensor(device="cuda:0", storage_id="different", object_id="other",
                  content_fingerprint="sha256:same")
    result = normalize_records([
        _event("transfer", 1, inputs=[cpu], outputs=[gpu], duration=5),
        _event("module_call", 2, inputs=[cpu], outputs=[cpu], duration=5),
    ])
    assert len(result.bundle.values.logical_values) == 4
    assert len(result.bundle.values.versions) == 4
    assert not result.bundle.values.provenance
    assert all(v.metadata["equivalence"] == "UNKNOWN" for v in result.bundle.values.logical_values.values())
    encoded = ir.canonical_json(result.bundle)
    assert '"values":[0,1,2' not in encoded
    assert all("values" not in v.metadata["legacy_hints"] for v in result.bundle.values.versions.values())


def test_explicit_memory_event_has_typed_storage_edge_without_guessed_free_pairing():
    result = normalize_records([
        _event("allocation", 1, resource={"allocation_id": "address", "bytes": 64, "device": "cuda:0"}),
        _event("free", 2, resource={"allocation_id": "address", "device": "cuda:0"}),
    ])
    allocations = list(result.bundle.values.allocations.values())
    assert len(allocations) == 2
    assert allocations[0].metadata["allocation_event"] is True
    assert allocations[1].metadata["free_observation"] is True
    assert allocations[0].id != allocations[1].id
    assert sum(e.relation is ir.EvidenceRelation.USES_STORAGE
               for e in result.bundle.evidence.edges.values()) == 2


def test_effect_writes_are_observations_and_empty_effects_do_not_imply_purity():
    snapshot = _tensor()
    record = _event("torch_dispatch", 1, inputs=[snapshot], outputs=[snapshot])
    record["effect"] = {"writes": [snapshot["logical_version"]]}
    result = normalize_records([record])
    assert any(e.relation is ir.EvidenceRelation.OBSERVED_WRITE
               for e in result.bundle.evidence.edges.values())
    assert all(i.metadata["effects_complete"] is False for i in result.bundle.evidence.instances.values())
    assert all(i.contract is None for i in result.bundle.semantic.definitions.values())


def test_unknown_event_and_invalid_lines_have_exact_recoverable_coverage(tmp_path):
    valid = json.dumps(_event("future_collector_event", 1)).encode() + b"\n"
    bad = b'{"kind":"broken",\n'
    duplicate = b'{"kind":"a","kind":"b"}\n'
    nonfinite = b'{"kind":"x","ts_ns":1e999}\n'
    path = tmp_path / "events.jsonl"
    path.write_bytes(valid + bad + duplicate + nonfinite + b"\n")
    result = normalize_trace(path)
    assert result.coverage["raw_records"] == result.coverage["accounted_records"] == 5
    assert result.coverage["status_counts"]["opaque"] == 1
    assert result.coverage["status_counts"]["invalid"] == 4
    assert result.coverage["source_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert [r["line"] for r in result.coverage["records"]] == [1, 2, 3, 4, 5]
    assert result.coverage["records"][0]["sha256"] == hashlib.sha256(valid).hexdigest()


def test_malformed_nested_records_are_accounted_without_aborting_the_trace():
    records = [_event("python_return", 1), _event("module_call", 2),
               _event("python_call", 3), _event("future_event", 4)]
    records[0]["outputs"] = None
    records[1]["inputs"] = "not-an-array"
    records[2]["effect"] = []
    records[3]["metadata"] = None
    result = normalize_records(records)
    assert result.coverage["raw_records"] == result.coverage["status_counts"]["invalid"] == 4
    assert not result.bundle.evidence.instances


def test_normalization_is_deterministic_roundtrips_and_never_creates_candidates(tmp_path):
    path = tmp_path / "events.jsonl"
    records = [_event("module_call", 1, duration=10, inputs=[_tensor()]),
               _gpu("cuda_kernel", 2)]
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    first, second = normalize_trace(path), normalize_trace(path)
    encoded = ir.canonical_json(first.bundle)
    assert encoded == ir.canonical_json(second.bundle)
    assert first.coverage == second.coverage
    assert ir.canonical_json(ir.IRBundle.from_json(encoded)) == encoded
    assert first.bundle.optimization is None
    assert "candidate" not in first.coverage
    assert all(d.metadata["origin"] == "v1_runtime_stub" for d in first.bundle.semantic.definitions.values())
    assert not first.bundle.semantic.source_atoms
