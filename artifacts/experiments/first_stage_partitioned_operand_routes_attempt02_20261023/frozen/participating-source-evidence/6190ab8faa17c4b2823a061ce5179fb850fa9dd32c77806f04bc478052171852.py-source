"""Query-only scopes for composing explicit contract obligations.

These records are analysis inputs, not execution facts or persistent model
rows.  A scope selects one exact contract and one run/activation/operation
owner for a particular query.
"""
from __future__ import annotations

from dataclasses import dataclass

from scar.ir.program.providers import ProviderFactReference

from .common import MissingEvidence, _identifier, _record
from .ids import OperationOccurrenceID, RegionActivationID, RunID
from .observations import ContractRef


@dataclass(frozen=True, slots=True)
class CompositionScope:
    contract: ContractRef
    owner: RunID | RegionActivationID | OperationOccurrenceID
    source: ProviderFactReference | MissingEvidence

    def __post_init__(self) -> None:
        _record(self.contract, ContractRef, "composition contract")
        if type(self.owner) not in (RunID, RegionActivationID, OperationOccurrenceID):
            raise TypeError("composition owner must be an exact RunID, RegionActivationID, or OperationOccurrenceID")
        _identifier(self.owner, type(self.owner), "composition owner")
        if type(self.source) not in (ProviderFactReference, MissingEvidence):
            raise TypeError("composition source must be a ProviderFactReference or MissingEvidence")
        self.source.__post_init__()


__all__ = ["CompositionScope"]
