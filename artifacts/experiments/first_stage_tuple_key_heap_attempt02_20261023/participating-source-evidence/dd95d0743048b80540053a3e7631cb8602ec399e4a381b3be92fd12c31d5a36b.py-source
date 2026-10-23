"""Memory allocation opportunity detection from runtime evidence."""
from __future__ import annotations

from scar.ir import ExecutionGraph, Opportunity, ProofStatus, proof


_ALLOC_OPS = {
    "aten::empty", "aten::empty_strided", "aten::empty.memory_format",
    "aten::zeros", "aten::ones", "aten::clone", "aten::new_empty",
}


def allocation_candidates(graph: ExecutionGraph) -> list[Opportunity]:
    out: list[Opportunity] = []
    for idx, event in enumerate(graph.events):
        if event.kind != "torch_op" or not event.code_id:
            continue
        name = str(event.code_id).lower()
        if name not in _ALLOC_OPS:
            continue
        count = int(event.resource.get("count", 0))
        if count < 2:
            continue
        memory_bytes = max(
            abs(int(event.resource.get("self_device_memory_usage", 0))),
            abs(int(event.resource.get("device_memory_usage", 0))),
            abs(int(event.resource.get("self_cpu_memory_usage", 0))),
            abs(int(event.resource.get("cpu_memory_usage", 0))),
        )
        out.append(Opportunity(
            kind="AllocationReuseCandidate", code_id=event.code_id,
            evidence="Observed", applicability="repeated_runtime_allocation",
            guard=("allocation lifetime, alias overlap, writes, escapes, peak-memory "
                   "budget, and allocator ordering must be proven"),
            reason=(f"profiler observed {count} executions of allocation-like operator"
                    + (f"; measured memory delta {memory_bytes} bytes" if memory_bytes else
                       "; memory delta was unavailable")),
            supporting_events=[idx], expected_savings_ns=int(event.duration_ns or 0),
            # Aggregated net allocation deltas are not retained/peak memory.
            # Lifetime analysis is needed before estimating buffer residency.
            estimated_memory_bytes=None,
            decision="rejected", rejection_reason="allocation lifetime and alias guard is incomplete",
            proof_obligations=[
                proof(
                    "repeated_allocation", "applicability",
                    "the allocation action executes repeatedly in the observed run",
                    ProofStatus.PROVEN, evidence="Observed",
                    reason=f"profiler count is {count}", supporting_events=[idx],
                ),
                proof(
                    "buffer_lifetimes_do_not_overlap", "legality",
                    "old and new buffer live ranges permit one storage allocation to be reused",
                    ProofStatus.UNKNOWN, evidence="UNKNOWN",
                    reason="aggregate profiler memory deltas do not prove allocation lifetimes",
                    supporting_events=[idx],
                ),
                proof(
                    "buffer_aliases_and_escapes_safe", "legality",
                    "no live alias or escaped consumer observes destructive buffer reuse",
                    ProofStatus.UNKNOWN, evidence="UNKNOWN",
                    reason="alias and escape sets are incomplete",
                    supporting_events=[idx],
                ),
            ],
        ))
    return out
