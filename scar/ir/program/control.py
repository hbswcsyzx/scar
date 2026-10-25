"""Typed declarations for synchronous language completion payloads and ports.

These records express static interfaces, not evidence of source correspondence
or an implemented cleanup adapter. Pending control, mutable state and active
exception context are separate: no record here freezes an exception's mutable
attributes, snapshots a returned object or authorizes finally execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from scar.ir.program.ids import (
    BlockID, ControlPortID, ControlScopeID, RegionID, UseID, ValueID,
)
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import SourceAtomID
from scar.ir.program.source_subjects import ModuleUnitSource


def _exact(value, expected, name):
    if type(value) is not expected:
        raise TypeError(f"{name} must be {expected.__name__}")


def _source_reference(source):
    """Recheck existing source field types without adding source truth claims."""
    _exact(source, SourceReference, "control scope source")
    _exact(source.atom_id, SourceAtomID, "source atom")
    for name in ("path", "fingerprint"):
        _exact(getattr(source, name), str, f"source {name}")
        if not getattr(source, name):
            raise ValueError(f"source {name} must be nonempty")
    for name in ("start_line", "end_line", "start_column"):
        _exact(getattr(source, name), int, f"source {name}")
    if source.end_column is not None:
        _exact(source.end_column, int, "source end_column")
    if source.start_line < 1 or source.end_line < source.start_line:
        raise ValueError("invalid source line span")
    if source.start_column < 0 or (source.end_column is not None and source.end_column < 0):
        raise ValueError("source columns must be nonnegative")


class ProtocolValueKind(str, Enum):
    PENDING_COMPLETION = "PENDING_COMPLETION"
    EXCEPTION_PACKET = "EXCEPTION_PACKET"
    SAVED_HANDLED_CONTEXT = "SAVED_HANDLED_CONTEXT"
    FRAME_CONTEXT = "FRAME_CONTEXT"
    DRIVE_CALLER_CONTEXT = "DRIVE_CALLER_CONTEXT"
    RAW_DRIVER_REQUEST = "RAW_DRIVER_REQUEST"


@dataclass(frozen=True, slots=True)
class ProtocolValueType:
    protocol: ProtocolValueKind

    def __post_init__(self):
        _exact(self.protocol, ProtocolValueKind, "protocol value kind")

    @property
    def kind(self):
        """Keep protocol kinds distinct from ordinary core ValueKind values."""
        return self.protocol


class LanguageCompletionKind(str, Enum):
    FALLTHROUGH = "FALLTHROUGH"
    RETURN = "RETURN"
    RAISE = "RAISE"
    BREAK = "BREAK"
    CONTINUE = "CONTINUE"


class ControlScopeKind(str, Enum):
    FUNCTION = "FUNCTION"
    FRAME = "FRAME"
    BLOCK = "BLOCK"
    LOOP = "LOOP"
    CLEANUP = "CLEANUP"


@dataclass(frozen=True, slots=True)
class ControlScope:
    """Declared lexical owner with nonempty, directly owned block identities.

    Scope nesting, graph ownership and source correspondence need graph checks
    or separate evidence. Declaring CLEANUP does not authorize execution.
    """

    id: ControlScopeID
    region: RegionID
    parent: ControlScopeID | None
    kind: ControlScopeKind
    source: SourceReference | ModuleUnitSource
    blocks: tuple[BlockID, ...]

    def __post_init__(self):
        _exact(self.id, ControlScopeID, "control scope id")
        _exact(self.region, RegionID, "control scope region")
        if self.parent is not None:
            _exact(self.parent, ControlScopeID, "control scope parent")
        _exact(self.kind, ControlScopeKind, "control scope kind")
        if type(self.source) is ModuleUnitSource:
            self.source.__post_init__()
            if self.kind is not ControlScopeKind.FRAME:
                raise ValueError("a module unit subject requires a FRAME control root")
        else:
            _source_reference(self.source)
        _exact(self.blocks, tuple, "control scope blocks")
        for block in self.blocks:
            _exact(block, BlockID, "control scope block")
        if not self.blocks or len(set(self.blocks)) != len(self.blocks):
            raise ValueError("control scope needs nonempty distinct directly owned blocks")
        if self.kind in (ControlScopeKind.FUNCTION, ControlScopeKind.FRAME):
            if self.parent is not None:
                raise ValueError("function/frame control root must not have a parent")
        elif self.parent is None:
            raise ValueError("non-root control scope needs a parent")


@dataclass(frozen=True, slots=True)
class ControlPort:
    """A declared completion destination, never an inferred live transfer."""

    id: ControlPortID
    scope: ControlScopeID
    kind: LanguageCompletionKind
    block: BlockID | None = None
    exit: str | None = None

    def __post_init__(self):
        _exact(self.id, ControlPortID, "control port id")
        _exact(self.scope, ControlScopeID, "control port scope")
        _exact(self.kind, LanguageCompletionKind, "language completion kind")
        if self.block is not None:
            _exact(self.block, BlockID, "control port block")
        if self.exit is not None:
            _exact(self.exit, str, "control port exit")
            if not self.exit:
                raise ValueError("control port exit must be nonempty")
        if (self.block is None) == (self.exit is None):
            raise ValueError("control port needs exactly one block or exit destination")
        if self.kind is LanguageCompletionKind.RETURN and self.exit is None:
            raise ValueError("RETURN control port needs an exit destination")
        if (self.kind in (LanguageCompletionKind.FALLTHROUGH,
                          LanguageCompletionKind.BREAK, LanguageCompletionKind.CONTINUE)
                and self.block is None):
            raise ValueError("FALLTHROUGH/BREAK/CONTINUE control port needs a block destination")


@dataclass(frozen=True, slots=True)
class ExceptionPacketDefinition:
    """Exception and traceback references for this particular propagation.

    A traceback operand may refer to legitimate None. It is not asserted equal
    to exception.__traceback__ at every later point. Mutable exception attributes,
    active handler context and current state are not captured by this record.
    """

    value: ValueID
    exception: UseID
    traceback: UseID

    def __post_init__(self):
        _exact(self.value, ValueID, "exception packet value")
        _exact(self.exception, UseID, "exception packet exception operand")
        _exact(self.traceback, UseID, "exception packet traceback operand")
        if self.exception == self.traceback:
            raise ValueError("exception and traceback need distinct operand UseIDs")


@dataclass(frozen=True, slots=True)
class PendingCompletionDefinition:
    """Already evaluated control payload; its referenced target stays mutable."""

    value: ValueID
    port: ControlPortID
    payload: UseID | None = None

    def __post_init__(self):
        _exact(self.value, ValueID, "pending completion value")
        _exact(self.port, ControlPortID, "pending completion port")
        if self.payload is not None:
            _exact(self.payload, UseID, "pending completion payload operand")


@dataclass(frozen=True, slots=True)
class PendingPayload:
    """Project the existing pending payload on a matching dispatch successor."""


@dataclass(frozen=True, slots=True)
class PendingSuccessor:
    port: ControlPortID
    block: BlockID
    arguments: tuple[UseID | PendingPayload, ...]

    def __post_init__(self):
        _exact(self.port, ControlPortID, "pending successor port")
        _exact(self.block, BlockID, "pending successor block")
        _exact(self.arguments, tuple, "pending successor arguments")
        if any(type(argument) not in (UseID, PendingPayload) for argument in self.arguments):
            raise TypeError("pending successor arguments must be exact UseID or PendingPayload")


@dataclass(frozen=True, slots=True)
class PendingDispatchTerminator:
    """Declared dispatch over pending ports, with current-state operands separate.

    Destination compatibility and operand ownership/availability are graph
    obligations. Reusing a target block is representable; these records neither
    authorize cleanup nor store a second table of dynamic actuals.
    """

    pending: UseID
    successors: tuple[PendingSuccessor, ...]

    def __post_init__(self):
        _exact(self.pending, UseID, "pending dispatch operand")
        _exact(self.successors, tuple, "pending dispatch successors")
        for successor in self.successors:
            _exact(successor, PendingSuccessor, "pending dispatch successor")
        if not self.successors:
            raise ValueError("pending dispatch needs nonempty successors")
        if len({successor.port for successor in self.successors}) != len(self.successors):
            raise ValueError("pending dispatch successor ports must be distinct")

    @property
    def kind(self):
        # Keep the record module importable while model imports these records.
        from scar.ir.program.model import TerminatorKind
        return TerminatorKind.PENDING_DISPATCH

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
    "ControlPort", "ControlScope", "ControlScopeKind", "ExceptionPacketDefinition",
    "LanguageCompletionKind", "PendingCompletionDefinition", "PendingDispatchTerminator",
    "PendingPayload", "PendingSuccessor", "ProtocolValueKind", "ProtocolValueType",
]
