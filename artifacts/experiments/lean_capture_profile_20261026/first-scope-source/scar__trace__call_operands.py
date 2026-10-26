"""Bounded, metadata-only observations of Python operand occurrences.

The sidecar records CPython instruction/call events and references to objects
present at those events. It neither changes the base frame recorder nor
executes comparison helpers.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import platform
import sys
import threading
import types
import weakref

from scar.ir.program.call_edges import CallTraceFile
from scar.ir.program.call_operands import (
    CALL_WINDOWS_RULE, LOAD_OCCURRENCES_RULE, LEAN_PORTS_RULE, CallableKind, FunctionLayout,
    OperandCollectionLimits, OperandCollectionMetadata,
)
from scar.ir.record_codec import encode
from scar.trace.code_snapshot import describe_code, site
from scar.trace.operand_bytecode import (
    call_family_offsets, call_window_selection, load_slots,
)


_SCHEMA = "scar.call-operands-trace"
_RULE = LOAD_OCCURRENCES_RULE
_CAPTURE_INSTRUCTIONS = "instructions"
_CAPTURE_WINDOWS = "windows"
_CAPTURE_LEAN = "lean-ports"
_CAPTURE_RULES = {
    _CAPTURE_INSTRUCTIONS: LOAD_OCCURRENCES_RULE,
    _CAPTURE_WINDOWS: CALL_WINDOWS_RULE,
    _CAPTURE_LEAN: LEAN_PORTS_RULE,
}
_MONITOR_NAME = "scar-call-operands"
_LOCAL_MASK = sys.monitoring.events.INSTRUCTION | sys.monitoring.events.CALL
_MAX_EVENT_LINE_BYTES = 2_000_000
_MISSING = object()


def _positive(value, label):
    if type(value) is not int or value < 1:
        raise ValueError(label + " must be a positive exact integer")
    return value


def _inside(filename, root, prefix):
    return type(filename) is str and os.path.isabs(filename) and (filename == root or filename.startswith(prefix))


def _raw_site(code, offset):
    value = site(code, offset)
    return {"code": value["code"], "offset": value["offset"],
            "opname": value["opname"], "position": value["position"]}


def _layout(code):
    count = code.co_argcount + code.co_kwonlyargcount
    count += bool(code.co_flags & inspect.CO_VARARGS)
    count += bool(code.co_flags & inspect.CO_VARKEYWORDS)
    if count > len(code.co_varnames):
        raise ValueError("function parameter layout exceeds local slots")
    return FunctionLayout(code.co_argcount, code.co_posonlyargcount, code.co_kwonlyargcount,
                          code.co_flags, tuple(code.co_varnames[:count]))


class CallOperandObserver:
    """One per-process monitor attached to an existing CallEdgeRecorder."""

    def __init__(self, recorder, *, capture="instructions", max_events=100_000,
                 max_bytes=32_000_000, max_loads=64, max_namespace_items=4096,
                 max_references=None, python_targets=False):
        if type(capture) is not str or capture not in _CAPTURE_RULES:
            raise ValueError("operand capture must be 'instructions' or 'windows'")
        for name, value in (("max_events", max_events), ("max_bytes", max_bytes),
                            ("max_loads", max_loads), ("max_namespace_items", max_namespace_items)):
            _positive(value, name)
        base_reference_limit = recorder.limits["max_references"]
        if max_references is None:
            max_references = base_reference_limit
        _positive(max_references, "max_references")
        if max_references != base_reference_limit:
            raise ValueError("operand reference limit must match the shared frame weak-reference table")
        if type(recorder.pid) is not int or recorder.pid != os.getpid():
            raise ValueError("operand observer must be installed in the frame recorder process")
        if getattr(recorder, "operand_observer", None) is not None:
            raise ValueError("frame recorder already has an operand observer")
        monitoring = getattr(sys, "monitoring", None)
        if monitoring is None or platform.python_implementation() != "CPython" or sys.version_info < (3, 14):
            raise RuntimeError("operand capture requires CPython 3.14 sys.monitoring")

        self.recorder = recorder
        self.pid = recorder.pid
        self.root = recorder.root
        self.root_prefix = recorder.root_prefix
        self.capture = capture
        self.lean_plan = getattr(recorder, 'lean_plan', None)
        if (capture == _CAPTURE_LEAN) != (self.lean_plan is not None):
            raise ValueError('lean capture requires its explicit typed frame plan and lean-ports mode')
        if capture == _CAPTURE_LEAN and python_targets is not True:
            raise ValueError('lean capture requires explicit Python target interfaces')
        self._local_mask = sys.monitoring.events.CALL if capture == _CAPTURE_LEAN else _LOCAL_MASK
        self.rule = _CAPTURE_RULES[capture]
        self.limits = OperandCollectionLimits(max_events, max_bytes, max_loads,
                                               max_namespace_items, max_references)
        self.tool_id = None
        self.tool_name = f"{_MONITOR_NAME}-{self.pid}-{id(self):x}"
        self._lock = threading.RLock()
        self._fd = None
        self._buffer = bytearray()
        self._buffer_limit = 65536
        self._event_path = recorder.out / f"call-operands.{self.pid}.jsonl"
        self._metadata_path = recorder.out / f"call-operand-meta.{self.pid}.json"
        self._event_index = self._event_count = self._event_attempts = 0
        self._instruction_count = self._attempt_count = self._handshake_count = self._gap_count = 0
        self._loads = self._references = self._bytes = self._dropped = 0
        self._errors = []
        self._io_failed = self._stopped = self._closed = self._interfered = False
        self._monitoring_interfered = False
        self._hook_epoch = 1
        # These maps contain weak code/function references, invocation IDs,
        # and small normalized opcode plans. No frame or application value is
        # retained between callbacks.
        self._frames = {}
        self._code_states = {}
        self._plans = {}
        self._window_plans = {}
        self._planned_instruction_count = 0
        self._disabled_instruction_count = 0
        self._pending = {}
        self.environment_observer = None
        self.python_targets = None
        if type(python_targets) is not bool:
            raise TypeError("python_targets must be an explicit bool")
        self._target_event_digest = hashlib.sha256() if python_targets else None
        self._arg0_missing = getattr(sys.monitoring, "MISSING", _MISSING)
        if self._arg0_missing is _MISSING:
            raise RuntimeError("sys.monitoring.MISSING is required for exact no-argument CALL capture")

        self._acquire_tool()
        try:
            self._fd = os.open(self._event_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            from scar.trace.callable_environment import CallableEnvironmentObserver
            self.environment_observer = CallableEnvironmentObserver(
                recorder.out, self.pid, max_events=max_events, max_bytes=max_bytes,
                max_references=max_references)
            if python_targets:
                from scar.trace.python_call_targets import PythonTargetObserver, PythonTargetBudget
                self.python_targets = PythonTargetObserver(self, PythonTargetBudget(
                    max_records=max_events,max_bytes=max_bytes,max_selected_codes=recorder.limits["max_codes"]))
        except BaseException:
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None
            self._release_tool()
            raise
        recorder.operand_observer = self
        witness = getattr(recorder, 'collector_witness', None)
        if witness is not None:
            witness.register('operands', self, ('_on_instruction','_on_call','_reference'))
            witness.register('environments', self.environment_observer, ('dispatch','entry'))

    def _acquire_tool(self):
        monitoring = sys.monitoring
        for tool_id in range(6):
            if monitoring.get_tool(tool_id) is None:
                monitoring.use_tool_id(tool_id, self.tool_name)
                self.tool_id = tool_id
                break
        if self.tool_id is None:
            raise RuntimeError("no free sys.monitoring tool ID")
        try:
            monitoring.register_callback(self.tool_id, monitoring.events.INSTRUCTION, self._on_instruction)
            monitoring.register_callback(self.tool_id, monitoring.events.CALL, self._on_call)
            monitoring.set_events(self.tool_id, 0)
        except BaseException:
            self._release_tool()
            raise

    def _release_tool(self):
        if self.tool_id is None:
            return
        try:
            monitoring = sys.monitoring
            if monitoring.get_tool(self.tool_id) == self.tool_name and monitoring.get_events(self.tool_id) == 0:
                monitoring.free_tool_id(self.tool_id)
        except BaseException:
            pass
        self.tool_id = None

    def _remember_error(self, error):
        if len(self._errors) < 16:
            self._errors.append(type(error).__name__)

    @staticmethod
    def _row_reference_count(kind, fields):
        if kind == "INSTRUCTION":
            return sum(int(item["reference"] is not None) +
                       int(item["callable_shape"]["reference"] is not None) for item in fields["loads"])
        if kind == "CALL_ATTEMPT":
            return int(fields["dispatch"]["reference"] is not None) + int(fields["arg0"] is not None)
        return 0

    def _emit(self, kind, owner, frame_index, fields):
        if self._stopped or self._closed or self._io_failed:
            return None
        if self._event_attempts >= self.limits.max_events:
            self._dropped += 1
            self._stopped = True
            self._hook_epoch += 1
            return None
        self._event_attempts += 1
        self._event_index += 1
        index = self._event_index
        row = {"index": index, "kind": kind, "process_id": self.pid,
               "thread_id": threading.get_ident(), "invocation_id": owner,
               "frame_index": frame_index, "hook_epoch": self._hook_epoch, **fields}
        try:
            data = (json.dumps(row, ensure_ascii=True, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")
            if len(data) > _MAX_EVENT_LINE_BYTES:
                self._dropped += 1
                self._stopped = True
                self._hook_epoch += 1
                return None
            if self._bytes + len(data) > self.limits.max_bytes:
                self._dropped += 1
                self._stopped = True
                self._hook_epoch += 1
                return None
            if len(self._buffer) + len(data) > self._buffer_limit:
                self._flush()
            if len(data) >= self._buffer_limit:
                self._write_all(data)
            else:
                self._buffer.extend(data)
            self._bytes += len(data)
            if self._target_event_digest is not None:
                self._target_event_digest.update(data)
            self._event_count += 1
            if kind == "INSTRUCTION":
                self._instruction_count += 1
                self._loads += len(fields["loads"])
            elif kind == "CALL_ATTEMPT":
                self._attempt_count += 1
            elif kind == "ENTRY_HANDSHAKE":
                self._handshake_count += 1
            elif kind in ("GAP", "SCOPED_GAP"):
                self._gap_count += 1
            self._references += self._row_reference_count(kind, fields)
            return index
        except BaseException as error:
            self._io_failed = self._stopped = True
            self._dropped += 1
            self._remember_error(error)
            return None

    def _write_all(self, data):
        if os.getpid() != self.pid:
            raise OSError("forked process cannot flush parent operand records")
        offset = 0
        while offset < len(data):
            written = os.write(self._fd, data[offset:])
            if written <= 0:
                raise OSError("operand sidecar write made no progress")
            offset += written

    def _flush(self):
        if self._buffer:
            self._write_all(self._buffer)
            self._buffer.clear()

    def _gap(self, reason, owner=None, frame_index=None, *, advance=True):
        if frame_index is None:
            frame_index = self.recorder.index
        if self.lean_plan is not None and owner is not None:
            key = next((state[1] for state in (*self._frames.values(), *self.recorder.active.values())
                        if state[0] == owner), None)
            if key is not None:
                return self._emit("SCOPED_GAP", owner, frame_index, {"reason":reason,"code":key})
        result = self._emit("GAP", owner, frame_index, {"reason": reason})
        if advance:
            self._hook_epoch += 1
        return result

    def _scoped_gap(self, reason, code, owner=None):
        # Actual code is retained even when no invocation was successfully
        # issued. This is not a fabricated activation or a global epoch gap.
        key = describe_code(code)['key']
        return self._emit("SCOPED_GAP", owner, self.recorder.index, {"reason":reason,"code":key})

    def _base_state(self, frame):
        thread_id = threading.get_ident()
        state = self.recorder.active.get((thread_id, id(frame)))
        if state is None:
            return None
        return state[0], state[1]

    def _code_inside(self, code):
        return type(code) is types.CodeType and _inside(code.co_filename, self.root, self.root_prefix)

    def _monitor_is_intact(self, code):
        try:
            return (sys.monitoring.get_tool(self.tool_id) == self.tool_name
                    and sys.monitoring.get_events(self.tool_id) == 0
                    and sys.monitoring.get_local_events(self.tool_id, code) == self._local_mask)
        except BaseException:
            return False

    def _profile_setter(self, callback):
        setters = [sys.setprofile, sys.settrace, threading.setprofile, threading.settrace]
        if hasattr(threading, "setprofile_all_threads"):
            setters.append(threading.setprofile_all_threads)
        if hasattr(threading, "settrace_all_threads"):
            setters.append(threading.settrace_all_threads)
        if any(callback is item for item in setters):
            return "profile"
        monitoring = getattr(sys, "monitoring", None)
        if monitoring is not None:
            for name in ("set_events", "set_local_events", "register_callback",
                         "use_tool_id", "free_tool_id", "restart_events"):
                method = getattr(monitoring, name, None)
                if method is not None:
                    if callback is method:
                        return "monitoring"
        if type(callback) is types.BuiltinMethodType and monitoring is not None:
            if callback.__self__ is monitoring and callback.__name__ in {
                "set_events", "set_local_events", "register_callback", "use_tool_id",
                "free_tool_id", "restart_events",
            }:
                return "monitoring"
        return None

    def _mark_interference(self, frame, reason, *, monitoring=False):
        state = self._base_state(frame) if frame is not None else None
        self._gap(reason, None if self.lean_plan is not None else state[0] if state is not None else None)
        self._interfered = True
        self._monitoring_interfered = self._monitoring_interfered or monitoring
        self._stopped = True

    def profile(self, frame, event, arg):
        """Called by the existing profile wrapper after its frame event."""
        if self._closed:
            return
        try:
            setter_kind = self._profile_setter(arg) if event == "c_call" else None
            if event == "c_call":
                # Hook/monitoring mutation remains visible from any source,
                # including outside the selected project. Other C events have
                # no action here and do not need an owner-process syscall.
                if setter_kind is None:
                    return
            elif event == "call":
                if self.lean_plan is not None:
                    if self._base_state(frame) is None:return
                elif not (self._code_inside(frame.f_code) or (self.python_targets is not None
                        and ((self.python_targets.observed_code(frame.f_code) and self._base_state(frame) is not None)
                             or self.python_targets.accepts_frame(frame)))):
                    return
            elif event == "return":
                locked = self._lock.acquire(blocking=False)
                if locked:
                    try:
                        # The frame recorder already popped its active entry;
                        # this observer's retained frame is the right source.
                        if (threading.get_ident(), id(frame)) not in self._frames:
                            return
                    finally:
                        self._lock.release()
                elif os.getpid() != self.pid:
                    return
            else:
                return
            if os.getpid() != self.pid:
                return
            with self._lock:
                if setter_kind is not None:
                    if not self._stopped:
                        self._mark_interference(frame, "VISIBLE_HOOK_OR_MONITORING_MUTATION",
                                                monitoring=setter_kind == "monitoring")
                    return
                if self._stopped or self._io_failed:
                    return
                if event == "call":
                    self._on_frame_enter(frame)
                elif event == "return":
                    self._on_frame_exit(frame)
        except BaseException as error:
            if os.getpid() != self.pid:
                return
            if self.lean_plan is not None:
                state = self._base_state(frame)
                self._scoped_gap("OBSERVER_CALLBACK_FAILURE_" + type(error).__name__, frame.f_code,
                                 state[0] if state is not None else None)
                return
            self._remember_error(error)
            try:
                with self.recorder.lock:
                    self._gap("OBSERVER_CALLBACK_FAILURE_" + type(error).__name__)
            except BaseException:
                pass
            self._stopped = True

    def _on_frame_enter(self, frame):
        code = frame.f_code
        target_entry = self.python_targets.on_frame_enter(frame) if self.python_targets is not None else False
        if self.lean_plan is None and not (self._code_inside(code) or target_entry or (self.python_targets is not None and self.python_targets.observed_code(code))):
            return
        if self._event_attempts >= self.limits.max_events:
            self._dropped += 1
            self._stopped = True
            self._hook_epoch += 1
            return
        state = self._base_state(frame)
        if state is None:
            self._gap("FRAME_ENTRY_NOT_RETAINED")
            return
        invocation, code_key = state
        parent = frame.f_back
        parent_state = self._base_state(parent) if parent is not None else None
        if parent_state is not None:
            pending_key = (threading.get_ident(), parent_state[0])
            pending = self._pending.get(pending_key)
            if pending is not None:
                target_ref, target_code_ref, expected_code, caller_key, call_site, attempt_index = pending
                target, target_code = target_ref(), target_code_ref()
                try:
                    caller_site = site(parent.f_code, parent.f_lasti)
                except BaseException:
                    caller_site = None
                matches = (target is not None and target_code is code and target.__code__ is code
                           and expected_code == code_key and caller_key == parent_state[1]
                           and caller_site == call_site)
                if matches:
                    self._emit("ENTRY_HANDSHAKE", invocation, self.recorder.index,
                               {"attempt_index": attempt_index, "entry_index": self.recorder.index})
                    witness = getattr(self.recorder, 'collector_witness', None)
                    if witness is not None and not witness.guard('environments'):
                        self._stopped = True
                        return
                    self.environment_observer.entry(target, attempt_index, invocation,
                        self.recorder.index, frame.f_globals, frame.f_builtins)
                else:
                    self._gap("EXPECTED_FUNCTION_ENTRY_NOT_MATCHED", parent_state[0])
                    self.environment_observer.discard(attempt_index)
                self._pending.pop(pending_key, None)

        if self.lean_plan is not None:
            body = self.lean_plan.match(code)
            if body is None:
                if self.lean_plan.candidate(code) is not None:
                    self._scoped_gap("LEAN_PLANNED_CODE_VERSION_MISMATCH", code, invocation)
                return  # An interface observation never opts in the callee body.
            if body.unsupported_offsets:
                self._scoped_gap("LEAN_UNEXPANDED_STATIC_CALL_SITES:" + ','.join(map(str,body.unsupported_offsets)), code, invocation)
        if self.capture == _CAPTURE_WINDOWS:
            try:
                window_plan = self._window_plan(code, code_key)
            except BaseException as error:
                self._remember_error(error)
                self._gap("CALL_WINDOW_PLAN_FAILED_" + type(error).__name__, invocation)
                self._stopped = True
                return
            if window_plan is None:
                self._gap("CALL_WINDOW_PLAN_INSTRUCTION_BUDGET_EXCEEDED", invocation)
                self._stopped = True
                return

        identity = threading.get_ident(), id(frame)
        code_reference = weakref.ref(code)
        self._frames[identity] = (invocation, code_key, code_reference)
        record = self._code_state(code, code_reference)
        if record is None:
            self._frames.pop(identity, None)
            if self.lean_plan is not None:
                self._scoped_gap("CALL_WINDOW_CODE_OBJECT_BUDGET_EXCEEDED", code, invocation)
            else:
                self._gap("CALL_WINDOW_CODE_OBJECT_BUDGET_EXCEEDED", invocation)
                self._stopped = True
            return
        record["active"] += 1
        try:
            if sys.monitoring.get_tool(self.tool_id) != self.tool_name or sys.monitoring.get_events(self.tool_id) != 0:
                self._gap("MONITORING_TOOL_OR_GLOBAL_MASK_CHANGED", invocation)
                self._interfered = self._stopped = True
                self._monitoring_interfered = True
                return
            if self.capture == _CAPTURE_WINDOWS and record["installed"]:
                if sys.monitoring.get_local_events(self.tool_id, code) != self._local_mask:
                    self._gap("MONITORING_MASK_CHANGED_AT_CODE_REENTRY", invocation)
                    self._interfered = self._stopped = True
                    self._monitoring_interfered = True
            else:
                sys.monitoring.set_local_events(self.tool_id, code, self._local_mask)
                record["installed"] = True
        except BaseException as error:
            self._gap("MONITORINGself._local_mask_INSTALL_FAILED_" + type(error).__name__, invocation)
            self._stopped = True

    def _on_frame_exit(self, frame):
        identity = threading.get_ident(), id(frame)
        state = self._frames.pop(identity, None)
        if state is None:
            return
        invocation, _code_key, code_reference = state
        pending = self._pending.pop((threading.get_ident(), invocation), None)
        if pending is not None:
            if self.lean_plan is not None:self._scoped_gap("PROJECT_FUNCTION_CALL_DID_NOT_ENTER", frame.f_code, invocation)
            else:self._gap("PROJECT_FUNCTION_CALL_DID_NOT_ENTER", invocation)
            self.environment_observer.discard(pending[-1])
        code = code_reference()
        entry = self._code_states.get(id(code)) if code is not None else None
        if entry is None or entry["reference"]() is not code:
            return
        entry["active"] -= 1
        if self.capture == _CAPTURE_WINDOWS:
            try:
                intact = (sys.monitoring.get_tool(self.tool_id) == self.tool_name
                          and sys.monitoring.get_events(self.tool_id) == 0
                          and sys.monitoring.get_local_events(self.tool_id, code) == self._local_mask)
                if not intact:
                    self._gap("MONITORING_MASK_OR_TOOL_CHANGED_AT_FRAME_EXIT", invocation)
                    self._interfered = self._stopped = True
                    self._monitoring_interfered = True
            except BaseException as error:
                self._remember_error(error)
            return
        if entry["active"] <= 0:
            self._code_states.pop(id(code), None)
            try:
                intact = (sys.monitoring.get_tool(self.tool_id) == self.tool_name
                          and sys.monitoring.get_events(self.tool_id) == 0
                          and sys.monitoring.get_local_events(self.tool_id, code) == self._local_mask)
                if intact:
                    sys.monitoring.set_local_events(self.tool_id, code, 0)
                else:
                    self._gap("MONITORING_MASK_OR_TOOL_CHANGED_AT_FRAME_EXIT", invocation)
                    self._interfered = self._stopped = True
                    self._monitoring_interfered = True
            except BaseException as error:
                self._remember_error(error)

    def _plan(self, code, code_key):
        cached = self._plans.get(code_key)
        if cached is not None:
            return cached
        import dis
        result = {}
        for instruction in dis.get_instructions(code):
            if self._planned_instruction_count + len(result) >= self.limits.max_events:
                return None
            result[instruction.offset] = (instruction.opname, load_slots(code, instruction))
        self._planned_instruction_count += len(result)
        self._plans[code_key] = result
        return result

    def _window_plan(self, code, code_key):
        """Build one bounded static sparse-selection plan per code descriptor."""
        cached = self._window_plans.get(code_key)
        if cached is not None:
            return cached
        import dis
        remaining = self.limits.max_events - self._planned_instruction_count
        if remaining < 1:
            return None
        instructions = []
        for instruction in dis.get_instructions(code):
            if len(instructions) >= remaining:
                return None
            instructions.append(instruction)
        instructions = tuple(instructions)
        opcode_plan = {}
        for instruction in instructions:
            opcode_plan[instruction.offset] = (
                instruction.opname, load_slots(code, instruction))
        windows, expiry_offsets = call_window_selection(code, instructions)
        call_offsets = call_family_offsets(code, instructions)
        selected_offsets = frozenset(expiry_offsets | call_offsets |
                                     {offset for window in windows.values() for offset in window})
        if not selected_offsets <= opcode_plan.keys():
            raise ValueError("call-window plan references an unknown logical instruction")
        plan = {
            "opcodes": opcode_plan,
            "windows": windows,
            "call_offsets": call_offsets,
            "expiry_offsets": expiry_offsets,
            "selected_offsets": selected_offsets,
        }
        self._planned_instruction_count += len(instructions)
        self._plans[code_key] = opcode_plan
        self._window_plans[code_key] = plan
        return plan

    def _code_state(self, code, code_reference):
        key = id(code)
        state = self._code_states.get(key)
        if state is not None and state["reference"]() is code:
            return state
        if state is not None:
            self._code_states.pop(key, None)
        # Inactive but still live CodeType objects retain their monitoring mask
        # until stop(), so count them against the same bounded code ceiling.
        for stale_key, stale in tuple(self._code_states.items()):
            if stale["reference"]() is None:
                self._code_states.pop(stale_key, None)
        if len(self._code_states) >= self.recorder.limits["max_codes"]:
            return None
        state = {"reference": code_reference, "active": 0, "installed": False,
                 "disabled_instruction_offsets": set()}
        self._code_states[key] = state
        return state

    def _event_owner(self, frame, code):
        if frame is None or frame.f_code is not code:
            return None
        base = self._base_state(frame)
        tracked = self._frames.get((threading.get_ident(), id(frame)))
        if base is None or tracked is None or tracked[0] != base[0] or tracked[2]() is not code:
            return None
        return base[0], base[1]

    def _reference(self, value, seen, event_index, snapshots):
        token = self.recorder._reference(value, seen)
        if token.startswith("snapshot:"):
            old = seen[id(value)][1]
            found = snapshots.get(old)
            if found is not None:
                return found
            token = f"operand-snapshot:{self.pid}:{event_index}:{len(snapshots) + 1}"
            snapshots[old] = token
        return token

    def _shape(self, value, seen, event_index, snapshots, deferred_gaps, observed_code=_MISSING):
        if type(value) is types.FunctionType:
            try:
                reference = self._reference(value, seen, event_index, snapshots)
                function_code = value.__code__ if observed_code is _MISSING else observed_code
                code = describe_code(function_code)["key"]
                return {"kind": CallableKind.EXACT_FUNCTION.value, "reference": reference,
                        "code": code, "layout": encode(_layout(function_code))}
            except BaseException:
                deferred_gaps.append("EXACT_FUNCTION_CODE_UNAVAILABLE")
                return {"kind": CallableKind.UNAVAILABLE.value, "reference": None,
                        "code": None, "layout": None}
        if type(value) is types.MethodType:
            reference = self._reference(value, seen, event_index, snapshots)
            return {"kind": CallableKind.EXACT_METHOD.value, "reference": reference,
                    "code": None, "layout": None}
        reference = self._reference(value, seen, event_index, snapshots)
        return {"kind": CallableKind.OTHER.value, "reference": reference,
                "code": None, "layout": None}

    def _namespace_pass(self, mapping, name):
        identities = []
        found = _MISSING
        try:
            for ordinal, (key, value) in enumerate(dict.items(mapping), 1):
                if ordinal > self.limits.max_namespace_items:
                    return None, None, "GLOBAL_NAMESPACE_LOOKUP_LIMIT"
                if type(key) is not str:
                    return None, None, "GLOBAL_NAMESPACE_HAS_NONSTRING_KEY"
                identities.append((id(key), id(value)))
                if key == name:
                    found = value
        except BaseException:
            return None, None, "GLOBAL_NAMESPACE_LOOKUP_FAILED"
        return identities, found, None

    def _resolve_global(self, frame, name):
        for namespace, mapping in (("GLOBAL", frame.f_globals), ("BUILTIN", frame.f_builtins)):
            if type(mapping) is not dict:
                return None, None, "GLOBAL_NAMESPACE_NOT_EXACT_DICT"
            before, found, reason = self._namespace_pass(mapping, name)
            if reason is not None:
                return None, None, reason
            after, _second_found, reason = self._namespace_pass(mapping, name)
            if reason is not None:
                return None, None, reason
            if before != after:
                return None, None, "GLOBAL_NAMESPACE_MUTATED_DURING_LOOKUP"
            if found is not _MISSING:
                return found, namespace, None
        return None, None, "GLOBAL_NAME_UNBOUND"

    def _on_instruction(self, code, offset):
        try:
            frame = sys._getframe(1)
        except BaseException:
            return
        with self.recorder.lock:
            with self._lock:
                try:
                    if self._stopped or self._closed or os.getpid() != self.pid:
                        return self._disabled_callback_result(code)
                    witness = getattr(self.recorder, 'collector_witness', None)
                    if witness is not None and not witness.guard('operands', sys._getframe().f_code):
                        self._stopped = True
                        return self._disabled_callback_result(code)
                    if self._event_attempts >= self.limits.max_events:
                        self._dropped += 1
                        self._stopped = True
                        self._hook_epoch += 1
                        return self._disabled_callback_result(code)
                    owner_info = self._event_owner(frame, code)
                    if owner_info is None:
                        self._gap("INSTRUCTION_FRAME_UNAVAILABLE")
                        self._stopped = self.capture == _CAPTURE_WINDOWS
                        return self._disabled_callback_result(code)
                    owner, code_key = owner_info
                    if not self._monitor_is_intact(code):
                        self._mark_interference(frame, "MONITORING_MASK_OR_TOOL_CHANGED", monitoring=True)
                        return self._disabled_callback_result(code)
                    pending_key = (threading.get_ident(), owner)
                    previous_pending = self._pending.pop(pending_key, None)
                    if previous_pending is not None:
                        self._gap("PROJECT_FUNCTION_CALL_DID_NOT_ENTER", owner)
                        self.environment_observer.discard(previous_pending[-1])
                    if self.capture == _CAPTURE_WINDOWS:
                        sparse_plan = self._window_plan(code, code_key)
                        if sparse_plan is None:
                            self._gap("CALL_WINDOW_PLAN_INSTRUCTION_BUDGET_EXCEEDED", owner)
                            self._stopped = True
                            return self._disabled_callback_result(code)
                        if type(offset) is not int or offset not in sparse_plan["opcodes"]:
                            self._gap("INSTRUCTION_NOT_IN_VERIFIED_CODE", owner)
                            self._stopped = True
                            return self._disabled_callback_result(code)
                        if offset not in sparse_plan["selected_offsets"]:
                            state = self._code_states.get(id(code))
                            if state is None or state["reference"]() is not code:
                                self._gap("CALL_WINDOW_CODE_STATE_UNAVAILABLE", owner)
                                self._stopped = True
                                return self._disabled_callback_result(code)
                            disabled = state["disabled_instruction_offsets"]
                            if offset in disabled:
                                self._mark_interference(
                                    frame, "DISABLED_INSTRUCTION_LOCATION_REFIRED", monitoring=True)
                                return self._disabled_callback_result(code)
                            if self._disabled_instruction_count >= self.limits.max_events:
                                self._gap("CALL_WINDOW_DISABLED_OFFSET_BUDGET_EXCEEDED", owner)
                                self._stopped = True
                                return self._disabled_callback_result(code)
                            disabled.add(offset)
                            self._disabled_instruction_count += 1
                            return sys.monitoring.DISABLE
                        opcode_plan = sparse_plan["opcodes"]
                    else:
                        opcode_plan = self._plan(code, code_key)
                        if opcode_plan is None:
                            self._gap("OPCODE_PLAN_INSTRUCTION_BUDGET_EXCEEDED", owner)
                            self._stopped = True
                            return
                    plan = opcode_plan.get(offset)
                    if plan is None:
                        self._gap("INSTRUCTION_NOT_IN_VERIFIED_CODE", owner)
                        self._stopped = self.capture == _CAPTURE_WINDOWS
                        return self._disabled_callback_result(code)
                    _opname, slots = plan
                    row_site = _raw_site(code, offset)
                    if self._event_attempts >= self.limits.max_events:
                        self._dropped += 1
                        self._stopped = True
                        self._hook_epoch += 1
                        return self._disabled_callback_result(code)
                    event_index = self._event_index + 1
                    seen, snapshots, loads, deferred_gaps = {}, {}, [], []
                    if slots is not None:
                        for suboperand, namespace, name, slot_index in slots:
                            if namespace == "FAST_LOCAL":
                                value = frame.f_locals.get(name, _MISSING)
                                actual_namespace, reason = "FAST_LOCAL", None
                            else:
                                value, actual_namespace, reason = self._resolve_global(frame, name)
                            if value is _MISSING or reason is not None:
                                shape = {"kind": CallableKind.UNAVAILABLE.value, "reference": None,
                                         "code": None, "layout": None}
                                reference = None
                                deferred_gaps.append(reason or "FAST_LOCAL_UNAVAILABLE")
                            else:
                                shape = self._shape(value, seen, event_index, snapshots, deferred_gaps)
                                reference = shape["reference"]
                            loads.append({"suboperand": suboperand, "namespace": actual_namespace or namespace,
                                          "slot": name, "slot_index": slot_index,
                                          "reference": reference, "callable_shape": shape})
                    if len(loads) > self.limits.max_loads:
                        self._gap("INSTRUCTION_LOAD_BUDGET_EXCEEDED", owner, advance=False)
                        loads = []
                    self._emit("INSTRUCTION", owner, self.recorder.index,
                               {"site": row_site, "loads": loads})
                    for reason in deferred_gaps:
                        self._gap(reason, owner, advance=False)
                except BaseException as error:
                    self._remember_error(error)
                    self._gap("INSTRUCTION_CALLBACK_FAILURE_" + type(error).__name__)
                    if self.capture == _CAPTURE_WINDOWS:
                        self._stopped = True
                        return self._disabled_callback_result(code)

    def _disabled_callback_result(self, code=None):
        if (self.capture != _CAPTURE_WINDOWS or self._monitoring_interfered
                or self.tool_id is None):
            return None
        try:
            if (sys.monitoring.get_tool(self.tool_id) != self.tool_name
                    or sys.monitoring.get_events(self.tool_id) != 0):
                return None
            if code is not None and sys.monitoring.get_local_events(self.tool_id, code) != self._local_mask:
                return None
        except BaseException:
            return None
        return sys.monitoring.DISABLE

    def _on_call(self, code, offset, callable_object, arg0):
        try:
            frame = sys._getframe(1)
        except BaseException:
            return
        with self.recorder.lock:
            with self._lock:
                try:
                    if self._stopped or self._closed or os.getpid() != self.pid:
                        return self._disabled_callback_result(code)
                    witness = getattr(self.recorder, 'collector_witness', None)
                    if witness is not None and not witness.guard('operands', sys._getframe().f_code):
                        self._stopped = True
                        return self._disabled_callback_result(code)
                    if self._event_attempts >= self.limits.max_events:
                        self._dropped += 1
                        self._stopped = True
                        self._hook_epoch += 1
                        return self._disabled_callback_result(code)
                    owner_info = self._event_owner(frame, code)
                    if owner_info is None:
                        if self.lean_plan is not None:
                            self._scoped_gap("CALL_FRAME_UNAVAILABLE", code)
                            return None
                        self._gap("CALL_FRAME_UNAVAILABLE")
                        self._stopped = self.capture == _CAPTURE_WINDOWS
                        return self._disabled_callback_result(code)
                    owner, _code_key = owner_info
                    if self.lean_plan is not None:
                        body = self.lean_plan.match(code)
                        if body is None or offset not in body.call_offsets:
                            self._scoped_gap("LEAN_CALL_NOT_IN_STATIC_PLAN", code, owner)
                            return None
                        if offset in body.unsupported_offsets:
                            self._scoped_gap("LEAN_UNSUPPORTED_CALL_SITE", code, owner)
                            return None
                    if not self._monitor_is_intact(code):
                        self._mark_interference(frame, "MONITORING_MASK_OR_TOOL_CHANGED", monitoring=True)
                        return self._disabled_callback_result(code)
                    pending_key = (threading.get_ident(), owner)
                    if self._pending.pop(pending_key, None) is not None:
                        self._gap("PROJECT_FUNCTION_CALL_DID_NOT_ENTER", owner)
                    row_site = _raw_site(code, offset)
                    if self._event_attempts >= self.limits.max_events:
                        self._dropped += 1
                        self._stopped = True
                        self._hook_epoch += 1
                        return self._disabled_callback_result(code)
                    event_index = self._event_index + 1
                    seen, snapshots, deferred_gaps = {}, {}, []
                    observed_target_code = (callable_object.__code__
                                            if type(callable_object) is types.FunctionType else _MISSING)
                    dispatch = self._shape(callable_object, seen, event_index, snapshots, deferred_gaps,
                                           observed_code=observed_target_code)
                    missing = arg0 is self._arg0_missing
                    arg0_reference = None if missing else self._reference(arg0, seen, event_index, snapshots)
                    attempt_index = self._emit("CALL_ATTEMPT", owner, self.recorder.index,
                                               {"site": row_site, "dispatch": dispatch,
                                                "arg0": arg0_reference, "arg0_missing": missing})
                    for reason in deferred_gaps:
                        self._gap(reason, owner, advance=False)
                    if attempt_index is None:
                        return self._disabled_callback_result(code)
                    if self.python_targets is not None:
                        self.python_targets.on_call(callable_object, arg0, missing, code, owner, row_site, attempt_index,
                            lambda value: self._reference(value, seen, event_index, snapshots), _layout)
                    if dispatch["kind"] == CallableKind.EXACT_FUNCTION.value and type(callable_object) is types.FunctionType:
                        target_code = observed_target_code
                        witness = getattr(self.recorder, 'collector_witness', None)
                        if witness is not None and not witness.guard('environments'):
                            self._stopped = True
                            return self._disabled_callback_result(code)
                        self.environment_observer.dispatch(callable_object, attempt_index, owner,
                            self.recorder.index, dispatch["code"],
                            lambda value: self._reference(value, seen, event_index, snapshots))
                        if self._code_inside(target_code):
                            try:
                                self._pending[pending_key] = (
                                    weakref.ref(callable_object), weakref.ref(target_code),
                                    describe_code(target_code)["key"], describe_code(code)["key"],
                                    row_site, attempt_index,
                                )
                            except BaseException:
                                self._gap("EXPECTED_FUNCTION_ENTRY_CANNOT_BE_TRACKED", owner)
                                self.environment_observer.discard(attempt_index)
                        else:
                            self.environment_observer.discard(attempt_index)
                except BaseException as error:
                    if self.lean_plan is not None:
                        state = self._base_state(frame)
                        self._scoped_gap("CALL_CALLBACK_FAILURE_" + type(error).__name__, code,
                                         state[0] if state is not None else None)
                        return None
                    self._remember_error(error)
                    self._gap("CALL_CALLBACK_FAILURE_" + type(error).__name__)
                    if self.capture == _CAPTURE_WINDOWS:
                        self._stopped = True
                        return self._disabled_callback_result(code)

    def stop(self):
        """Stop observation and remove only masks still owned by this tool."""
        if self._closed or os.getpid() != self.pid:
            return
        with self.recorder.lock:
            with self._lock:
                if self._stopped and self._fd is None:
                    return
                if self.lean_plan is not None:
                    try:self.lean_plan.verify_sources()
                    except (OSError, ValueError, UnicodeError):
                        self._gap("LEAN_SOURCE_VERSION_GUARD_FAILED")
                        self._remember_error(ValueError('lean source changed'))
                for (_, owner), _pending in tuple(self._pending.items()):
                    self._gap("PROJECT_FUNCTION_CALL_DID_NOT_ENTER", owner)
                    self.environment_observer.discard(_pending[-1])
                self._pending.clear()
                self._stopped = True
                if not self._monitoring_interfered:
                    try:
                        owns_tool = sys.monitoring.get_tool(self.tool_id) == self.tool_name
                        owns_global_mask = sys.monitoring.get_events(self.tool_id) == 0
                        installed_codes = []
                        for state in tuple(self._code_states.values()):
                            code = state["reference"]()
                            if code is not None and state["installed"]:
                                installed_codes.append(code)
                        owns_local_masks = all(
                            sys.monitoring.get_local_events(self.tool_id, code) == self._local_mask
                            for code in installed_codes
                        )
                        if owns_tool and owns_global_mask and owns_local_masks:
                            for code in installed_codes:
                                sys.monitoring.set_local_events(self.tool_id, code, 0)
                        elif self.capture == _CAPTURE_WINDOWS and installed_codes:
                            if len(self._errors) < 16:
                                self._errors.append("MONITORING_MASK_OR_TOOL_CHANGED_AT_STOP")
                            self._interfered = True
                            self._monitoring_interfered = True
                    except BaseException as error:
                        self._remember_error(error)
                        self._interfered = True
                        self._monitoring_interfered = True
                self._code_states.clear()
                self._frames.clear()
                if not self._monitoring_interfered:
                    self._release_tool()
                if self._fd is not None:
                    try:
                        if not self._io_failed:
                            self._flush()
                    except OSError as error:
                        self._io_failed = True
                        self._remember_error(error)
                    finally:
                        self._buffer.clear()
                    try:
                        os.close(self._fd)
                    except OSError as error:
                        self._io_failed = True
                        self._remember_error(error)
                    self._fd = None

    def after_fork(self):
        """Child-side cleanup; parent remains the owner of this sidecar."""
        if os.getpid() == self.pid:
            return
        self._stopped = self._closed = True
        self._buffer.clear()
        if not self._monitoring_interfered and self.tool_id is not None:
            try:
                monitoring = sys.monitoring
                owns_tool = monitoring.get_tool(self.tool_id) == self.tool_name
                owns_global_mask = monitoring.get_events(self.tool_id) == 0
                installed_codes = []
                for state in tuple(self._code_states.values()):
                    code = state["reference"]()
                    if code is not None and state["installed"]:
                        installed_codes.append(code)
                owns_local_masks = all(
                    monitoring.get_local_events(self.tool_id, code) == self._local_mask
                    for code in installed_codes
                )
                if owns_tool and owns_global_mask and owns_local_masks:
                    for code in installed_codes:
                        monitoring.set_local_events(self.tool_id, code, 0)
                    if monitoring.get_events(self.tool_id) == 0:
                        monitoring.free_tool_id(self.tool_id)
                else:
                    # A child-side mismatch means another owner may have
                    # taken over the tool or one of its local masks.  Do not
                    # partially clear masks or free the shared tool slot.
                    self._interfered = True
                    self._monitoring_interfered = True
            except BaseException:
                self._interfered = True
                self._monitoring_interfered = True
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

    @staticmethod
    def _manifest(path, family, process_id):
        digest = hashlib.sha256()
        size = lines = 0
        with open(path, "rb") as stream:
            while True:
                block = stream.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
                size += len(block)
                lines += block.count(b"\n")
        return CallTraceFile(str(path), family, process_id, digest.hexdigest(), size, lines)

    def close(self):
        """Write final metadata after the original frame recorder closes."""
        if self._closed or os.getpid() != self.pid:
            return
        if not self._stopped:
            self.stop()
        if not self.recorder.closed:
            self._remember_error(RuntimeError("base frame recorder must close before operand metadata"))
        try:
            manifest = tuple(self._manifest(path, family, self.pid) for path, family in (
                (self.recorder.code_path, "codes"),
                (self.recorder.event_path, "events"),
                (self.recorder.out / f"call-meta.{self.pid}.json", "meta"),
            ))
            metadata = OperandCollectionMetadata(
                schema=_SCHEMA, schema_version=1, process_id=self.pid, project_root=self.root,
                python=sys.version, implementation="cpython", rule=self.rule, limits=self.limits,
                events=self._event_count, event_attempts=self._event_attempts,
                instructions=self._instruction_count, call_attempts=self._attempt_count,
                handshakes=self._handshake_count, gaps=self._gap_count,
                loads=self._loads, references=self._references, bytes=self._bytes,
                dropped_events=self._dropped, errors=tuple(self._errors), io_failed=self._io_failed,
                previous_profile=bool(self.recorder.previous_profile_present), base_manifest=manifest,
                reference_contents_observed=False, callable_environment_established=False,
                transformation_authorized=False,
            )
            payload = json.dumps(encode(metadata), ensure_ascii=True, indent=2, allow_nan=False) + "\n"
            fd = os.open(self._metadata_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                data = payload.encode("ascii")
                position = 0
                while position < len(data):
                    written = os.write(fd, data[position:])
                    if written <= 0:
                        raise OSError("operand metadata write made no progress")
                    position += written
            finally:
                os.close(fd)
            if self.python_targets is not None:
                self.python_targets.legacy_inputs = (*manifest,
                    CallTraceFile(str(self._event_path), "operands", self.pid,
                        self._target_event_digest.hexdigest(), self._bytes, self._event_count),
                    CallTraceFile(str(self._metadata_path), "operand-meta", self.pid,
                        hashlib.sha256(data).hexdigest(), len(data), data.count(b"\n")))
        except BaseException as error:
            self._remember_error(error)
            raise
        finally:
            if self.environment_observer is not None:
                self.environment_observer.close()
            if self.python_targets is not None:
                self.python_targets.close()
            self._closed = True
            if self.recorder.operand_observer is self:
                self.recorder.operand_observer = None


def _environment_limit(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return default
    if not raw.isascii() or not raw.isdecimal() or raw.startswith("0"):
        raise ValueError(name + " must be a canonical positive decimal integer")
    return _positive(int(raw), name)


def install(recorder, *, capture=None, max_events=None, max_bytes=None,
            max_loads=None, max_namespace_items=None, max_references=None, python_targets=None):
    """Attach the sidecar without replacing the existing sys.setprofile hook."""
    if capture is None:
        capture = os.environ.get("SCAR_OPERAND_CAPTURE", _CAPTURE_INSTRUCTIONS)
    if python_targets is None:
        selection = os.environ.get("SCAR_PYTHON_CALL_TARGETS", "0")
        if selection not in ("0", "PYTHON_CALL_TARGETS_V2"):
            raise ValueError("SCAR_PYTHON_CALL_TARGETS must be 0 or PYTHON_CALL_TARGETS_V2")
        python_targets = selection == "PYTHON_CALL_TARGETS_V2"
    if type(capture) is not str or capture not in _CAPTURE_RULES:
        raise ValueError("SCAR_OPERAND_CAPTURE must be 'instructions' or 'windows'")
    max_events = _environment_limit("SCAR_OPERAND_MAX_EVENTS", 100_000) if max_events is None else max_events
    max_bytes = _environment_limit("SCAR_OPERAND_MAX_BYTES", 32_000_000) if max_bytes is None else max_bytes
    max_loads = _environment_limit("SCAR_OPERAND_MAX_LOADS", 64) if max_loads is None else max_loads
    max_namespace_items = (_environment_limit("SCAR_OPERAND_MAX_NAMESPACE_ITEMS", 4096)
                           if max_namespace_items is None else max_namespace_items)
    return CallOperandObserver(recorder, capture=capture, max_events=max_events, max_bytes=max_bytes,
                               max_loads=max_loads, max_namespace_items=max_namespace_items,
                               max_references=max_references, python_targets=python_targets)


__all__ = ["CallOperandObserver", "install"]
