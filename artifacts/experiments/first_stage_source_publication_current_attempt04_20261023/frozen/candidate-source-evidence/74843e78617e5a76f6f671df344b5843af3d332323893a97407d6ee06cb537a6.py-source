"""Typed records shared by streamed runtime trace source discovery.

These records retain raw source/code identifiers and bounded observations. They
do not assert that a trace is authentic or that a filename identifies source.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import TypeAlias


ProcessID: TypeAlias = int | str | None
RawEventID: TypeAlias = int | str | None


def _exact_int(value: object, name: str, *, minimum: int = 0) -> None:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an exact integer >= {minimum}")


def _exact_text(value: object, name: str, *, nonempty: bool = True) -> None:
    if type(value) is not str or (nonempty and not value):
        qualifier = "non-empty " if nonempty else ""
        raise TypeError(f"{name} must be an exact {qualifier}string")


def _process_id(value: object, name: str) -> None:
    if value is not None and type(value) not in (int, str):
        raise TypeError(f"{name} must be an exact int, exact str, or None")


def _tuple(value: object, name: str) -> None:
    if type(value) is not tuple:
        raise TypeError(f"{name} must be a tuple")


@dataclass(frozen=True, slots=True)
class RuntimeTraceBudget:
    max_uncompressed_bytes: int = 128_000_000
    max_lines: int = 200_000
    max_line_bytes: int = 2_000_000
    max_codes: int = 4096
    max_filename_hints_per_code: int = 8
    max_issues: int = 4096

    def __post_init__(self) -> None:
        for name in ("max_uncompressed_bytes", "max_lines", "max_line_bytes",
                     "max_codes", "max_filename_hints_per_code", "max_issues"):
            _exact_int(getattr(self, name), f"RuntimeTraceBudget.{name}", minimum=1)


@dataclass(frozen=True, slots=True)
class EventKindCount:
    kind: str
    count: int

    def __post_init__(self) -> None:
        _exact_text(self.kind, "EventKindCount.kind")
        _exact_int(self.count, "EventKindCount.count", minimum=1)


@dataclass(frozen=True, slots=True)
class TraceManifest:
    logical_path: str
    raw_sha256: str
    raw_bytes: int
    line_count: int
    record_count: int
    event_counts: tuple[EventKindCount, ...]
    supported_event_count: int
    ignored_event_count: int

    def __post_init__(self) -> None:
        _exact_text(self.logical_path, "TraceManifest.logical_path")
        _exact_text(self.raw_sha256, "TraceManifest.raw_sha256")
        if re.fullmatch(r"[0-9a-f]{64}", self.raw_sha256) is None:
            raise ValueError("TraceManifest.raw_sha256 must be lowercase SHA-256 hex")
        for name in ("raw_bytes", "line_count", "record_count", "supported_event_count",
                     "ignored_event_count"):
            _exact_int(getattr(self, name), f"TraceManifest.{name}")
        _tuple(self.event_counts, "TraceManifest.event_counts")
        if any(not isinstance(item, EventKindCount) for item in self.event_counts):
            raise TypeError("TraceManifest.event_counts must contain EventKindCount")
        if len({item.kind for item in self.event_counts}) != len(self.event_counts):
            raise ValueError("TraceManifest.event_counts kinds must be unique")
        if sum(item.count for item in self.event_counts) != self.record_count:
            raise ValueError("TraceManifest event counts must sum to record_count")
        if self.supported_event_count + self.ignored_event_count != self.record_count:
            raise ValueError("supported and ignored event counts must sum to record_count")
        if self.record_count > self.line_count:
            raise ValueError("TraceManifest.record_count cannot exceed line_count")


class RuntimeFilenameSource(str, Enum):
    CODE_ID_SOURCE = "code_id.source"
    METADATA_FILE = "metadata.file"
    METADATA_FILENAME = "metadata.filename"
    METADATA_SOURCE_FILE = "metadata.source_file"
    METADATA_SOURCE_PATH = "metadata.source_path"
    METADATA_FILENAME_HINT = "metadata.filename_hint"
    EVENT_FILE = "file"
    EVENT_FILENAME = "filename"
    EVENT_SOURCE_FILE = "source_file"
    EVENT_SOURCE_PATH = "source_path"


@dataclass(frozen=True, slots=True)
class RuntimeFilenameHint:
    value: str
    source: RuntimeFilenameSource

    def __post_init__(self) -> None:
        _exact_text(self.value, "RuntimeFilenameHint.value", nonempty=False)
        if not isinstance(self.source, RuntimeFilenameSource):
            raise TypeError("RuntimeFilenameHint.source must be RuntimeFilenameSource")


@dataclass(frozen=True, slots=True)
class RuntimeEventAnchor:
    line_number: int
    line_sha256: str
    kind: str
    index: RawEventID = None
    invocation_id: RawEventID = None

    def __post_init__(self) -> None:
        _exact_int(self.line_number, "RuntimeEventAnchor.line_number", minimum=1)
        _exact_text(self.line_sha256, "RuntimeEventAnchor.line_sha256")
        if re.fullmatch(r"[0-9a-f]{64}", self.line_sha256) is None:
            raise ValueError("RuntimeEventAnchor.line_sha256 must be lowercase SHA-256 hex")
        _exact_text(self.kind, "RuntimeEventAnchor.kind")
        for name in ("index", "invocation_id"):
            value = getattr(self, name)
            if value is not None and type(value) not in (int, str):
                raise TypeError(f"RuntimeEventAnchor.{name} must be an exact int, exact str, or None")


@dataclass(frozen=True, slots=True)
class RuntimeCodeObservation:
    code_id: str
    process_id: ProcessID
    count: int
    first: RuntimeEventAnchor
    last: RuntimeEventAnchor
    filename_hints: tuple[RuntimeFilenameHint, ...] = ()
    dropped_filename_hints: int = 0

    def __post_init__(self) -> None:
        _exact_text(self.code_id, "RuntimeCodeObservation.code_id", nonempty=False)
        _process_id(self.process_id, "RuntimeCodeObservation.process_id")
        _exact_int(self.count, "RuntimeCodeObservation.count", minimum=1)
        if not isinstance(self.first, RuntimeEventAnchor) or not isinstance(self.last, RuntimeEventAnchor):
            raise TypeError("RuntimeCodeObservation first/last must be RuntimeEventAnchor")
        _tuple(self.filename_hints, "RuntimeCodeObservation.filename_hints")
        if any(not isinstance(item, RuntimeFilenameHint) for item in self.filename_hints):
            raise TypeError("RuntimeCodeObservation.filename_hints must contain RuntimeFilenameHint")
        if len({(item.source, item.value) for item in self.filename_hints}) != len(self.filename_hints):
            raise ValueError("RuntimeCodeObservation.filename_hints must be unique")
        _exact_int(self.dropped_filename_hints, "RuntimeCodeObservation.dropped_filename_hints")


class RuntimeTraceIssueKind(str, Enum):
    INVALID_CODE_ID = "INVALID_CODE_ID"
    CODE_ID_PARSE_FAILED = "CODE_ID_PARSE_FAILED"
    INVALID_PROCESS_ID = "INVALID_PROCESS_ID"
    INVALID_EVENT_ID = "INVALID_EVENT_ID"
    INVALID_METADATA = "INVALID_METADATA"
    INVALID_FILENAME_HINT = "INVALID_FILENAME_HINT"
    FILENAME_HINT_LIMIT = "FILENAME_HINT_LIMIT"


@dataclass(frozen=True, slots=True)
class RuntimeTraceIssue:
    kind: RuntimeTraceIssueKind
    line_number: int
    line_sha256: str
    code_id: str | None
    process_id: ProcessID
    count: int
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, RuntimeTraceIssueKind):
            raise TypeError("RuntimeTraceIssue.kind must be RuntimeTraceIssueKind")
        _exact_int(self.line_number, "RuntimeTraceIssue.line_number", minimum=1)
        _exact_text(self.line_sha256, "RuntimeTraceIssue.line_sha256")
        if re.fullmatch(r"[0-9a-f]{64}", self.line_sha256) is None:
            raise ValueError("RuntimeTraceIssue.line_sha256 must be lowercase SHA-256 hex")
        if self.code_id is not None:
            _exact_text(self.code_id, "RuntimeTraceIssue.code_id", nonempty=False)
        _process_id(self.process_id, "RuntimeTraceIssue.process_id")
        _exact_int(self.count, "RuntimeTraceIssue.count", minimum=1)
        _exact_text(self.detail, "RuntimeTraceIssue.detail")


@dataclass(frozen=True, slots=True)
class RuntimeTrace:
    manifest: TraceManifest
    observations: tuple[RuntimeCodeObservation, ...]
    issues: tuple[RuntimeTraceIssue, ...]
    budget: RuntimeTraceBudget

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, TraceManifest):
            raise TypeError("RuntimeTrace.manifest must be TraceManifest")
        if not isinstance(self.budget, RuntimeTraceBudget):
            raise TypeError("RuntimeTrace.budget must be RuntimeTraceBudget")
        _tuple(self.observations, "RuntimeTrace.observations")
        _tuple(self.issues, "RuntimeTrace.issues")
        if any(not isinstance(item, RuntimeCodeObservation) for item in self.observations):
            raise TypeError("RuntimeTrace.observations must contain RuntimeCodeObservation")
        if any(not isinstance(item, RuntimeTraceIssue) for item in self.issues):
            raise TypeError("RuntimeTrace.issues must contain RuntimeTraceIssue")
        keys = [(item.code_id, type(item.process_id), item.process_id) for item in self.observations]
        if len(set(keys)) != len(keys):
            raise ValueError("RuntimeTrace observations must be unique by code_id and process_id")


class RuntimeSeedStatus(str, Enum):
    UNPARSEABLE_CODE_ID = "UNPARSEABLE_CODE_ID"
    AVAILABLE_PYTHON = "AVAILABLE_PYTHON"
    GENERATED = "GENERATED"
    RELATIVE_NO_CWD = "RELATIVE_NO_CWD"
    NON_CANONICAL_PATH = "NON_CANONICAL_PATH"
    OUTSIDE_PROJECT = "OUTSIDE_PROJECT"
    SYMLINK = "SYMLINK"
    MISSING = "MISSING"
    NON_PYTHON = "NON_PYTHON"


@dataclass(frozen=True, slots=True)
class RuntimeSeed:
    observation_index: int
    code_id: str
    process_id: ProcessID
    candidate_path: str
    source: RuntimeFilenameSource
    status: RuntimeSeedStatus
    reason: str

    def __post_init__(self) -> None:
        _exact_int(self.observation_index, "RuntimeSeed.observation_index")
        _exact_text(self.code_id, "RuntimeSeed.code_id", nonempty=False)
        _process_id(self.process_id, "RuntimeSeed.process_id")
        _exact_text(self.candidate_path, "RuntimeSeed.candidate_path", nonempty=False)
        if not isinstance(self.source, RuntimeFilenameSource):
            raise TypeError("RuntimeSeed.source must be RuntimeFilenameSource")
        if not isinstance(self.status, RuntimeSeedStatus):
            raise TypeError("RuntimeSeed.status must be RuntimeSeedStatus")
        _exact_text(self.reason, "RuntimeSeed.reason")


__all__ = [
    "EventKindCount", "ProcessID", "RawEventID", "RuntimeCodeObservation",
    "RuntimeEventAnchor", "RuntimeFilenameHint", "RuntimeFilenameSource",
    "RuntimeSeed", "RuntimeSeedStatus", "RuntimeTrace", "RuntimeTraceBudget",
    "RuntimeTraceIssue", "RuntimeTraceIssueKind", "TraceManifest",
]
