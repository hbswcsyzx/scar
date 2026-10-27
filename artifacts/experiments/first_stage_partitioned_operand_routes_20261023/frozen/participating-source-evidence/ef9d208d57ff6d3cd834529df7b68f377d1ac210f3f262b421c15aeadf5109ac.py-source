"""Strict static declarations for a resumable body's temporal boundaries.

Saved operands remain canonical operation Uses. Resume inputs describe a later
body ingress, without asserting its runtime instance, generation or driver.
Context switching, availability and cleanup composition need graph validation;
these records do not establish source correspondence or a Python adapter.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from scar.ir.program.ids import BlockID, LocationID, OperationID, RegionID, UseID, ValueID


def _exact(value, expected, name):
    if type(value) is not expected:
        raise TypeError(f"{name} must be {expected.__name__}")


def _record(value, expected, name):
    _exact(value, expected, name)
    value.__post_init__()


def _index(value, name):
    _exact(value, int, name)
    if value < 0:
        raise ValueError(f"{name} must be nonnegative")


class ResumableKind(str, Enum):
    GENERATOR = "GENERATOR"
    COROUTINE = "COROUTINE"
    ASYNC_GENERATOR = "ASYNC_GENERATOR"
    GENERATOR_COROUTINE = "GENERATOR_COROUTINE"


class SuspensionFlavor(str, Enum):
    YIELD = "YIELD"
    DELEGATION = "DELEGATION"
    AWAIT = "AWAIT"
    ASYNC_YIELD = "ASYNC_YIELD"


class SavedRole(str, Enum):
    VALUE = "VALUE"
    LOCAL_BINDING = "LOCAL_BINDING"
    PENDING_COMPLETION = "PENDING_COMPLETION"
    CLEANUP_CONTEXT = "CLEANUP_CONTEXT"
    FRAME_CONTEXT = "FRAME_CONTEXT"
    DELEGATE_REFERENCE = "DELEGATE_REFERENCE"


class ResumeSlotKind(str, Enum):
    STATE = "STATE"
    SENT_VALUE = "SENT_VALUE"
    THROWN_PACKET = "THROWN_PACKET"
    DELEGATE_VALUE = "DELEGATE_VALUE"
    DELEGATE_PACKET = "DELEGATE_PACKET"


@dataclass(frozen=True, slots=True)
class ResumableBody:
    region: RegionID
    kind: ResumableKind
    context_location: LocationID

    def __post_init__(self):
        _exact(self.region, RegionID, "resumable body region")
        _exact(self.kind, ResumableKind, "resumable body kind")
        _exact(self.context_location, LocationID, "resumable context location")


@dataclass(frozen=True, slots=True)
class FrameContextInitial:
    operation: OperationID
    frame: ValueID

    def __post_init__(self):
        _exact(self.operation, OperationID, "initial frame operation")
        _exact(self.frame, ValueID, "initial frame result")


@dataclass(frozen=True, slots=True)
class FrameContextAttach:
    operation: OperationID
    frame: UseID
    caller: ValueID

    def __post_init__(self):
        _exact(self.operation, OperationID, "frame attach operation")
        _exact(self.frame, UseID, "frame attach operand")
        _exact(self.caller, ValueID, "caller context result")


@dataclass(frozen=True, slots=True)
class FrameContextDetach:
    operation: OperationID
    caller: UseID
    frame: ValueID

    def __post_init__(self):
        _exact(self.operation, OperationID, "frame detach operation")
        _exact(self.caller, UseID, "caller context operand")
        _exact(self.frame, ValueID, "detached frame result")


@dataclass(frozen=True, slots=True)
class SavedSlot:
    role: SavedRole
    use: UseID

    def __post_init__(self):
        _exact(self.role, SavedRole, "saved slot role")
        _exact(self.use, UseID, "saved slot operand")


@dataclass(frozen=True, slots=True)
class SavedInput:
    saved_slot: int

    def __post_init__(self):
        _index(self.saved_slot, "saved slot index")


@dataclass(frozen=True, slots=True)
class ResumeInput:
    resume_slot: int

    def __post_init__(self):
        _index(self.resume_slot, "resume slot index")


@dataclass(frozen=True, slots=True)
class ResumeSlot:
    kind: ResumeSlotKind
    location: LocationID | None = None

    def __post_init__(self):
        _exact(self.kind, ResumeSlotKind, "resume slot kind")
        if self.location is not None:
            _exact(self.location, LocationID, "resume state location")
        if self.kind is ResumeSlotKind.STATE:
            if self.location is None:
                raise ValueError("STATE resume slot needs a location")
        elif self.location is not None:
            raise ValueError("only STATE resume slots may carry a location")


@dataclass(frozen=True, slots=True)
class ResumeSuccessor:
    """One temporal ingress; saved sources are resolved at its Suspend."""

    inputs: tuple[ResumeSlot, ...]
    block: BlockID
    arguments: tuple[SavedInput | ResumeInput, ...]

    def __post_init__(self):
        _exact(self.inputs, tuple, "resume successor inputs")
        for slot in self.inputs:
            _record(slot, ResumeSlot, "resume successor input")
        _exact(self.block, BlockID, "resume successor block")
        _exact(self.arguments, tuple, "resume successor arguments")
        for argument in self.arguments:
            if type(argument) not in (SavedInput, ResumeInput):
                raise TypeError("resume arguments must be exact SavedInput or ResumeInput")
            argument.__post_init__()
        if sum(slot.kind is not ResumeSlotKind.STATE for slot in self.inputs) != 1:
            raise ValueError("resume successor needs exactly one delivered payload")
        locations = [slot.location for slot in self.inputs if slot.kind is ResumeSlotKind.STATE]
        if len(set(locations)) != len(locations):
            raise ValueError("resume state locations must be distinct")
        projected = [argument.resume_slot for argument in self.arguments
                     if type(argument) is ResumeInput]
        if (len(set(projected)) != len(projected)
                or set(projected) != set(range(len(self.inputs)))):
            raise ValueError("every resume input slot must bind exactly once")


@dataclass(frozen=True, slots=True)
class SuspendTerminator:
    """Export this drive's payload/state and name possible later ingress edges."""

    flavor: SuspensionFlavor
    exported: UseID
    saved: tuple[SavedSlot, ...]
    handoff: tuple[UseID, ...]
    successors: tuple[ResumeSuccessor, ...]

    def __post_init__(self):
        _exact(self.flavor, SuspensionFlavor, "suspension flavor")
        _exact(self.exported, UseID, "suspension exported operand")
        _exact(self.saved, tuple, "suspension saved slots")
        for slot in self.saved:
            _record(slot, SavedSlot, "suspension saved slot")
        if sum(slot.role is SavedRole.FRAME_CONTEXT for slot in self.saved) != 1:
            raise ValueError("suspension needs exactly one FRAME_CONTEXT saved slot")
        _exact(self.handoff, tuple, "suspension state handoff")
        for use in self.handoff:
            _exact(use, UseID, "suspension handoff operand")
        if len(set(self.values)) != len(self.values):
            raise ValueError("suspension owned operand UseIDs must be distinct")
        _exact(self.successors, tuple, "suspension successors")
        for successor in self.successors:
            _record(successor, ResumeSuccessor, "suspension successor")
            for argument in successor.arguments:
                if type(argument) is SavedInput and argument.saved_slot >= len(self.saved):
                    raise ValueError("saved input index exceeds suspension saved slots")
        if not self.successors:
            raise ValueError("suspension needs nonempty successors")
        if len({edge.block for edge in self.successors}) != len(self.successors):
            raise ValueError("resume successor targets must be distinct")

    @property
    def kind(self):
        from scar.ir.program.model import TerminatorKind
        return TerminatorKind.SUSPEND

    @property
    def condition(self):
        return None

    @property
    def exit(self):
        return None

    @property
    def values(self):
        return (self.exported, *(slot.use for slot in self.saved), *self.handoff)


