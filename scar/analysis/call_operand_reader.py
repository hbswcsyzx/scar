"""Independently read bounded operand sidecars and their original v1 frame trace."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re

from scar.analysis.call_trace_reader import CallTraceScan, CollectingCallSink, scan_call_trace
from scar.analysis.runtime_sources import _json_object
from scar.ir.program.call_edges import (
    CallEdgeBudget, CallRecordAnchor, CallTraceFile, FrameEntry, FrameExit, InvocationKey,
)
from scar.ir.program.call_operands import (
    CallOperandBudget, CallableKind, OperandCallAttempt, OperandCollectionMetadata,
    OperandEntryHandshake, OperandEvent, OperandEventKind, OperandGap, OperandInstruction,
    operand_references,
)
from scar.ir.record_codec import decode
from scar.trace.files import open_binary


_PATTERN = re.compile(r"call-(operands|operand-meta)\.([1-9][0-9]*)\.(jsonl|json)(?:\.gz)?$")
_TYPES = {
    "INSTRUCTION": OperandInstruction,
    "CALL_ATTEMPT": OperandCallAttempt,
    "ENTRY_HANDSHAKE": OperandEntryHandshake,
    "GAP": OperandGap,
}


def _require(condition, detail):
    if not condition:
        raise ValueError(detail)


@dataclass(frozen=True, slots=True)
class OperandReadIssue:
    """An observed boundary, never a successfully established operand route."""
    kind: str
    detail: str
    process_id: int
    anchor: CallRecordAnchor | None = None
    invocation: InvocationKey | None = None


@dataclass(frozen=True, slots=True)
class CallOperandTrace:
    directory: str
    project_root: str
    budget: CallOperandBudget
    frame_budget: CallEdgeBudget
    frame_scan: CallTraceScan
    entries: tuple[FrameEntry, ...]
    exits: tuple[FrameExit, ...]
    events: tuple[OperandEvent, ...]
    files: tuple[CallTraceFile, ...]
    metadata: tuple[OperandCollectionMetadata, ...]
    issues: tuple[OperandReadIssue, ...] = ()

    @property
    def instructions(self):
        return tuple(event for event in self.events if type(event) is OperandInstruction)

    @property
    def attempts(self):
        return tuple(event for event in self.events if type(event) is OperandCallAttempt)

    @property
    def handshakes(self):
        return tuple(event for event in self.events if type(event) is OperandEntryHandshake)

    @property
    def gaps(self):
        return tuple(event for event in self.events if type(event) is OperandGap)


def read_call_operands(trace, root, *, budget=CallOperandBudget(), frame_budget=CallEdgeBudget()):
    """Read both protocols afresh; no caller-provided validated trace is accepted.

    Structural errors raise ValueError. Captured code/layout inconsistencies,
    incomplete collection and hook interference remain explicit boundaries.
    This reader does not establish source correspondence or argument routing.
    """
    _require(type(budget) is CallOperandBudget, "operand reader requires a typed independent budget")
    _require(type(frame_budget) is CallEdgeBudget, "operand reader requires a typed frame budget")
    budget.__post_init__()
    frame_budget.__post_init__()
    trace_path, root_path = Path(trace).resolve(), Path(root).resolve()
    _require(root_path.is_dir(), "operand project root must be a directory")
    sink = CollectingCallSink()
    frame_scan = scan_call_trace(trace_path, root_path, frame_budget, sink=sink)
    entries, exits = tuple(sink.entries), tuple(sink.exits)
    families = {}
    processes = set()
    for path in trace_path.iterdir():
        match = _PATTERN.fullmatch(path.name)
        if match is None:
            continue
        family, process_text, suffix = match.groups()
        _require((family == "operand-meta") == (suffix == "json"), "operand family has wrong suffix")
        process = int(process_text)
        processes.add(process)
        _require(len(processes) <= budget.max_processes, "operand process budget exceeded")
        _require((process, family) not in families, "plain and gzip operand files are ambiguous")
        _require(path.is_file() and not path.is_symlink(), "operand files must be ordinary retained files")
        families[process, family] = path
    _require(processes, "trace has no operand sidecars")
    _require(all((process, family) in families for process in processes for family in ("operands", "operand-meta")),
             "each operand process requires events and metadata")
    base_files = {(item.process_id, item.family): item for item in frame_scan.files}
    base_meta = {item["process_id"]: item for item in frame_scan.metadata}
    _require(processes <= set(base_meta), "operand process has no original frame trace")

    total_bytes = total_lines = total_events = total_loads = total_references = 0
    files, metadata, events, issues = [], [], [], []

    def read_lines(process, family):
        nonlocal total_bytes, total_lines
        path = families[process, family]
        logical = str(path.with_suffix("")) if path.suffix == ".gz" else str(path)
        digest = hashlib.sha256()
        file_bytes = lines = 0
        with open_binary(path) as stream:
            while True:
                allowance = min(budget.max_line_bytes, budget.max_raw_bytes - total_bytes)
                if family == "operand-meta":
                    allowance = min(allowance, budget.max_metadata_bytes - file_bytes)
                if total_lines >= budget.max_lines:
                    allowance = 0
                # At most one byte beyond a ceiling, including decompression.
                raw = stream.readline(max(0, allowance) + 1)
                if not raw:
                    break
                _require(len(raw) <= budget.max_line_bytes, "operand line byte budget exceeded")
                total_bytes += len(raw)
                total_lines += 1
                file_bytes += len(raw)
                lines += 1
                _require(total_bytes <= budget.max_raw_bytes and total_lines <= budget.max_lines,
                         "operand decompressed byte/line budget exceeded")
                if family == "operand-meta":
                    _require(file_bytes <= budget.max_metadata_bytes, "operand metadata byte budget exceeded")
                digest.update(raw)
                yield logical, lines, raw
        files.append(CallTraceFile(logical, family, process, digest.hexdigest(), file_bytes, lines))

    for process in sorted(processes):
        meta_raw = bytearray()
        meta_logical = None
        for logical, line, raw in read_lines(process, "operand-meta"):
            meta_logical = logical
            meta_raw.extend(raw)
        _require(meta_logical is not None, "operand metadata is empty")
        meta = decode(OperandCollectionMetadata, _json_object(bytes(meta_raw), path=meta_logical, line_number=1))
        _require(meta.process_id == process, "operand metadata process differs from filename")
        _require(meta.project_root == str(root_path), "operand project root differs from replay")
        _require(meta.python == base_meta[process].get("python"), "operand/frame interpreter descriptions differ")
        _require(meta.limits.max_references == base_meta[process]["limits"].get("max_references"),
                 "operand weak-reference limit differs from original shared issuer")
        expected = {family: base_files[process, family] for family in ("codes", "events", "meta")}
        _require({item.family: item for item in meta.base_manifest} == expected,
                 "operand metadata does not bind the original frame file manifest")
        metadata.append(meta)
        if meta.previous_profile:
            issues.append(OperandReadIssue("PREVIOUS_PROFILE", "a previous profile callback was chained", process))
        if meta.dropped_events or meta.errors or meta.io_failed:
            issues.append(OperandReadIssue("COLLECTION_GAP", "operand collector reports drops/errors/I/O failure", process))
        if any(base_meta[process][name] for name in ("dropped_events", "dropped_codes", "open_invocations")) or base_meta[process]["errors"] or base_meta[process].get("io_failed"):
            issues.append(OperandReadIssue("FRAME_COLLECTION_GAP", "original frame collector reports incomplete observations", process))
        counts = {kind: 0 for kind in OperandEventKind}
        count_loads = count_references = event_bytes = 0
        previous_index, previous_frame, previous_epoch = 0, 0, 1
        previous_event = None
        process_events = []
        base_attempts = base_meta[process].get("event_attempts", base_meta[process]["events"])
        for logical, line, raw in read_lines(process, "operands"):
            event_bytes += len(raw)
            _require(raw.endswith(b"\n") and bool(raw.strip()), "operand events must be complete nonempty JSON lines")
            row = _json_object(raw, path=logical, line_number=line)
            kind = row.get("kind")
            _require(type(kind) is str and kind in _TYPES, "unknown operand event kind")
            anchor = CallRecordAnchor(logical, line, hashlib.sha256(raw).hexdigest(), row.get("index"))
            _require("anchor" not in row, "raw operand events cannot supply their own anchors")
            event = decode(_TYPES[kind], {**row, "anchor": {
                "path": anchor.path, "line_number": anchor.line_number,
                "line_sha256": anchor.line_sha256, "index": anchor.index,
            }})
            _require(event.process_id == process, "operand event process differs from filename")
            _require(previous_index < event.index <= meta.event_attempts, "operand event indices are not ordered within attempts")
            _require(previous_frame <= event.frame_index <= base_attempts, "operand frame watermark is outside the original event sequence")
            _require(previous_epoch <= event.hook_epoch, "operand hook epoch moved backwards")
            if event.hook_epoch > previous_epoch:
                _require(type(event) is OperandGap or type(previous_event) is OperandGap,
                         "operand hook epoch changed without a gap")
            previous_index, previous_frame, previous_epoch = event.index, event.frame_index, event.hook_epoch
            previous_event = event
            count = len(event.loads) if type(event) is OperandInstruction else 0
            _require(count <= meta.limits.max_loads, "instruction load vector exceeds collector limit")
            refs = operand_references(event)
            for reference in refs:
                parts = reference.split(":")
                _require(int(parts[1]) == process, "operand reference belongs to another process")
                if parts[0] == "operand-snapshot":
                    _require(int(parts[2]) == event.index, "operand snapshot belongs to another observation")
            total_events += 1
            total_loads += count
            total_references += len(refs)
            _require(total_events <= budget.max_events and total_loads <= budget.max_loads
                     and total_references <= budget.max_references, "operand aggregate event/load/reference budget exceeded")
            counts[event.kind] += 1
            count_loads += count
            count_references += len(refs)
            process_events.append(event)
        _require(meta.events == len(process_events) and meta.bytes == event_bytes,
                 "operand retained event/byte counts disagree with metadata")
        for field, kind in (("instructions", OperandEventKind.INSTRUCTION), ("call_attempts", OperandEventKind.CALL_ATTEMPT),
                            ("handshakes", OperandEventKind.ENTRY_HANDSHAKE), ("gaps", OperandEventKind.GAP)):
            _require(getattr(meta, field) == counts[kind], "operand kind count differs from metadata: " + field)
        _require(meta.loads == count_loads and meta.references == count_references,
                 "operand load/reference counts differ from metadata")
        events.extend(process_events)

    _validate_relationships(tuple(events), entries, exits, frame_scan, issues)
    for process in sorted(set(base_meta) - processes):
        issues.append(OperandReadIssue("MISSING_SIDECAR", "original frame process has no operand observations", process))
    return CallOperandTrace(str(trace_path), str(root_path), budget, frame_budget, frame_scan,
                            entries, exits, tuple(events), tuple(files), tuple(metadata), tuple(issues))


def _validate_relationships(events, entries, exits, frame_scan, issues):
    by_entry = {entry.invocation: entry for entry in entries}
    by_exit = {exit.invocation: exit for exit in exits}
    captures = {(capture.process_id, capture.code.key): capture.code for capture in frame_scan.captures}
    original_parents = {}
    stacks = {}
    for record in sorted((*entries, *exits), key=lambda item: (item.invocation.process_id, item.anchor.index)):
        thread = record.invocation.process_id, record.invocation.thread_id
        stack = stacks.setdefault(thread, [])
        if type(record) is FrameEntry:
            original_parents[record.invocation] = stack[-1] if stack else None
            stack.append(record.invocation)
        elif stack and stack[-1] == record.invocation:
            stack.pop()
        elif record.invocation in stack:
            # A malformed/incomplete base stack must not furnish a direct-parent proof.
            del stack[stack.index(record.invocation):]
    attempts, pending = {}, {}
    consumed_attempts, consumed_entries = set(), set()
    for event in events:
        owner = event.invocation
        entry = by_entry.get(owner)
        if owner is not None:
            _require(entry is not None, "operand owner has no original frame entry")
            _require(entry.anchor.index <= event.frame_index, "operand precedes its original owner entry")
            exit = by_exit.get(owner)
            if type(event) is not OperandGap:
                _require(exit is None or event.frame_index < exit.anchor.index,
                         "operand belongs to an already completed original frame")
        if type(event) in (OperandInstruction, OperandCallAttempt):
            _require(event.site.code == entry.code, "operand site code differs from its owner frame")
            if (event.process_id, event.site.code) not in captures:
                issues.append(OperandReadIssue("MISSING_CODE", "owner code was not captured in this process", event.process_id, event.anchor, owner))
            shapes = (load.callable_shape for load in event.loads) if type(event) is OperandInstruction else (event.dispatch,)
            for shape in shapes:
                if shape.kind is not CallableKind.EXACT_FUNCTION:
                    continue
                captured = captures.get((event.process_id, shape.code))
                if captured is None:
                    issues.append(OperandReadIssue("MISSING_CODE", "callable code was not captured in this process", event.process_id, event.anchor, owner))
                elif shape.layout.flags != captured.flags or shape.layout.parameters != captured.parameters:
                    issues.append(OperandReadIssue("LAYOUT_MISMATCH", "callable layout disagrees with the captured descriptor", event.process_id, event.anchor, owner))
        if type(event) is OperandInstruction:
            # Resuming caller bytecode ends the preceding dispatch window.
            pending.pop(owner, None)
        elif type(event) is OperandCallAttempt:
            attempts[event.key] = event
            pending[owner] = event.key
        elif type(event) is OperandEntryHandshake:
            key = event.process_id, event.attempt_index
            attempt = attempts.get(key)
            _require(attempt is not None, "operand handshake has no earlier attempt")
            _require(key not in consumed_attempts and owner not in consumed_entries,
                     "operand attempt/entry handshake was reused")
            _require(pending.get(attempt.invocation) == key,
                     "operand handshake selected a stale or superseded attempt")
            _require(attempt.thread_id == event.thread_id and attempt.hook_epoch == event.hook_epoch,
                     "operand handshake crosses a thread or hook epoch")
            _require(entry.anchor.index == event.entry_index and attempt.frame_index < event.entry_index,
                     "operand handshake does not identify its original entry interval")
            _require(entry.caller_invocation == attempt.invocation and original_parents[owner] == attempt.invocation
                     and entry.ancestor_invocation == attempt.invocation and len(entry.path) == 1
                     and entry.path_complete and entry.caller == attempt.site,
                     "operand handshake does not have the original direct active caller/site")
            consumed_attempts.add(key)
            consumed_entries.add(owner)
            pending.pop(attempt.invocation)
            if attempt.dispatch.code != entry.code:
                issues.append(OperandReadIssue("CODE_MISMATCH", "dispatch code differs from the entered frame", event.process_id, event.anchor, owner))
        elif type(event) is OperandGap:
            if owner is None:
                pending = {identity: key for identity, key in pending.items() if identity.process_id != event.process_id}
            else:
                pending.pop(owner, None)
            issues.append(OperandReadIssue("HOOK_OR_OBSERVATION_GAP", event.reason, event.process_id, event.anchor, owner))


__all__ = ["CallOperandTrace", "OperandReadIssue", "read_call_operands"]
