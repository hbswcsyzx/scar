"""Typed records for bounded, non-executing source discovery.

Discovery records describe physical source candidates and lexical import
edges. They do not claim that a candidate is on ``sys.path`` or that an import
executes at runtime.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum
import json
from pathlib import Path
from typing import ClassVar

from scar.ir.record_codec import decode, encode, loads as _loads
from scar.ir.semantics_v2 import ImportForm, SourceSnapshot
from scar.ir.v2.common import SourceReference


class DiscoveryRootMode(str, Enum):
    INFERRED = "INFERRED"
    DECLARED = "DECLARED"


class DiscoveryStatus(str, Enum):
    LOCAL_CANDIDATE = "LOCAL_CANDIDATE"
    AMBIGUOUS = "AMBIGUOUS"
    EXTERNAL_OR_UNAVAILABLE = "EXTERNAL_OR_UNAVAILABLE"
    RELATIVE_IMPORT_OVERFLOW = "RELATIVE_IMPORT_OVERFLOW"
    STAR_IMPORT = "STAR_IMPORT"


class CandidateRole(str, Enum):
    REQUESTED_MODULE = "REQUESTED_MODULE"
    FROM_SUBMODULE = "FROM_SUBMODULE"
    PARENT_NAMESPACE = "PARENT_NAMESPACE"


class DiscoveryControlKind(str, Enum):
    IF_TRUE = "IF_TRUE"
    IF_FALSE = "IF_FALSE"
    LOOP_BODY = "LOOP_BODY"
    LOOP_ELSE = "LOOP_ELSE"
    TRY_BODY = "TRY_BODY"
    HANDLER = "HANDLER"
    TRY_ELSE = "TRY_ELSE"
    FINALLY = "FINALLY"
    WITH_BODY = "WITH_BODY"
    MATCH_CASE = "MATCH_CASE"


@dataclass(frozen=True, slots=True)
class ImportControlContext:
    source: SourceReference
    kind: DiscoveryControlKind
    index: int = 0

    def __post_init__(self):
        if not isinstance(self.source, SourceReference) or not isinstance(self.kind, DiscoveryControlKind):
            raise TypeError("control context requires typed source and control kind")
        if type(self.index) is not int or self.index < 0:
            raise ValueError("control context index must be non-negative")


class DiscoveryGapKind(str, Enum):
    DIRECTORY_BUDGET = "DIRECTORY_BUDGET"
    FILE_BUDGET = "FILE_BUDGET"
    BYTE_BUDGET = "BYTE_BUDGET"
    FILE_UNAVAILABLE = "FILE_UNAVAILABLE"
    FILE_OUTSIDE_ROOT = "FILE_OUTSIDE_ROOT"
    SYMLINK = "SYMLINK"
    DECODE_ERROR = "DECODE_ERROR"
    SYNTAX_ERROR = "SYNTAX_ERROR"
    RELATIVE_IMPORT_OVERFLOW = "RELATIVE_IMPORT_OVERFLOW"
    STAR_IMPORT = "STAR_IMPORT"
    EXTERNAL_OR_UNAVAILABLE = "EXTERNAL_OR_UNAVAILABLE"
    AMBIGUOUS = "AMBIGUOUS"
    DYNAMIC_IMPORT = "DYNAMIC_IMPORT"
    DYNAMIC_EXECUTION = "DYNAMIC_EXECUTION"
    SOURCE_ROOT_INVALID = "SOURCE_ROOT_INVALID"


def _nonempty(value: object, name: str) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be non-empty text")


def _absolute_path(value: str, name: str) -> None:
    _nonempty(value, name)
    if not Path(value).is_absolute():
        raise ValueError(f"{name} must be an absolute path")


@dataclass(frozen=True, slots=True)
class ModuleMapping:
    """One physical file's dotted name under one candidate search root."""

    name: str
    source_root: str

    def __post_init__(self) -> None:
        _nonempty(self.name, "ModuleMapping.name")
        _absolute_path(self.source_root, "ModuleMapping.source_root")


