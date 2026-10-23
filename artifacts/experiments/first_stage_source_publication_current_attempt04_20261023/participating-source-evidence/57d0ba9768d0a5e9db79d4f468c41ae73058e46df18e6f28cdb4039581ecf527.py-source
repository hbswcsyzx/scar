"""Machine-readable proof obligations for graph simplification.

Candidates are hypotheses.  A repeated node or a static label is not a
transformation instruction until every required claim has evidence.  This
module gives detectors, planners and selectors one small vocabulary for those
claims instead of making the selector parse human-readable rejection text.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class ProofStatus(str, Enum):
    """Three-valued proof state; missing evidence is always ``UNKNOWN``."""

    PROVEN = "PROVEN"
    DISPROVEN = "DISPROVEN"
    UNKNOWN = "UNKNOWN"


_CATEGORIES = frozenset({
    "applicability", "legality", "cost", "backend", "validation",
})


@dataclass(slots=True)
class ProofObligation:
    """One auditable claim required by a candidate transformation.

    ``evidence`` names the provenance class (for example ``Observed`` or
    ``Inferred``), while ``status`` states whether that evidence proves the
    claim.  Inferred syntax can therefore support a useful hypothesis while
    the claim itself remains unknown.
    """

    name: str
    category: str
    claim: str
    status: ProofStatus = ProofStatus.UNKNOWN
    evidence: str = "UNKNOWN"
    reason: str = ""
    supporting_events: list[int] = field(default_factory=list)
    supporting_nodes: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    required: bool = True

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("proof obligation name must be non-empty")
        if self.category not in _CATEGORIES:
            raise ValueError(f"unsupported proof category: {self.category!r}")
        self.status = ProofStatus(self.status)

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        return value


def proof(name: str, category: str, claim: str, status: ProofStatus | str,
          *, evidence: str = "UNKNOWN", reason: str = "",
          supporting_events: list[int] | None = None,
          supporting_nodes: list[str] | None = None,
          details: dict[str, Any] | None = None,
          required: bool = True) -> ProofObligation:
    """Concise constructor used by generic detectors."""
    return ProofObligation(
        name=name, category=category, claim=claim, status=ProofStatus(status),
        evidence=evidence, reason=reason,
        supporting_events=list(supporting_events or []),
        supporting_nodes=list(supporting_nodes or []),
        details=dict(details or {}), required=required,
    )


def proof_summary(obligations: list[ProofObligation]) -> dict[str, Any]:
    """Summarize required proof state without inventing missing obligations."""
    counts = {state.value: 0 for state in ProofStatus}
    by_category: dict[str, dict[str, int]] = {}
    for item in obligations:
        if not item.required:
            continue
        counts[item.status.value] += 1
        bucket = by_category.setdefault(
            item.category, {state.value: 0 for state in ProofStatus})
        bucket[item.status.value] += 1
    required_count = sum(counts.values())
    return {
        "required": required_count,
        "counts": counts,
        "by_category": by_category,
        "complete": required_count > 0 and counts[ProofStatus.UNKNOWN.value] == 0,
        "all_proven": required_count > 0 and counts[ProofStatus.UNKNOWN.value] == 0
        and counts[ProofStatus.DISPROVEN.value] == 0,
    }


__all__ = ["ProofObligation", "ProofStatus", "proof", "proof_summary"]
