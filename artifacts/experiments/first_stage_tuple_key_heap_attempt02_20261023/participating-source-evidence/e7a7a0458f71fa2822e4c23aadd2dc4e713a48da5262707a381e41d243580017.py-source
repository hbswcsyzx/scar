"""Serializable event records and opportunity records."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from .effects import ActionLabel, Effect
from .proofs import ProofObligation, proof_summary


@dataclass(slots=True)
class Event:
    kind: str
    ts_ns: int = field(default_factory=time.perf_counter_ns)
    duration_ns: int | None = None
    code_id: str | None = None
    invocation_id: int | None = None
    labels: list[str] = field(default_factory=list)
    inputs: list[dict[str, Any]] = field(default_factory=list)
    outputs: list[dict[str, Any]] = field(default_factory=list)
    effect: Effect = field(default_factory=Effect)
    resource: dict[str, Any] = field(default_factory=dict)
    evidence: str = "Observed"
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["effect"] = self.effect.as_dict()
        return d


@dataclass(slots=True)
class Opportunity:
    kind: str
    code_id: str | None
    evidence: str
    applicability: str
    guard: str
    reason: str
    supporting_events: list[int] = field(default_factory=list)
    expected_savings_ns: int | None = None
    estimated_memory_bytes: int | None = None
    guard_cost_ns: int | None = None
    lookup_cost_ns: int | None = None
    cost_assessment: dict[str, Any] = field(default_factory=dict)
    decision: str = "proposed"
    backend: str | None = None
    rejection_reason: str | None = None
    proof_obligations: list[ProofObligation] = field(default_factory=list)

    def __post_init__(self) -> None:
        normalized: list[ProofObligation] = []
        for item in self.proof_obligations:
            normalized.append(item if isinstance(item, ProofObligation)
                              else ProofObligation(**item))
        self.proof_obligations = normalized

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["proof_obligations"] = [item.as_dict() for item in self.proof_obligations]
        value["proof_summary"] = proof_summary(self.proof_obligations)
        return value


def json_line(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)
