import json

from scar.ir import Event
from scar.trace.cuda import correlate_transfer_states, profiler_activities
from scar.analysis.materialization import materialization_candidates
from scar.ir import ExecutionGraph
from scar.trace.resources import ResourceSampler


def test_cuda_copy_requires_gpu_activity_and_preserves_correlation(tmp_path):
    path = tmp_path / "torch-profiler.42.json"
    records = [
        {"ph": "X", "cat": "cuda_runtime", "name": "cudaMemcpyAsync",
         "pid": 42, "tid": 43, "ts": 100, "dur": 20, "args": {"correlation": 7}},
        {"ph": "X", "cat": "gpu_memcpy", "name": "Memcpy HtoD (Pageable -> Device)",
         "pid": 0, "tid": 2, "ts": 104, "dur": 8,
         "args": {"correlation": 7, "device": 0, "stream": 2, "bytes": 4096}},
        {"ph": "X", "cat": "kernel", "name": "elementwise_kernel",
         "ts": 116, "dur": 9, "args": {"device": 0, "stream": 2}},
        {"ph": "X", "cat": "cuda_runtime", "name": "cudaStreamSynchronize",
         "ts": 117, "dur": 12, "args": {}},
    ]
    path.write_text(json.dumps({"traceEvents": records}))
    events = list(profiler_activities(path, process_id=42))
    assert [event.kind for event in events] == ["cuda_memcpy", "cuda_kernel", "cuda_barrier"]
    copy = events[0]
    assert copy.resource["bytes"] == 4096 and copy.resource["direction"] == "HtoD"
    assert copy.metadata["physical"] is True and copy.metadata["host_tid"] == 43
    assert copy.metadata["logical_tensor_mapping"] == "UNKNOWN"
    assert copy.metadata["clock_domain"] == "kineto"
    assert copy.ts_ns == 104000 and copy.duration_ns == 8000


def test_cuda_copy_can_attach_unique_logical_materialization_inference():
    transfer = Event(kind="transfer", inputs=[{"logical_version": "x:v0"}],
                     outputs=[{"logical_version": "x:v0", "storage_id": "gpu:x"}],
                     resource={"source_device": "cpu", "destination_device": "cuda:0",
                               "bytes": 4096})
    physical = Event(kind="cuda_memcpy", resource={"direction": "HtoD", "bytes": 4096},
                     metadata={"logical_tensor_mapping": "UNKNOWN"})
    counts = correlate_transfer_states([(12, transfer)], [physical])
    assert counts == {"matched_unique": 1, "ambiguous": 0, "unmatched": 0}
    assert physical.metadata["logical_tensor_mapping"] == "inferred_unique_signature"
    assert physical.metadata["mapping_confidence"] == "Inferred"
    assert physical.metadata["logical_version"] == "x:v0"


def test_cuda_copy_keeps_repeated_signature_ambiguous():
    transfers = [
        Event(kind="transfer", outputs=[{"logical_version": "x:v0"}],
              resource={"source_device": "cpu", "destination_device": "cuda:0", "bytes": 4096}),
        Event(kind="transfer", outputs=[{"logical_version": "y:v0"}],
              resource={"source_device": "cpu", "destination_device": "cuda:0", "bytes": 4096}),
    ]
    physical = Event(kind="cuda_memcpy", resource={"direction": "HtoD", "bytes": 4096},
                     metadata={"logical_tensor_mapping": "UNKNOWN"})
    counts = correlate_transfer_states(list(enumerate(transfers)), [physical])
    assert counts == {"matched_unique": 0, "ambiguous": 1, "unmatched": 0}
    assert physical.metadata["logical_tensor_mapping"] == "AMBIGUOUS_SIGNATURE"
    assert physical.metadata["mapping_confidence"] == "UNKNOWN"


def test_unique_physical_logical_links_can_form_residency_candidate():
    events = [
        Event(kind="cuda_memcpy", duration_ns=100,
              resource={"direction": "HtoD", "device": 0, "bytes": 4096},
              metadata={"logical_version": "x:v0", "mapping_confidence": "Inferred"}),
        Event(kind="cuda_memcpy", duration_ns=120,
              resource={"direction": "HtoD", "device": 0, "bytes": 4096},
              metadata={"logical_version": "x:v0", "mapping_confidence": "Inferred"}),
    ]
    candidates = materialization_candidates(ExecutionGraph(events))
    assert len(candidates) == 1
    assert candidates[0].kind == "ResidencyCandidate"
    assert candidates[0].evidence == "Inferred"
    assert candidates[0].decision == "rejected"


def test_resource_sampler_emits_machine_readable_cpu_summary(tmp_path):
    sampler = ResourceSampler(tmp_path, interval_s=0.01)
    sampler.start()
    import time
    time.sleep(0.04)
    summary = sampler.stop()
    assert summary["enabled"] is True
    assert summary["sample_count"] >= 1
    assert (tmp_path / "resources.jsonl").is_file()
    assert (tmp_path / "resources.summary.json").is_file()
    assert summary["evidence"] == "Observed"
