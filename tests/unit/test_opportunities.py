from scar.analysis.synchronization import synchronization_candidates
from scar.analysis.memory import allocation_candidates
from scar.ir import Effect, Event, ExecutionGraph
from scar.planner import plan
from scar.planner.cost import decide
from scar.analysis.repetition import repeated_regions


def test_host_materialization_and_barrier_are_observed_but_rejected():
    graph = ExecutionGraph([
        Event(kind="torch_op", code_id="aten::item", invocation_id=4,
              duration_ns=100, resource={"count": 4}, effect=Effect()),
        Event(kind="torch_op", code_id="cudaDeviceSynchronize", invocation_id=1,
              duration_ns=200, resource={"count": 1}, effect=Effect()),
    ])
    found = synchronization_candidates(graph)
    assert [item.kind for item in found] == [
        "DeferredMaterializationCandidate", "SynchronizationCandidate"]
    assert all(item.evidence == "Observed" and item.decision == "rejected" for item in found)


def test_repeated_allocation_is_a_guarded_generic_candidate():
    event = Event(kind="torch_op", code_id="aten::empty.memory_format",
                  duration_ns=1000, resource={"count": 5,
                                             "device_memory_usage": 4096})
    candidates = allocation_candidates(ExecutionGraph([event]))
    assert len(candidates) == 1
    assert candidates[0].kind == "AllocationReuseCandidate"
    assert candidates[0].evidence == "Observed"
    assert candidates[0].decision == "rejected"
    assert candidates[0].estimated_memory_bytes is None
    assert "4096 bytes" in candidates[0].reason


def test_repeated_python_region_is_detected_without_assuming_purity():
    graph = ExecutionGraph([
        Event(kind="python_call", code_id="user:parse", duration_ns=200,
              inputs=[{"logical_version": "literal:config", "device": "python"}],
              effect=Effect(reads=["literal:config"])),
        Event(kind="python_call", code_id="user:parse", duration_ns=210,
              inputs=[{"logical_version": "literal:config", "device": "python"}],
              effect=Effect(reads=["literal:config"])),
    ])
    candidates = repeated_regions(graph)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.kind == "PythonReuseCandidate"
    assert candidate.applicability == "same_input_logical_versions"
    assert candidate.decision == "rejected"
    assert "incomplete" in candidate.rejection_reason


def test_planner_records_budget_cost_separately_from_legality():
    values = {"storage_id": "storage:s", "logical_version": "s:v0",
              "shape": [1024], "dtype": "torch.float32", "device": "cuda:0"}
    graph = ExecutionGraph([
        Event(kind="transfer", inputs=[values], outputs=[values],
              metadata={"physical": True}),
        Event(kind="transfer", inputs=[values], outputs=[values],
              metadata={"physical": True}),
    ])
    found = plan(graph, memory_budget_bytes=1024)
    assert found[0].decision == "rejected"
    assert found[0].rejection_reason == "residency lifetime and invalidation guard is incomplete"
    assert found[0].cost_assessment["reason"] == "memory occupation exceeds configured budget"


def test_residency_cost_accepts_short_dtype_spelling():
    values = {"storage_id": "storage:s", "logical_version": "s:v0",
              "shape": [8], "dtype": "float32", "device": "cuda:0"}
    graph = ExecutionGraph([
        Event(kind="transfer", inputs=[values], outputs=[values],
              metadata={"physical": True}),
        Event(kind="transfer", inputs=[values], outputs=[values],
              metadata={"physical": True}),
    ])
    found = plan(graph, memory_budget_bytes=32)
    assert found[0].estimated_memory_bytes == 32


def test_missing_cost_evidence_is_not_zero_overhead_or_not_profitable():
    unknown = decide(1000)
    assert not unknown.accepted and "evidence incomplete" in unknown.reason
    assert unknown.overhead_ns is None
    slower = decide(1000, guard_ns=900, lookup_ns=200)
    assert not slower.accepted and slower.reason.startswith("not profitable")
    faster = decide(1000, guard_ns=100, lookup_ns=100)
    assert faster.accepted


def test_no_physical_evidence_does_not_create_residency_candidate():
    from scar.analysis.materialization import materialization_candidates

    value = {"logical_version": "s:v0", "device": "cuda:0"}
    graph = ExecutionGraph([Event(kind="transfer", inputs=[value], outputs=[value]),
                            Event(kind="transfer", inputs=[value], outputs=[value])])
    assert materialization_candidates(graph) == []


def test_dynamic_waits_are_detected_without_double_counting_aggregates():
    graph = ExecutionGraph([
        Event(kind="cuda_barrier", duration_ns=100,
              metadata={"operation": "cudaDeviceSynchronize"}),
        Event(kind="cuda_barrier", duration_ns=200,
              metadata={"operation": "cudaDeviceSynchronize"}),
        Event(kind="torch_op", code_id="cudaDeviceSynchronize", resource={"count": 2}),
    ])
    candidate, = synchronization_candidates(graph)
    assert candidate.supporting_events == [0, 1]
    assert "300 ns" in candidate.reason
    assert candidate.expected_savings_ns is None
    assert candidate.decision == "rejected"
