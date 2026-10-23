"""Dynamic associations between a canonical call and its callee activation."""
from __future__ import annotations

from dataclasses import dataclass

from scar.ir.program.providers import ProviderFactReference
from .common import MissingEvidence, Unresolved, _identifier, _record
from .coordinates import BlockVisitID, OperationOccurrenceID, RegionActivationID
from .ids import CallActivationID


@dataclass(frozen=True, slots=True)
class CallActivation:
    id: CallActivationID
    caller: OperationOccurrenceID
    activation: RegionActivationID
    entry: BlockVisitID | Unresolved
    completion: OperationOccurrenceID | Unresolved
    source: ProviderFactReference | MissingEvidence

    def __post_init__(self) -> None:
        _identifier(self.id, CallActivationID, "call activation ID")
        _identifier(self.caller, OperationOccurrenceID, "call activation caller")
        _identifier(self.activation, RegionActivationID, "callee region activation")
        if type(self.entry) is BlockVisitID:
            _identifier(self.entry, BlockVisitID, "callee entry visit")
        elif type(self.entry) is Unresolved:
            _record(self.entry, Unresolved, "callee entry")
        else:
            raise TypeError("callee entry must be an exact BlockVisitID or Unresolved")
        if type(self.completion) is OperationOccurrenceID:
            _identifier(self.completion, OperationOccurrenceID, "callee completion occurrence")
        elif type(self.completion) is Unresolved:
            _record(self.completion, Unresolved, "callee completion")
        else:
            raise TypeError("callee completion must be an exact OperationOccurrenceID or Unresolved")
        if type(self.source) is ProviderFactReference:
            _record(self.source, ProviderFactReference, "call activation source")
        elif type(self.source) is MissingEvidence:
            _record(self.source, MissingEvidence, "call activation source")
        else:
            raise TypeError("call activation source must be a fact reference or MissingEvidence")


__all__ = ["CallActivation"]
