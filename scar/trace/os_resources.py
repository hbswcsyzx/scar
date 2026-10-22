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
from pathlib import Path
import re

from scar.ir.execution.common import EvidencePoint, Unresolved
from scar.ir.execution.coordinates import ExecutionRun, HostThreadInstance, ProcessInstance
from scar.ir.execution.ids import (HandleBindingID, HostThreadInstanceID, ProcessInstanceID,
    ResourceInstanceID, RunID, TargetLifetimeEventID)
from scar.ir.execution.resources import (EndedAt, HandleBinding, ImportedAt, InstanceTarget,
    ResourceInstance, RunRealm, UnresolvedHandle)
from scar.ir.execution.validity import LifetimeEventKind, TargetLifetimeEvent
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.program.resources import ResourceKind, ResourceRole
from scar.ir.record_codec import encode


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

    def to_dict(self):
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


def _scan(directory, max_bytes, max_lines):
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
                if body.startswith("--- "):
                    row[2:5] = ["SIGNAL", None, None]; continue
                if body.startswith("+++ "):
                    row[2:5] = ["PROCESS_EXIT", None, "OFD_release_not_established"]; continue
                unfinished = _UNFINISHED.match(body)
                if unfinished:
                    if pending is not None:
                        pending[3][4] = "unfinished_replaced_without_resume"
                    pending = (unfinished[1], unfinished[2], line_number, row)
                    # A signal handler may run before the resumed receipt.
                    # Replaying that receipt against a later FD table could
                    # connect it to a reopened descriptor's different OFD.
                    barrier("unfinished_call_requires_entry_table_snapshot", unfinished[1])
                    row[2:5] = ["UNFINISHED", unfinished[1], None]; continue
                resumed = _RESUMED.match(body)
                first_line = line_number
                if resumed:
                    row[2:5] = ["RESUMED", resumed[1], None]
                    if pending is None or pending[0] != resumed[1]:
                        row[4] = "resume_without_matching_unfinished"
                        barrier(row[4], resumed[1]); continue
                    body, first_line = pending[0] + "(" + pending[1] + resumed[2], pending[2]
                    pending = None
                completed = _CALL.match(body)
                if completed is None:
                    row[4] = "unsupported_completed_rendering"; barrier(row[4]); continue
                name, arguments, result, tail = completed.groups()
                if not resumed:
                    row[2:5] = ["COMPLETED", name, None]
                if name not in _SELECTED:
                    row[4] = "outside_fd_profile"; continue
                try:
                    args = _arguments(arguments)
                    # Never retain the rendered read/write buffer or iovecs.
                    if name in _READ | _WRITE:
                        args = [args[0], None, *args[2:]]
                    elif name in ("execve", "execveat"):
                        args = []
                except (ValueError, IndexError):
                    row[4] = "unsupported_argument_rendering"
                    barrier(row[4], name, invalidates=name not in _READ | _WRITE); continue
                calls.append({"file": file_index, "tid": tid, "line": line_number,
                    "first_line": first_line, "name": name, "args": args,
                    "result": _number(result),
                    "errno": tail.strip().split()[0] if result == "-1" and tail.strip() else None})
        if pending is not None:
            pending[3][4] = "unfinished_at_capture_end"
        artifacts.append(ProviderArtifact(str(path.absolute()), digest.hexdigest(), size,
                                          "strace.syscalls.text.v1"))
    return files, artifacts, lines, calls


class _Replay:
    def __init__(self, scope, run, artifacts, files, protocol, processes):
        self.scope, self.run, self.artifacts, self.protocol = scope, run, artifacts, protocol
        self.processes = processes
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
        if name == "unshare" and result == 0:
            if args and "CLONE_FILES" in args[0]:
                state["fds"].clear(); state["safe"] = True
                self.gap("unshare_inheritance_open", call, "private table established; copied descriptor identities remain unknown")
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


def import_os_resources(directory, *, scope, run=None, root_tid=None,
                        max_bytes=512_000_000, max_lines=2_000_000):
    """Import one retained capture; scope always includes the artifact manifest hash.

    root_tid is an explicit capture declaration, never inferred from the lowest
    TID or timestamp.  Its provenance and capture completeness remain OPEN.
    protocol_bytes is the exact generated manifest payload for catalog export.
    """
    if type(scope) is not str or not scope or (root_tid is not None and (type(root_tid) is not int or root_tid <= 0)):
        raise ValueError("OS import needs a nonempty scope and optional positive root_tid")
    if any(type(value) is not int or value <= 0 for value in (max_bytes, max_lines)):
        raise ValueError("OS import budgets must be positive exact integers")
    if run is not None and type(run) is not RunID:
        raise TypeError("run must be an exact RunID or None")
    files, artifacts, lines, calls = _scan(Path(directory), max_bytes, max_lines)
    if root_tid is not None and root_tid not in {tid for _, tid in files}:
        raise ValueError("declared root_tid has no retained per-TID artifact")
    manifest = {"schema": "scar.os-resource-profile", "schema_version": 1,
        "contract": {"namespace": scope, "root_tid": root_tid, "provider": "strace -ff -ttt -T",
            "artifacts": [{"tid": tid, "artifact": encode(artifact)}
                          for (_, tid), artifact in zip(files, artifacts, strict=True)],
            "assumptions": ["retained files belong to one declared capture", "Linux syscall contract",
                "no unobserved shared FD-table actor in connected private intervals"],
            "canonical_source_connected": False, "complete_resource_model": False}}
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
    replay = _Replay(bound_scope, execution_run, artifacts, files, protocol, process_for_tid)
    for child in private_children & replay.states.keys():
        replay.states[child]["safe"] = True
    for call in calls:
        replay.apply(call)
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
    return OSResourceFragment(bound_scope, execution_run, processes, threads, tuple(replay.resources),
        tuple(replay.handles), tuple(replay.lifetimes), tuple(replay.observations),
        tuple(tuple(row) for row in lines), tuple(gaps), tuple(artifacts), protocol_artifact, payload, summary)


__all__ = ["OSResourceFragment", "import_os_resources"]