@dataclass(frozen=True, slots=True)
class DiscoveredFile:
    snapshot: SourceSnapshot
    module_names: tuple[str, ...]
    module_mappings: tuple[ModuleMapping, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, SourceSnapshot):
            raise TypeError("DiscoveredFile.snapshot must be SourceSnapshot")
        _absolute_path(self.snapshot.path, "DiscoveredFile.snapshot.path")
        if type(self.module_names) is not tuple or any(type(name) is not str or not name for name in self.module_names):
            raise TypeError("DiscoveredFile.module_names must be a tuple of non-empty strings")
        if type(self.module_mappings) is not tuple or any(not isinstance(item, ModuleMapping) for item in self.module_mappings):
            raise TypeError("DiscoveredFile.module_mappings must be a tuple of ModuleMapping")
        expected = tuple(sorted({item.name for item in self.module_mappings}))
        if self.module_names != expected:
            raise ValueError("DiscoveredFile.module_names must match sorted module_mappings")
        if len(set(self.module_mappings)) != len(self.module_mappings):
            raise ValueError("DiscoveredFile.module_mappings contains duplicates")
        if self.module_mappings != tuple(sorted(self.module_mappings,
                key=lambda item: (item.source_root, item.name))):
            raise ValueError("DiscoveredFile.module_mappings must be deterministically sorted")


@dataclass(frozen=True, slots=True)
class ModuleCandidate:
    """A possible module path; namespace candidates point to directories."""

    name: str
    path: str
    source_root: str
    parent_initializers: tuple[str, ...]
    namespace: bool
    role: CandidateRole = CandidateRole.REQUESTED_MODULE

    def __post_init__(self) -> None:
        _nonempty(self.name, "ModuleCandidate.name")
        _absolute_path(self.path, "ModuleCandidate.path")
        _absolute_path(self.source_root, "ModuleCandidate.source_root")
        if type(self.parent_initializers) is not tuple:
            raise TypeError("ModuleCandidate.parent_initializers must be a tuple")
        for path in self.parent_initializers:
            _absolute_path(path, "ModuleCandidate.parent_initializer")
        if len(set(self.parent_initializers)) != len(self.parent_initializers):
            raise ValueError("ModuleCandidate.parent_initializers contains duplicates")
        if self.namespace and Path(self.path).suffix == ".py":
            raise ValueError("namespace ModuleCandidate.path must name a directory")
        if not self.namespace and Path(self.path).suffix != ".py":
            raise ValueError("source ModuleCandidate.path must name a .py file")
        if type(self.namespace) is not bool:
            raise TypeError("ModuleCandidate.namespace must be bool")
        if not isinstance(self.role, CandidateRole):
            raise TypeError("ModuleCandidate.role must be CandidateRole")


