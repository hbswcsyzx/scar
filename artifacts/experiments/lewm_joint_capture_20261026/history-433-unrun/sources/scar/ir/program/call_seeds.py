"""Compact entered-code evidence records; decoding never replays raw/source data."""
from __future__ import annotations

from dataclasses import dataclass, fields
import os
import re

from scar.ir.program.call_edges import (
    CallEdgeBudget, CallEdgeIssue, CallEdgeIssueKind, CallLinkStatus,
    CallRecordAnchor, CallTraceFile, CapturedCode, CodeCapture, CodeSourceLink,
    InvocationKey,
)
from scar.ir.record_codec import decode, encode
from scar.ir.v2._validation import record_errors


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _integer(value, name, minimum=0):
    _require(type(value) is int and value >= minimum, name + " needs an exact integer")


def _text(value, name):
    _require(type(value) is str and bool(value), name + " needs nonempty text")


def _path(value, name):
    _text(value, name)
    _require(os.path.isabs(value) and os.path.normpath(value) == value,
             name + " needs an absolute normalized path")


def _hash(value, name, prefix=""):
    _require(type(value) is str and re.fullmatch(re.escape(prefix) + r"[0-9a-f]{64}", value) is not None,
             name + " needs a canonical SHA256")


def _record(value, expected, name):
    _require(type(value) is expected, name + " has the wrong record type")
    errors = record_errors(value, expected, name)
    if errors:
        raise ValueError("; ".join(errors))


def _anchor(value, name):
    _record(value, CallRecordAnchor, name)
    _path(value.path, name + ".path")
    _hash(value.line_sha256, name + ".line_sha256")


class _WireRecord:
    def to_dict(self):
        self.__post_init__()
        return encode(self)

    @classmethod
    def from_dict(cls, document):
        """Validate record consistency only, not capture or source truth."""
        return decode(cls, document)


@dataclass(frozen=True, slots=True)
class SeedCollectorLimits(_WireRecord):
    max_events: int
    max_bytes: int
    max_codes: int
    max_values: int
    max_path: int
    max_references: int | None = None

    def __post_init__(self):
        for member in fields(self):
            value = getattr(self, member.name)
            if member.name == "max_references" and value is None:
                continue
            _integer(value, member.name, 1)


@dataclass(frozen=True, slots=True)
class SeedCollectionMetadata(_WireRecord):
    process_id: int
    limits: SeedCollectorLimits
    events: int
    invocations: int
    codes: int
    bytes: int
    dropped_events: int
    dropped_codes: int
    unknown_exits: int
    suspended_exits: int
    open_invocations: int
    error_count: int
    event_attempts: int | None = None
    invocation_attempts: int | None = None
    active_frames: int | None = None
    path_gaps: int | None = None
    io_failed: bool | None = None

    def __post_init__(self):
        _integer(self.process_id, "process_id", 1)
        _record(self.limits, SeedCollectorLimits, "limits")
        for member in fields(self):
            if member.name in ("process_id", "limits", "io_failed"):
                continue
            value = getattr(self, member.name)
            if value is None and member.name in ("event_attempts", "invocation_attempts", "active_frames", "path_gaps"):
                continue
            _integer(value, member.name)
        _require(self.io_failed is None or type(self.io_failed) is bool, "io_failed needs an exact optional boolean")
        _require(self.open_invocations <= self.invocations, "open count exceeds entries")
        exits = self.invocations - self.open_invocations
        _require(self.events == self.invocations + exits, "event/entry/open counts disagree")
        _require(self.unknown_exits + self.suspended_exits <= exits, "completion counts exceed exits")
        attempts = self.events if self.event_attempts is None else self.event_attempts
        _require(self.events <= attempts <= self.events + self.dropped_events, "event attempts disagree with drops")
        _require(attempts <= self.limits.max_events and self.bytes <= self.limits.max_bytes
                 and self.codes <= self.limits.max_codes, "collection exceeds declared limits")
        if self.invocation_attempts is not None:
            _require(self.invocations <= self.invocation_attempts <= self.invocations + self.dropped_events,
                     "invocation attempts disagree with entries/drops")
        if self.active_frames is not None:
            _require(self.active_frames <= self.open_invocations, "active frames exceed open entries")
            if not self.dropped_events and not self.error_count:
                _require(self.active_frames == self.open_invocations, "complete active/open counts disagree")
        if self.path_gaps is not None:
            _require(self.path_gaps <= self.invocations + self.dropped_events, "path gaps exceed attempted entries")

    @classmethod
    def from_metadata(cls, raw):
        """Project checked collector metadata without retaining extension payloads.

        The scanner still validates the full raw metadata and binds its bytes
        via CallTraceFile. This projection is not a replacement raw validator.
        """
        _require(type(raw) is dict, "collector metadata needs an object")
        _require(raw.get("schema") == "scar.call-edge-trace" and type(raw.get("schema_version")) is int
                 and raw["schema_version"] == 1, "collector metadata version mismatch")
        _require(raw.get("reference_contents_observed") is False
                 and raw.get("callable_environment_established") is False, "collector cannot promote authority")
        limits = raw.get("limits")
        _require(type(limits) is dict, "collector limits need an object")
        errors = raw.get("errors")
        _require(type(errors) is list and all(type(item) is str for item in errors), "collector errors need text entries")
        try:
            selected_limits = SeedCollectorLimits(**{member.name: limits.get(member.name)
                                                     for member in fields(SeedCollectorLimits)})
            required = ("process_id", "events", "invocations", "codes", "bytes", "dropped_events",
                        "dropped_codes", "unknown_exits", "suspended_exits", "open_invocations")
            optional = ("event_attempts", "invocation_attempts", "active_frames", "path_gaps", "io_failed")
            return cls(**{name: raw[name] for name in required}, limits=selected_limits,
                       error_count=len(errors), **{name: raw.get(name) for name in optional})
        except KeyError as error:
            raise ValueError("collector metadata missing field: " + str(error)) from error


