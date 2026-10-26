"""Explicit source-language capabilities and original-port provenance.

These overlays index existing operations and source slots. They neither define
another producer/state graph nor certify runtime identity, effects or purity.
Historical source wrappers must reject the extended protocol names.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from scar.ir.program.ids import OperationID
from scar.ir.semantics_v2 import SourceSnapshot
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import ValueSlotID


class SourceLanguageCapability(str, Enum):
    FIXED_UNPACK = "PYTHON_FIXED_LOCAL_UNPACK_V1"
    SLICE_KEYS = "PYTHON_SLICE_KEYS_314_V1"
    LEXICAL_LOCALS = "PYTHON_LEXICAL_LOCALS_314_V1"
    CALL_KWARGS_314_V1 = "PYTHON_CALL_KWARGS_314_V1"
    CALL_EXPANSION_314_V1 = "PYTHON_CALL_EXPANSION_314_V1"
    NESTED_FUNCTION_314_V1 = "PYTHON_NESTED_FUNCTION_314_V1"
    GENEXPR_314_V1 = "PYTHON_GENEXPR_314_V1"
    GENEXPR_CREATION_314_V1 = "PYTHON_GENEXPR_CREATION_314_V1"
    FUNCTION_TRY_314_V1 = "PYTHON_FUNCTION_TRY_314_V1"
    FUNCTION_IMPORT_314_V1 = "PYTHON_FUNCTION_IMPORT_314_V1"
    FUNCTION_WITH_314_V1 = "PYTHON_FUNCTION_WITH_314_V1"
    SET_DISPLAY_314_V1 = "PYTHON_SET_DISPLAY_314_V1"
    UNPACK_TARGETS_314_V1 = "PYTHON_UNPACK_TARGETS_314_V1"


EXTENDED_PROTOCOLS = frozenset(("UNPACK_FIXED", "BUILD_SLICE", "READ_CODE_CONSTANT",
    "BUILD_CALL_POSITIONALS", "DICT_MERGE", "CALL_FUNCTION_EX",
    "MAKE_GENEXPR_FUNCTION", "CREATE_GENEXPR", "MAKE_UNPACK_ARITY_ERROR",
    "GENERATOR_ESCAPE_STOPITER_TO_RUNTIME_ERROR", "BUILD_CALL_POSITIONAL_LIST",
    "EXTEND_CALL_POSITIONALS", "APPEND_CALL_POSITIONAL", "CALL_POSITIONALS_TO_TUPLE"))
EXTENDED_PROTOCOLS = EXTENDED_PROTOCOLS | frozenset(('GENEXPR_CONTAINS',))
FUNCTION_TRY_PROTOCOLS = frozenset(("FUNCTION_EXCEPTION_PACKET", "FUNCTION_PENDING_COMPLETION",
    "FUNCTION_HANDLED_CONTEXT_ENTER", "FUNCTION_CLEANUP_RESUME", "FUNCTION_CLEANUP_REPLACE",
    "FUNCTION_FRAME_EXIT_EXCEPTION_PACKET", "FUNCTION_FRAME_EXIT_BINDINGS", "FUNCTION_START_PROPAGATION", "FUNCTION_CLEAR_EXCEPTION_NAME",
    "VALIDATE_EXCEPT_TYPE_314", "MATCH_EXCEPTION_BORROWED_314", "FUNCTION_INPLACE_BINARY"))
EXTENDED_PROTOCOLS = EXTENDED_PROTOCOLS | FUNCTION_TRY_PROTOCOLS
NESTED_FUNCTION_PROTOCOLS = frozenset(('MAKE_NESTED_FUNCTION', 'STORE_NESTED_FUNCTION_CELL'))
EXTENDED_PROTOCOLS = EXTENDED_PROTOCOLS | NESTED_FUNCTION_PROTOCOLS
FUNCTION_IMPORT_PROTOCOLS = frozenset(('FUNCTION_IMPORT_NAME', 'FUNCTION_IMPORT_FROM'))
EXTENDED_PROTOCOLS = EXTENDED_PROTOCOLS | FUNCTION_IMPORT_PROTOCOLS
FUNCTION_WITH_PROTOCOLS = frozenset(('WITH_ENTER_CONTEXT', 'WITH_EXIT_NORMAL', 'WITH_EXIT_EXCEPTION'))
EXTENDED_PROTOCOLS = EXTENDED_PROTOCOLS | FUNCTION_WITH_PROTOCOLS
FUNCTION_SET_PROTOCOLS = frozenset(('BUILD_SET_DISPLAY',))
EXTENDED_PROTOCOLS = EXTENDED_PROTOCOLS | FUNCTION_SET_PROTOCOLS


def _need(condition, detail):
    if not condition:
        raise ValueError("source language: " + detail)


def reject_extended_protocols(model):
    """A v1-v4/v8 wrapper cannot acquire new language semantics via enum growth."""
    if model is not None and any(row.kind.value in EXTENDED_PROTOCOLS for row in model.protocols):
        raise ValueError("historical source wrapper cannot contain extended source-language capability")


@dataclass(frozen=True, slots=True)
class UnpackShape:
    operation: OperationID
    source: SourceReference
    child_targets: tuple[SourceReference, ...]

    def __post_init__(self):
        _need(type(self.operation) is OperationID and type(self.source) is SourceReference,
              "unpack shape needs original operation/source")
        _need(type(self.child_targets) is tuple and all(type(row) is SourceReference for row in self.child_targets),
              "unpack children need ordered original source references")


@dataclass(frozen=True, slots=True)
class SliceShape:
    operation: OperationID
    source: SourceReference
    lower: SourceReference | None
    upper: SourceReference | None
    step: SourceReference | None

    def __post_init__(self):
        _need(type(self.operation) is OperationID and type(self.source) is SourceReference,
              "slice shape needs original operation/source")
        _need(all(row is None or type(row) is SourceReference for row in (self.lower, self.upper, self.step)),
              "slice components must retain source or explicit omission")


@dataclass(frozen=True, slots=True)
class CodeConstantSource:
    operation: OperationID
    source: SourceReference
    code_key: str
    constant_path: tuple[int, ...]

    def __post_init__(self):
        import re
        _need(type(self.operation) is OperationID and type(self.source) is SourceReference,
              "code constant needs original operation/source")
        _need(type(self.code_key) is str and re.fullmatch(r"pycode-v2:[0-9a-f]{64}", self.code_key) is not None,
              "code constant needs a complete structural code key")
        _need(type(self.constant_path) is tuple and bool(self.constant_path)
              and all(type(index) is int and index >= 0 for index in self.constant_path),
              "code constant path must be a nonempty tuple of exact indices")


@dataclass(frozen=True, slots=True)
class CompilerLocalMapping:
    name: str
    category: str
    lexical_slots: tuple[ValueSlotID, ...]
    comp_iteration: bool
    comp_cell: bool

    def __post_init__(self):
        _need(type(self.name) is str and bool(self.name), "compiler local needs a name")
        _need(self.category in ("LEXICAL_FUNCTION", "COMPREHENSION_TRANSIENT"),
              "unsupported compiler-local classification")
        _need(type(self.lexical_slots) is tuple and all(type(row) is ValueSlotID for row in self.lexical_slots),
              "compiler-local mapping only references original slots")
        _need(type(self.comp_iteration) is bool and type(self.comp_cell) is bool,
              "compiler-local flags must be exact bool")


@dataclass(frozen=True, slots=True)
class SourceLanguageOverlay:
    source: SourceSnapshot
    capabilities: tuple[SourceLanguageCapability, ...]
    unpackings: tuple[UnpackShape, ...] = ()
    slices: tuple[SliceShape, ...] = ()
    constants: tuple[CodeConstantSource, ...] = ()
    compiler_locals: tuple[CompilerLocalMapping, ...] = ()
    code_evidence: dict[str, Any] | None = None
    version: str = "PYTHON_SOURCE_LANGUAGE_V1"
    namespace_root: str | None = None

    def __post_init__(self):
        _need(type(self.source) is SourceSnapshot and self.version == "PYTHON_SOURCE_LANGUAGE_V1",
              "overlay needs its pinned source/version")
        from pathlib import PurePosixPath
        _need(type(self.namespace_root) is str and PurePosixPath(self.namespace_root).is_absolute()
              and PurePosixPath(self.source.path).is_relative_to(PurePosixPath(self.namespace_root)),
              "overlay must retain its exact source namespace root")
        _need(type(self.capabilities) is tuple and bool(self.capabilities)
              and all(type(row) is SourceLanguageCapability for row in self.capabilities)
              and len(set(self.capabilities)) == len(self.capabilities), "capabilities must be unique typed entries")
        for rows, kind in ((self.unpackings, UnpackShape), (self.slices, SliceShape),
                           (self.constants, CodeConstantSource), (self.compiler_locals, CompilerLocalMapping)):
            _need(type(rows) is tuple and all(type(row) is kind for row in rows), "overlay record type differs")
        _need(self.code_evidence is None or type(self.code_evidence) is dict,
              "code evidence must be a receipt projection, never a CodeType")


__all__ = ["SourceLanguageCapability", "SourceLanguageOverlay", "UnpackShape", "SliceShape",
           "CodeConstantSource", "CompilerLocalMapping", "EXTENDED_PROTOCOLS", "reject_extended_protocols"]
