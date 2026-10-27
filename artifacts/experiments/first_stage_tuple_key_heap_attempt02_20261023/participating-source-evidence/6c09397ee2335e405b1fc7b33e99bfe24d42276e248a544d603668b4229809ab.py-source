"""Detect synchronization and host materialization signals conservatively."""
from __future__ import annotations

from collections import defaultdict

from scar.ir import ExecutionGraph, Opportunity, ProofStatus, proof


_SCALAR_NAMES = {"aten::item", "aten::_local_scalar_dense", "item"}
_BARRIER_NAMES = {"cudadevicesynchronize", "aten::synchronize"}


def synchronization_candidates(graph: ExecutionGraph) -> list[Opportunity]:
    result: list[Opportunity] = []
    dynamic = defaultdict(list)
    for idx, event in enumerate(graph.events):
        if event.kind == "cuda_barrier":
            dynamic[str(event.metadata.get("operation", "unknown"))].append((idx, event))
    observed_names = {name.lower() for name in dynamic}
    for name, calls in dynamic.items():
        duration = sum(event.duration_ns or 0 for _, event in calls)
        result.append(Opportunity(
            kind="SynchronizationCandidate", code_id=None, evidence="Observed",
            applicability="measured_runtime_wait",
            guard="stream/event, host consumer, escape and exception dependencies must prove removable waiting",
            reason=(f"Kineto observed {len(calls)} {name} calls with {duration} ns total host API duration; "
                    "this is not an estimate of removable time"),
            supporting_events=[idx for idx, _ in calls], expected_savings_ns=None,
            decision="rejected", rejection_reason="consumer or ordering guard is incomplete",
            proof_obligations=[
                proof(
                    "runtime_wait_observed", "applicability",
                    "a physical host or device wait occurs in the observed execution",
                    ProofStatus.PROVEN, evidence="Observed",
                    reason=f"Kineto observed {len(calls)} wait activities",
                    supporting_events=[idx for idx, _ in calls],
                ),
                proof(
                    "wait_has_no_required_consumer", "legality",
                    "removing or moving the wait preserves stream, host consumer, escape, exception and external ordering",
                    ProofStatus.UNKNOWN, evidence="UNKNOWN",
                    reason="the trace does not contain a complete happens-before and consumer proof",
                    supporting_events=[idx for idx, _ in calls],
                ),
            ],
        ))
    for idx, event in enumerate(graph.events):
        if event.kind != "torch_op" or not event.code_id:
            continue
        name = str(event.code_id)
        lowered = name.lower()
        if lowered in observed_names:
            continue  # A profiler aggregate is not another set of dynamic calls.
        count = int(event.resource.get("count", event.invocation_id or 0))
        if name in _SCALAR_NAMES or lowered in _BARRIER_NAMES:
            if count < 1:
                continue
            scalar = name in _SCALAR_NAMES
            result.append(Opportunity(
                kind="DeferredMaterializationCandidate" if scalar else "SynchronizationCandidate",
                code_id=name, evidence="Observed",
                applicability="repeated_host_scalar_materialization" if scalar else "explicit_device_barrier",
                guard=("consumer, escape, exception, ordering, and contract effects must prove "
                       "that materialization can be delayed" if scalar else
                       "stream/event dependencies and host-visible ordering must prove that the barrier can be removed"),
                reason=(f"profiler observed {count} host scalar materializations" if scalar else
                        f"profiler observed {count} explicit device synchronization calls"),
                supporting_events=[idx], expected_savings_ns=event.duration_ns or 0,
                decision="rejected",
                rejection_reason="consumer or ordering guard is incomplete",
                proof_obligations=[
                    proof(
                        "host_materialization_or_barrier_observed", "applicability",
                        ("a device value is materialized for host scalar use"
                         if scalar else "an explicit device synchronization is invoked"),
                        ProofStatus.PROVEN, evidence="Observed",
                        reason=f"profiler observed {count} calls", supporting_events=[idx],
                    ),
                    proof(
                        "defer_or_remove_preserves_consumers", "legality",
                        "all consumers, branches, exceptions, escapes and ordering remain equivalent",
                        ProofStatus.UNKNOWN, evidence="UNKNOWN",
                        reason="aggregate operator evidence lacks complete consumer and ordering dependencies",
                        supporting_events=[idx],
                    ),
                ],
            ))
    return result
