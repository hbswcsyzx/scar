"""Stream runtime event traces into bounded source-code observations.

The reader preserves raw CodeID strings and trace-file witnesses. It does not
load event payloads into the graph, import target modules, or authenticate the
trace producer.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import stat
from typing import Any
import zlib

from scar.ir.ids import CodeID
from scar.ir.program.runtime_sources import (
    EventKindCount, ProcessID, RuntimeCodeObservation, RuntimeEventAnchor,
    RuntimeFilenameHint, RuntimeFilenameSource, RuntimeSeed, RuntimeSeedStatus,
    RuntimeTrace, RuntimeTraceBudget, RuntimeTraceIssue, RuntimeTraceIssueKind,
    TraceManifest,
)
from scar.trace.files import open_binary, resolve


_SUPPORTED_KINDS = frozenset({
    "python_call", "python_return", "module_call", "python_c_call",
    "python_line", "loop_iteration",
})
_EVENT_HINT_FIELDS = (
    ("file", RuntimeFilenameSource.EVENT_FILE),
    ("filename", RuntimeFilenameSource.EVENT_FILENAME),
    ("source_file", RuntimeFilenameSource.EVENT_SOURCE_FILE),
    ("source_path", RuntimeFilenameSource.EVENT_SOURCE_PATH),
)
_METADATA_HINT_FIELDS = (
    ("file", RuntimeFilenameSource.METADATA_FILE),
    ("filename", RuntimeFilenameSource.METADATA_FILENAME),
    ("source_file", RuntimeFilenameSource.METADATA_SOURCE_FILE),
    ("source_path", RuntimeFilenameSource.METADATA_SOURCE_PATH),
    ("filename_hint", RuntimeFilenameSource.METADATA_FILENAME_HINT),
)


@dataclass(slots=True)
class _MutableObservation:
    code_id: str
    process_id: ProcessID
    count: int
    first: RuntimeEventAnchor
    last: RuntimeEventAnchor
    hints: list[RuntimeFilenameHint] = field(default_factory=list)
    hint_keys: set[tuple[RuntimeFilenameSource, str]] = field(default_factory=set)
    dropped_hints: int = 0


@dataclass(slots=True)
class _MutableIssue:
    kind: RuntimeTraceIssueKind
    line_number: int
    line_sha256: str
    code_id: str | None
    process_id: ProcessID
    count: int
    detail: str


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("non-finite JSON number")
    return value


def _reject_constant(text: str):
    raise ValueError(f"non-finite JSON constant: {text}")


def _json_object(raw_line: bytes, *, path: str, line_number: int) -> dict[str, Any]:
    try:
        text = raw_line.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ValueError(f"{path}: invalid UTF-8 at raw line {line_number}") from error
    try:
        value = json.loads(text, object_pairs_hook=_strict_object,
                           parse_float=_finite_float, parse_constant=_reject_constant)
    except (json.JSONDecodeError, ValueError, OverflowError) as error:
        raise ValueError(f"{path}: invalid JSON at raw line {line_number}: {error}") from error
    if type(value) is not dict:
        raise ValueError(f"{path}: raw line {line_number} must contain a JSON object")
    return value


def _process_id(
    row: dict[str, Any], metadata: dict[str, Any] | None,
) -> tuple[ProcessID, str | None]:
    """Read all supported process identity fields without choosing conflicts.

    SCAR's TraceSession records ``process_id`` in event metadata. Other trace
    producers may use top-level ``process_id`` or ``pid``. If a record carries
    more than one spelling, they must agree by both exact type and value.
    """
    candidates: list[tuple[str, Any]] = []
    for field_name in ("process_id", "pid"):
        if field_name in row:
            candidates.append((f"event.{field_name}", row[field_name]))
    if metadata is not None and "process_id" in metadata:
        candidates.append(("metadata.process_id", metadata["process_id"]))

    for field_name, value in candidates:
        if value is not None and type(value) not in (int, str):
            return None, (
                f"{field_name} must be exact int, exact str, or None "
                f"(received {type(value).__name__})")
    if not candidates:
        return None, None

    source, value = candidates[0]
    for other_source, other_value in candidates[1:]:
        if type(value) is not type(other_value) or value != other_value:
            return None, f"{source} and {other_source} process identity fields disagree"
    return value, None


def _event_id(row: dict[str, Any], field_name: str) -> tuple[int | str | None, str | None]:
    if field_name not in row or row[field_name] is None:
        return None, None
    value = row[field_name]
    if type(value) in (int, str):
        return value, None
    return None, f"{field_name} must be exact int, exact str, or None (received {type(value).__name__})"


def _logical_path(path: Path) -> str:
    if path.suffix == ".gz":
        path = path.with_suffix("")
    return str(path)


def read_runtime_trace(
    trace: str | Path,
    *,
    budget: RuntimeTraceBudget = RuntimeTraceBudget(),
) -> RuntimeTrace:
    """Read a JSONL trace in bounded decompressed-byte and line-size chunks.

    Every returned summary is complete for the selected stream. Any read,
    decode, JSON, or budget failure raises ``ValueError`` instead of returning
    a partial trace that could be mistaken for a complete one.
    """
    if type(budget) is not RuntimeTraceBudget:
        raise TypeError("budget must be RuntimeTraceBudget")
    # Freeze the trace input's cwd interpretation at the call boundary. The
    # logical path is later stored in reports and may be replayed from another
    # working directory. This does not apply to CodeID source paths.
    trace_input = Path(os.path.abspath(Path(trace)))
    resolved = resolve(trace_input, default_name="events.jsonl")
    if not resolved.is_file():
        raise ValueError("runtime trace must be a regular file")
    # Frozen dataclasses can still be deliberately corrupted via
    # object.__setattr__; never let mutated limits weaken the read boundary.
    RuntimeTraceBudget.__post_init__(budget)
    logical_path = _logical_path(resolved)
    raw_digest = hashlib.sha256()
    raw_bytes = 0
    line_count = 0
    record_count = 0
    supported_count = 0
    ignored_count = 0
    kind_counts: Counter[str] = Counter()
    observations: dict[tuple[str, type, object], _MutableObservation] = {}
    issues: dict[tuple[RuntimeTraceIssueKind, str | None, type, object, str], _MutableIssue] = {}

    def add_issue(kind: RuntimeTraceIssueKind, line_number: int, line_hash: str,
                  code_id: str | None, process_id: ProcessID, detail: str) -> None:
        key = (kind, code_id, type(process_id), process_id, detail)
        issue = issues.get(key)
        if issue is not None:
            issue.count += 1
            return
        if len(issues) >= budget.max_issues:
            raise ValueError(f"{logical_path}: runtime trace issue budget exceeded ({budget.max_issues})")
        issues[key] = _MutableIssue(kind, line_number, line_hash, code_id,
                                    process_id, 1, detail)

    try:
        with open_binary(resolved) as stream:
            while True:
                raw_line = stream.readline(budget.max_line_bytes + 1)
                if not raw_line:
                    break
                line_count += 1
                if line_count > budget.max_lines:
                    raise ValueError(f"{logical_path}: raw line budget exceeded ({budget.max_lines})")
                if len(raw_line) > budget.max_line_bytes:
                    raise ValueError(
                        f"{logical_path}: raw line {line_count} exceeds {budget.max_line_bytes} bytes")
                raw_bytes += len(raw_line)
                if raw_bytes > budget.max_uncompressed_bytes:
                    raise ValueError(
                        f"{logical_path}: decompressed byte budget exceeded "
                        f"({budget.max_uncompressed_bytes})")
                raw_digest.update(raw_line)
                line_hash = hashlib.sha256(raw_line).hexdigest()
                if not raw_line.strip():
                    continue
                row = _json_object(raw_line, path=logical_path, line_number=line_count)
                record_count += 1
                raw_kind = row.get("kind")
                if type(raw_kind) is str and raw_kind:
                    kind = raw_kind
                elif raw_kind is None:
                    kind = "<missing-kind>"
                else:
                    kind = "<non-string-kind>"
                kind_counts[kind] += 1
                if kind not in _SUPPORTED_KINDS:
                    ignored_count += 1
                    continue
                supported_count += 1

                raw_code_id = row.get("code_id")
                code_id = raw_code_id if type(raw_code_id) is str else None
                metadata = row.get("metadata")
                metadata_error = None
                if "metadata" in row and type(metadata) is not dict:
                    metadata_error = (
                        f"metadata must be a JSON object "
                        f"(received {type(metadata).__name__})")
                    metadata = None
                process_id, process_error = _process_id(row, metadata)
                if metadata_error is not None:
                    add_issue(RuntimeTraceIssueKind.INVALID_METADATA,
                              line_count, line_hash, code_id,
                              process_id if process_error is None else None,
                              metadata_error)
                if process_error is not None:
                    add_issue(RuntimeTraceIssueKind.INVALID_PROCESS_ID,
                              line_count, line_hash, code_id, None, process_error)
                    continue
                if code_id is None:
                    received = "missing" if "code_id" not in row else type(raw_code_id).__name__
                    add_issue(RuntimeTraceIssueKind.INVALID_CODE_ID,
                              line_count, line_hash, None, process_id,
                              f"code_id must be an exact string ({received})")
                    continue

                parsed = CodeID.parse_key(code_id)
                if parsed is None:
                    add_issue(RuntimeTraceIssueKind.CODE_ID_PARSE_FAILED,
                              line_count, line_hash, code_id, process_id,
                              "CodeID.parse_key did not recognize the raw code_id")

                event_index, index_error = _event_id(row, "index")
                invocation_id, invocation_error = _event_id(row, "invocation_id")
                if index_error is not None:
                    add_issue(RuntimeTraceIssueKind.INVALID_EVENT_ID,
                              line_count, line_hash, code_id, process_id, index_error)
                if invocation_error is not None:
                    add_issue(RuntimeTraceIssueKind.INVALID_EVENT_ID,
                              line_count, line_hash, code_id, process_id, invocation_error)
                anchor = RuntimeEventAnchor(line_count, line_hash, kind,
                                            event_index, invocation_id)
                key = (code_id, type(process_id), process_id)
                observation = observations.get(key)
                if observation is None:
                    if len(observations) >= budget.max_codes:
                        raise ValueError(f"{logical_path}: code observation budget exceeded ({budget.max_codes})")
                    observation = _MutableObservation(code_id, process_id, 1, anchor, anchor)
                    observations[key] = observation
                else:
                    observation.count += 1
                    observation.last = anchor

                candidates = [(row, _EVENT_HINT_FIELDS)]
                if metadata is not None:
                    candidates.append((metadata, _METADATA_HINT_FIELDS))
                for container, fields in candidates:
                    for field_name, hint_source in fields:
                        if field_name not in container:
                            continue
                        hint = container[field_name]
                        if type(hint) is not str:
                            add_issue(RuntimeTraceIssueKind.INVALID_FILENAME_HINT,
                                      line_count, line_hash, code_id, process_id,
                                      f"{hint_source.value} must be an exact string "
                                      f"(received {type(hint).__name__})")
                            continue
                        hint_key = (hint_source, hint)
                        if hint_key in observation.hint_keys:
                            continue
                        if len(observation.hints) >= budget.max_filename_hints_per_code:
                            observation.dropped_hints += 1
                            add_issue(RuntimeTraceIssueKind.FILENAME_HINT_LIMIT,
                                      line_count, line_hash, code_id, process_id,
                                      "distinct filename hint cap reached for this observation")
                            continue
                        observation.hint_keys.add(hint_key)
                        observation.hints.append(RuntimeFilenameHint(hint, hint_source))
    except ValueError:
        raise
    except (OSError, EOFError, gzip.BadGzipFile, zlib.error) as error:
        raise ValueError(f"{logical_path}: trace stream could not be read: {error}") from error

    manifest = TraceManifest(
        logical_path=logical_path,
        raw_sha256=raw_digest.hexdigest(),
        raw_bytes=raw_bytes,
        line_count=line_count,
        record_count=record_count,
        event_counts=tuple(EventKindCount(name, count)
                           for name, count in sorted(kind_counts.items())),
        supported_event_count=supported_count,
        ignored_event_count=ignored_count,
    )
    frozen_observations = tuple(
        RuntimeCodeObservation(
            code_id=item.code_id,
            process_id=item.process_id,
            count=item.count,
            first=item.first,
            last=item.last,
            filename_hints=tuple(item.hints),
            dropped_filename_hints=item.dropped_hints,
        )
        for item in observations.values()
    )
    frozen_issues = tuple(
        RuntimeTraceIssue(item.kind, item.line_number, item.line_sha256,
                          item.code_id, item.process_id, item.count, item.detail)
        for item in issues.values()
    )
    return RuntimeTrace(manifest, frozen_observations, frozen_issues, budget)


def _classify_candidate(candidate: str, root: Path) -> tuple[RuntimeSeedStatus, str]:
    if candidate.startswith("<") and candidate.endswith(">"):
        return RuntimeSeedStatus.GENERATED, "CodeID source is a generated filename, not a filesystem path"
    path = Path(candidate)
    if not path.is_absolute():
        return RuntimeSeedStatus.RELATIVE_NO_CWD, "relative source path is retained without resolving against analyzer cwd"
    normalized_text = os.path.normpath(candidate)
    if normalized_text != candidate:
        return RuntimeSeedStatus.NON_CANONICAL_PATH, (
            "absolute source path is non-canonical; it is retained without "
            "normalization or filesystem access")
    normalized = Path(normalized_text)
    if not normalized.is_relative_to(root):
        return RuntimeSeedStatus.OUTSIDE_PROJECT, "absolute source path lies outside project_root"
    if normalized.suffix != ".py":
        return RuntimeSeedStatus.NON_PYTHON, "source candidate does not have a .py suffix"

    relative_parts = normalized.relative_to(root).parts
    current = root
    for part in relative_parts:
        current = current / part
        try:
            info = current.lstat()
        except (OSError, ValueError):
            return RuntimeSeedStatus.MISSING, "source path or one of its components is unavailable"
        if stat.S_ISLNK(info.st_mode):
            return RuntimeSeedStatus.SYMLINK, "source candidate passes through a symlink; it was not followed"
        if current != normalized and not stat.S_ISDIR(info.st_mode):
            return RuntimeSeedStatus.MISSING, "source path has a non-directory parent component"
    try:
        info = normalized.lstat()
    except (OSError, ValueError):
        return RuntimeSeedStatus.MISSING, "source file does not exist"
    if stat.S_ISLNK(info.st_mode):
        return RuntimeSeedStatus.SYMLINK, "source candidate is a symlink; it was not followed"
    if not stat.S_ISREG(info.st_mode):
        return RuntimeSeedStatus.MISSING, "source candidate is not a regular file"
    return RuntimeSeedStatus.AVAILABLE_PYTHON, "absolute in-project non-symlink .py file exists"


def resolve_runtime_seeds(runtime: RuntimeTrace,
                          project_root: str | Path) -> tuple[RuntimeSeed, ...]:
    """Classify each observation's CodeID source path without opening it.

    Metadata filename hints remain attached to observations for compile-time
    candidate trials; they never replace or repair the CodeID source path.
    """
    if not isinstance(runtime, RuntimeTrace):
        raise TypeError("runtime must be RuntimeTrace")
    root_input = Path(project_root)
    if not root_input.is_absolute():
        raise ValueError("project_root must be absolute to avoid cwd-dependent source resolution")
    try:
        root = root_input.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ValueError(f"project_root is unavailable: {error}") from error
    if not root.is_dir():
        raise ValueError("project_root must be a directory")

    seeds = []
    for index, observation in enumerate(runtime.observations):
        parsed = CodeID.parse_key(observation.code_id)
        if parsed is None:
            seeds.append(RuntimeSeed(
                index, observation.code_id, observation.process_id, "",
                RuntimeFilenameSource.CODE_ID_SOURCE,
                RuntimeSeedStatus.UNPARSEABLE_CODE_ID,
                "raw CodeID did not parse; filename hints are retained only as compile filename candidates",
            ))
            continue
        candidate = parsed.source
        status, reason = _classify_candidate(candidate, root)
        seeds.append(RuntimeSeed(
            index, observation.code_id, observation.process_id, candidate,
            RuntimeFilenameSource.CODE_ID_SOURCE, status, reason,
        ))
    return tuple(seeds)


__all__ = ["read_runtime_trace", "resolve_runtime_seeds"]