@dataclass(frozen=True, slots=True)
class ImportDependency:
    source: SourceReference
    alias_source: SourceReference
    requested: str
    relative_level: int
    symbol: str | None
    bound_name: str | None
    owner_qualname: str
    deferred: bool
    candidates: tuple[ModuleCandidate, ...]
    status: DiscoveryStatus
    source_root: str
    importer_module: str
    resolved_module: str | None
    form: ImportForm
    control_context: tuple[ImportControlContext, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.source, SourceReference):
            raise TypeError("ImportDependency.source must be SourceReference")
        if not isinstance(self.alias_source, SourceReference):
            raise TypeError("ImportDependency.alias_source must be SourceReference")
        if (self.source.path != self.alias_source.path
                or self.source.fingerprint != self.alias_source.fingerprint):
            raise ValueError("ImportDependency source and alias_source must refer to one source snapshot")
        if type(self.requested) is not str:
            raise TypeError("ImportDependency.requested must be str")
        if type(self.relative_level) is not int or self.relative_level < 0:
            raise ValueError("ImportDependency.relative_level must be a non-negative int")
        if self.symbol is not None and (type(self.symbol) is not str or not self.symbol):
            raise ValueError("ImportDependency.symbol must be non-empty text or None")
        if self.bound_name is not None and (type(self.bound_name) is not str or not self.bound_name):
            raise ValueError("ImportDependency.bound_name must be non-empty text or None")
        _nonempty(self.owner_qualname, "ImportDependency.owner_qualname")
        if type(self.deferred) is not bool:
            raise TypeError("ImportDependency.deferred must be bool")
        if type(self.candidates) is not tuple or any(not isinstance(item, ModuleCandidate) for item in self.candidates):
            raise TypeError("ImportDependency.candidates must be a tuple of ModuleCandidate")
        if not isinstance(self.status, DiscoveryStatus):
            raise TypeError("ImportDependency.status must be DiscoveryStatus")
        _absolute_path(self.source_root, "ImportDependency.source_root")
        if type(self.importer_module) is not str:
            raise TypeError("ImportDependency.importer_module must be str")
        if self.resolved_module is not None and type(self.resolved_module) is not str:
            raise TypeError("ImportDependency.resolved_module must be str or None")
        if not isinstance(self.form, ImportForm):
            raise TypeError("ImportDependency.form must be ImportForm")
        if type(self.control_context) is not tuple or any(not isinstance(item, ImportControlContext) for item in self.control_context):
            raise TypeError("ImportDependency.control_context must contain typed contexts")
        if (self.form is ImportForm.MODULE) != (self.symbol is None):
            raise ValueError("ImportDependency.form and symbol disagree")
        if self.form is ImportForm.MODULE and self.relative_level:
            raise ValueError("module imports cannot have a relative level")
        if self.status is DiscoveryStatus.RELATIVE_IMPORT_OVERFLOW and self.resolved_module is not None:
            raise ValueError("overflowed relative import cannot have a resolved_module")


@dataclass(frozen=True, slots=True)
class DiscoveryGap:
    kind: DiscoveryGapKind
    detail: str
    source: SourceReference | None = None
    path: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, DiscoveryGapKind):
            raise TypeError("DiscoveryGap.kind must be DiscoveryGapKind")
        _nonempty(self.detail, "DiscoveryGap.detail")
        if self.source is not None and not isinstance(self.source, SourceReference):
            raise TypeError("DiscoveryGap.source must be SourceReference or None")
        if self.path is not None:
            _absolute_path(self.path, "DiscoveryGap.path")


