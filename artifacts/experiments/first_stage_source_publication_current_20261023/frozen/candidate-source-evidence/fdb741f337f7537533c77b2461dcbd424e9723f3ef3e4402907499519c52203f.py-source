"""Associations between one body drive and its persistent activation."""
from __future__ import annotations

from dataclasses import dataclass

from scar.ir.program.providers import ProviderFactReference
from .common import FactSource, MissingEvidence, Unresolved, _identifier, _record
from .coordinates import BlockVisitID, OperationOccurrenceID, RegionActivationID


def _endpoint(value, expected, name):
    if type(value) is expected:
        _identifier(value, expected, name)
    elif expected is BlockVisitID and type(value) is Unresolved:
        _record(value, Unresolved, name)
    elif expected is OperationOccurrenceID and type(value) is Unresolved:
        _record(value, Unresolved, name)
    else:
        raise TypeError(f"{name} must be an exact {expected.__name__} or Unresolved")


def _fact_source(value, name):
    if type(value) is ProviderFactReference:
        _record(value, ProviderFactReference, name)
    elif type(value) is MissingEvidence:
        _record(value, MissingEvidence, name)
    else:
        raise TypeError(f"{name} must be ProviderFactReference or MissingEvidence")


@dataclass(frozen=True, slots=True)
class BodyDriveExecution:
    drive: OperationOccurrenceID
    activation: RegionActivationID
    entry: BlockVisitID | Unresolved
    outcome: OperationOccurrenceID | Unresolved
    source: FactSource

    def __post_init__(self):
        _identifier(self.drive, OperationOccurrenceID, "body-drive occurrence")
        _identifier(self.activation, RegionActivationID, "body activation")
        _endpoint(self.entry, BlockVisitID, "body entry visit")
        _endpoint(self.outcome, OperationOccurrenceID, "body outcome occurrence")
        _fact_source(self.source, "body-drive execution source")


@dataclass(frozen=True, slots=True)
class BodyActivationOrigin:
    activation: RegionActivationID
    creation: OperationOccurrenceID | Unresolved
    source: FactSource

    def __post_init__(self):
        _identifier(self.activation, RegionActivationID, "body activation")
        _endpoint(self.creation, OperationOccurrenceID, "body activation creation")
        _fact_source(self.source, "body activation origin source")


__all__ = ["BodyDriveExecution", "BodyActivationOrigin"]