def saved_actual_use(operation, argument):
    """Resolve an existing actual Use, never an external resume result.

    Preserve historic UseID subclasses and object identity on ordinary edges.
    Malformed or unrelated projections supply no copy/freshness evidence.
    """
    if isinstance(argument, UseID):
        return argument
    term = getattr(operation, "terminator", None)
    if type(argument) is not SavedInput or type(term) is not SuspendTerminator:
        return None
    index = argument.saved_slot
    if type(index) is not int or index < 0 or index >= len(term.saved):
        return None
    slot = term.saved[index]
    return slot.use if type(slot) is SavedSlot and isinstance(slot.use, UseID) else None


def resume_slot_type(slot):
    """Derive an ingress slot's existing core type without a module cycle."""
    _record(slot, ResumeSlot, "resume slot")
    from scar.ir.program.control import ProtocolValueKind, ProtocolValueType
    from scar.ir.program.model import ValueKind, ValueType

    if slot.kind is ResumeSlotKind.STATE:
        return ValueType(ValueKind.STATE, location=slot.location)
    if slot.kind in (ResumeSlotKind.SENT_VALUE, ResumeSlotKind.DELEGATE_VALUE):
        return ValueType(ValueKind.REFERENCE)
    return ProtocolValueType(ProtocolValueKind.EXCEPTION_PACKET)


__all__ = [
    "ResumableKind", "SuspensionFlavor", "SavedRole", "ResumeSlotKind",
    "ResumableBody", "FrameContextInitial", "FrameContextAttach", "FrameContextDetach",
    "SavedSlot", "SavedInput", "ResumeInput", "ResumeSlot", "ResumeSuccessor",
    "SuspendTerminator", "saved_actual_use", "resume_slot_type",
]