@dataclass(frozen=True, slots=True)
class EnteredCodeGroup(_WireRecord):
    process_id: int
    code: str
    count: int
    first_invocation: InvocationKey
    last_invocation: InvocationKey
    first_anchor: CallRecordAnchor
    last_anchor: CallRecordAnchor

    def __post_init__(self):
        _integer(self.process_id, "process_id", 1)
        _hash(self.code, "code", "pycode-v2:")
        _integer(self.count, "count", 1)
        for name in ("first_invocation", "last_invocation"):
            invocation = getattr(self, name)
            _record(invocation, InvocationKey, name)
            _require(invocation.process_id == self.process_id, "group invocation belongs to another process")
        for name in ("first_anchor", "last_anchor"):
            anchor = getattr(self, name)
            _anchor(anchor, name)
            _require(anchor.index is not None, "entry anchor needs an event index")
        first, last = self.first_anchor, self.last_anchor
        _require(first.path == last.path, "group endpoints need one process event file")
        if self.count == 1:
            _require(first == last and self.first_invocation == self.last_invocation, "one entry needs identical endpoints")
        else:
            _require(first.line_number < last.line_number and first.index < last.index,
                     "multiple entries need ordered distinct anchors")
            _require(self.first_invocation.invocation_id < self.last_invocation.invocation_id,
                     "multiple entries need ordered invocation IDs")
            _require(self.count <= min(last.line_number - first.line_number + 1,
                                      last.index - first.index + 1,
                                      self.last_invocation.invocation_id - self.first_invocation.invocation_id + 1),
                     "group count exceeds its endpoint interval")


def _link(link):
    _record(link, CodeSourceLink, "code link")
    _hash(link.code, "link code", "pycode-v2:")
    _require(type(link.status) is CallLinkStatus, "link status needs its enum")
    _require(type(link.optimize_levels) is tuple and all(type(level) is int and level in (0, 1, 2)
             for level in link.optimize_levels), "optimize levels must be exact supported integers")
    _require(len(set(link.optimize_levels)) == len(link.optimize_levels), "duplicate optimize level")
    _require((link.definition is None) == (link.source is None), "definition and source must be paired")
    if link.snapshot is not None:
        _path(link.snapshot.path, "snapshot path")
        _hash(link.snapshot.fingerprint, "snapshot fingerprint", "sha256:")
    if link.source is not None:
        _require(link.snapshot is not None and link.source.path == link.snapshot.path
                 and link.source.fingerprint == link.snapshot.fingerprint, "source differs from linked snapshot")


