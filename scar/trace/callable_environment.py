"""Bounded identity observations of exact Python function environments.

Readonly function ownership can witness identity of non-weakrefable namespaces
and cells while a weakly tracked owner remains live.  Addresses are lookup keys,
never continuity evidence.  Mutable defaults use event-local tokens.  No cell or
container contents, tensor values, logical versions or effect closure is read.
CALL-time fields are not an atomic snapshot or proof of defaults used at entry.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import sys
import threading
import types
import weakref

from scar.ir.program.environments import EnvironmentRole
from scar.trace.code_snapshot import code_key as captured_code_key


_MAX_LINE_BYTES = 2_000_000
_MAX_METADATA_BYTES = 64_000
_MAX_ANCHORS_PER_OBJECT = 4
_PREFIX = (
    EnvironmentRole.FUNCTION_OBJECT, EnvironmentRole.GLOBALS_NAMESPACE,
    EnvironmentRole.BUILTINS_NAMESPACE, EnvironmentRole.DEFAULTS,
    EnvironmentRole.KEYWORD_DEFAULTS,
)
_AUTHORITY = {
    "reference_contents_observed": False,
    "cell_contents_observed": False,
    "logical_versions_established": False,
    "callable_environment_established": False,
    "defaults_binding_established": False,
    "atomic_snapshot_established": False,
    "effects_established": False,
    "transformation_authorized": False,
}


@dataclass(slots=True)
class _AnchorRecord:
    token: str
    anchors: list


def _positive(value, name):
    if type(value) is not int or value < 1:
        raise ValueError(name + " must be a positive exact integer")
    return value


class CallableEnvironmentObserver:
    """Independent sidecar attached by an existing exact-function CALL hook."""

    def __init__(self, out, pid, *, max_events, max_bytes, max_references):
        _positive(pid, "pid")
        for name, value in (("max_events", max_events), ("max_bytes", max_bytes),
                            ("max_references", max_references)):
            _positive(value, name)
        if pid != os.getpid():
            raise ValueError("environment observer must belong to the current process")
        if platform.python_implementation() != "CPython":
            raise RuntimeError("readonly function-owner identity requires CPython")
        self.out = Path(out).resolve()
        self.out.mkdir(parents=True, exist_ok=True)
        self.pid = pid
        self.limits = {"max_events": max_events, "max_bytes": max_bytes,
                       "max_references": max_references}
        self.event_path = self.out / f"function-environments.{pid}.jsonl"
        self.metadata_path = self.out / f"function-environment-meta.{pid}.json"
        if self.metadata_path.exists() or self.metadata_path.is_symlink():
            raise ValueError("environment metadata output must be fresh")
        self._fd = os.open(self.event_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        self._deferred = None
        from scar.trace.deferred_jsonl import DeferredJsonl, snapshot_transport_enabled
        if snapshot_transport_enabled():
            self._deferred = DeferredJsonl(self.event_path, max_bytes=max_bytes)
        self._buffer = bytearray()
        self._buffer_limit = 65536
        self._lock = threading.RLock()
        self._observer_ref = weakref.ref(self)
        self._index = self._attempts = self._events = self._bytes = self._references = 0
        self._dispatch_count = self._entry_count = self._gap_count = self._dropped = 0
        self._discarded = 0
        self._epoch = self._anchor_serial = self._anchor_count = 0
        self._anchor_peak = self._registry_peak = self._pending_peak = 0
        self._records = {}
        self._dispatches = {}
        self._errors = []
        self._digest = hashlib.sha256()
        self._io_failed = self._stopped = self._closed = False
        self._stop_reason = None
        if hasattr(os, 'register_at_fork'):
            reference = self._observer_ref
            def child_cleanup():
                observer = reference()
                if observer is not None:
                    observer._after_fork()
            os.register_at_fork(after_in_child=child_cleanup)

    def _after_fork(self):
        # Never replay a parent's accepted-but-unflushed rows in its child.
        # Do not take an inherited lock, which another parent thread may own.
        if os.getpid() == self.pid:
            return
        self._buffer.clear()
        self._stopped = self._closed = True
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

    def _write_all(self, data):
        position = 0
        while position < len(data):
            written = os.write(self._fd, data[position:])
            if written <= 0:
                raise OSError('environment write made no progress')
            self._digest.update(data[position:position + written])
            self._bytes += written
            position += written

    def _flush(self):
        if self._deferred is not None:
            result = self._deferred.finalize()
            self._bytes = result['output']['raw_bytes']
            return
        if self._buffer:
            self._write_all(self._buffer)
            self._buffer.clear()

    def _live(self):
        return os.getpid() == self.pid and not self._closed and not self._stopped

    def _remember_error(self, error):
        if len(self._errors) < 16:
            try:
                name = type(error).__name__
                self._errors.append(name if type(name) is str and name else "CAPTURE_ERROR")
            except Exception:
                self._errors.append("CAPTURE_ERROR")

    def _stop(self, reason):
        self._stopped = True
        if self._stop_reason is None:
            self._stop_reason = reason

    def _emit(self, kind, fields, *, references=0):
        if not self._live():
            return None
        if self._attempts >= self.limits["max_events"]:
            self._dropped += 1
            self._stop("EVENT_BUDGET")
            return None
        self._attempts += 1
        self._index += 1
        # As in the base recorder, max_references bounds live identity state,
        # not the number of times the same identity can be observed.  Event,
        # byte and per-line limits bound the serialized observation stream.
        if references > self.limits["max_references"]:
            self._dropped += 1
            self._stop("REFERENCE_BUDGET")
            return None
        row = {"index": self._index, "kind": kind, "process_id": self.pid,
               "thread_id": threading.get_ident(), **fields}
        try:
            if self._deferred is not None:
                if not self._deferred.append(row):
                    self._dropped += 1
                    self._stop('SNAPSHOT_TRANSPORT_REJECTED')
                    return None
                self._bytes = self._deferred.accepted_bytes
            else:
                data = (json.dumps(row, ensure_ascii=True, separators=(",", ":"),
                                   allow_nan=False) + "\n").encode("ascii")
                if len(data) > _MAX_LINE_BYTES or self._bytes + len(self._buffer) + len(data) > self.limits["max_bytes"]:
                    self._dropped += 1
                    self._stop("LINE_BYTE_BUDGET" if len(data) > _MAX_LINE_BYTES else "BYTE_BUDGET")
                    return None
                if len(self._buffer) + len(data) > self._buffer_limit:
                    self._flush()
                if len(data) >= self._buffer_limit:
                    self._write_all(data)
                else:
                    self._buffer.extend(data)
        except Exception as error:
            self._io_failed = True
            self._dropped += 1
            self._remember_error(error)
            self._stop("WRITE_FAILURE")
            return None
        self._events += 1
        self._references += references
        if kind == "DISPATCH":
            self._dispatch_count += 1
        elif kind == "ENTRY":
            self._entry_count += 1
        else:
            self._gap_count += 1
        return row["index"]

    def _gap(self, reason, attempt_index=None, invocation=None, frame_index=None):
        return self._emit("GAP", {
            "attempt_index": attempt_index if type(attempt_index) is int and attempt_index > 0 else None,
            "invocation_id": invocation if type(invocation) is int and invocation > 0 else None,
            "frame_index": frame_index if type(frame_index) is int and frame_index >= 0 else None,
            "reason": reason,
        })

    @staticmethod
    def _owned(function, field, position):
        if type(function) is not types.FunctionType:
            return None
        if field == "globals":
            return function.__globals__
        if field == "builtins":
            return function.__builtins__
        if field == "cell":
            closure = function.__closure__
            if type(closure) is tuple and type(position) is int and 0 <= position < len(closure):
                return closure[position]
        return None

    def _forget_anchor(self, address, token, serial):
        # Weak callbacks capture only the observer weakref and scalar keys.
        with self._lock:
            record = self._records.get(address)
            if record is None or record.token != token:
                return
            remaining = [anchor for anchor in record.anchors if anchor[0] != serial]
            self._anchor_count -= len(record.anchors) - len(remaining)
            record.anchors[:] = remaining
            if not remaining:
                self._records.pop(address, None)

    def _anchored_reference(self, value, function, field, position=None):
        address = id(value)
        record = self._records.get(address)
        matching = False
        if record is not None:
            survivors = []
            live_owners = []
            for anchor in tuple(record.anchors):
                owner = anchor[1]()
                if owner is not None and self._owned(owner, anchor[2], anchor[3]) is value:
                    # Keep at most four owners alive inside this callback so
                    # weak callbacks cannot mutate the list being filtered.
                    live_owners.append(owner)
                    survivors.append(anchor)
                    matching = True
            self._anchor_count -= len(record.anchors) - len(survivors)
            record.anchors[:] = survivors
            if not matching:
                self._records.pop(address, None)
                record = None
        if record is None:
            if (self._anchor_count >= self.limits["max_references"]
                    or len(self._records) >= self.limits["max_references"]):
                raise ValueError("environment owner-anchor budget exceeded")
            self._epoch += 1
            record = _AnchorRecord(f"environment-anchor:{self.pid}:{self._epoch}", [])
            self._records[address] = record
        for anchor in record.anchors:
            if anchor[1]() is function and (anchor[2], anchor[3]) == (field, position):
                return record.token
        if (len(record.anchors) < _MAX_ANCHORS_PER_OBJECT
                and self._anchor_count < self.limits["max_references"]):
            self._anchor_serial += 1
            serial, token, observer_ref = self._anchor_serial, record.token, self._observer_ref
            def forgotten(_reference, observer_ref=observer_ref, address=address,
                          token=token, serial=serial):
                observer = observer_ref()
                if observer is not None:
                    try:
                        observer._forget_anchor(address, token, serial)
                    except BaseException:
                        pass
            try:
                reference = weakref.ref(function, forgotten)
            except BaseException:
                if not record.anchors:
                    self._records.pop(address, None)
                raise
            record.anchors.append((serial, reference, field, position))
            self._anchor_count += 1
            self._anchor_peak = max(self._anchor_peak, self._anchor_count)
            self._registry_peak = max(self._registry_peak, len(self._records))
        # If all four slots belong to other live owners, their checked `is`
        # already establishes continuity.  A new owner need not be retained;
        # once those anchors die, later observations receive a new token.
        if not record.anchors:
            self._records.pop(address, None)
            raise ValueError("environment owner-anchor unavailable")
        return record.token

    @staticmethod
    def _member(role, reference, basis, owner_reference=None, name=None, position=None):
        return {"role": role.value, "reference": reference, "basis": basis,
                "owner_reference": owner_reference, "cell_name": name, "cell_position": position}

    def dispatch(self, function, attempt_index, invocation, frame_index, code_key, reference_function):
        """Observe exact callable fields at CALL time; return the sidecar index."""
        try:
            with self._lock:
                if not self._live():
                    return None
                if (type(function) is not types.FunctionType or type(attempt_index) is not int
                        or attempt_index < 1 or type(invocation) is not int or invocation < 1
                        or type(frame_index) is not int or frame_index < 0):
                    return self._gap("INVALID_EXACT_FUNCTION_DISPATCH", attempt_index, invocation, frame_index)
                if type(code_key) is not str or re.fullmatch(r"pycode-v2:[0-9a-f]{64}", code_key) is None:
                    return self._gap("INVALID_DISPATCH_CODE", attempt_index, invocation, frame_index)
                code = function.__code__
                if captured_code_key(code) != code_key:
                    return self._gap("DISPATCH_CODE_CHANGED", attempt_index, invocation, frame_index)
                names, closure = code.co_freevars, function.__closure__
                if (type(names) is not tuple or any(type(name) is not str for name in names)
                        or (closure is not None and type(closure) is not tuple)
                        or len(closure or ()) != len(names)
                        or any(type(cell) is not types.CellType for cell in closure or ())):
                    return self._gap("CLOSURE_LAYOUT_MISMATCH", attempt_index, invocation, frame_index)
                # Every serialized reference field is charged, including the
                # repeated owner_reference on each namespace/cell member.
                reference_count = 7 + 2 * len(names)
                if reference_count > self.limits["max_references"]:
                    self._dropped += 1
                    self._stop("REFERENCE_BUDGET")
                    return None
                function_ref = reference_function(function)
                if (type(function_ref) is not str
                        or re.fullmatch(rf"weak:{self.pid}:[1-9][0-9]*", function_ref) is None):
                    return self._gap("FUNCTION_REFERENCE_NOT_LIFETIME_TRACKED", attempt_index, invocation, frame_index)
                globals_value, builtins_value = function.__globals__, function.__builtins__
                defaults, keyword_defaults = function.__defaults__, function.__kwdefaults__
                event_index, snapshots = self._index + 1, []
                def snapshot(value):
                    for ordinal, previous in enumerate(snapshots, 1):
                        if previous is value:
                            return f"environment-snapshot:{self.pid}:{event_index}:{ordinal}"
                    snapshots.append(value)
                    return f"environment-snapshot:{self.pid}:{event_index}:{len(snapshots)}"
                members = [self._member(_PREFIX[0], function_ref, "BASE_WEAK_REFERENCE")]
                for role, value, field in ((_PREFIX[1], globals_value, "globals"),
                                           (_PREFIX[2], builtins_value, "builtins")):
                    members.append(self._member(role,
                        self._anchored_reference(value, function, field), "LIVE_READONLY_FUNCTION_OWNER", function_ref))
                members.extend((self._member(_PREFIX[3], snapshot(defaults), "EVENT_LOCAL_SNAPSHOT"),
                                self._member(_PREFIX[4], snapshot(keyword_defaults), "EVENT_LOCAL_SNAPSHOT")))
                for position, (name, cell) in enumerate(zip(names, closure or ())):
                    members.append(self._member(EnvironmentRole.CAPTURED_CELL,
                        self._anchored_reference(cell, function, "cell", position),
                        "LIVE_READONLY_FUNCTION_OWNER", function_ref, name, position))
                if function.__code__ is not code:
                    return self._gap("DISPATCH_CODE_CHANGED", attempt_index, invocation, frame_index)
                key = threading.get_ident(), attempt_index
                if key in self._dispatches:
                    return self._gap("DUPLICATE_DISPATCH_ATTEMPT", attempt_index, invocation, frame_index)
                index = self._emit("DISPATCH", {"attempt_index": attempt_index,
                    "invocation_id": invocation, "frame_index": frame_index, "code_key": code_key,
                    "members": members, "observation_stage": "DISPATCH_FIELD_OBSERVATIONS"},
                    references=reference_count)
                if index is not None:
                    self._dispatches[key] = (weakref.ref(function), function_ref, index)
                    self._pending_peak = max(self._pending_peak, len(self._dispatches))
                return index
        except Exception as error:
            try:
                with self._lock:
                    self._remember_error(error)
                    return self._gap("DISPATCH_CAPTURE_FAILED", attempt_index, invocation, frame_index)
            except Exception:
                self._stop("CALLBACK_FAILURE")
                return None

    def discard(self, attempt_index):
        """Release an attempt for which the caller cannot supply an entry."""
        if os.getpid() != self.pid or self._closed:
            return
        with self._lock:
            if self._dispatches.pop((threading.get_ident(), attempt_index), None) is not None:
                self._discarded += 1

    def entry(self, function, attempt_index, invocation, frame_index, frame_globals, frame_builtins):
        """Check readonly associations at a supplied exact-function handshake."""
        try:
            with self._lock:
                if not self._live():
                    return None
                if (type(attempt_index) is not int or attempt_index < 1
                        or type(invocation) is not int or invocation < 1
                        or type(frame_index) is not int or frame_index < 0):
                    return self._gap("INVALID_ENTRY_HANDSHAKE", attempt_index, invocation, frame_index)
                captured = self._dispatches.pop((threading.get_ident(), attempt_index), None)
                if captured is None:
                    return self._gap("NO_RETAINED_DISPATCH", attempt_index, invocation, frame_index)
                same = type(function) is types.FunctionType and captured[0]() is function
                return self._emit("ENTRY", {"attempt_index": attempt_index,
                    "dispatch_index": captured[2], "invocation_id": invocation, "frame_index": frame_index,
                    "function_reference": captured[1], "function_match": same,
                    "globals_match": same and function.__globals__ is frame_globals,
                    "builtins_match": same and function.__builtins__ is frame_builtins,
                    "readonly_association_checks_only": True}, references=1)
        except Exception as error:
            try:
                with self._lock:
                    self._remember_error(error)
                    return self._gap("ENTRY_CAPTURE_FAILED", attempt_index, invocation, frame_index)
            except Exception:
                self._stop("CALLBACK_FAILURE")
                return None

    def close(self):
        """Close once; suppress capture errors, not process-control exceptions."""
        if os.getpid() != self.pid:
            # A child must not write a parent manifest or keep its inherited FD.
            self._after_fork()
            return
        try:
            with self._lock:
                if self._closed:
                    return
                self._closed = True
                pending = len(self._dispatches)
                if self._fd is not None:
                    try:
                        if not self._io_failed:
                            self._flush()
                    except Exception as error:
                        self._io_failed = True
                        self._remember_error(error)
                        self._stop('WRITE_FAILURE')
                    finally:
                        if self._deferred is not None:
                            try:
                                self._deferred.close_capture()
                            except Exception as error:
                                self._io_failed = True
                                self._remember_error(error)
                        self._buffer.clear()
                    try:
                        os.close(self._fd)
                    except Exception as error:
                        self._io_failed = True
                        self._remember_error(error)
                    self._fd = None
                digest = (self._digest.hexdigest() if self._deferred is None
                          else self._deferred.result['output']['sha256'] if self._deferred.result is not None else None)
                metadata = {
                    "schema": "scar.function-environment-trace", "schema_version": 1,
                    "process_id": self.pid, "python": sys.version, "implementation": "cpython",
                    "limits": dict(self.limits), "events": self._events, "event_attempts": self._attempts,
                    "dispatches": self._dispatch_count, "entries": self._entry_count, "gaps": self._gap_count,
                    "references": self._references, "bytes": self._bytes, "dropped_events": self._dropped,
                    "errors": list(self._errors), "io_failed": self._io_failed, "stop_reason": self._stop_reason,
                    "registry_peak": self._registry_peak, "anchor_peak": self._anchor_peak,
                    "anchors_per_object_limit": _MAX_ANCHORS_PER_OBJECT, "pending_peak": self._pending_peak,
                    "pending_dispatches": pending,
                    "discarded_dispatches": self._discarded,
                    "scope": "exact-function dispatch fields and supplied entry readonly-association checks only",
                    "identity_continuity": "live readonly owner checked by is; no anchors means unknown continuity",
                    "owner_contract": "Python-level readonly exact-function fields; native owner mutation is not closed",
                    "file": {"path": str(self.event_path), "raw_sha256": digest,
                             "raw_bytes": self._bytes, "lines": self._events},
                    **_AUTHORITY,
                }
                self._dispatches.clear()
                self._records.clear()
                self._anchor_count = 0
                payload = (json.dumps(metadata, ensure_ascii=True, separators=(",", ":"),
                                      allow_nan=False) + "\n").encode("ascii")
                if len(payload) > _MAX_METADATA_BYTES:
                    raise ValueError("environment metadata byte budget exceeded")
                descriptor = os.open(self.metadata_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                try:
                    position = 0
                    while position < len(payload):
                        written = os.write(descriptor, payload[position:])
                        if written <= 0:
                            raise OSError("environment metadata write made no progress")
                        position += written
                finally:
                    os.close(descriptor)
        except Exception as error:
            self._remember_error(error)
            self._stop("CLOSE_FAILURE")


__all__ = ["CallableEnvironmentObserver"]
