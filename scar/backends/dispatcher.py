"""Generic candidate-to-backend dispatch with an explicit no-op fallback."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Callable

from .base import BackendResult
from .residency import persistent_residency
from .reuse import exact_reuse


def apply_candidate(candidate, fn: Callable) -> BackendResult:
    """Apply one already-planned candidate to a callable."""
    if candidate.decision != "accepted":
        return BackendResult(fn, False, candidate.rejection_reason or "candidate was not accepted")
    obligations = [item for item in getattr(candidate, "proof_obligations", [])
                   if item.required]
    if obligations:
        blocker = next((item for item in obligations
                        if item.category in {"applicability", "legality", "cost", "backend"}
                        and item.status.value != "PROVEN"), None)
        if blocker is not None:
            return BackendResult(
                fn, False,
                f"proof obligation {blocker.name} is {blocker.status.value}: "
                f"{blocker.reason or blocker.claim}",
            )
        if not any(item.category == "cost" for item in obligations):
            return BackendResult(fn, False, "accepted candidate has no required cost proof")
    if candidate.backend != "exact_reuse":
        if candidate.backend == "persistent_residency":
            if not getattr(fn, "scar_residency_safe", False):
                return BackendResult(fn, False,
                                     "persistent_residency requires an explicit read-only contract")
            return BackendResult(persistent_residency(fn), True,
                                 "persistent_residency backend applied")
        return BackendResult(fn, False, f"unsupported backend: {candidate.backend}")
    if not getattr(fn, "scar_pure", False):
        return BackendResult(fn, False, "exact_reuse requires an explicit purity contract")
    return BackendResult(exact_reuse(fn), True, "exact_reuse backend applied")


def apply_candidates(candidates, functions: Mapping[str, Callable]) -> dict[str, BackendResult]:
    """Dispatch accepted candidates by generic CodeID, retaining no-op results."""
    results: dict[str, BackendResult] = {}
    for candidate in candidates:
        if not candidate.code_id or candidate.code_id in results:
            continue
        fn = functions.get(candidate.code_id)
        if fn is None:
            continue
        results[candidate.code_id] = apply_candidate(candidate, fn)
    return results
