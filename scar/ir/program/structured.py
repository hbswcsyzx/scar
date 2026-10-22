"""Typed source protocols for structured synchronous Python bodies.

These records describe the language operations introduced by lowering.  A
protocol is not a purity claim, an observation, or a replacement permission.
The canonical control edges remain in ProgramGraph; loop interfaces index
those edges rather than keeping a second, independent control graph.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from scar.ir.program.frames import FrameRules
from scar.ir.program.ids import BlockID, OperationID, RegionID, ValueID
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import OperationDefinitionID, ValueSlotID


class PythonProtocolKind(str, Enum):
    TRUTH = "TRUTH"
    GET_ITERATOR = "GET_ITERATOR"
    ADVANCE_ITERATOR = "ADVANCE_ITERATOR"
    MATCH_STOP_ITERATION = "MATCH_STOP_ITERATION"
    MAKE_UNBOUND_LOCAL_ERROR = "MAKE_UNBOUND_LOCAL_ERROR"
    LOOKUP_GLOBAL = "LOOKUP_GLOBAL"
    READ_FREE_CELL = "READ_FREE_CELL"
    READ_LOCAL_CELL = "READ_LOCAL_CELL"
    MAKE_CELL = "MAKE_CELL"
    STORE_CELL = "STORE_CELL"
    STORE_GLOBAL = "STORE_GLOBAL"
    FRAME_ENTER = "FRAME_ENTER"
    FRAME_BIND = "FRAME_BIND"
    FRAME_DISCARD = "FRAME_DISCARD"
    FRAME_EXIT = "FRAME_EXIT"
    FRAME_HOLD_TEMPORARY = "FRAME_HOLD_TEMPORARY"
    FRAME_RELEASE_TEMPORARY = "FRAME_RELEASE_TEMPORARY"
    OPAQUE_EXPRESSION = "OPAQUE_EXPRESSION"
    OPAQUE_STATEMENT = "OPAQUE_STATEMENT"


@dataclass(frozen=True, slots=True)
class PythonProtocol:
    operation: OperationID
    kind: PythonProtocolKind
    source: SourceReference

    def __post_init__(self):
        if type(self.operation) is not OperationID:
            raise TypeError("protocol operation must be OperationID")
        if type(self.kind) is not PythonProtocolKind:
            raise TypeError("protocol kind must be explicit")
        if type(self.source) is not SourceReference:
            raise TypeError("protocol source must be a versioned source reference")


class LoopKind(str, Enum):
    WHILE = "WHILE"
    FOR = "FOR"


@dataclass(frozen=True, slots=True)
class LoopBindingPort:
    slot: ValueSlotID
    header_value: ValueID

    def __post_init__(self):
        if type(self.slot) is not ValueSlotID or type(self.header_value) is not ValueID:
            raise TypeError("loop binding port needs a typed slot and value")


@dataclass(frozen=True, slots=True)
class ControlEdgeReference:
    operation: OperationID
    successor_index: int

    def __post_init__(self):
        if type(self.operation) is not OperationID:
            raise TypeError("control edge needs its terminating operation")
        if type(self.successor_index) is not int or self.successor_index < 0:
            raise ValueError("control edge successor index must be nonnegative")


@dataclass(frozen=True, slots=True)
class LoopInterface:
    source: SourceReference
    kind: LoopKind
    region: RegionID
    header: BlockID
    body_entry: BlockID
    natural_exit: BlockID
    after: BlockID | None
    bindings: tuple[LoopBindingPort, ...]
    backedges: tuple[ControlEdgeReference, ...] = ()
    breaks: tuple[ControlEdgeReference, ...] = ()
    continues: tuple[ControlEdgeReference, ...] = ()

    def __post_init__(self):
        if type(self.source) is not SourceReference or type(self.kind) is not LoopKind:
            raise TypeError("loop interface needs source and loop kind")
        if type(self.region) is not RegionID:
            raise TypeError("loop interface needs its owning region")
        if any(type(value) is not BlockID for value in
               (self.header, self.body_entry, self.natural_exit)):
            raise TypeError("loop control ports must be block identities")
        if self.after is not None and type(self.after) is not BlockID:
            raise TypeError("loop after port must be a block or absent")
        for name, cls in (("bindings", LoopBindingPort), ("backedges", ControlEdgeReference),
                          ("breaks", ControlEdgeReference), ("continues", ControlEdgeReference)):
            values = getattr(self, name)
            if type(values) is not tuple or any(type(value) is not cls for value in values):
                raise TypeError("loop " + name + " needs exact typed records")
            if len(set(values)) != len(values):
                raise ValueError("loop " + name + " must not repeat records")
        if len({port.slot for port in self.bindings}) != len(self.bindings):
            raise ValueError("loop binding slots must be unique")


@dataclass(frozen=True, slots=True)
class StructuredBodyModel:
    definition: OperationDefinitionID
    region: RegionID
    source: SourceReference
    protocols: tuple[PythonProtocol, ...] = ()
    loops: tuple[LoopInterface, ...] = ()
    frame_rules: FrameRules = FrameRules()

    def __post_init__(self):
        if type(self.definition) is not OperationDefinitionID or type(self.region) is not RegionID:
            raise TypeError("structured body needs a definition and owning region")
        if type(self.source) is not SourceReference:
            raise TypeError("structured body needs its exact source")
        if type(self.protocols) is not tuple or any(type(p) is not PythonProtocol for p in self.protocols):
            raise TypeError("structured protocols must be an exact typed tuple")
        if len({p.operation for p in self.protocols}) != len(self.protocols):
            raise ValueError("one source protocol per operation")
        if type(self.loops) is not tuple or any(type(loop) is not LoopInterface for loop in self.loops):
            raise TypeError("structured loops must be an exact typed tuple")
        if type(self.frame_rules) is not FrameRules:
            raise TypeError("structured body must retain explicit frame conditions")


__all__ = ["PythonProtocolKind", "PythonProtocol", "LoopKind", "LoopBindingPort",
           "ControlEdgeReference", "LoopInterface", "StructuredBodyModel"]
