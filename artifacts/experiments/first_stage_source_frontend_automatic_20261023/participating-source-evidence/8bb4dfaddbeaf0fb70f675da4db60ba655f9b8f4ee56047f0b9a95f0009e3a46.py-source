"""Typed relations for Python local-name bindings in the program graph."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from scar.ir.program.ids import OperationID, UseID, ValueID


class BindingState(str, Enum):
    """Information established by one local binding definition."""

    BOUND = "BOUND"
    UNBOUND = "UNBOUND"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class BindingDefinition:
    """Define the state of one LocalBindingValue.

    ``value`` must be an operation result. Block arguments are merges and get
    their state from the actual incoming CFG edges, so they have no row here.
    UNKNOWN means an imprecise update whose possible values are not asserted;
    ``previous`` and the producing operation's incomplete world access keep the
    uncertainty connected to the prior binding and effect state.
    """

    value: ValueID
    state: BindingState
    payload: UseID | None = None
    previous: UseID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.value, ValueID):
            raise TypeError("BindingDefinition.value must be ValueID")
        if not isinstance(self.state, BindingState):
            raise TypeError("BindingDefinition.state must be BindingState")
        if self.payload is not None and not isinstance(self.payload, UseID):
            raise TypeError("BindingDefinition.payload must be UseID or None")
        if self.previous is not None and not isinstance(self.previous, UseID):
            raise TypeError("BindingDefinition.previous must be UseID or None")

        if self.state is BindingState.BOUND:
            if self.payload is None:
                raise ValueError("BOUND definition requires a payload use")
        elif self.payload is not None:
            raise ValueError("UNBOUND and UNKNOWN definitions cannot assert a payload")
        if self.state is BindingState.UNKNOWN and self.previous is None:
            raise ValueError("UNKNOWN definition requires a previous binding use")
        if self.previous is not None and self.previous == self.payload:
            raise ValueError("payload and previous binding must be distinct uses")


@dataclass(frozen=True, slots=True)
class BindingRead:
    """Connect a local-binding input to a read's possible normal result.

    A missing result is valid only when validation proves the binding
    definitely UNBOUND and the operation terminates by raising. A present
    result may be a dormant NORMAL completion value of an INVOKE whose
    binding is definitely UNBOUND; derived feasibility says that completion
    cannot occur, so the value is not an ordinary successful read.
    """

    operation: OperationID
    binding: UseID
    normal_result: ValueID | None

    def __post_init__(self) -> None:
        if not isinstance(self.operation, OperationID):
            raise TypeError("BindingRead.operation must be OperationID")
        if not isinstance(self.binding, UseID):
            raise TypeError("BindingRead.binding must be UseID")
        if self.normal_result is not None and not isinstance(self.normal_result, ValueID):
            raise TypeError("BindingRead.normal_result must be ValueID or None")


__all__ = ["BindingDefinition", "BindingRead", "BindingState"]
