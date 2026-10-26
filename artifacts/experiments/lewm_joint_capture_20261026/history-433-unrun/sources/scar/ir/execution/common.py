"""Small provenance and unresolved variants for execution records.

These records retain evidence references and gaps. Constructing them does not
open artifacts, validate a graph, or grant runtime authority.
"""
from __future__ import annotations

from dataclasses import dataclass

from scar.ir.program.providers import ProviderFactReference
from .ids import ProcessInstanceID, RunID


def _exact(value, expected, name):
    if type(value) is not expected:
        raise TypeError(f"{name} must be {expected.__name__}")


def _identifier(value, expected, name):
    _exact(value, expected, name)
    value.__post_init__()
    if type(value.value) is not str or not value.value:
        raise ValueError(f"{name} must contain a nonempty exact string")


def _record(value, expected, name):
    _exact(value, expected, name)
    value.__post_init__()


@dataclass(frozen=True, slots=True)
class MissingEvidence:
    reason: str

    def __post_init__(self):
        _exact(self.reason, str, "missing-evidence reason")
        if not self.reason:
            raise ValueError("missing-evidence reason must be nonempty")


FactSource = ProviderFactReference | MissingEvidence


@dataclass(frozen=True, slots=True)
class EvidencePoint:
    run: RunID
    process: ProcessInstanceID | None
    source: FactSource

    def __post_init__(self):
        _identifier(self.run, RunID, "evidence-point run")
        if self.process is not None:
            _identifier(self.process, ProcessInstanceID, "evidence-point process")
        if type(self.source) is ProviderFactReference:
            _record(self.source, ProviderFactReference, "evidence-point source")
        elif type(self.source) is MissingEvidence:
            _record(self.source, MissingEvidence, "evidence-point source")
        else:
            raise TypeError("evidence-point source must be a ProviderFactReference or MissingEvidence")


@dataclass(frozen=True, slots=True)
class Unresolved:
    reason: str
    point: EvidencePoint

    def __post_init__(self):
        _exact(self.reason, str, "unresolved reason")
        if not self.reason:
            raise ValueError("unresolved reason must be nonempty")
        _record(self.point, EvidencePoint, "unresolved point")


__all__ = ["MissingEvidence", "FactSource", "EvidencePoint", "Unresolved"]
