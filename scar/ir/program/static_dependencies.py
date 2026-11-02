"""Versioned material candidates for an existing static import index.

This is an inventory view, not another program graph. Relations address the
original import records; no definitions, values, import effects or execution
identities are invented here. A filesystem match proves neither import
selection nor the implementation/effects of an external library.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path

from scar.ir.program.discovery import ModuleMapping
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.v2.common import SourceVersion


class DependencyMaterialKind(str, Enum):
    SOURCE = "SOURCE"
    STUB = "STUB"
    NATIVE = "NATIVE"
    NAMESPACE_DIRECTORY = "NAMESPACE_DIRECTORY"


class DependencyVersionStatus(str, Enum):
    SUPPLIED_SNAPSHOT = "SUPPLIED_SNAPSHOT"
    CONTENT_HASHED = "CONTENT_HASHED"
    CONTENT_NOT_READ = "CONTENT_NOT_READ"
    READ_FAILED = "READ_FAILED"
    DIRECTORY_ONLY = "DIRECTORY_ONLY"


class DependencySearchStatus(str, Enum):
    SEARCHED_EXPLICIT_ROOTS = "SEARCHED_EXPLICIT_ROOTS"
    MODULE_BUDGET = "MODULE_BUDGET"
    INVALID_MODULE_NAME = "INVALID_MODULE_NAME"


def _path(value, name):
    if (type(value) is not str or not value or "\0" in value
            or not Path(value).is_absolute() or os.path.normpath(value) != value):
        raise ValueError(name + " must be an absolute normalized path")


def _record(value, expected):
    if type(value) is not expected:
        raise TypeError("expected " + expected.__name__)
    value.__post_init__()


def _indices(values, name):
    if type(values) is not tuple or any(type(x) is not int or x < 0 for x in values):
        raise TypeError(name + " must contain nonnegative exact integers")
    if values != tuple(sorted(set(values))):
        raise ValueError(name + " must be sorted and unique")


@dataclass(frozen=True, slots=True)
class DependencyLimits:
    max_modules: int = 4096
    max_files: int = 4096
    max_bytes: int = 64 * 1024 * 1024
    max_file_bytes: int = 8 * 1024 * 1024

    def __post_init__(self):
        for name in ("max_modules", "max_files", "max_bytes", "max_file_bytes"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(name + " must be a positive exact integer")


@dataclass(frozen=True, slots=True)
class DependencyFrontier:
    kind: str
    path: str | None
    detail: str

    def __post_init__(self):
        if type(self.kind) is not str or not self.kind or type(self.detail) is not str or not self.detail:
            raise ValueError("dependency frontier needs a kind and detail")
        if self.path is not None:
            _path(self.path, "dependency frontier path")


@dataclass(frozen=True, slots=True)
class DependencyMaterial:
    path: str
    kind: DependencyMaterialKind
    mappings: tuple[ModuleMapping, ...]
    version_status: DependencyVersionStatus
    artifact: ProviderArtifact | None = None
    supplied_unit: str | None = None
    supplied_source: SourceArtifactLocator | None = None
    supplied_version: SourceVersion | None = None
    stat_stamp: tuple[int, ...] | None = None
    version_detail: str = ""

    def __post_init__(self):
        _path(self.path, "dependency material path")
        if type(self.kind) is not DependencyMaterialKind or type(self.version_status) is not DependencyVersionStatus:
            raise TypeError("dependency material kind and version status must be typed")
        if type(self.mappings) is not tuple or not self.mappings:
            raise ValueError("dependency material needs original/candidate module mappings")
        for mapping in self.mappings:
            _record(mapping, ModuleMapping)
        if self.mappings != tuple(sorted(set(self.mappings), key=lambda x: (x.source_root, x.name))):
            raise ValueError("dependency material mappings must be sorted and unique")
        if self.artifact is not None:
            _record(self.artifact, ProviderArtifact)
            if self.artifact.uri != self.path:
                raise ValueError("external material receipt must address its actual file")
        if self.supplied_source is not None:
            _record(self.supplied_source, SourceArtifactLocator)
        if self.supplied_version is not None:
            _record(self.supplied_version, SourceVersion)
            if self.supplied_version.path != self.path:
                raise ValueError("supplied source version belongs to another file")
        if self.version_status is DependencyVersionStatus.SUPPLIED_SNAPSHOT:
            if (type(self.supplied_unit) is not str or not self.supplied_unit
                    or self.supplied_source is None or self.supplied_version is None or self.artifact is not None):
                raise ValueError("supplied material requires its original snapshot/unit/version")
        elif any(x is not None for x in (self.supplied_unit, self.supplied_source, self.supplied_version)):
            raise ValueError("external material cannot claim an analyzed source unit")
        if (self.version_status is DependencyVersionStatus.CONTENT_HASHED) != (self.artifact is not None):
            raise ValueError("only a completely content-hashed file may carry a new artifact receipt")
        if self.stat_stamp is not None and (type(self.stat_stamp) is not tuple or len(self.stat_stamp) != 6
                or any(type(x) is not int or x < 0 for x in self.stat_stamp)):
            raise ValueError("file stamp must contain six nonnegative stat fields")
        if type(self.version_detail) is not str:
            raise TypeError("version detail must be text")


@dataclass(frozen=True, slots=True)
class DependencyModuleQuery:
    module: str
    status: DependencySearchStatus
    materials: tuple[int, ...]
    frontiers: tuple[DependencyFrontier, ...] = ()

    def __post_init__(self):
        if type(self.module) is not str or not self.module:
            raise ValueError("module query needs an original module name")
        if type(self.status) is not DependencySearchStatus:
            raise TypeError("module search status must be typed")
        _indices(self.materials, "material references")
        if type(self.frontiers) is not tuple:
            raise TypeError("query frontiers must be a tuple")
        for frontier in self.frontiers:
            _record(frontier, DependencyFrontier)


@dataclass(frozen=True, slots=True)
class DependencyImportRelation:
    """Pointer applies to the inventory's exact, version-qualified import index."""

    origin: str
    module_query: int | None
    original_frontier: str | None = None

    def __post_init__(self):
        if type(self.origin) is not str or not self.origin.startswith("#/relations/"):
            raise ValueError("dependency relation must address an original import relation")
        if not self.origin.removeprefix("#/relations/").isdigit():
            raise ValueError("dependency relation pointer must address one relation index")
        if self.module_query is not None and (type(self.module_query) is not int or self.module_query < 0):
            raise ValueError("module query reference must be a nonnegative exact integer")
        if self.original_frontier is not None and (type(self.original_frontier) is not str or not self.original_frontier):
            raise ValueError("original import frontier must be nonempty text")


