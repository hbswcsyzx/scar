"""Conservative selection over the unified candidate vocabulary.

Candidate generation and cost planning intentionally produce facts rather than
mutating a program.  This module is the final, generic decision layer for a
batch of candidates.  It makes the distinction between an accepted
transformation, a legal but unprofitable opportunity, an opportunity whose
legality is still unknown, and work that should remain on the original path.

The selection record is separate from :class:`~scar.ir.Opportunity` so that a
report can preserve the detector's evidence and the planner's decision without
overwriting either one.  Unknown evidence is never converted to a keep or a
transform decision merely because a candidate is repeated.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Iterable

from scar.ir import ProofStatus, proof_summary


SUPPORTED_BACKENDS = frozenset({
    "exact_reuse",
    "persistent_residency",
    "dead_expression_elimination",
})


@dataclass(slots=True)
class SimplificationDecision:
    """An auditable action selected for one candidate.

    ``action`` is deliberately small and stable:

    * ``TRANSFORM``: legality and cost were accepted and a backend is present;
    * ``REJECT``: the opportunity is understood but cost or backend selection
      rules reject it;
    * ``UNKNOWN``: evidence may support a transformation, but legality or
      cost is incomplete;
    * ``KEEP``: the candidate does not apply to the observed execution.
    """

    candidate_index: int
    kind: str
    code_id: str | None
    action: str
    legality: str
    cost: str
    backend: str | None
    reason: str
    supporting_events: list[int] = field(default_factory=list)
    selected: bool = False
    supersedes: list[int] = field(default_factory=list)
    proof_summary: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class SelectionResult:
    """All decisions plus the candidate indices selected for application."""

    decisions: list[SimplificationDecision]
    selected_indices: list[int]

    @property
    def selected(self):
        selected = set(self.selected_indices)
        return [item for item in self.decisions if item.candidate_index in selected]

    def counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for item in self.decisions:
            result[item.action] = result.get(item.action, 0) + 1
        return result

    def as_dict(self) -> dict:
        return {
            "decisions": [item.as_dict() for item in self.decisions],
            "selected_indices": list(self.selected_indices),
            "counts": self.counts(),
        }


_UNKNOWN_MARKERS = (
    "unknown", "incomplete", "cannot prove", "must be proven", "not proven",
    "not captured", "not observed", "insufficient", "missing", "unavailable",
    "effect knowledge", "guard is incomplete", "contract is incomplete",
)
_COST_REJECT_MARKERS = (
    "not profitable", "exceeds configured budget", "memory occupation exceeds",
)
_KEEP_MARKERS = (
    "changing input", "changed input", "does not apply", "unsupported",
)


def _classification(candidate) -> tuple[str, str, str, str]:
    """Return ``action, legality, cost, reason`` without changing candidate."""
    decision = str(getattr(candidate, "decision", "proposed"))
    backend = getattr(candidate, "backend", None)
    rejection = str(getattr(candidate, "rejection_reason", None) or "").lower()
    applicability = str(getattr(candidate, "applicability", "")).lower()
    assessment = getattr(candidate, "cost_assessment", {}) or {}
    cost_reason = str(assessment.get("reason", "")).lower()
    reason = str(getattr(candidate, "rejection_reason", None)
                 or getattr(candidate, "reason", "candidate was not selected"))

    obligations = [item for item in
                   getattr(candidate, "proof_obligations", []) if item.required]
    if obligations:
        by_category = {
            category: [item for item in obligations if item.category == category]
            for category in {item.category for item in obligations}
        }
        applicability_proofs = by_category.get("applicability", [])
        legality_proofs = by_category.get("legality", [])
        cost_proofs = by_category.get("cost", [])
        backend_proofs = by_category.get("backend", [])

        disproven_applicability = next(
            (item for item in applicability_proofs
             if item.status == ProofStatus.DISPROVEN), None)
        if disproven_applicability is not None:
            return ("KEEP", "violated", "not_applicable",
                    disproven_applicability.reason or disproven_applicability.claim)

        disproven_legality = next(
            (item for item in legality_proofs
             if item.status == ProofStatus.DISPROVEN), None)
        if disproven_legality is not None:
            return ("REJECT", "violated", "not_evaluated",
                    disproven_legality.reason or disproven_legality.claim)

        unknown_precondition = next(
            (item for item in applicability_proofs + legality_proofs + backend_proofs
             if item.status == ProofStatus.UNKNOWN), None)
        if unknown_precondition is not None:
            return ("UNKNOWN", "unknown", "unknown",
                    unknown_precondition.reason or unknown_precondition.claim)

        disproven_backend = next(
            (item for item in backend_proofs
             if item.status == ProofStatus.DISPROVEN), None)
        if disproven_backend is not None:
            return ("REJECT", "proven", "backend_unavailable",
                    disproven_backend.reason or disproven_backend.claim)

        disproven_cost = next(
            (item for item in cost_proofs if item.status == ProofStatus.DISPROVEN), None)
        if disproven_cost is not None:
            return ("REJECT", "proven", "unprofitable",
                    disproven_cost.reason or disproven_cost.claim)
        unknown_cost = next(
            (item for item in cost_proofs if item.status == ProofStatus.UNKNOWN), None)
        if unknown_cost is not None:
            return ("UNKNOWN", "proven", "unknown",
                    unknown_cost.reason or unknown_cost.claim)
        if decision == "accepted" and not cost_proofs:
            return ("UNKNOWN", "proven", "unknown",
                    "accepted candidate has no required cost proof")

    if decision == "accepted":
        if backend not in SUPPORTED_BACKENDS:
            return "REJECT", "proven", "accepted", f"backend unavailable: {backend}"
        return "TRANSFORM", "proven", "profitable", "candidate accepted by planner"

    if any(marker in rejection or marker in cost_reason for marker in _COST_REJECT_MARKERS):
        return "REJECT", "proven", "unprofitable", reason

    # A detector may report a repeated shape while explicitly observing that
    # its logical inputs change.  That is a known non-applicability fact even
    # when the same detector also records another unknown effect.
    if "changing" in applicability or "changed" in applicability:
        return "KEEP", "violated", "not_applicable", reason

    if any(marker in rejection for marker in _KEEP_MARKERS):
        return "KEEP", "violated", "not_applicable", reason

    if any(marker in rejection or marker in cost_reason for marker in _UNKNOWN_MARKERS):
        return "UNKNOWN", "unknown", "unknown", reason

    if decision == "proposed":
        return "UNKNOWN", "unknown", "unknown", "candidate was not cost-selected"
    if decision == "rejected":
        # A rejection without a recognizable proof or cost reason is itself
        # incomplete evidence. Keeping it visible as UNKNOWN is safer than
        # presenting it as a proven no-op.
        return "UNKNOWN", "unknown", "unknown", reason
    return "KEEP", "violated", "not_applicable", reason


def _conflict_key(candidate):
    backend = getattr(candidate, "backend", None)
    code_id = getattr(candidate, "code_id", None)
    support = tuple(sorted(set(getattr(candidate, "supporting_events", []) or [])))
    # One CodeID target can be emitted by event and graph views, or by two
    # competing backends.  Candidates without a code id are grouped only when
    # they refer to the same observed support, avoiding accidental suppression
    # of unrelated materializations.
    if code_id and backend:
        # Different backends targeting one CodeID still conflict: composing
        # two transformations without a backend-specific proof can change
        # guards, aliases, or visible ordering.
        return ("code", code_id)
    if backend and support:
        return ("support", backend, support)
    return None


def select_candidates(candidates: Iterable, *, max_transformations: int | None = None,
                      supported_backends: Iterable[str] = SUPPORTED_BACKENDS) -> SelectionResult:
    """Select a conflict-free subset while preserving every decision.

    ``candidates`` may come from static, event, or graph views.  Selection is
    conservative: only ``accepted`` candidates can transform, duplicate
    accepted candidates are resolved by evidence and measured savings, and all
    rejected/unknown candidates remain in the returned audit trail.
    """
    items = list(candidates)
    available = frozenset(supported_backends)
    decisions: list[SimplificationDecision] = []
    for index, candidate in enumerate(items):
        action, legality, cost, reason = _classification(candidate)
        backend = getattr(candidate, "backend", None)
        if action == "TRANSFORM" and backend not in available:
            action, legality, cost = "REJECT", "proven", "backend_unavailable"
            reason = f"backend unavailable in this runtime: {backend}"
        decisions.append(SimplificationDecision(
            candidate_index=index,
            kind=str(getattr(candidate, "kind", "unknown")),
            code_id=getattr(candidate, "code_id", None),
            action=action,
            legality=legality,
            cost=cost,
            backend=backend,
            reason=reason,
            supporting_events=list(getattr(candidate, "supporting_events", []) or []),
            proof_summary=proof_summary(
                list(getattr(candidate, "proof_obligations", []) or [])),
        ))

    by_key: dict[tuple, list[int]] = {}
    for index, candidate in enumerate(items):
        key = _conflict_key(candidate)
        if key is not None and decisions[index].action == "TRANSFORM":
            by_key.setdefault(key, []).append(index)

    # Prefer stronger evidence, then larger measured savings.  The original
    # candidate objects are not mutated; the result only records which one is
    # selected and why the others were superseded.
    selected: list[int] = []
    for indices in by_key.values():
        winner = max(indices, key=lambda i: (
            1 if getattr(items[i], "evidence", "") == "Observed" else 0,
            int(getattr(items[i], "expected_savings_ns", 0) or 0),
            -i,
        ))
        selected.append(winner)
        losers = [i for i in indices if i != winner]
        decisions[winner].selected = True
        decisions[winner].supersedes.extend(losers)
        for loser in losers:
            decisions[loser].action = "KEEP"
            decisions[loser].legality = "proven"
            decisions[loser].cost = "duplicate"
            decisions[loser].reason = f"superseded by candidate {winner} for the same backend target"

    # Candidates with no conflict key are independently selectable.
    for index, decision in enumerate(decisions):
        if decision.action == "TRANSFORM" and index not in selected:
            selected.append(index)
            decision.selected = True

    selected.sort()
    if max_transformations is not None:
        if max_transformations < 0:
            raise ValueError("max_transformations must be non-negative")
        for index in selected[max_transformations:]:
            decisions[index].selected = False
            decisions[index].action = "REJECT"
            decisions[index].cost = "selection_limit"
            decisions[index].reason = "transformation selection limit reached"
        selected = selected[:max_transformations]
    return SelectionResult(decisions, selected)


__all__ = ["SUPPORTED_BACKENDS", "SimplificationDecision", "SelectionResult",
           "select_candidates"]
