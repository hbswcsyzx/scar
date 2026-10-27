from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class CostDecision:
    accepted: bool
    saved_ns: int | None
    overhead_ns: int | None
    reason: str


def decide(expected_savings_ns: int | None, guard_ns: int | None = None,
           lookup_ns: int | None = None, memory_bytes: int | None = None,
           memory_budget_bytes: int | None = None) -> CostDecision:
    values = (expected_savings_ns, guard_ns, lookup_ns, memory_bytes, memory_budget_bytes)
    if any(value is not None and value < 0 for value in values):
        raise ValueError("cost and budget values must be non-negative")
    overhead = guard_ns + lookup_ns if guard_ns is not None and lookup_ns is not None else None
    if memory_budget_bytes is not None and memory_bytes is not None and memory_bytes > memory_budget_bytes:
        return CostDecision(False, expected_savings_ns, overhead,
                            "memory occupation exceeds configured budget")
    if memory_budget_bytes is not None and memory_bytes is None:
        return CostDecision(False, expected_savings_ns, overhead,
                            "cost evidence incomplete: retained memory is unknown")
    if expected_savings_ns is None or overhead is None:
        return CostDecision(False, expected_savings_ns, overhead,
                            "cost evidence incomplete: saved work or guard/lookup overhead is unknown")
    if expected_savings_ns <= overhead:
        return CostDecision(False, expected_savings_ns, overhead,
                            "not profitable: guard and lookup cost meet or exceed saved work")
    return CostDecision(True, expected_savings_ns, overhead, "estimated profitable")