@dataclass(frozen=True, slots=True)
class DependencyRelationCount:
    relation_kind: str
    availability: str
    count: int

    def __post_init__(self):
        if not self.relation_kind or not self.availability or type(self.count) is not int or self.count < 1:
            raise ValueError("invalid dependency relation aggregate")


@dataclass(frozen=True, slots=True)
class StaticDependencyInventory:
    import_index: SourceArtifactLocator
    search_roots: tuple[str, ...]
    native_suffixes: tuple[str, ...]
    limits: DependencyLimits
    materials: tuple[DependencyMaterial, ...]
    module_queries: tuple[DependencyModuleQuery, ...]
    relations: tuple[DependencyImportRelation, ...]
    relation_counts: tuple[DependencyRelationCount, ...]
    roots_frontiers: tuple[DependencyFrontier, ...] = ()
    read_files: int = 0
    read_bytes: int = 0
    read_attempts: int = 0

    SCHEMA = "scar.static-dependencies"
    SCHEMA_VERSION = 1

    def __post_init__(self):
        _record(self.import_index, SourceArtifactLocator)
        _record(self.limits, DependencyLimits)
        for root in self.search_roots:
            _path(root, "dependency search root")
        if type(self.search_roots) is not tuple or len(set(self.search_roots)) != len(self.search_roots):
            raise ValueError("search roots must be a tuple of unique explicit roots")
        if type(self.native_suffixes) is not tuple or any(type(x) is not str or not x.startswith(".") or "/" in x
                for x in self.native_suffixes):
            raise ValueError("native suffixes must be explicit filename suffixes")
        for rows, expected in ((self.materials, DependencyMaterial), (self.module_queries, DependencyModuleQuery),
                (self.relations, DependencyImportRelation), (self.relation_counts, DependencyRelationCount),
                (self.roots_frontiers, DependencyFrontier)):
            if type(rows) is not tuple:
                raise TypeError("dependency collections must be tuples")
            for row in rows:
                _record(row, expected)
        for query in self.module_queries:
            if any(x >= len(self.materials) for x in query.materials):
                raise ValueError("material reference is outside the inventory")
        for index, relation in enumerate(self.relations):
            if relation.origin != "#/relations/" + str(index):
                raise ValueError("import relations must retain their original order and pointers")
            if relation.module_query is not None and relation.module_query >= len(self.module_queries):
                raise ValueError("module query reference is outside the inventory")
        if sum(row.count for row in self.relation_counts) != len(self.relations):
            raise ValueError("relation aggregate does not cover the original import index")
        if any(type(x) is not int or x < 0 for x in (self.read_files, self.read_bytes, self.read_attempts)):
            raise ValueError("dependency read counts must be nonnegative exact integers")
        if self.read_files > self.read_attempts or self.read_attempts > self.limits.max_files or self.read_bytes > self.limits.max_bytes:
            raise ValueError("dependency read counts exceed their stated budgets")

    def summary(self):
        from collections import Counter
        kinds = Counter(x.kind.value for x in self.materials)
        external = Counter(x.kind.value for x in self.materials if x.supplied_unit is None)
        statuses = Counter(x.status.value for x in self.module_queries)
        missing = sum(not x.materials and x.status is DependencySearchStatus.SEARCHED_EXPLICIT_ROOTS
                      and not x.frontiers and not self.roots_frontiers for x in self.module_queries)
        return {"import_relations": len(self.relations), "requested_modules": len(self.module_queries),
                "material_candidates": len(self.materials), "material_kinds": dict(sorted(kinds.items())),
                "supplied_source_materials": sum(x.supplied_unit is not None for x in self.materials),
                "external_material_kinds": dict(sorted(external.items())), "query_statuses": dict(sorted(statuses.items())),
                "not_located_in_explicit_roots": missing,
                "unversioned_file_candidates": sum(x.version_status in (DependencyVersionStatus.CONTENT_NOT_READ,
                    DependencyVersionStatus.READ_FAILED) for x in self.materials),
                "external_files_content_hashed": self.read_files, "external_bytes_read": self.read_bytes,
                "external_file_read_attempts": self.read_attempts,
                "target_executed": False, "runtime_import_result_established": False,
                "external_source_analyzed": False, "dependency_closure_complete": False}

    def to_dict(self):
        from scar.ir.record_codec import encode
        return {"schema": self.SCHEMA, "schema_version": self.SCHEMA_VERSION, **encode(self),
                "summary": self.summary(),
                "qualification": "A conditional filesystem material view of the original import index. "
                    "Availability is not source analysis, runtime import selection, export resolution or an effect contract. "
                    "Roots do not establish sys.path order, import caches, hooks, .pth execution, package __path__, "
                    "builtin/frozen selection or initialization purity. Native/stub files do not supply implementation proofs."}
