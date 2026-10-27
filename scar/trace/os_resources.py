"""Bounded strace -ff -ttt -T observations into existing execution resources.

No target files or IO buffers are read.  Each decompressed trace line retains
an artifact/physical-line locator; IO payload renderings are not exported.
Successful open receipts introduce distinct open-file-description instances,
never path identities.  Dup shares a known OFD; close ends a known handle,
never proves the OFD's final release.  No canonical operation/value is invented.

Descriptor connections are restricted to observed private-table intervals:
successful exec/unshare(CLONE_FILES), or a captured child born without
CLONE_FILES.  Shared/unknown tables and inherited descriptors stay OPEN.
There is no global timestamp sort or guessed cross-thread linearization.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, replace
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import secrets

from scar.ir.execution.common import EvidencePoint, Unresolved
from scar.ir.execution.coordinates import ExecutionRun, HostThreadInstance, ProcessInstance
from scar.ir.execution.ids import (HandleBindingID, HostThreadInstanceID, ProcessInstanceID,
    ResourceInstanceID, RunID, TargetLifetimeEventID, WorkTicketID, WorkOutcomeID)
from scar.ir.execution.resources import (EndedAt, HandleBinding, ImportedAt, InstanceTarget,
    ResourceInstance, RunRealm, UnresolvedHandle)
from scar.ir.execution.validity import LifetimeEventKind, TargetLifetimeEvent
from scar.ir.execution.work import (DirectExecution, ExternalWorkSource, ResourceOutcome,
    WorkOutcomeKind, WorkSubmission)
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.program.resources import ResourceKind, ResourceRole
from scar.ir.record_codec import encode, loads as strict_loads
from scar.ir.v2.common import Completeness


_OPEN = frozenset(("open", "openat", "openat2", "creat"))
_READ = frozenset(("read", "readv", "pread", "pread64", "preadv", "preadv2"))
_WRITE = frozenset(("write", "writev", "pwrite", "pwrite64", "pwritev", "pwritev2"))
_CLONE = frozenset(("clone", "clone3", "fork", "vfork"))
_TABLE = frozenset(("close_range", "io_uring_setup", "io_uring_enter"))
_SELECTED = _OPEN | _READ | _WRITE | _CLONE | _TABLE | frozenset((
    "close", "dup", "dup2", "dup3", "fcntl", "fcntl64", "execve", "execveat", "unshare"))
_TIME = re.compile(r"^\d+(?:\.\d+)?\s+(.*)$")
_CALL = re.compile(r"^([a-zA-Z0-9_]+)\((.*)\)\s+=\s+(\S+)(.*)$")
_RESUMED = re.compile(r"^<\.\.\. ([a-zA-Z0-9_]+) resumed>(.*)$")
_UNFINISHED = re.compile(r"^([a-zA-Z0-9_]+)\((.*)<unfinished \.\.\.>$")
_FLAGS = re.compile(r"\bflags=([^,}]+)")

# Kernel interface categories describe the observed protocol, not application
# purpose, purity, physical data movement, or complete effects.
_METADATA = frozenset(("stat", "lstat", "fstat", "newfstatat", "statx", "statfs", "fstatfs",
    "access", "faccessat", "faccessat2", "readlink", "readlinkat", "getcwd", "getdents", "getdents64"))
_MAPPING = frozenset(("mmap", "mmap2", "munmap", "mprotect", "mremap", "brk", "madvise",
    "mbind", "get_mempolicy", "set_mempolicy"))
_WAIT = frozenset(("poll", "ppoll", "epoll_wait", "epoll_pwait", "epoll_pwait2", "wait4", "waitid", "flock"))
_NAMESPACE = frozenset(("mkdir", "mkdirat", "rmdir", "unlink", "unlinkat", "rename", "renameat",
    "renameat2", "symlink", "symlinkat", "link", "linkat", "utimensat"))
_FD_PRODUCERS = frozenset(("pipe", "pipe2", "eventfd", "eventfd2", "epoll_create", "epoll_create1"))
_EXIT = frozenset(("exit", "exit_group"))
_EXTRA = _METADATA | _MAPPING | _WAIT | _NAMESPACE | _FD_PRODUCERS | _EXIT | frozenset(("lseek", "ioctl", "epoll_ctl"))
_DURATION = re.compile(r"\s*<([0-9]+(?:\.[0-9]+)?)>\s*$")
_STAMP = re.compile(r"^([0-9]+(?:\.[0-9]+)?)\s+")
_PIPE_PAIR = re.compile(r"^\[\s*(-?(?:0x[0-9a-fA-F]+|[0-9]+))\s*,\s*(-?(?:0x[0-9a-fA-F]+|[0-9]+))\s*\]$")


def _decimal_ns(text):
    """Keep exact decimal provider precision; never float-round or infer order."""
    if type(text) is not str or re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", text) is None:
        return None
    whole, _, fraction = text.partition(".")
    if len(fraction) > 9:
        return None
    return int(whole) * 1_000_000_000 + int(fraction.ljust(9, "0") or "0")


def _interface_family(name):
    if name in _OPEN | _FD_PRODUCERS:
        return "DESCRIPTOR_PRODUCER"
    if name in _READ | _WRITE:
        return "BYTE_IO"
    if name in _METADATA:
        return "METADATA_QUERY"
    if name in _MAPPING:
        return "VIRTUAL_MEMORY_INTERFACE"
    if name in _WAIT:
        return "WAIT_OR_LOCK_INTERFACE"
    if name in _NAMESPACE:
        return "FILESYSTEM_NAMESPACE_INTERFACE"
    if name in _CLONE | _EXIT | frozenset(("execve", "execveat", "unshare")):
        return "EXECUTION_CONTEXT_INTERFACE"
    if name in _SELECTED | frozenset(("lseek", "ioctl", "epoll_ctl")):
        return "DESCRIPTOR_OR_DEVICE_INTERFACE"
    return "UNMODELED_KERNEL_INTERFACE"


def _interface_arguments(name, args):
    """Preserve ordered protocol scalars/renderings, omit all data payloads.

    Unknown interfaces retain arity only. Structured return buffers are not
    parsed as complete values; their original line remains the authority.
    """
    omitted = set()
    if name in _READ | _WRITE | frozenset(("getdents", "getdents64")):
        omitted.add(1)
    elif name == "readlink":
        omitted.add(1)
    elif name == "readlinkat":
        omitted.add(2)
    elif name == "getcwd":
        omitted.add(0)
    elif name == "execve":
        omitted.update((1, 2))
    elif name == "execveat":
        omitted.update((2, 3))
    elif name == "ioctl":
        omitted.update(range(2, len(args)))
    elif name not in _SELECTED | _EXTRA:
        omitted.update(range(len(args)))
    result = [None if index in omitted else (_number(value) if _number(value) is not None else value)
              for index, value in enumerate(args)]
    return result, sorted(index for index in omitted if index < len(args))


def _number(text):
    if type(text) is not str or re.fullmatch(r"-?(?:0x[0-9a-fA-F]+|[0-9]+)", text.strip()) is None:
        return None
    text = text.strip()
    return int(text, 16 if "x" in text.lower() else 10)


def _arguments(text):
    """Split only top-level arguments; strings/buffers remain uninterpreted."""
    result, start, depth, quoted, escaped = [], 0, 0, False, False
    for index, char in enumerate(text):
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
            if depth < 0:
                raise ValueError("unbalanced syscall argument rendering")
        elif char == "," and depth == 0:
            result.append(text[start:index].strip()); start = index + 1
    if quoted or depth:
        raise ValueError("truncated syscall argument rendering")
    result.append(text[start:].strip())
    return result


@dataclass(slots=True)
class OSResourceFragment:
    scope: str
    run: ExecutionRun
    processes: tuple
    threads: tuple
    resources: tuple
    handles: tuple
    target_lifetime_events: tuple
    observations: tuple
    line_classifications: tuple
    gaps: tuple
    artifacts: tuple
    protocol_artifact: ProviderArtifact
    protocol_bytes: bytes
    summary: dict
    interface_work: bool = False

    def to_dict(self):
        if self.interface_work:
            raise ValueError("interface_work schema2 requires publish_os_interfaces; refusing a giant JSON/work copy")
        return {"schema": "scar.os-resource-fragment", "schema_version": 1, "scope": self.scope,
            "run": encode(self.run), "processes": encode(self.processes), "threads": encode(self.threads),
            "resources": encode(self.resources), "handles": encode(self.handles),
            "target_lifetime_events": encode(self.target_lifetime_events),
            "observations": list(self.observations), "gaps": list(self.gaps),
            "artifacts": encode(self.artifacts), "protocol_artifact": encode(self.protocol_artifact),
            "protocol_document": json.loads(self.protocol_bytes),
            "line_columns": ["artifact", "line", "classification", "syscall", "reason"],
            "observation_source_encoding": "artifact is an index into artifacts; line is a one-based decompressed physical line",
            "line_classifications": list(self.line_classifications), "summary": self.summary}

    def iter_work_records(self, table):
        """Construct original typed work one at a time, without a second graph.

        Syscall return is not device quiescence or whole-effect completion.
        Source/canonical bindings and all unknown coverage remain explicit.
        """
        if not self.interface_work or table not in ("submissions", "outcomes"):
            raise ValueError("typed OS interface work requires schema2 submissions/outcomes")
        native_threads = {row.tid: row.id for row in self.threads if row.tid is not None}
        processes = {row.id.wire: row.id for row in self.processes}
        for row in self.observations:
            if row.get("interface_record") is not True:
                continue
            entry_source = row["entry_source"]
            return_source = row["source"]
            artifact = self.artifacts[entry_source["artifact"]]
            entry = EvidencePoint(self.run.id, processes.get(row["process"]),
                ProviderFactReference(artifact, "#/lines/" + str(entry_source["line"])))
            source = ProviderFactReference(self.artifacts[return_source["artifact"]],
                                          "#/lines/" + str(return_source["line"]))
            ticket = WorkTicketID(row["work_ticket"])
            unresolved = Unresolved("source operation, executor, dependency/effect/retention closure is not established", entry)
            if table == "submissions":
                thread = native_threads.get(row["tid"])
                scheduling = DirectExecution(thread if thread is not None else
                    Unresolved("native thread coordinate is not established", entry), entry.source)
                yield WorkSubmission(ticket, ExternalWorkSource(entry, entry.source), unresolved, scheduling,
                    (), Completeness.UNKNOWN, (), Completeness.UNKNOWN, (), Completeness.UNKNOWN,
                    unresolved, ProviderFactReference(self.protocol_artifact, "#/contract/interface_work"), source)
            elif row["ordinary_return"]:
                point = EvidencePoint(self.run.id, entry.process, source)
                # COMPLETED means only that this syscall returned. brk, partial
                # IO, readiness, driver work and filesystem visibility retain
                # their distinct protocol receipts, never a device completion.
                kind = WorkOutcomeKind.FAILED if row["result"] == -1 else WorkOutcomeKind.COMPLETED
                yield ResourceOutcome(WorkOutcomeID(row["work_ticket"] + ":return"), ticket, kind,
                    point, source, (), Completeness.UNKNOWN,
                    Unresolved("syscall return does not establish device/work quiescence or complete effects", point), source)


@dataclass(frozen=True, slots=True)
class OSFileObservation:
    """Read-only provider callback view; not a new IR or FD qualification.

    binding is supplied only by the existing private-table replay at entry.
    Shared/unknown tables and resumed calls never receive a guessed binding.
    """
    ordinal: int
    source: ProviderFactReference
    entry_source: ProviderFactReference
    point: EvidencePoint
    tid: int
    syscall: str
    arguments: tuple
    result: int | None
    binding: HandleBinding | None
    complete_entry: bool


def _scan(directory, max_bytes, max_lines, *, interface_work=False):
    files = []
    for path in sorted(directory.iterdir()):
        match = re.search(r"\.([0-9]+)(?:\.gz)?$", path.name)
        if path.is_file() and match:
            files.append((path, int(match[1])))
    if not files or len(files) > 4096:
        raise ValueError("strace input needs 1..4096 per-TID files ending .<tid>[.gz]")
    if len({tid for _, tid in files}) != len(files):
        raise ValueError("duplicate per-TID files cannot define one trace interval")
    artifacts, lines, calls, total_bytes = [], [], [], 0
    for file_index, (path, tid) in enumerate(files):
        digest, size, pending = hashlib.sha256(), 0, None
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rb") as stream:
            bounded_lines = iter(lambda: stream.readline(max_bytes - total_bytes + 1), b"")
            for line_number, raw in enumerate(bounded_lines, 1):
                total_bytes += len(raw); size += len(raw); digest.update(raw)
                if total_bytes > max_bytes or len(lines) >= max_lines:
                    raise ValueError("strace decompressed byte/line budget exceeded")
                row = [file_index, line_number, "UNSUPPORTED", None, "unrecognized_line_shape"]
                lines.append(row)
                def barrier(reason, name=None, *, invalidates=True):
                    calls.append({"file": file_index, "tid": tid, "line": line_number,
                        "first_line": line_number, "name": name, "args": [], "result": None,
                        "errno": None, "parser_gap": reason, "invalidates_fd_table": invalidates})
                try:
                    text = raw.decode("utf-8").rstrip("\r\n")
                except UnicodeError:
                    row[4] = "invalid_utf8"; barrier(row[4]); continue
                match = _TIME.match(text)
                if match is None:
                    barrier(row[4])
                    continue
                body = match[1]
                timestamp = _STAMP.match(text)[1] if interface_work and _STAMP.match(text) is not None else None
                if body.startswith("--- "):
                    row[2:5] = ["SIGNAL", None, None]; continue
                if body.startswith("+++ "):
                    row[2:5] = ["PROCESS_EXIT", None, "OFD_release_not_established"]; continue
                unfinished = _UNFINISHED.match(body)
                if unfinished:
                    if pending is not None:
                        pending[3][4] = "unfinished_replaced_without_resume"
                    pending = (unfinished[1], unfinished[2], line_number, row, timestamp)
                    # A signal handler may run before the resumed receipt.
                    # Replaying that receipt against a later FD table could
                    # connect it to a reopened descriptor's different OFD.
                    barrier("unfinished_call_requires_entry_table_snapshot", unfinished[1])
                    row[2:5] = ["UNFINISHED", unfinished[1], None]; continue
                resumed = _RESUMED.match(body)
                first_line = line_number
                entry_timestamp = timestamp
                if resumed:
                    row[2:5] = ["RESUMED", resumed[1], None]
                    if pending is None or pending[0] != resumed[1]:
                        row[4] = "resume_without_matching_unfinished"
                        barrier(row[4], resumed[1]); continue
                    body, first_line = pending[0] + "(" + pending[1] + resumed[2], pending[2]
                    entry_timestamp = pending[4]
                    pending = None
                completed = _CALL.match(body)
                if completed is None:
                    row[4] = "unsupported_completed_rendering"; barrier(row[4]); continue
                name, arguments, result, tail = completed.groups()
                if not resumed:
                    row[2:5] = ["COMPLETED", name, None]
                if name not in _SELECTED:
                    row[4] = "outside_fd_profile"
                    if not interface_work:
                        continue
                try:
                    args = _arguments(arguments)
                    if interface_work:
                        normalized, omitted = _interface_arguments(name, [] if args == [""] else args)
                        parsed_arguments = True
                    # Never retain the rendered read/write buffer or iovecs.
                    if name in _READ | _WRITE:
                        args = [args[0], None, *args[2:]]
                    elif name in ("execve", "execveat"):
                        args = []
                except (ValueError, IndexError):
                    if interface_work:
                        # Retain the known interface/return even if its argument
                        # rendering is incomplete; no argument identity is made.
                        args, normalized, omitted = [], [], []
                        parsed_arguments = False
                    else:
                        row[4] = "unsupported_argument_rendering"
                        barrier(row[4], name, invalidates=name not in _READ | _WRITE); continue
                call = {"file": file_index, "tid": tid, "line": line_number,
                    "first_line": first_line, "name": name, "args": args,
                    "result": _number(result),
                    "errno": tail.strip().split()[0] if result == "-1" and tail.strip() else None}
                if interface_work:
                    duration = _DURATION.search(tail)
                    errno = re.match(r"\s*([A-Z][A-Z0-9_]+)\b", tail) if result == "-1" else None
                    call["errno"] = errno[1] if errno is not None else None
                    call.update(interface_record=True, legacy_outside_fd_profile=name not in _SELECTED,
                        normalized_arguments=normalized, payload_argument_indices_omitted=omitted,
                        argument_rendering_complete=parsed_arguments and "..." not in arguments,
                        result_rendering=result, provider_entry_line_timestamp=entry_timestamp,
                        provider_line_timestamp=timestamp, duration=duration[1] if duration else None,
                        post_receipt_rendering=(tail[:duration.start()].strip() if duration else tail.strip())
                            if name in ("poll", "ppoll", "epoll_wait", "epoll_pwait", "epoll_pwait2") else None)
                calls.append(call)
        if pending is not None:
            pending[3][4] = "unfinished_at_capture_end"
        artifacts.append(ProviderArtifact(str(path.absolute()), digest.hexdigest(), size,
                                          "strace.syscalls.text.v1"))
    return files, artifacts, lines, calls


class _Replay:
    def __init__(self, scope, run, artifacts, files, protocol, processes, *, interface_work=False):
        self.scope, self.run, self.artifacts, self.protocol = scope, run, artifacts, protocol
        self.processes = processes
        self.interface_work = interface_work
        self.resources, self.handles, self.lifetimes, self.observations = [], [], [], []
        self.gaps, self.gap_counts = {}, Counter()
        self.states = {tid: {"safe": False, "fds": {}, "generation": Counter()} for _, tid in files}

    def fact(self, call, first=False):
        return ProviderFactReference(self.artifacts[call["file"]],
            "#/lines/" + str(call["first_line"] if first else call["line"]))

    def point(self, call):
        return EvidencePoint(self.run.id, self.processes.get(call["tid"]), self.fact(call))

    def gap(self, code, call, detail):
        key = (code, call["tid"], call["name"])
        self.gap_counts[key] += 1
        self.gaps.setdefault(key, {"code": code, "source": encode(self.fact(call)), "detail": detail})

    def invalidate(self, state, call, reason):
        state["fds"].clear(); state["safe"] = False
        self.gap("fd_table_identity_open", call, reason)

    def binding(self, state, call, fd, target):
        state["generation"][fd] += 1
        generation = state["generation"][fd]
        point = self.point(call)
        binding = HandleBinding(HandleBindingID(self.scope + ":fd:" + str(call["tid"]) + ":" +
            str(fd) + ":" + str(generation)),
            UnresolvedHandle(None, Unresolved("numeric FD/generation has no canonical ValueOccurrence/NativeHandle port", point)),
            InstanceTarget(target), point, Unresolved("descriptor end is not observed or table identity remains open", point), (),
            Unresolved("descriptor rights/state are not established", point),
            Unresolved("OFD ownership and sharing completeness are not established", point), self.fact(call))
        index = len(self.handles); self.handles.append(binding)
        if state["safe"]:
            state["fds"][fd] = index
        return index, generation

    def end(self, index, call):
        binding = self.handles[index]
        self.handles[index] = replace(binding, end=EndedAt(self.point(call), self.fact(call)))

    def introduced_fd(self, state, call, fd, port):
        """One actual producer port, never a path identity or shared pipe OFD."""
        if fd in state["fds"]:
            self.invalidate(state, call, "FD producer reuses a believed-live descriptor; table history is incomplete")
        point, source = self.point(call), self.fact(call)
        target = ResourceInstanceID(self.scope + ":ofd:" + str(call["file"]) + ":" + str(call["line"]) + ":" + port)
        self.resources.append(ResourceInstance(target, ResourceKind.FILE, ResourceRole.OPEN_FILE_DESCRIPTION,
            RunRealm(self.run.id), ImportedAt(point), source))
        self.lifetimes.append(TargetLifetimeEvent(TargetLifetimeEventID(target.value + ":live"),
            InstanceTarget(target), LifetimeEventKind.LIVE, point,
            Unresolved("raw syscall stage is not connected to a canonical source stage", point),
            Unresolved("syscall effects are not connected to canonical state/effect ports", point), self.protocol, source))
        index, generation = self.binding(state, call, fd, target)
        return {"port": port, "fd": fd, "generation": generation,
                "binding": self.handles[index].id.wire, "target": target.wire}

    def apply(self, call):
        state, name, args, result = self.states[call["tid"]], call["name"], call["args"], call["result"]
        # Diagnostic IO rows reference the immutable artifact table.  Repeating
        # its URI/hash/schema twice per syscall inflated this real trace beyond
        # 512 MB.  Typed resource records retain full ProviderFactReferences.
        observation = {"source": {"artifact": call["file"], "line": call["line"]},
            "entry_source": {"artifact": call["file"], "line": call["first_line"]},
            "tid": call["tid"], "syscall": name, "result": result, "errno": call["errno"],
            "fd_relation_status": "OPEN", "binding": None, "ofd": None,
            "canonical_stage": "OPEN", "canonical_effect": "OPEN"}
        if self.interface_work:
            observation["interface_record"] = call.get("interface_record", False)
            if observation["interface_record"]:
                ordinary = result is not None and name not in _EXIT and not (
                    name in ("execve", "execveat") and result == 0)
                observation.update(process=self.processes[call["tid"]].wire if call["tid"] in self.processes else None,
                    family=_interface_family(name), legacy_outside_fd_profile=call["legacy_outside_fd_profile"],
                    arguments=call["normalized_arguments"],
                    payload_argument_indices_omitted=call["payload_argument_indices_omitted"],
                    argument_rendering_complete=call["argument_rendering_complete"],
                    result_rendering=call["result_rendering"], ordinary_return=ordinary,
                    return_source={"artifact": call["file"], "line": call["line"]} if ordinary else None,
                    nonreturn_protocol="EXIT_REQUEST" if name in _EXIT else (
                        "EXEC_IMAGE_REPLACED" if name in ("execve", "execveat") and result == 0 else (
                        "RETURN_RENDERING_UNRECOVERED" if not ordinary else None)),
                    provider_entry_line_timestamp=call["provider_entry_line_timestamp"],
                    provider_line_timestamp=call["provider_line_timestamp"],
                    provider_entry_line_timestamp_ns=_decimal_ns(call["provider_entry_line_timestamp"]),
                    provider_line_timestamp_ns=_decimal_ns(call["provider_line_timestamp"]),
                    provider_entry_line_point_kind="STRACE_UNFINISHED_ENTRY_PRINTLEADER" if call["first_line"] != call["line"]
                        else "STRACE_COMPLETED_LINE_PRINTLEADER_NOT_RETURN_TIME",
                    provider_line_point_kind="STRACE_RESUMED_LINE_PRINTLEADER_NOT_VERIFIED_RETURN_TIME" if call["first_line"] != call["line"]
                        else "STRACE_COMPLETED_LINE_PRINTLEADER_NOT_RETURN_TIME",
                    duration=call["duration"], duration_ns=_decimal_ns(call["duration"]),
                    post_receipt_rendering=call["post_receipt_rendering"],
                    work_ticket=self.scope + ":syscall-work:" + str(call["file"]) + ":" + str(call["first_line"]),
                    resource_association_status="OPEN_R2", effects_coverage="UNKNOWN",
                    dependency_coverage="UNKNOWN", retention_coverage="UNKNOWN")
        self.observations.append(observation)
        if "parser_gap" in call:
            observation.update(kind="TRACE_PARSE_FRONTIER", reason=call["parser_gap"],
                               fd_table_invalidated=call["invalidates_fd_table"])
            if call["invalidates_fd_table"]:
                self.invalidate(state, call, call["parser_gap"])
            else:
                self.gap("io_argument_parse_open", call, call["parser_gap"])
            return
        if result is None and name in _CLONE | _TABLE | frozenset(("dup2", "dup3", "execve", "execveat", "unshare")):
            self.invalidate(state, call, "unknown syscall return does not close descriptor-table mutation")
            return
        if name in ("execve", "execveat") and result == 0:
            state["fds"].clear(); state["safe"] = True
            self.gap("exec_inheritance_open", call, "exec unshares the FD table; inherited/CLOEXEC descriptor identities remain unknown")
            return
        if self.interface_work and name in ("execve", "execveat"):
            # Importer defect in schema1: PATH-search failures previously fell
            # through to an absent-FD diagnostic after argv/env were omitted.
            # Failure does not install an image or produce a handle.
            observation["fd_relation_status"] = "NOT_A_DESCRIPTOR_ARGUMENT_INTERFACE"
            return
        if name == "unshare" and result == 0:
            if args and "CLONE_FILES" in args[0]:
                state["fds"].clear(); state["safe"] = True
                self.gap("unshare_inheritance_open", call, "private table established; copied descriptor identities remain unknown")
            return
        if self.interface_work and name == "unshare":
            observation["fd_relation_status"] = "NOT_A_DESCRIPTOR_ARGUMENT_INTERFACE"
            return
        if name in _CLONE:
            if result is not None and result > 0:
                flags = _clone_flags(call)
                if flags is None or "CLONE_FILES" in flags:
                    self.invalidate(state, call, "shared/unknown CLONE_FILES table requires cross-thread causal FD-table evidence")
            return
        if name in _TABLE:
            self.invalidate(state, call, "unmodeled range/asynchronous FD-table mutation prevents later descriptor matching")
            return
        if self.interface_work and name in _FD_PRODUCERS:
            if result is None or result < 0:
                if result is None:
                    self.invalidate(state, call, "unknown FD producer return leaves its introduced descriptor ports unresolved")
                return
            if name in ("pipe", "pipe2"):
                pair = _PIPE_PAIR.fullmatch(args[0]) if args else None
                fds = [_number(pair[1]), _number(pair[2])] if pair is not None else []
                if len(fds) != 2 or any(fd is None or fd < 0 for fd in fds) or fds[0] == fds[1] or result != 0:
                    self.invalidate(state, call, "successful pipe producer lacks its exact distinct output FD pair")
                    self.gap("fd_producer_ports_open", call, "pipe output endpoints are not fully rendered")
                    return
                receipts = [self.introduced_fd(state, call, fd, port)
                            for fd, port in zip(fds, ("read_end", "write_end"), strict=True)]
            else:
                receipts = [self.introduced_fd(state, call, result,
                    "counter_endpoint" if name.startswith("eventfd") else "eventpoll_endpoint")]
            observation.update(created_handles=receipts, fd_relation_status="OBSERVED_FD_PRODUCER_PORTS",
                table_status="PRIVATE_OBSERVED_INTERVAL" if state["safe"] else "OPEN",
                endpoint_pair_relation="SAME_PIPE_RECEIPT_DISTINCT_OFD_ENDPOINTS" if name in ("pipe", "pipe2") else None,
                resource_association_status="PRODUCER_PORTS_OBSERVED_R2_TYPED_RELATION_OPEN",
                generation_basis="observed_bound_assignments_not_complete_kernel_history")
            return
        if self.interface_work and name not in _SELECTED:
            # Inputs/outputs and actual work are retained, but mapping, poll,
            # metadata and shared-context relations are not fabricated here.
            if name not in _EXTRA:
                self.invalidate(state, call, "unmodeled kernel interface may mutate descriptor state")
                self.gap("kernel_interface_contract_open", call, "arguments and side effects have no supported protocol")
            return
        if name in _OPEN:
            if result is None or result < 0:
                return
            path_index = 1 if name in ("openat", "openat2") else 0
            observation.update(path_rendering=args[path_index] if len(args) > path_index else None,
                dirfd_rendering=args[0] if path_index and args else None,
                flags_rendering=args[path_index + 1] if len(args) > path_index + 1 else None,
                file_entity_identity_established=False)
            if result in state["fds"]:
                self.invalidate(state, call, "successful open reuses a believed-live FD; trace/table history is incomplete")
            point, source = self.point(call), self.fact(call)
            target = ResourceInstanceID(self.scope + ":ofd:" + str(call["file"]) + ":" + str(call["line"]))
            self.resources.append(ResourceInstance(target, ResourceKind.FILE, ResourceRole.OPEN_FILE_DESCRIPTION,
                RunRealm(self.run.id), ImportedAt(point), source))
            self.lifetimes.append(TargetLifetimeEvent(TargetLifetimeEventID(target.value + ":live"),
                InstanceTarget(target), LifetimeEventKind.LIVE, point,
                Unresolved("raw syscall stage is not connected to a canonical source stage", point),
                Unresolved("syscall effects are not connected to canonical state/effect ports", point), self.protocol, source))
            index, generation = self.binding(state, call, result, target)
            observation.update(fd=result, generation=generation, binding=self.handles[index].id.wire,
                ofd=target.wire, fd_relation_status="OBSERVED_OPEN_RECEIPT",
                table_status="PRIVATE_OBSERVED_INTERVAL" if state["safe"] else "OPEN",
                generation_basis="observed_bound_assignments_not_complete_kernel_history")
            return
        if not args:
            self.gap("fd_argument_open", call, "required descriptor argument is absent")
            return
        fd = _number(args[0]); observation["fd"] = fd
        resumed_io = name in _READ | _WRITE and call["first_line"] != call["line"]
        index = state["fds"].get(fd) if state["safe"] and not resumed_io else None
        if resumed_io:
            self.gap("io_entry_binding_open", call,
                     "resumed IO needs its entry FD-table snapshot; completion-time bindings cannot substitute")
        if index is not None:
            binding = self.handles[index]
            observation.update(binding=binding.id.wire, ofd=binding.target.instance.wire,
                               fd_relation_status="CONNECTED_PRIVATE_INTERVAL")
        elif name not in ("fcntl", "fcntl64"):
            self.gap("fd_binding_open", call, "descriptor has unknown inheritance, producer, or shared-table history")
        if name == "close":
            state["fds"].pop(fd, None)
            if result == 0 and index is not None:
                self.end(index, call)
            elif result != 0:
                self.gap("failed_close_lifetime_open", call, "failed/interrupted close does not justify retaining or retiring the old binding")
        elif name in ("dup", "dup2", "dup3") or name in ("fcntl", "fcntl64") and len(args) > 1 and args[1] in ("F_DUPFD", "F_DUPFD_CLOEXEC"):
            if result is None or result < 0:
                return
            if name in ("dup2", "dup3") and (len(args) < 2 or _number(args[1]) != result):
                self.invalidate(state, call, "dup replacement result does not match its exact destination argument")
                observation.update(fd_relation_status="OPEN", binding=None, ofd=None)
                return
            if name == "dup2" and result == fd:
                return  # dup2(fd, fd) neither replaces nor creates a handle.
            previous = state["fds"].pop(result, None)
            if previous is not None:
                if name in ("dup2", "dup3"):
                    self.end(previous, call)
                else:
                    self.invalidate(state, call, "dup returned a believed-live FD without replacement semantics")
                    index = None
            if index is not None:
                target = self.handles[index].target.instance
                new_index, generation = self.binding(state, call, result, target)
                observation.update(new_fd=result, generation=generation,
                    new_binding=self.handles[new_index].id.wire, shared_ofd=target.wire,
                    generation_basis="observed_bound_assignments_not_complete_kernel_history")
            else:
                self.gap("dup_source_open", call, "dup target is observed but original OFD identity is unresolved")
        elif name in _READ | _WRITE:
            observation.update(direction="READ" if name in _READ else "WRITE",
                transferred_bytes=result if result is not None and result >= 0 else None,
                requested_count=_number(args[2]) if len(args) > 2 else None,
                requested_unit="iovecs" if "v" in name else "bytes",
                offset_mode="EXPLICIT" if name.startswith(("pread", "pwrite")) else "SHARED_OFD_POSITION",
                offset=_number(args[3]) if len(args) > 3 and name.startswith(("pread", "pwrite")) else None)


def _clone_flags(call):
    if call["name"] in ("fork", "vfork"):
        return ""
    match = _FLAGS.search(", ".join(call["args"]))
    if match is None or "..." in match[1] or "0x" in match[1] or _number(match[1]) is not None:
        return None
    return match[1].strip()


def import_os_resources(directory, *, scope, run=None, root_tid=None, coordinates=None,
                        max_bytes=512_000_000, max_lines=2_000_000, interface_work=False, file_observer=None):
    """Import one retained capture; scope always includes the artifact manifest hash.

    root_tid is an explicit capture declaration, never inferred from the lowest
    TID or timestamp.  Its provenance and capture completeness remain OPEN.
    protocol_bytes is the exact generated manifest payload for catalog export.
    interface_work=True explicitly enables schema2 interface/work coverage and
    bounded export. The default legacy schema1 and to_dict path is unchanged.
    """
    if type(scope) is not str or not scope or (root_tid is not None and (type(root_tid) is not int or root_tid <= 0)):
        raise ValueError("OS import needs a nonempty scope and optional positive root_tid")
    if any(type(value) is not int or value <= 0 for value in (max_bytes, max_lines)):
        raise ValueError("OS import budgets must be positive exact integers")
    if type(interface_work) is not bool:
        raise TypeError("interface_work must be an exact bool")
    if file_observer is not None and (not callable(file_observer) or not interface_work):
        raise TypeError("file_observer requires interface_work and a callable")
    if run is not None and type(run) is not RunID:
        raise TypeError("run must be an exact RunID or None")
    if coordinates is not None:
        from scar.trace.capture_coordinates import CaptureCoordinates
        if type(coordinates) is not CaptureCoordinates:
            raise TypeError("OS coordinates must be a bound CaptureCoordinates")
        if run is not None and run != coordinates.run.id:
            raise ValueError("OS run declaration contradicts bound capture coordinates")
    files, artifacts, lines, calls = _scan(Path(directory), max_bytes, max_lines, interface_work=interface_work)
    if root_tid is not None and root_tid not in {tid for _, tid in files}:
        raise ValueError("declared root_tid has no retained per-TID artifact")
    manifest = {"schema": "scar.os-resource-profile", "schema_version": 1,
        "contract": {"namespace": scope, "root_tid": root_tid, "provider": "strace -ff -ttt -T",
            "artifacts": [{"tid": tid, "artifact": encode(artifact)}
                          for (_, tid), artifact in zip(files, artifacts, strict=True)],
            "assumptions": ["retained files belong to one declared capture", "Linux syscall contract",
                "no unobserved shared FD-table actor in connected private intervals"],
            "canonical_source_connected": False, "complete_resource_model": False}}
    if interface_work:
        manifest["schema_version"] = 2
        interface_counts = Counter(call["name"] for call in calls if call.get("interface_record"))
        manifest["contract"]["interface_work"] = {
            "mode": "OBSERVED_KERNEL_INTERFACES_R1", "fragment_schema_version": 2,
            "interfaces": [{"name": name, "count": count, "family": _interface_family(name),
                "legacy_fd_profile": name in _SELECTED} for name, count in sorted(interface_counts.items())],
            "parameter_encoding": "ordered exact numeric scalars or strace renderings; payload positions are null and explicitly listed",
            "argument_truncation": "argument_rendering_complete describes only formatting/ellipsis; structured stat outputs remain provider renderings, not complete out values",
            "timestamps": "provider_line_timestamp and provider_entry_line_timestamp are strace -ttt realtime printleader stamps, never independently observed host return times; see each point_kind",
            "duration": "strace -T reported decimal elapsed duration; no inferred end timestamp or cross-thread order",
            "outcome_scope": "ordinary syscall return only; not full effects, GPU ready or device quiescence",
            "successful_exec_and_exit_have_ordinary_return": False,
            "work_dependencies_effects_materializations_retention": "UNKNOWN, never NONE",
            "quiescence_records_created": 0, "r2_resource_associations_established": False,
            "importer_defect_fixed": "failed execve/execveat PATH search no longer produces a missing-FD-argument gap",
            "linux_contracts": ["https://man7.org/linux/man-pages/man2/pipe.2.html",
                "https://man7.org/linux/man-pages/man2/eventfd.2.html",
                "https://man7.org/linux/man-pages/man2/epoll_create.2.html",
                "https://man7.org/linux/man-pages/man2/execve.2.html"]}
    if coordinates is not None:
        manifest["contract"]["coordinate_binding"] = encode(coordinates.artifact)
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    bound_scope = scope + ":os:" + digest
    protocol_artifact = ProviderArtifact("memory:os-resource-profile:" + digest, digest, len(payload), manifest["schema"])
    protocol = ProviderFactReference(protocol_artifact, "#/contract")
    execution_run = ExecutionRun(run or RunID(bound_scope + ":run"), protocol)
    pid_by_tid, birth_by_tid, private_children = {}, {}, set()
    if root_tid is not None:
        pid_by_tid[root_tid] = root_tid
    clone_calls = [call for call in calls if call["name"] in _CLONE and call["result"] is not None and call["result"] > 0]
    children = Counter(call["result"] for call in clone_calls)
    for _ in range(len(files) + 1):
        changed = False
        for call in clone_calls:
            child, flags = call["result"], _clone_flags(call)
            if children[child] != 1 or flags is None:
                continue
            birth_by_tid[child] = call
            if "CLONE_FILES" not in flags:
                private_children.add(child)
            pid = pid_by_tid.get(call["tid"]) if "CLONE_THREAD" in flags else child
            if pid is not None and child not in pid_by_tid:
                pid_by_tid[child] = pid; changed = True
        if not changed:
            break
    process_ids = {pid: ProcessInstanceID(bound_scope + ":process:" + str(pid)) for pid in set(pid_by_tid.values())}
    process_for_tid = {tid: process_ids[pid] for tid, pid in pid_by_tid.items()}
    processes = tuple(ProcessInstance(identity, execution_run.id, pid, protocol)
                      for pid, identity in sorted(process_ids.items()))
    threads = tuple(HostThreadInstance(HostThreadInstanceID(bound_scope + ":thread:" + str(tid)),
        process_for_tid[tid], tid, ProviderFactReference(artifact, "#"))
        for (_, tid), artifact in zip(files, artifacts, strict=True) if tid in process_for_tid)
    if coordinates is not None:
        # Preserve resource/handle identities.  Only the coordinates used by
        # their evidence points change, at construction time before hashing.
        execution_run = coordinates.run
        process_for_tid, bound_processes, bound_threads = {}, {}, {}
        for (_, tid), artifact in zip(files, artifacts, strict=True):
            process = coordinates.process_for(artifact, tid)
            if process is None:
                continue
            process_for_tid[tid] = process.id
            bound_processes[process.id] = process
            thread = coordinates.thread_for(artifact, tid, "linux_native_tid")
            if type(thread) is HostThreadInstance:
                bound_threads[thread.id] = thread
        processes, threads = tuple(bound_processes.values()), tuple(bound_threads.values())
    replay = _Replay(bound_scope, execution_run, artifacts, files, protocol, process_for_tid,
                     interface_work=interface_work)
    for child in private_children & replay.states.keys():
        replay.states[child]["safe"] = True
    for call in calls:
        context = None
        if file_observer is not None and call['name'] in _READ | _WRITE | frozenset(('fstat','newfstatat','statx','mmap','mmap2')):
            state = replay.states[call['tid']]
            position = 4 if call['name'] in ('mmap','mmap2') else 0
            arguments = call['args']
            fd = _number(arguments[position]) if len(arguments)>position else None
            complete = call['first_line']==call['line'] and 'parser_gap' not in call
            index = state['fds'].get(fd) if state['safe'] and complete else None
            binding = replay.handles[index] if index is not None else None
            context = OSFileObservation(len(replay.observations),replay.fact(call),replay.fact(call,True),
                replay.point(call),call['tid'],call['name'],tuple(arguments),call['result'],binding,complete)
        replay.apply(call)
        if context is not None:
            file_observer(context)
    gaps = []
    for key, gap in replay.gaps.items():
        gaps.append(gap | {"occurrences": replay.gap_counts[key]})
    gaps.append({"code": "canonical_os_bridge_open", "source": encode(protocol), "occurrences": 1,
        "detail": "source stages, effects, native handle values, inheritance, file identity and hardware closure remain unproved"})
    counts = Counter(row[2] for row in lines)
    reasons = Counter(row[4] for row in lines if row[4] is not None)
    summary = {"physical_lines": len(lines), "tid_artifacts": len(artifacts), "classification_counts": dict(counts),
        "unconnected_line_reasons": dict(reasons), "syscall_observations": len(replay.observations),
        "open_file_descriptions": len(replay.resources), "handle_generations": len(replay.handles),
        "observed_handle_ends": sum(type(row.end) is EndedAt for row in replay.handles),
        "connected_io": sum(row["syscall"] in _READ | _WRITE and row["fd_relation_status"] == "CONNECTED_PRIVATE_INTERVAL"
                            for row in replay.observations),
        "source_runtime_verified": False, "transformation_authorized": False, "complete_resource_model": False}
    if interface_work:
        observed = [row for row in replay.observations if row.get("interface_record")]
        outside = Counter(row["syscall"] for row in observed if row["legacy_outside_fd_profile"])
        summary.update(interface_mode="OBSERVED_KERNEL_INTERFACES_R1", interface_records=len(observed),
            interface_counts=dict(sorted(Counter(row["syscall"] for row in observed).items())),
            interface_families=dict(sorted(Counter(row["family"] for row in observed).items())),
            legacy_syscall_observations=len(replay.observations) - sum(outside.values()),
            legacy_outside_fd_profile_count=sum(outside.values()), legacy_outside_fd_profile_by_syscall=dict(sorted(outside.items())),
            ordinary_return_outcomes=sum(row["ordinary_return"] for row in observed),
            nonreturn_protocol_counts=dict(sorted(Counter(row["nonreturn_protocol"] for row in observed
                if row["nonreturn_protocol"] is not None).items())),
            argument_frontiers=sum(not row["argument_rendering_complete"] for row in observed),
            missing_duration=sum(row["duration_ns"] is None for row in observed),
            process_coordinate_open=sum(row["process"] is None for row in observed),
            legacy_process_coordinate_open=sum(row["process"] is None and not row["legacy_outside_fd_profile"]
                                               for row in observed),
            actual_fd_producer_ports=sum(len(row.get("created_handles", ())) for row in observed),
            gap_groups=len(gaps), gap_occurrences=sum(row["occurrences"] for row in gaps),
            quiescence_records=0, canonical_dependencies_established=False,
            syscall_work_dependencies_coverage="UNKNOWN", complete_work_effects_established=False)
    return OSResourceFragment(bound_scope, execution_run, processes, threads, tuple(replay.resources),
        tuple(replay.handles), tuple(replay.lifetimes), tuple(replay.observations),
        tuple(tuple(row) for row in lines), tuple(gaps), tuple(artifacts), protocol_artifact, payload, summary,
        interface_work=interface_work)


_INTERFACE_TABLES = ("observations", "line_classifications", "resources", "handles",
    "target_lifetime_events", "processes", "threads", "artifacts", "gaps", "submissions", "outcomes")


def publish_os_interfaces(fragment, fresh_out, *, budgets=None, progress=None):
    """Export schema2 records through the existing bounded bundle chunk sink.

    This is immutable transport of the original resource fragment plus its
    lazy typed syscall work, not a new resource IR. No giant to_dict, complete
    graph copy, or quiescence record is created. Inputs must remain stable.
    """
    from scar.store.bundle_partitions import _Chunk, _budgets, _line, _require
    from dataclasses import fields
    limits = _budgets(budgets)
    _require(type(fragment) is OSResourceFragment and fragment.interface_work is True,
             "OS interface partitions require the explicit schema2 fragment")
    _require(progress is None or callable(progress), "progress must be callable or None")
    out = Path(fresh_out).absolute()
    out.mkdir(mode=0o700, parents=False, exist_ok=False)
    totals = {"records": 0, "chunks": 0, "decoded_bytes": 0, "stored_bytes": 0}
    tables, active = {}, None
    try:
        for table in _INTERFACE_TABLES:
            if table in ("submissions", "outcomes"):
                expected = fragment.summary["interface_records" if table == "submissions" else "ordinary_return_outcomes"]
                records = (encode(record) for record in fragment.iter_work_records(table))
            else:
                collection = getattr(fragment, table)
                expected = len(collection)
                records = (encode(record) for record in collection)
            ordinal, chunks = 0, []
            if progress is not None:
                progress({"phase": "TABLE_BEGIN", "table": table, "expected": expected, **totals})
            for record in records:
                _require(totals["records"] < limits.max_records, "OS interface record budget exceeded")
                data = _line({"ordinal": ordinal, "record": record}, limits)
                _require(totals["decoded_bytes"] + len(data) <= limits.max_total_decoded_bytes,
                         "OS interface decoded budget exceeded")
                if active is not None and active.decoded_bytes + len(data) > limits.max_chunk_decoded_bytes:
                    chunks.append(active.close()); active = None
                    if progress is not None:
                        progress({"phase": "CHUNK_CLOSED", "table": table, "table_records": ordinal, **totals})
                if active is None:
                    active = _Chunk(out, "os", table, len(chunks), ordinal, totals, limits)
                active.write(data)
                ordinal += 1
            if active is not None:
                chunks.append(active.close()); active = None
            _require(ordinal == expected, "OS interface original table/work denominator differs")
            tables[table] = {"records": ordinal, "chunks": chunks}
            if progress is not None:
                progress({"phase": "TABLE_COMPLETE", "table": table, "table_records": ordinal, **totals})
        document = {"schema": "scar.partitioned-os-resource-fragment", "schema_version": 1,
            "status": "PUBLISHED", "fragment": {"schema": "scar.os-resource-fragment", "schema_version": 2},
            "scope": fragment.scope, "run": encode(fragment.run), "tables": tables,
            "protocol_artifact": encode(fragment.protocol_artifact),
            "protocol_document": json.loads(fragment.protocol_bytes), "summary": fragment.summary,
            "totals": totals, "limits": {field.name: getattr(limits, field.name) for field in fields(limits)},
            "line_columns": ["artifact", "line", "classification", "syscall", "reason"],
            "observation_source_encoding": "artifact table index + one-based decompressed physical line",
            "work_id_encoding": "observation.work_ticket is WorkTicketID.value, not wire or a canonical operation ID",
            "validation": {"typed_constructor_validation_performed": True,
                "full_execution_model_cross_reference_validation_performed": False,
                "reader_semantic_revalidation_performed": False,
                "quiescence_records_created": 0,
                "stability_assumption": "original fragment remains stable through export"},
            "whole_model_established": False, "first_stage_complete": False,
            "transformation_authorized": False}
        manifest_limits = replace(limits, max_record_bytes=limits.max_manifest_bytes,
                                  max_chunk_decoded_bytes=max(limits.max_chunk_decoded_bytes, limits.max_manifest_bytes))
        payload = _line(document, manifest_limits)
        _require(len(payload) <= limits.max_manifest_bytes, "OS interface manifest byte budget exceeded")
        temporary = out / (".manifest." + secrets.token_hex(16) + ".tmp")
        with temporary.open("xb") as stream:
            stream.write(payload); stream.flush(); os.fsync(stream.fileno())
        os.link(temporary, out / "manifest.json")
        try:
            temporary.unlink()
        except OSError:
            pass
        return {**document, "manifest_receipt": {"path": str(out / "manifest.json"),
            "physical_sha256": hashlib.sha256(payload).hexdigest(), "physical_bytes": len(payload)}}
    finally:
        if active is not None and not active.closed:
            active.close()


class OSInterfacePartitions:
    """Read only PUBLISHED schema2 transport, checking full chunks before yield.

    Byte/ordinal verification does not validate Linux effects, canonical links,
    or all cross-record references. Callers can decode selected typed records
    through the existing public record_codec independently.
    """
    def __init__(self, manifest, *, budgets=None):
        from scar.store.bundle_partitions import _budgets, _require
        self.limits = _budgets(budgets)
        path = Path(manifest).absolute()
        if path.is_dir():
            path = path / "manifest.json"
        _require(path.is_file() and not path.is_symlink(), "OS interface manifest is not published/regular")
        with path.open("rb") as stream:
            payload = stream.read(self.limits.max_manifest_bytes + 1)
        _require(len(payload) <= self.limits.max_manifest_bytes, "OS interface manifest read budget exceeded")
        self.root, self.manifest = path.parent, strict_loads(payload.decode("utf-8"))
        self.manifest_receipt = {"path": str(path), "physical_sha256": hashlib.sha256(payload).hexdigest(),
                                 "physical_bytes": len(payload)}
        m = self.manifest
        _require(type(m) is dict and m.get("schema") == "scar.partitioned-os-resource-fragment"
                 and type(m.get("schema_version")) is int and m["schema_version"] == 1
                 and m.get("status") == "PUBLISHED"
                 and m.get("fragment") == {"schema": "scar.os-resource-fragment", "schema_version": 2},
                 "unsupported/unpublished OS interface storage/fragment version")
        _require(type(m.get("tables")) is dict and set(m["tables"]) == set(_INTERFACE_TABLES)
                 and m.get("whole_model_established") is False and m.get("first_stage_complete") is False
                 and m.get("transformation_authorized") is False,
                 "OS interface tables/authority differ from the explicit transport contract")
        totals = {"records": 0, "chunks": 0, "decoded_bytes": 0, "stored_bytes": 0}
        for table in _INTERFACE_TABLES:
            descriptor, ordinal = m["tables"][table], 0
            _require(type(descriptor) is dict and type(descriptor.get("chunks")) is list,
                     "OS interface table descriptor is invalid")
            for number, chunk in enumerate(descriptor["chunks"]):
                _require(chunk.get("uri") == f"os/{table}/{number:06d}.jsonl.gz"
                         and chunk.get("compression") == "gzip", "OS interface chunk path/compression differs")
                for field in ("lines", "decoded_bytes", "physical_bytes"):
                    _require(type(chunk.get(field)) is int and chunk[field] > 0, "OS chunk counters must be positive")
                _require(type(chunk.get("first_ordinal")) is int and chunk["first_ordinal"] == ordinal
                         and type(chunk.get("last_ordinal")) is int
                         and chunk["last_ordinal"] == ordinal + chunk["lines"] - 1,
                         "OS interface chunk ordinals are not contiguous")
                for field in ("physical_sha256", "decoded_sha256"):
                    _require(type(chunk.get(field)) is str and re.fullmatch(r"[0-9a-f]{64}", chunk[field]) is not None,
                             "OS interface chunk SHA is invalid")
                _require(chunk["physical_bytes"] <= self.limits.max_chunk_stored_bytes
                         and chunk["decoded_bytes"] <= self.limits.max_chunk_decoded_bytes,
                         "OS interface chunk exceeds its independent budget")
                ordinal += chunk["lines"]; totals["chunks"] += 1
                totals["decoded_bytes"] += chunk["decoded_bytes"]; totals["stored_bytes"] += chunk["physical_bytes"]
            _require(type(descriptor.get("records")) is int and descriptor["records"] == ordinal,
                     "OS interface table count differs from its chunk ranges")
            totals["records"] += ordinal
        _require(m.get("totals") == totals and all(type(value) is int for value in m["totals"].values()),
                 "OS interface totals differ from original chunk declarations")
        _require(totals["records"] <= self.limits.max_records and totals["chunks"] <= self.limits.max_chunks
                 and totals["decoded_bytes"] <= self.limits.max_total_decoded_bytes
                 and totals["stored_bytes"] <= self.limits.max_total_stored_bytes,
                 "OS interface aggregate read budget exceeded")
        protocol = (json.dumps(m["protocol_document"], sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False)).encode("utf-8")
        _require(hashlib.sha256(protocol).hexdigest() == m["protocol_artifact"]["sha256"]
                 and len(protocol) == m["protocol_artifact"]["size_bytes"], "OS protocol receipt differs")
        for table, count in (("observations", m["summary"]["syscall_observations"]),
                             ("line_classifications", m["summary"]["physical_lines"]),
                             ("submissions", m["summary"]["interface_records"]),
                             ("outcomes", m["summary"]["ordinary_return_outcomes"])):
            _require(m["tables"][table]["records"] == count, "OS work/line source denominator differs")

    def iter_records(self, table):
        import io
        from scar.store.bundle_partitions import BundlePartitions, _require
        _require(table in _INTERFACE_TABLES, "unknown explicit OS interface table")
        for chunk in self.manifest["tables"][table]["chunks"]:
            # Reuse the existing stored+decoded SHA/size/line and safe-path
            # reader. It verifies the entire bounded chunk before first yield.
            decoded = BundlePartitions._chunk(self, chunk)
            stream = io.BytesIO(decoded)
            for index in range(chunk["lines"]):
                raw = stream.readline(self.limits.max_record_bytes + 1)
                _require(len(raw) <= self.limits.max_record_bytes and raw.endswith(b"\n"), "OS record byte bound exceeded")
                row = strict_loads(raw.decode("utf-8"))
                ordinal = chunk["first_ordinal"] + index
                _require(type(row) is dict and set(row) == {"ordinal", "record"}
                         and type(row["ordinal"]) is int and row["ordinal"] == ordinal,
                         "OS record envelope/ordinal differs")
                yield {**row, "locator": {"artifact": dict(chunk), "line": index + 1,
                    "pointer_within_line": "/record", "manifest_receipt": dict(self.manifest_receipt)},
                    "verification": {"whole_chunk_stored_sha_verified": True,
                        "whole_chunk_decoded_sha_verified": True, "current_row_ordinal_verified": True,
                        "record_semantics_revalidated": False, "whole_model_revalidated": False}}
            _require(stream.read(1) == b"", "unexpected bytes after OS chunk records")


__all__ = ["OSResourceFragment", "import_os_resources", "publish_os_interfaces", "OSInterfacePartitions"]
