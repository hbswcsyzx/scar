from __future__ import annotations

from dataclasses import asdict

from scar.analysis import detect
from scar.ir import ExecutionGraph, ProofStatus, proof
from .cost import decide


def plan(graph: ExecutionGraph, memory_budget_bytes: int | None = None):
    return plan_candidates(detect(graph), memory_budget_bytes=memory_budget_bytes)


def plan_candidates(candidates, memory_budget_bytes: int | None = None):
    plans = []
    for candidate in candidates:
        decision = decide(candidate.expected_savings_ns,
                          guard_ns=candidate.guard_cost_ns,
                          lookup_ns=candidate.lookup_cost_ns,
                          memory_bytes=candidate.estimated_memory_bytes,
                          memory_budget_bytes=memory_budget_bytes)
        candidate.cost_assessment = asdict(decision)
        candidate.proof_obligations = [
            item for item in candidate.proof_obligations
            if item.name != "cost_profitable"
        ]
        if decision.accepted:
            cost_status = ProofStatus.PROVEN
            cost_evidence = "Measured"
        elif "incomplete" in decision.reason:
            cost_status = ProofStatus.UNKNOWN
            cost_evidence = "UNKNOWN"
        else:
            cost_status = ProofStatus.DISPROVEN
            cost_evidence = "Measured"
        candidate.proof_obligations.append(proof(
            "cost_profitable", "cost",
            "saved work exceeds guard and lookup overhead within the memory budget",
            cost_status, evidence=cost_evidence, reason=decision.reason,
            supporting_events=list(candidate.supporting_events),
            details={
                "saved_ns": decision.saved_ns,
                "overhead_ns": decision.overhead_ns,
                "retained_memory_bytes": candidate.estimated_memory_bytes,
                "memory_budget_bytes": memory_budget_bytes,
            },
        ))
        preconditions = [
            item for item in candidate.proof_obligations
            if item.required and item.category in {"applicability", "legality", "backend"}
        ]
        blocker = next((item for item in preconditions
                        if item.status != ProofStatus.PROVEN), None)
        if decision.accepted and candidate.decision == "proposed" and blocker is None:
            candidate.decision = "accepted"
        elif decision.accepted and candidate.decision == "proposed" and blocker is not None:
            candidate.decision = "rejected"
            candidate.rejection_reason = (
                f"proof obligation {blocker.name} is {blocker.status.value}: "
                f"{blocker.reason or blocker.claim}"
            )
        if not decision.accepted and candidate.decision == "proposed":
            candidate.decision = "rejected"
            candidate.rejection_reason = decision.reason
        plans.append(candidate)
    return plans
