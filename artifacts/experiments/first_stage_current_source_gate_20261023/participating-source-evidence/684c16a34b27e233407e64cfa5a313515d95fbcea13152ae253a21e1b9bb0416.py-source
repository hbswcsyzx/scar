"""Bounded strict reader for captured call-edge trace files.

The reader validates the collector wire records while delivering each decoded
entry/exit to a caller-owned sink.  It retains code descriptors, metadata and
file digests, but never accumulates event rows, frame records or references.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Protocol

from scar.analysis.runtime_sources import _json_object
from scar.ir.program.call_edges import (
    CallEdgeBudget, CallEdgeIssue, CallEdgeIssueKind, CallRecordAnchor,
    CallTraceFile, CapturedCode, CapturedSite, CodeCapture, FrameCompletion,
    FrameEntry, FrameExit, InvocationKey, NamedReference,
)
from scar.ir.record_codec import decode
from scar.trace.files import open_binary


_ENTER_FIELDS = {
    "index", "kind", "process_id", "thread_id", "invocation_id", "code", "parameters",
    "parameters_complete", "caller", "caller_invocation_id", "ancestor_invocation_id",
    "path", "path_complete", "caller_locals", "caller_locals_complete", "suspended",
}
_EXIT_FIELDS = {
    "index", "kind", "process_id", "thread_id", "invocation_id", "code", "return_site",
    "completion", "return_ref", "locals", "locals_complete",
}
_TRACE_FAMILIES = ("codes", "events", "meta")
_TRACE_PATTERN = re.compile(r"call-(codes|events|meta)\.([1-9][0-9]*)\.(jsonl|json)(?:\.gz)?$")


def _require(condition, detail):
    if not condition:
        raise ValueError(detail)


def _exact_int(value, name, minimum=0):
    _require(type(value) is int and value >= minimum, name + " must be an exact integer")
    return value


def _boolean(value, name):
    _require(type(value) is bool, name + " must be an exact boolean")
    return value


def _issue(kind, detail, anchor=None):
    return CallEdgeIssue(kind, detail, anchor)


def _reference(reference, process, index):
    NamedReference("capture", reference)
    parts = reference.split(":")
    _require(int(parts[1]) == process, "reference token belongs to another process")
    if parts[0] == "snapshot":
        _require(int(parts[2]) == index, "snapshot token belongs to another event")
    return reference


def _bindings(value, process, index):
    result = decode(tuple[NamedReference, ...], value)
    _require(len({item.name for item in result}) == len(result), "captured names must be unique")
    for item in result:
        _reference(item.ref, process, index)
    return result


class CallEventSink(Protocol):
    """Consumer for one event at a time; callbacks must not rely on later success."""

    def entry(self, value: FrameEntry) -> None: ...

    def exit(self, value: FrameExit) -> None: ...


class CollectingCallSink:
    """Compatibility sink used by the full call-link reader."""

    def __init__(self):
        self.entries: list[FrameEntry] = []
        self.exits: list[FrameExit] = []

    def entry(self, value: FrameEntry) -> None:
        self.entries.append(value)

    def exit(self, value: FrameExit) -> None:
        self.exits.append(value)

    def abort(self) -> None:
        self.entries.clear()
        self.exits.clear()


@dataclass(frozen=True, slots=True)
class CallTraceScan:
    directory: str
    files: tuple[CallTraceFile, ...]
    captures: tuple[CodeCapture, ...]
    metadata: tuple[dict, ...]
    issues: tuple[CallEdgeIssue, ...]


@dataclass(slots=True)
class _ProcessCounts:
    event_count: int = 0
    entry_count: int = 0
    exit_count: int = 0
    last_index: int = -1
    max_invocation_id: int = 0
    max_parameters: int = 0
    max_caller_locals: int = 0
    max_exit_locals: int = 0
    max_path: int = 0
    incomplete_path_lengths: set[int] | None = None
    unknown_exits: int = 0
    suspended_exits: int = 0
    retained_code_event_bytes: int = 0
    entered: set[InvocationKey] | None = None
    exited: set[InvocationKey] | None = None

    def __post_init__(self):
        self.entered = set()
        self.exited = set()
        self.incomplete_path_lengths = set()


def _read_meta(raw: bytes, *, logical: str, process: int, root: str,
               code_count: int, event_count: int) -> tuple[dict, int, list[CallEdgeIssue]]:
    meta = _json_object(raw, path=logical, line_number=1)
    _require(meta.get("schema") == "scar.call-edge-trace" and type(meta.get("schema_version")) is int
             and meta["schema_version"] == 1, "call collector schema/version mismatch")
    _require(type(meta.get("process_id")) is int and meta["process_id"] == process,
             "collector metadata process disagrees with its filename")
    _require(meta.get("project_root") == root, "collector project root differs from replay")
    _require(meta.get("reference_contents_observed") is False
             and meta.get("callable_environment_established") is False,
             "collector metadata cannot certify contents or callable environments")
    for name in ("events", "invocations", "codes", "bytes", "dropped_events", "dropped_codes",
                 "unknown_exits", "suspended_exits", "open_invocations"):
        _exact_int(meta.get(name), "collector " + name)
    _require(type(meta.get("errors")) is list and all(type(item) is str for item in meta["errors"]),
             "collector errors must be a text array")
    _require(type(meta.get("limits")) is dict and all(type(value) is int and value > 0
                                                       for value in meta["limits"].values()),
             "collector limits must be positive integers")
    _require(meta["codes"] == code_count, "collector code count differs from retained records")
    _require(meta["events"] == event_count, "collector event count differs from retained records")
    attempts = (_exact_int(meta["event_attempts"], "collector event_attempts")
                if "event_attempts" in meta else meta["events"])
    issues = []
    if any(meta[name] for name in ("dropped_events", "dropped_codes", "open_invocations")) or meta["errors"]:
        issues.append(_issue(CallEdgeIssueKind.TRACE_COLLECTION_GAP,
                             "collector reports dropped, failed or still-open frame observations"))
    return meta, attempts, issues


def _decode_event(row: dict, anchor: CallRecordAnchor, process: int, index: int,
                  codes: dict[str, CapturedCode], budget: CallEdgeBudget):
    kind = row.get("kind")
    _require(kind in ("call_enter", "call_exit"), "unknown call edge event kind")
    _require(set(row) == (_ENTER_FIELDS if kind == "call_enter" else _EXIT_FIELDS),
             "call edge event fields mismatch")
    event_index = _exact_int(row["index"], "event index")
    _require(index < event_index, "event indices must be increasing within collector attempts")
    _require(type(row["process_id"]) is int and row["process_id"] == process,
             "event process disagrees with its file")
    identity = InvocationKey(process, row["thread_id"], row["invocation_id"])
    _require(type(row["code"]) is str and re.fullmatch(r"pycode-v2:[0-9a-f]{64}", row["code"]),
             "event needs a stable captured code key")
    if kind == "call_enter":
        def related(value):
            return InvocationKey(process, identity.thread_id, value) if value is not None else None

        path = decode(tuple[CapturedSite, ...], row["path"])
        caller = decode(CapturedSite | None, row["caller"])
        _require(len(path) <= budget.max_path, "captured frame path exceeds replay budget")
        _require(caller == (path[0] if path else None), "caller differs from the immediate path site")
        caller_id, ancestor = related(row["caller_invocation_id"]), related(row["ancestor_invocation_id"])
        _require(caller_id is None or len(path) == 1 and caller_id == ancestor
                 or not path and not row["path_complete"] and ancestor is None,
                 "a tracked immediate caller cannot skip intervening frames")
        parameters = _bindings(row["parameters"], process, event_index)
        caller_locals = _bindings(row["caller_locals"], process, event_index)
        parameters_complete = _boolean(row["parameters_complete"], "parameters_complete")
        path_complete = _boolean(row["path_complete"], "path_complete")
        caller_locals_complete = _boolean(row["caller_locals_complete"], "caller_locals_complete")
        suspended = _boolean(row["suspended"], "suspended")
        entry = FrameEntry(anchor, identity, row["code"], parameters, parameters_complete,
                           caller, caller_id, ancestor, path, path_complete,
                           caller_locals, caller_locals_complete, suspended)
        descriptor = codes.get(entry.code)
        if entry.parameters_complete and descriptor is not None:
            _require(tuple(item.name for item in entry.parameters) == descriptor.parameters,
                     "complete captured formals differ from the code descriptor")
        return kind, event_index, entry, None

    values = _bindings(row["locals"], process, event_index)
    return_site = decode(CapturedSite, row["return_site"])
    completion = FrameCompletion(row["completion"])
    return_ref = _reference(row["return_ref"], process, event_index)
    locals_complete = _boolean(row["locals_complete"], "locals_complete")
    exit_record = FrameExit(anchor, identity, row["code"], return_site, completion,
                            return_ref, values, locals_complete)
    return kind, event_index, None, exit_record


def _validate_process_counts(meta: dict, attempts: int, counts: _ProcessCounts,
                             code_count: int) -> list[CallEdgeIssue]:
    _require(counts.last_index <= attempts, "event indices must be increasing within collector attempts")
    entered, exited = counts.entered, counts.exited
    _require(exited <= entered, "retained frame exit has no retained entry")
    _require(meta["invocations"] == counts.entry_count,
             "collector invocation count differs from retained entries")
    _require(meta["open_invocations"] == len(entered - exited),
             "collector open count differs from unmatched entries")
    _require(meta["unknown_exits"] == counts.unknown_exits,
             "collector unknown completion count differs from retained exits")
    _require(meta["suspended_exits"] == counts.suspended_exits,
             "collector suspension count differs from retained exits")
    actual_bytes = counts.retained_code_event_bytes
    _require(meta["bytes"] == actual_bytes, "collector byte count differs from retained code/events")
    _require(counts.event_count <= attempts and attempts - counts.event_count <= meta["dropped_events"],
             "collector attempt gaps have no declared dropped events")
    if "invocation_attempts" in meta:
        invocations = _exact_int(meta["invocation_attempts"], "collector invocation_attempts")
        _require(counts.entry_count <= invocations <= counts.entry_count + meta["dropped_events"],
                 "collector invocation attempt count is inconsistent")
        _require(counts.max_invocation_id <= invocations,
                 "retained invocation exceeds attempted invocation IDs")
    if "active_frames" in meta:
        active = _exact_int(meta["active_frames"], "collector active_frames")
        _require(active <= meta["open_invocations"],
                 "active frame count exceeds unmatched retained entries")
        if not meta["dropped_events"] and not meta["errors"]:
            _require(active == meta["open_invocations"],
                     "complete collector active/open counts disagree")
    limits = meta["limits"]
    _require(all(name in limits for name in ("max_events", "max_bytes", "max_codes", "max_values", "max_path")),
             "collector metadata is missing required collection limits")
    _require(attempts <= limits["max_events"] and actual_bytes <= limits["max_bytes"]
             and code_count <= limits["max_codes"],
             "retained collection exceeds its declared limits")
    _require(counts.max_parameters <= limits["max_values"]
             and counts.max_caller_locals <= limits["max_values"]
             and counts.max_exit_locals <= limits["max_values"]
             and counts.max_path <= limits["max_path"],
             "retained capture vectors exceed collection limits")
    if "path_gaps" in meta:
        gaps = _exact_int(meta["path_gaps"], "collector path_gaps")
        _require(gaps <= counts.entry_count + meta["dropped_events"],
                 "collector path gap count is inconsistent")
        _require(gaps or all(length == limits["max_path"]
                             for length in counts.incomplete_path_lengths),
                 "short incomplete frame path has no declared capture gap")
    issues = []
    if "io_failed" in meta:
        _boolean(meta["io_failed"], "io_failed")
        if meta["io_failed"]:
            issues.append(_issue(CallEdgeIssueKind.TRACE_COLLECTION_GAP,
                                 "collector reports an I/O failure"))
    return issues


def scan_call_trace(trace, root, budget, *, sink: CallEventSink) -> CallTraceScan:
    """Validate one complete calls-trace directory and stream decoded events.

    `sink.entry` and `sink.exit` are called in process/file order. If scanning
    or a sink callback fails, no `CallTraceScan` is returned. Sinks that keep
    state should implement `abort()` to discard callbacks from a failed scan.
    """
    if not isinstance(budget, CallEdgeBudget):
        raise TypeError("scan_call_trace requires a CallEdgeBudget")
    budget.__post_init__()
    trace_path = Path(trace).resolve()
    _require(trace_path.is_dir(), "call trace must be a directory")
    root_text = str(root)
    families: dict[tuple[int, str], Path] = {}
    admitted_processes = set()
    for path in trace_path.iterdir():
        match = _TRACE_PATTERN.fullmatch(path.name)
        if not match:
            continue
        family, process_text, suffix = match.groups()
        _require((family == "meta") == (suffix == "json"), "call trace family has the wrong suffix")
        process = int(process_text)
        admitted_processes.add(process)
        _require(len(admitted_processes) <= budget.max_processes, "call trace process budget exceeded")
        key = process, family
        _require(key not in families, "plain and gzip call trace files are ambiguous")
        _require(path.is_file() and not path.is_symlink(), "call trace files must be ordinary retained files")
        families[key] = path
    processes = sorted({process for process, _ in families})
    _require(processes, "call trace has no call-codes/events/meta families")
    _require(len(processes) <= budget.max_processes, "call trace process budget exceeded")
    _require(all((process, family) in families for process in processes for family in _TRACE_FAMILIES),
             "each process requires codes, events and metadata")

    files_by_key: dict[tuple[int, str], CallTraceFile] = {}
    captures: list[CodeCapture] = []
    metadata: list[dict] = []
    issues: list[CallEdgeIssue] = []
    codes: dict[str, CapturedCode] = {}
    total_bytes = total_lines = total_events = references = 0
    all_entries: set[InvocationKey] = set()
    all_exits: set[InvocationKey] = set()
    duplicate_entry = duplicate_exit = False

    def read_family(process: int, family: str):
        nonlocal total_bytes, total_lines, total_events, references
        nonlocal duplicate_entry, duplicate_exit
        path = families[process, family]
        logical = str(path.with_suffix("")) if path.suffix == ".gz" else str(path)
        digest = hashlib.sha256()
        file_bytes = line_number = code_count = 0
        meta_buffer = bytearray() if family == "meta" else None
        counts = _ProcessCounts() if family == "events" else None
        pending_event_error = None
        previous = -1
        for raw in _iter_lines(path, budget.max_line_bytes):
            _require(len(raw) <= budget.max_line_bytes, "call trace line byte budget exceeded")
            line_number += 1
            total_lines += 1
            file_bytes += len(raw)
            total_bytes += len(raw)
            _require(total_lines <= budget.max_lines and total_bytes <= budget.max_raw_bytes,
                     "call trace decompressed byte/line budget exceeded")
            digest.update(raw)
            if family == "meta":
                meta_buffer.extend(raw)
                continue
            if not raw.strip():
                continue
            row = _json_object(raw, path=logical, line_number=line_number)
            anchor = CallRecordAnchor(logical, line_number, hashlib.sha256(raw).hexdigest(), row.get("index"))
            if family == "codes":
                code = decode(CapturedCode, row)
                _require(code.key not in codes or codes[code.key] == code,
                         "one fingerprint has conflicting code descriptors")
                codes[code.key] = code
                captures.append(CodeCapture(code, anchor, process))
                code_count += 1
                _require(len(captures) <= budget.max_codes, "call trace code budget exceeded")
                continue

            total_events += 1
            counts.event_count += 1
            _require(total_events <= budget.max_events, "call trace event budget exceeded")
            if pending_event_error is not None:
                # The old reader parses every event's JSON and anchor before it
                # semantically decodes events, which happens after metadata.
                # Keep that failure ordering without retaining prior rows.
                continue
            try:
                kind, event_index, entry, exit_record = _decode_event(
                    row, anchor, process, previous, codes, budget)
            except Exception as error:
                pending_event_error = error
                continue
            previous = event_index
            counts.last_index = event_index
            if kind == "call_enter":
                counts.entry_count += 1
                counts.entered.add(entry.invocation)
                counts.max_invocation_id = max(counts.max_invocation_id, entry.invocation.invocation_id)
                counts.max_parameters = max(counts.max_parameters, len(entry.parameters))
                counts.max_caller_locals = max(counts.max_caller_locals, len(entry.caller_locals))
                counts.max_path = max(counts.max_path, len(entry.path))
                if not entry.path_complete:
                    counts.incomplete_path_lengths.add(len(entry.path))
                duplicate_entry |= entry.invocation in all_entries
                all_entries.add(entry.invocation)
                sink.entry(entry)
                references += len(entry.parameters) + len(entry.caller_locals)
            else:
                counts.exit_count += 1
                counts.exited.add(exit_record.invocation)
                counts.max_invocation_id = max(counts.max_invocation_id, exit_record.invocation.invocation_id)
                counts.max_exit_locals = max(counts.max_exit_locals, len(exit_record.locals))
                counts.unknown_exits += exit_record.completion is FrameCompletion.UNKNOWN
                counts.suspended_exits += exit_record.completion is FrameCompletion.SUSPENDED
                duplicate_exit |= exit_record.invocation in all_exits
                all_exits.add(exit_record.invocation)
                sink.exit(exit_record)
                references += len(exit_record.locals) + 1
            _require(references <= budget.max_references, "captured reference budget exceeded")

        file_record = CallTraceFile(logical, family, process, digest.hexdigest(), file_bytes, line_number)
        files_by_key[process, family] = file_record
        if family == "codes":
            return code_count, file_bytes
        if family == "events":
            return counts, file_bytes, pending_event_error
        return bytes(meta_buffer), file_bytes

    try:
        # Preserve the original per-process descriptor visibility. A later
        # process's codes cannot retrospectively validate an earlier entry.
        for process in processes:
            code_count, _ = read_family(process, "codes")
            counts, events_bytes, pending_event_error = read_family(process, "events")
            meta_raw, _ = read_family(process, "meta")
            logical = files_by_key[process, "meta"].path
            meta, attempts, metadata_issues = _read_meta(
                meta_raw, logical=logical, process=process, root=root_text,
                code_count=code_count, event_count=counts.event_count)
            issues.extend(metadata_issues)
            metadata.append(meta)
            if pending_event_error is not None:
                raise pending_event_error
            code_event_bytes = (files_by_key[process, "codes"].raw_bytes + events_bytes)
            counts.retained_code_event_bytes = code_event_bytes
            issues.extend(_validate_process_counts(meta, attempts, counts, code_count))
        _require(not duplicate_entry, "duplicate process/thread/invocation entry")
        _require(not duplicate_exit, "duplicate process/thread/invocation exit")
        files = tuple(files_by_key[process, family]
                      for process in processes for family in _TRACE_FAMILIES)
        return CallTraceScan(str(trace_path), files, tuple(captures), tuple(metadata), tuple(issues))
    except BaseException:
        abort = getattr(sink, "abort", None)
        if callable(abort):
            try:
                abort()
            except BaseException:
                pass
        raise


def _iter_lines(path: Path, limit: int):
    with open_binary(path) as stream:
        while True:
            raw = stream.readline(limit + 1)
            if not raw:
                return
            yield raw


__all__ = [
    "CallTraceScan", "CollectingCallSink", "scan_call_trace",
    "_bindings", "_boolean", "_exact_int", "_issue", "_json_object", "_reference",
]