@dataclass(frozen=True, slots=True)
class CallSourceSeedModel(_WireRecord):
    trace_directory: str
    project_root: str
    budget: CallEdgeBudget
    files: tuple[CallTraceFile, ...]
    codes: tuple[CodeCapture, ...]
    groups: tuple[EnteredCodeGroup, ...]
    code_links: tuple[CodeSourceLink, ...]
    collection_metadata: tuple[SeedCollectionMetadata, ...]
    issues: tuple[CallEdgeIssue, ...]

    def __post_init__(self):
        _path(self.trace_directory, "trace directory")
        _path(self.project_root, "project root")
        _record(self.budget, CallEdgeBudget, "budget")
        for name, expected in (("files", CallTraceFile), ("codes", CodeCapture), ("groups", EnteredCodeGroup),
                               ("code_links", CodeSourceLink), ("collection_metadata", SeedCollectionMetadata),
                               ("issues", CallEdgeIssue)):
            values = getattr(self, name)
            _require(type(values) is tuple, name + " needs an exact tuple")
            for value in values:
                _record(value, expected, name)
        files, families = {}, {}
        for file in self.files:
            _path(file.path, "trace file")
            _integer(file.process_id, "file process", 1)
            _require(file.family in ("codes", "events", "meta"), "unknown trace file family")
            _hash(file.raw_sha256, "raw file hash")
            _integer(file.raw_bytes, "raw bytes"); _integer(file.lines, "raw lines")
            suffix = "json" if file.family == "meta" else "jsonl"
            _require(file.path == os.path.join(self.trace_directory, f"call-{file.family}.{file.process_id}.{suffix}"),
                     "trace file path/family/process mismatch")
            _require(file.path not in files and (file.process_id, file.family) not in families, "duplicate trace file")
            files[file.path] = file
            families[file.process_id, file.family] = file
        processes = {file.process_id for file in self.files}
        _require(processes and len(processes) <= self.budget.max_processes, "trace process coverage/budget mismatch")
        _require(all((pid, family) in families for pid in processes for family in ("codes", "events", "meta")),
                 "each process needs codes/events/meta files")
        _require(sum(file.raw_bytes for file in self.files) <= self.budget.max_raw_bytes
                 and sum(file.lines for file in self.files) <= self.budget.max_lines, "raw manifest exceeds budget")

        def owned_anchor(anchor, pid, family):
            _anchor(anchor, "record anchor")
            file = families.get((pid, family))
            _require(file is not None and anchor.path == file.path and anchor.line_number <= file.lines,
                     "anchor is outside its process/family manifest")

        captures, descriptors, capture_anchors = {}, {}, set()
        for capture in self.codes:
            _integer(capture.process_id, "capture process", 1)
            _record(capture.code, CapturedCode, "captured code")
            _hash(capture.code.key, "captured code", "pycode-v2:")
            _require(type(capture.code.parameters) is tuple, "captured parameters need a tuple")
            owned_anchor(capture.anchor, capture.process_id, "codes")
            _require(capture.anchor.index is None, "code capture cannot carry an event index")
            key = capture.process_id, capture.code.key
            _require(key not in captures and (capture.anchor.path, capture.anchor.line_number) not in capture_anchors,
                     "duplicate process/code capture or anchor")
            _require(capture.code.key not in descriptors or descriptors[capture.code.key] == capture.code,
                     "same code key has conflicting cross-process descriptors")
            captures[key] = capture
            descriptors[capture.code.key] = capture.code
            capture_anchors.add((capture.anchor.path, capture.anchor.line_number))
        _require(len(self.codes) <= self.budget.max_codes, "code captures exceed budget")
        groups, endpoints, event_endpoints, invocation_endpoints = {}, set(), set(), set()
        for group in self.groups:
            key = group.process_id, group.code
            _require(key not in groups, "duplicate process/code group")
            owned_anchor(group.first_anchor, group.process_id, "events")
            owned_anchor(group.last_anchor, group.process_id, "events")
            for anchor in {group.first_anchor, group.last_anchor}:
                endpoint = anchor.path, anchor.line_number
                _require(endpoint not in endpoints, "group endpoints share an event")
                endpoints.add(endpoint)
                event = group.process_id, anchor.index
                _require(event not in event_endpoints, "group endpoints share an event index")
                event_endpoints.add(event)
            for invocation in {group.first_invocation, group.last_invocation}:
                _require(invocation not in invocation_endpoints, "group endpoints share an invocation")
                invocation_endpoints.add(invocation)
            if key not in captures:
                _require(any(issue.kind is CallEdgeIssueKind.MISSING_CODE and issue.anchor == group.first_anchor
                             for issue in self.issues), "missing process code capture needs an anchored gap")
            groups[key] = group
        links = {}
        entered_codes = {group.code for group in self.groups}
        for link in self.code_links:
            _link(link)
            _require(link.code not in links and link.code in entered_codes,
                     "code links must be unique entered-code links")
            if link.snapshot is not None:
                _require(os.path.commonpath((self.project_root, link.snapshot.path)) == self.project_root,
                         "source snapshot lies outside project root")
                _require(link.code in descriptors and descriptors[link.code].filename == link.snapshot.path,
                         "source snapshot differs from captured code filename")
            links[link.code] = link
        metadata = {item.process_id: item for item in self.collection_metadata}
        _require(len(metadata) == len(self.collection_metadata) and set(metadata) == processes,
                 "metadata must cover each process exactly once")
        for pid, meta in metadata.items():
            owned = [group for group in self.groups if group.process_id == pid]
            _require(sum(group.count for group in owned) == meta.invocations, "group counts differ from retained entries")
            _require(sum(capture.process_id == pid for capture in self.codes) == meta.codes, "code count differs from manifest records")
            _require(sum(families[pid, family].raw_bytes for family in ("codes", "events")) == meta.bytes,
                     "collector bytes differ from raw code/events manifest")
            attempts = meta.events if meta.event_attempts is None else meta.event_attempts
            for group in owned:
                _require(group.last_anchor.index <= attempts, "group exceeds attempted event IDs")
                if meta.invocation_attempts is not None:
                    _require(group.last_invocation.invocation_id <= meta.invocation_attempts, "group exceeds invocation attempts")
        _require(sum(meta.events for meta in metadata.values()) <= self.budget.max_events, "events exceed replay budget")
        _require(len({link.snapshot.path for link in self.code_links if link.snapshot}) <= self.budget.max_source_files,
                 "linked source files exceed replay budget")
        for issue in self.issues:
            _require(type(issue.kind) is CallEdgeIssueKind, "issue kind needs its enum")
            if issue.anchor is not None:
                _anchor(issue.anchor, "issue anchor")
                _require(issue.anchor.path in files and issue.anchor.line_number <= files[issue.anchor.path].lines,
                         "issue anchor is outside the trace manifest")

    @staticmethod
    def authority_flags():
        return {name: False for name in ("caller_connections_established", "data_connections_established",
                "effects_established", "function_environment_established", "transformation_authorized")}

    def eligible_groups(self):
        """Structural eligibility only; consumers must first replay raw/source."""
        self.__post_init__()
        captured = {(capture.process_id, capture.code.key) for capture in self.codes}
        links = {link.code: link for link in self.code_links}
        return tuple(group for group in self.groups if (group.process_id, group.code) in captured
                     and (link := links.get(group.code)) is not None and link.status is CallLinkStatus.VERIFIED
                     and link.snapshot is not None and link.definition is not None and link.source is not None)

    def eligible_code_links(self):
        eligible = {group.code for group in self.eligible_groups()}
        return tuple(link for link in self.code_links if link.code in eligible)

    def summary(self):
        eligible = self.eligible_groups()
        return {"counts": {"processes": len(self.collection_metadata), "files": len(self.files),
                "code_captures": len(self.codes), "entered_code_groups": len(self.groups),
                "entered_invocations": sum(group.count for group in self.groups),
                "eligible_groups": len(eligible), "eligible_codes": len({group.code for group in eligible}),
                "issues": len(self.issues)}, **self.authority_flags()}


__all__ = ["SeedCollectorLimits", "SeedCollectionMetadata", "EnteredCodeGroup", "CallSourceSeedModel"]
