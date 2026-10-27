"""Typed records for a bounded, source-only project directory.

These records describe available source bytes and namespace candidates. They do
not create operation definitions, claim import reachability, or imply that any
module was loaded. Text stays in memory for downstream static lowering and is
omitted from the manifest representation.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import re

from scar.ir.program.discovery import ModuleMapping


class StaticSourcesStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"


class StaticSourceIssueKind(str, Enum):
    PROJECT_ROOT_INVALID = "PROJECT_ROOT_INVALID"
    SOURCE_ROOT_INVALID = "SOURCE_ROOT_INVALID"
    SOURCE_ROOT_SYMLINK = "SOURCE_ROOT_SYMLINK"
    DIRECTORY_UNAVAILABLE = "DIRECTORY_UNAVAILABLE"
    DIRECTORY_BUDGET = "DIRECTORY_BUDGET"
    SYMLINK_SKIPPED = "SYMLINK_SKIPPED"
    FILE_UNAVAILABLE = "FILE_UNAVAILABLE"
    FILE_CHANGED = "FILE_CHANGED"
    FILE_BUDGET = "FILE_BUDGET"
    BYTE_BUDGET = "BYTE_BUDGET"
    DECODE_ERROR = "DECODE_ERROR"


class StaticSourceRemainingKind(str, Enum):
    FILE = "FILE"
    DIRECTORY = "DIRECTORY"


def _absolute_normalized(path: str, label: str) -> None:
    if type(path) is not str or not path or not Path(path).is_absolute():
        raise ValueError(f"{label} must be an absolute path")
    if str(Path(path)) != path:
        raise ValueError(f"{label} must be normalized")


@dataclass(frozen=True, slots=True)
class StaticSourceIssue:
    kind: StaticSourceIssueKind
    path: str
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, StaticSourceIssueKind):
            raise TypeError("static source issue kind must be typed")
        _absolute_normalized(self.path, "static source issue path")
        if type(self.detail) is not str or not self.detail.strip():
            raise ValueError("static source issue needs a detail")

    def to_dict(self) -> dict:
        return {"kind": self.kind.value, "path": self.path, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class StaticSourceRemaining:
    """An exact file or an unvisited directory frontier left by a budget."""

    path: str
    kind: StaticSourceRemainingKind
    reason: str

    def __post_init__(self) -> None:
        _absolute_normalized(self.path, "remaining source path")
        if not isinstance(self.kind, StaticSourceRemainingKind):
            raise TypeError("remaining source kind must be typed")
        if type(self.reason) is not str or not self.reason.strip():
            raise ValueError("remaining source path needs a reason")

    def to_dict(self) -> dict:
        return {"path": self.path, "kind": self.kind.value, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class StaticSourceFile:
    """One decoded source file plus all candidate import-root mappings."""

    path: str
    namespace_root: str
    module_names: tuple[str, ...]
    text: str
    raw_sha256: str
    decoded_sha256: str
    encoding: str
    size_bytes: int
    module_mappings: tuple[ModuleMapping, ...] = ()

    def __post_init__(self) -> None:
        _absolute_normalized(self.path, "source file path")
        _absolute_normalized(self.namespace_root, "source namespace root")
        if not Path(self.path).is_relative_to(Path(self.namespace_root)):
            raise ValueError("primary namespace root must contain its source file")
        if type(self.module_names) is not tuple or any(type(name) is not str or not name for name in self.module_names):
            raise TypeError("source module names must be a tuple of nonempty strings")
        if self.module_names != tuple(sorted(set(self.module_names))):
            raise ValueError("source module names must be unique and sorted")
        if type(self.text) is not str:
            raise TypeError("decoded source text must be str")
        if (type(self.raw_sha256) is not str or re.fullmatch(r"[0-9a-f]{64}", self.raw_sha256) is None
                or type(self.decoded_sha256) is not str
                or re.fullmatch(r"[0-9a-f]{64}", self.decoded_sha256) is None):
            raise ValueError("source digests must be lowercase SHA256 hex")
        if type(self.encoding) is not str or not self.encoding:
            raise ValueError("detected source encoding is required")
        if type(self.size_bytes) is not int or self.size_bytes < 0:
            raise ValueError("source byte size must be nonnegative")
        if type(self.module_mappings) is not tuple or any(type(item) is not ModuleMapping for item in self.module_mappings):
            raise TypeError("source module mappings must be typed ModuleMapping records")
        if self.module_mappings != tuple(sorted(set(self.module_mappings),
                key=lambda item: (item.source_root, item.name))):
            raise ValueError("source module mappings must be unique and sorted")

    def to_manifest_dict(self) -> dict:
        """Return metadata only; source text is never copied into the manifest."""
        return {
            "path": self.path,
            "namespace_root": self.namespace_root,
            "module_names": list(self.module_names),
            "module_mappings": [
                {"name": item.name, "source_root": item.source_root}
                for item in self.module_mappings
            ],
            "raw_sha256": self.raw_sha256,
            "decoded_sha256": self.decoded_sha256,
            "encoding": self.encoding,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class StaticSources:
    """Deterministic source material inventory, not a program graph."""

    project_root: str
    source_roots: tuple[str, ...]
    files: tuple[StaticSourceFile, ...]
    issues: tuple[StaticSourceIssue, ...]
    remaining: tuple[StaticSourceRemaining, ...]
    status: StaticSourcesStatus

    SCHEMA = "scar.static-sources"
    SCHEMA_VERSION = 1

    def __post_init__(self) -> None:
        _absolute_normalized(self.project_root, "project root")
        if type(self.source_roots) is not tuple:
            raise TypeError("source roots must be a tuple")
        for root in self.source_roots:
            _absolute_normalized(root, "source root")
        if self.source_roots != tuple(sorted(set(self.source_roots))):
            raise ValueError("source roots must be unique and sorted")
        if type(self.files) is not tuple or any(type(item) is not StaticSourceFile for item in self.files):
            raise TypeError("files must contain StaticSourceFile records")
        paths = tuple(item.path for item in self.files)
        if paths != tuple(sorted(set(paths))):
            raise ValueError("source files must be unique and sorted by path")
        if type(self.issues) is not tuple or any(type(item) is not StaticSourceIssue for item in self.issues):
            raise TypeError("issues must contain StaticSourceIssue records")
        if self.issues != tuple(sorted(set(self.issues), key=lambda item: (item.path, item.kind.value, item.detail))):
            raise ValueError("source issues must be unique and sorted")
        if type(self.remaining) is not tuple or any(type(item) is not StaticSourceRemaining for item in self.remaining):
            raise TypeError("remaining must contain StaticSourceRemaining records")
        if self.remaining != tuple(sorted(set(self.remaining), key=lambda item: (item.path, item.kind.value, item.reason))):
            raise ValueError("remaining paths must be unique and sorted")
        expected = StaticSourcesStatus.PARTIAL if self.issues or self.remaining else StaticSourcesStatus.COMPLETE
        if self.status is not expected:
            raise ValueError("source status must reflect issues and unprocessed paths")
        roots = set(self.source_roots)
        for item in self.files:
            if item.namespace_root not in roots or any(mapping.source_root not in roots for mapping in item.module_mappings):
                raise ValueError("source file namespace mapping uses an undeclared root")

    def to_manifest_dict(self) -> dict:
        return {
            "schema": self.SCHEMA,
            "schema_version": self.SCHEMA_VERSION,
            "project_root": self.project_root,
            "source_roots": list(self.source_roots),
            "status": self.status.value,
            "files": [item.to_manifest_dict() for item in self.files],
            "issues": [item.to_dict() for item in self.issues],
            "remaining": [item.to_dict() for item in self.remaining],
            "summary": {
                "files": len(self.files),
                "source_bytes": sum(item.size_bytes for item in self.files),
                "issues": len(self.issues),
                "remaining_paths": len(self.remaining),
            },
        }


__all__ = [
    "StaticSourceFile", "StaticSourceIssue", "StaticSourceIssueKind",
    "StaticSourceRemaining", "StaticSourceRemainingKind", "StaticSources",
    "StaticSourcesStatus",
]
