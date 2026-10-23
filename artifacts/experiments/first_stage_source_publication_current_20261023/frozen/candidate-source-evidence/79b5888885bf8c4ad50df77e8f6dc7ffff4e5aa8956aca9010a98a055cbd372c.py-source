"""Strict declarations for synchronous cleanup and handled-context protocols.

Pending payloads, current state and saved handled context have separate canonical
values. These records only name existing core endpoints: scope containment,
state effects, activation-local forwarding, freshness and unwind destinations
need graph validation. Constructing them grants no source or runtime authority.
"""
from __future__ import annotations

from dataclasses import dataclass

from scar.ir.program.frames import FrameRules
from scar.ir.program.ids import (
    BlockID, ControlPortID, ControlScopeID, LocationID, OperationID, RegionID,
    UseID, ValueID,
)
from scar.ir.program.structured import ControlEdgeReference


def _exact(value, expected, name):
    if type(value) is not expected:
        raise TypeError(f"{name} must be {expected.__name__}")


def _record(value, expected, name):
    _exact(value, expected, name)
    value.__post_init__()


def _action(operation, cleanup):
    _exact(operation, OperationID, "cleanup operation")
    _exact(cleanup, ControlScopeID, "cleanup scope")


@dataclass(frozen=True, slots=True)
class HandledContextDomain:
    """Declare a use of an existing state location, without another world."""

    region: RegionID
    location: LocationID

    def __post_init__(self):
        _exact(self.region, RegionID, "handled-context region")
        _exact(self.location, LocationID, "handled-context location")


@dataclass(frozen=True, slots=True)
class CleanupInterface:
    """A lexical interface with fixed, explicitly unproved frame conditions."""

    scope: ControlScopeID
    protected: ControlScopeID
    entry: BlockID
    pending_argument: ValueID
    rules: FrameRules = FrameRules()

    def __post_init__(self):
        _exact(self.scope, ControlScopeID, "cleanup interface scope")
        _exact(self.protected, ControlScopeID, "cleanup protected scope")
        _exact(self.entry, BlockID, "cleanup entry")
        _exact(self.pending_argument, ValueID, "cleanup pending argument")
        _record(self.rules, FrameRules, "cleanup frame rules")


@dataclass(frozen=True, slots=True)
class CleanupEnter:
    """Name entry's pending operand and the saved-context canonical result."""

    operation: OperationID
    cleanup: ControlScopeID
    pending: UseID
    saved_context: ValueID

    def __post_init__(self):
        _action(self.operation, self.cleanup)
        _exact(self.pending, UseID, "cleanup enter pending")
        _exact(self.saved_context, ValueID, "cleanup saved context result")


@dataclass(frozen=True, slots=True)
class CleanupResume:
    """Restore context and forward pending through an existing CFG edge."""

    operation: OperationID
    cleanup: ControlScopeID
    pending: UseID
    context: UseID
    continuation: ControlEdgeReference

    def __post_init__(self):
        _action(self.operation, self.cleanup)
        _exact(self.pending, UseID, "cleanup resume pending")
        _exact(self.context, UseID, "cleanup resume context")
        _record(self.continuation, ControlEdgeReference, "cleanup continuation")


@dataclass(frozen=True, slots=True)
class CleanupReplace:
    """Retain separate saved/new pending Uses and the context restoration Use."""

    operation: OperationID
    cleanup: ControlScopeID
    saved_pending: UseID
    replacement: UseID
    context: UseID
    continuation: ControlEdgeReference

    def __post_init__(self):
        _action(self.operation, self.cleanup)
        _exact(self.saved_pending, UseID, "cleanup saved pending")
        _exact(self.replacement, UseID, "cleanup replacement pending")
        _exact(self.context, UseID, "cleanup replacement context")
        _record(self.continuation, ControlEdgeReference, "cleanup continuation")


@dataclass(frozen=True, slots=True)
class HandledContextRead:
    """Declare an abstract primitive's reference result, not a Python lookup."""

    operation: OperationID
    exception_result: ValueID

    def __post_init__(self):
        _exact(self.operation, OperationID, "handled-context read operation")
        _exact(self.exception_result, ValueID, "handled-context exception result")


@dataclass(frozen=True, slots=True)
class CleanupRouteSuccessor:
    """A next-hop case forwarding core Uses without projecting the payload."""

    port: ControlPortID
    block: BlockID
    arguments: tuple[UseID, ...]

    def __post_init__(self):
        _exact(self.port, ControlPortID, "cleanup route port")
        _exact(self.block, BlockID, "cleanup route block")
        _exact(self.arguments, tuple, "cleanup route arguments")
        for argument in self.arguments:
            _exact(argument, UseID, "cleanup route argument")


@dataclass(frozen=True, slots=True)
class CleanupRouteTerminator:
    """Select the next cleanup obligation; final dispatch remains a C0 action.

    Case coverage, actual operand ownership, current-state forwarding and the
    next Enter/Replace/dispatch destination are graph obligations. A shared
    destination block is representable; it is not a proof of a legal route.
    """

    pending: UseID
    successors: tuple[CleanupRouteSuccessor, ...]

    def __post_init__(self):
        _exact(self.pending, UseID, "cleanup route pending")
        _exact(self.successors, tuple, "cleanup route successors")
        for successor in self.successors:
            _record(successor, CleanupRouteSuccessor, "cleanup route successor")
        if not self.successors:
            raise ValueError("cleanup route needs nonempty successors")
        if len({successor.port for successor in self.successors}) != len(self.successors):
            raise ValueError("cleanup route successor ports must be distinct")

    @property
    def kind(self):
        # model imports these records; resolve the enum only on access.
        from scar.ir.program.model import TerminatorKind
        return TerminatorKind.CLEANUP_ROUTE

    @property
    def condition(self):
        return None

    @property
    def exit(self):
        return None

    @property
    def values(self):
        return ()


__all__ = [
    "HandledContextDomain", "CleanupInterface", "CleanupEnter", "CleanupResume",
    "CleanupReplace", "HandledContextRead", "CleanupRouteSuccessor",
    "CleanupRouteTerminator",
]
