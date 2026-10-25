"""Static source subjects and frame-entry ports for lexical control roots.

These declarations refer to canonical core Values and existing code identities.
They assert neither an activation, a FunctionObject/ModuleObject, namespace
contents/aliasing, an import protocol, nor verified source/code correspondence.
No Python-frame normal-result or closure rule follows from a frame kind.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath

from scar.ir.program.call_edges import CapturedCode
from scar.ir.program.ids import ControlScopeID, EnvironmentInterfaceID, ValueID
from scar.ir.semantics_v2 import SourceSnapshot
from scar.ir.v2.ids import OperationDefinitionID


@dataclass(frozen=True, slots=True)
class ModuleUnitSource:
    """The original MODULE declaration; a module need not have a SourceAtom."""

    snapshot: SourceSnapshot
    namespace_root: str
    initializer: OperationDefinitionID

    def __post_init__(self):
        if not (type(self.snapshot) is SourceSnapshot
                and type(self.initializer) is OperationDefinitionID):
            raise ValueError("module entry: unit requires original snapshot and MODULE initializer")
        if not (type(self.namespace_root) is str
                and PurePosixPath(self.namespace_root).is_absolute()
                and PurePosixPath(self.snapshot.path).is_relative_to(
                    PurePosixPath(self.namespace_root))):
            raise ValueError("module entry: unit must retain its absolute original source namespace")


class FrameKind(str, Enum):
    """Static code/source-body category, independent of the entering protocol."""

    FUNCTION = "FUNCTION"
    MODULE = "MODULE"
    CLASS = "CLASS"


@dataclass(frozen=True, slots=True)
class MappingFramePorts:
    """Exact entry ports; different ValueIDs never prove different objects.

    Cells retain their declared positional port order. Source/compiler and
    activation evidence must separately check their meaning and actuals.
    """

    locals_namespace: ValueID
    globals_namespace: ValueID
    builtins_namespace: ValueID
    closure_cells: tuple[ValueID, ...]
    world: ValueID

    def __post_init__(self):
        references = (self.locals_namespace, self.globals_namespace, self.builtins_namespace)
        if (any(type(value) is not ValueID for value in references)
                or type(self.world) is not ValueID):
            raise TypeError("mapping frame ports require exact existing ValueIDs")
        if type(self.closure_cells) is not tuple or any(
                type(value) is not ValueID for value in self.closure_cells):
            raise TypeError("mapping frame cells require an ordered tuple of ValueIDs")
        ports = references + self.closure_cells + (self.world,)
        if len(set(ports)) != len(ports):
            raise ValueError("mapping frame roles need distinct entry ports, without object-disjointness claims")


@dataclass(frozen=True, slots=True)
class FunctionFrameABI:
    """Reference the existing environment/formal partition, without copying it."""

    environment: EnvironmentInterfaceID

    def __post_init__(self):
        if type(self.environment) is not EnvironmentInterfaceID:
            raise TypeError("function frame ABI requires an existing EnvironmentInterfaceID")


@dataclass(frozen=True, slots=True)
class FrameRoot:
    """One entry authority for one FRAME scope, not a dynamic frame instance."""

    scope: ControlScopeID
    kind: FrameKind
    code: CapturedCode
    entry: MappingFramePorts | FunctionFrameABI

    def __post_init__(self):
        if type(self.scope) is not ControlScopeID or type(self.kind) is not FrameKind:
            raise TypeError("frame root requires exact scope identity and frame kind")
        if type(self.code) is not CapturedCode:
            raise TypeError("frame root requires the existing CapturedCode descriptor")
        self.code.__post_init__()
        expected = FunctionFrameABI if self.kind is FrameKind.FUNCTION else MappingFramePorts
        if type(self.entry) is not expected:
            raise TypeError("frame kind requires its exact declared entry ABI")
        self.entry.__post_init__()


FRAME_ROOT_RECORD_TAGS = {
    ModuleUnitSource: ("source_kind", "MODULE_UNIT"),
    MappingFramePorts: ("entry_kind", "MAPPING_PORTS"),
    FunctionFrameABI: ("entry_kind", "FUNCTION_ENVIRONMENT"),
}


__all__ = ["ModuleUnitSource", "FrameKind", "MappingFramePorts", "FunctionFrameABI",
           "FrameRoot", "FRAME_ROOT_RECORD_TAGS"]
