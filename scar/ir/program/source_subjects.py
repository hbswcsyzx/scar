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
import re

from scar.ir.program.call_edges import CapturedCode
from scar.ir.program.ids import ControlScopeID, EnvironmentInterfaceID, ValueID
from scar.ir.semantics_v2 import SourceSnapshot
from scar.ir.v2.common import SourceReference
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
class SourceCompilationCodeRef:
    """Static compiler layout for one original source definition.

    This record carries no CodeType, runtime code identity, or execution
    witness.  A module root uses its original ModuleUnitSource and the empty
    code path; a function uses its exact SourceReference and a non-empty path.
    """

    source: ModuleUnitSource | SourceReference
    definition: OperationDefinitionID
    code_path: tuple[int, ...]
    code_layout_key: str
    root_code_layout_key: str
    compiler_implementation: str
    compiler_version: tuple[int, int, int]
    compiler_python: str
    compiler_cache_tag: str | None
    compile_mode: str
    compile_flags: int
    dont_inherit: bool
    optimize: int
    evidence_kind: str = "SOURCE_COMPILATION"

    def __post_init__(self):
        if type(self.source) is ModuleUnitSource:
            self.source.__post_init__()
            if (type(self.definition) is not OperationDefinitionID
                    or self.definition != self.source.initializer
                    or type(self.code_path) is not tuple or self.code_path
                    or self.code_layout_key != self.root_code_layout_key):
                raise ValueError("module source compilation ref must identify its root initializer")
        elif type(self.source) is SourceReference:
            self.source.__post_init__()
            if type(self.definition) is not OperationDefinitionID:
                raise TypeError("source compilation ref needs an OperationDefinitionID")
            if self.source.end_column is None:
                raise ValueError("function source compilation ref needs an exact source-span end column")
            if type(self.code_path) is not tuple or not self.code_path:
                raise ValueError("function source compilation ref needs a non-empty code path")
        else:
            raise TypeError("source compilation ref needs an original source subject")
        if any(type(index) is not int or index < 0 for index in self.code_path):
            raise ValueError("source compilation code path must contain non-negative exact integers")
        for name, value in (("code layout key", self.code_layout_key),
                            ("root code layout key", self.root_code_layout_key)):
            if type(value) is not str or re.fullmatch(r"pycode-v2:[0-9a-f]{64}", value) is None:
                raise ValueError(f"source compilation {name} must be a canonical pycode-v2 key")
        if type(self.compiler_implementation) is not str or not self.compiler_implementation:
            raise ValueError("source compilation compiler implementation is required")
        if (type(self.compiler_version) is not tuple or len(self.compiler_version) != 3
                or any(type(part) is not int or part < 0 for part in self.compiler_version)):
            raise ValueError("source compilation compiler version must be three non-negative exact integers")
        if type(self.compiler_python) is not str or not self.compiler_python:
            raise ValueError("source compilation Python version is required")
        if (self.compiler_cache_tag is not None
                and (type(self.compiler_cache_tag) is not str or not self.compiler_cache_tag)):
            raise TypeError("source compilation cache tag must be nonempty str or None")
        if type(self.compile_mode) is not str or self.compile_mode != "exec":
            raise ValueError("source compilation mode must be exactly exec")
        if type(self.compile_flags) is not int or self.compile_flags != 0:
            raise ValueError("source compilation flags must be exactly zero")
        if type(self.dont_inherit) is not bool or self.dont_inherit is not True:
            raise ValueError("source compilation must use dont_inherit=True")
        if type(self.optimize) is not int or self.optimize != 0:
            raise ValueError("source compilation optimization level must be exactly zero")
        if type(self.evidence_kind) is not str or self.evidence_kind != "SOURCE_COMPILATION":
            raise ValueError("source compilation evidence kind must be exactly SOURCE_COMPILATION")


@dataclass(frozen=True, slots=True)
class SourceCompilationFrameRoot:
    """A lexical frame root backed by source compilation, not a runtime capture."""

    scope: ControlScopeID
    kind: FrameKind
    code: SourceCompilationCodeRef
    entry: MappingFramePorts | FunctionFrameABI

    def __post_init__(self):
        if type(self.scope) is not ControlScopeID or type(self.kind) is not FrameKind:
            raise TypeError("static frame root requires exact scope identity and frame kind")
        if type(self.code) is not SourceCompilationCodeRef:
            raise TypeError("static frame root requires SourceCompilationCodeRef")
        self.code.__post_init__()
        if self.kind is FrameKind.MODULE:
            if (type(self.code.source) is not ModuleUnitSource
                    or type(self.entry) is not MappingFramePorts):
                raise TypeError("static MODULE root requires ModuleUnitSource and MappingFramePorts")
            if self.entry.closure_cells:
                raise ValueError("static MODULE root cannot declare closure-cell entry ports")
        elif self.kind is FrameKind.FUNCTION:
            if (type(self.code.source) is not SourceReference
                    or type(self.entry) is not FunctionFrameABI):
                raise TypeError("static FUNCTION root requires SourceReference and FunctionFrameABI")
        else:
            raise ValueError("static CLASS frame roots are not implemented")
        self.entry.__post_init__()


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


STATIC_FRAME_ROOT_RECORD_TAGS = {
    SourceCompilationFrameRoot: ("frame_root_kind", "SOURCE_COMPILATION"),
}


__all__ = ["ModuleUnitSource", "FrameKind", "MappingFramePorts", "FunctionFrameABI",
           "FrameRoot", "SourceCompilationCodeRef", "SourceCompilationFrameRoot",
           "FRAME_ROOT_RECORD_TAGS", "STATIC_FRAME_ROOT_RECORD_TAGS"]