@dataclass(frozen=True, slots=True)
class SourceDiscovery:
    entry: str
    project_root: str
    source_roots: tuple[str, ...]
    root_mode: DiscoveryRootMode
    files: tuple[DiscoveredFile, ...]
    imports: tuple[ImportDependency, ...]
    gaps: tuple[DiscoveryGap, ...]

    SCHEMA: ClassVar[str] = "scar.source-discovery"
    SCHEMA_VERSION: ClassVar[int] = 1

    def __post_init__(self) -> None:
        _absolute_path(self.entry, "SourceDiscovery.entry")
        _absolute_path(self.project_root, "SourceDiscovery.project_root")
        project_root = Path(self.project_root)
        if not Path(self.entry).is_relative_to(project_root):
            raise ValueError("SourceDiscovery.entry must be within project_root")
        if type(self.source_roots) is not tuple:
            raise TypeError("SourceDiscovery.source_roots must be a tuple")
        for root in self.source_roots:
            _absolute_path(root, "SourceDiscovery.source_root")
            if not Path(root).is_relative_to(project_root):
                raise ValueError("SourceDiscovery.source_root must be within project_root")
        if self.source_roots != tuple(sorted(set(self.source_roots))):
            raise ValueError("SourceDiscovery.source_roots must be unique and sorted")
        if not isinstance(self.root_mode, DiscoveryRootMode):
            raise TypeError("SourceDiscovery.root_mode must be DiscoveryRootMode")
        for name, records, expected in (("files", self.files, DiscoveredFile),
                                        ("imports", self.imports, ImportDependency),
                                        ("gaps", self.gaps, DiscoveryGap)):
            if type(records) is not tuple or any(not isinstance(item, expected) for item in records):
                raise TypeError(f"SourceDiscovery.{name} must be a tuple of {expected.__name__}")
        file_paths = tuple(item.snapshot.path for item in self.files)
        if file_paths != tuple(sorted(set(file_paths))):
            raise ValueError("SourceDiscovery.files must be sorted by unique snapshot path")
        file_path_set = set(file_paths)
        for item in self.files:
            if not Path(item.snapshot.path).is_relative_to(project_root):
                raise ValueError("DiscoveredFile source must be within project_root")
            for mapping in item.module_mappings:
                if mapping.source_root not in self.source_roots:
                    raise ValueError("DiscoveredFile mapping uses an undeclared source root")
        import_keys = tuple((item.source.path, item.source.start_line,
            item.source.start_column, item.importer_module, item.source_root,
            item.source.atom_id.wire, item.requested, item.symbol or "")
            for item in self.imports)
        if import_keys != tuple(sorted(import_keys)):
            raise ValueError("SourceDiscovery.imports must be deterministically sorted")
        for item in self.imports:
            if item.source.path not in file_path_set:
                raise ValueError("ImportDependency.source must refer to a discovered file")
            if not Path(item.source_root).is_relative_to(project_root):
                raise ValueError("ImportDependency.source_root must be within project_root")
            for candidate in item.candidates:
                candidate_path = Path(candidate.path)
                candidate_root = Path(candidate.source_root)
                if not candidate_path.is_relative_to(project_root):
                    raise ValueError("ModuleCandidate.path must be within project_root")
                if not candidate_root.is_relative_to(project_root):
                    raise ValueError("ModuleCandidate.source_root must be within project_root")
                if candidate.source_root not in self.source_roots:
                    raise ValueError("ModuleCandidate uses an undeclared source root")
                if not candidate_path.is_relative_to(candidate_root):
                    raise ValueError("ModuleCandidate.path must be within its source_root")
                if any(not Path(path).is_relative_to(candidate_root)
                       for path in candidate.parent_initializers):
                    raise ValueError("ModuleCandidate parent initializer lies outside its source_root")
        gap_keys = tuple((item.source.path if item.source else "",
            item.source.start_line if item.source else 0,
            item.source.start_column if item.source else 0,
            item.path or "", item.kind.value, item.detail) for item in self.gaps)
        if gap_keys != tuple(sorted(gap_keys)):
            raise ValueError("SourceDiscovery.gaps must be deterministically sorted")
        for item in self.gaps:
            if item.source is not None and item.source.path not in file_path_set:
                raise ValueError("DiscoveryGap.source must refer to a discovered file")
            if item.path is not None and not Path(item.path).is_relative_to(project_root):
                raise ValueError("DiscoveryGap.path must be within project_root")

    def to_dict(self) -> dict:
        return {"schema": self.SCHEMA, "schema_version": self.SCHEMA_VERSION, **encode(self)}

    @classmethod
    def from_dict(cls, value: object) -> "SourceDiscovery":
        if type(value) is not dict:
            raise TypeError("source discovery document must be an object")
        fields_set = {item.name for item in fields(cls)}
        if set(value) != {"schema", "schema_version"} | fields_set:
            raise ValueError("source discovery document has incorrect fields")
        if value["schema"] != cls.SCHEMA or type(value["schema_version"]) is not int or value["schema_version"] != cls.SCHEMA_VERSION:
            raise ValueError("unsupported source discovery schema/version")
        return decode(cls, {name: value[name] for name in fields_set})

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False)

    @classmethod
    def from_json(cls, payload: str) -> "SourceDiscovery":
        if type(payload) is not str:
            raise TypeError("source discovery JSON payload must be str")
        return cls.from_dict(_loads(payload))


__all__ = [
    "CandidateRole", "DiscoveredFile", "DiscoveryGap", "DiscoveryGapKind",
    "DiscoveryControlKind", "ImportControlContext",
    "DiscoveryRootMode", "DiscoveryStatus", "ImportDependency", "ModuleCandidate",
    "ModuleMapping", "SourceDiscovery",
]
