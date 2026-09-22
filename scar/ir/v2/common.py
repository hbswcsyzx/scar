"""Shared claims and source references for the versioned IR.

These records distinguish how SCAR learned a fact from whether a proof goal is
true.  An observed runtime event can support a still-unknown legality claim;
the two axes must never be collapsed into one boolean.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .ids import SourceAtomID


class EvidenceKind(str, Enum):
    OBSERVED = "Observed"
    INFERRED = "Inferred"
    DECLARED = "Declared"
    PROPOSED = "Proposed"
    UNKNOWN = "UNKNOWN"


class ProofStatus(str, Enum):
    PROVEN = "PROVEN"
    DISPROVEN = "DISPROVEN"
    UNKNOWN = "UNKNOWN"


class Completeness(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class SourceReference:
    """A versioned source span; line number alone is never an identity."""

    atom_id: SourceAtomID
    path: str
    fingerprint: str
    start_line: int
    end_line: int
    start_column: int = 0
    end_column: int | None = None

    def __post_init__(self) -> None:
        if not self.path or not self.fingerprint:
            raise ValueError("source path and fingerprint are required")
        if self.start_line < 1 or self.end_line < self.start_line:
            raise ValueError("invalid source line span")
        if self.start_column < 0:
            raise ValueError("source start column cannot be negative")
        if self.end_column is not None and self.end_column < 0:
            raise ValueError("source end column cannot be negative")

    def as_dict(self) -> dict[str, Any]:
        return {
            "atom_id": self.atom_id.as_dict(),
            "path": self.path,
            "fingerprint": self.fingerprint,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "start_column": self.start_column,
            "end_column": self.end_column,
        }


@dataclass(frozen=True, slots=True)
class EvidenceClaim:
    """Provenance for one fact, without upgrading it to a proof."""

    kind: EvidenceKind
    references: tuple[str, ...] = ()
    scope: str | None = None
    confidence: float | None = None
    assumptions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between zero and one")
        if self.kind is EvidenceKind.UNKNOWN and self.confidence not in (None, 0.0):
            raise ValueError("UNKNOWN evidence cannot have positive confidence")

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "references": sorted(self.references),
            "scope": self.scope,
            "confidence": self.confidence,
            "assumptions": sorted(self.assumptions),
        }


@dataclass(frozen=True, slots=True)
class ProofClaim:
    """One auditable proof obligation and its evidence."""

    obligation: str
    status: ProofStatus
    evidence: tuple[EvidenceClaim, ...] = ()
    reason: str = ""
    required_next: str | None = None

    def __post_init__(self) -> None:
        if not self.obligation:
            raise ValueError("proof obligation name is required")
        if self.status is ProofStatus.UNKNOWN and not (self.required_next or self.reason):
            raise ValueError("UNKNOWN proof must explain the gap or required next action")

    def as_dict(self) -> dict[str, Any]:
        return {
            "obligation": self.obligation,
            "status": self.status.value,
            "evidence": [item.as_dict() for item in self.evidence],
            "reason": self.reason,
            "required_next": self.required_next,
        }


@dataclass(slots=True)
class ExtensionData:
    """Explicit extension namespace for facts outside the stable core schema."""

    namespace: str
    values: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"namespace": self.namespace, "values": self.values}


__all__ = [
    "Completeness", "EvidenceClaim", "EvidenceKind", "ExtensionData",
    "ProofClaim", "ProofStatus", "SourceReference",
]
