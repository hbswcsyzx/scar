"""Capture a narrow, real Python ``is``/``is not`` execution slice.

This adapter runs the supplied ordinary function once.  Profile events supply
its actual argument references and returned bool; CPython monitoring supplies
instruction offsets.  Operand and result stack links are explicitly inferred
from the exact source/code witness because monitoring does not expose a VM
operand stack.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from copy import deepcopy
import dis
import hashlib
import json
import os
import sys
import threading
import uuid
from pathlib import Path
from typing import Any

from scar.analysis.identity_source_v2 import (
    IdentityFunctionSource, prepare_identity_source, validate_identity_source,
)
from scar.analysis.source_semantics_v2 import extract_source_semantics
from scar.ir.frontend_v2 import build_semantic
from scar.ir import CodeID
from scar.ir.identity_execution_v2 import (
    IdentityExecutionCall, IdentityExecutionSnapshot, IdentityOperandOccurrence,
    IdentityResultOccurrence, IdentityRuntimeEvent, IdentityRuntimeEventKind,
    PythonBoolSingleton,
)
from scar.ir.provenance import EventPoint
from scar.ir.v2 import (
    EvidenceClaim, EvidenceKind, EvidenceEdge, EvidenceEndpoint, EvidenceGraph,
    EvidenceNodeKind, EvidenceRelation, EvidenceStatus, IRBundle,
    OperationDefinitionID, OperationInstanceID, OperationInstance, ValueObservation,
)
from scar.ir.v2.schemas import canonical_json
from scar.trace.python_objects_v2 import PythonObjectObserver


_MONITOR_VERSION = (3, 14, 7)
_OBSERVED = "actual CPython profile/monitoring callback"
_OPERAND_ASSUMPTION = (
    "exact witnessed code has no intervening store or call; parameter loads read the observed entry bindings",
)
_RESULT_ASSUMPTION = (
    "the witnessed IS_OP is followed directly by RETURN_VALUE; monitoring exposes no operand stack",
)


@dataclass(slots=True)
class _Attempt:
    number: int
    thread_id: int
    raw_events: list[IdentityRuntimeEvent]
    failure: list[str]
    locals_by_parameter: dict[str, Any] | None = None
    input_handles: dict[str, Any] | None = None
    input_observations: dict[str, str] | None = None
    entry_event: EventPoint | None = None
    monitor_start_event: EventPoint | None = None
    operand_events: dict[int, tuple[EventPoint, str]] | None = None
    operator_event: EventPoint | None = None
    operator_event_reference: str | None = None
    return_instruction_event: EventPoint | None = None
    return_event: EventPoint | None = None
    profile_return_result: PythonBoolSingleton | None = None
    monitor_return_result: PythonBoolSingleton | None = None
    result_handle: Any | None = None
    result_observation_id: str | None = None
    instruction_index: int = 0
    profile_call_reference: str | None = None
    monitor_start_reference: str | None = None
    profile_return_reference: str | None = None
    monitor_return_reference: str | None = None


class IdentityExecutionObserver:
    """Observe only an exact returned identity comparison function.

    The monitor hooks are installed for one direct call and always removed.
    Existing current-thread profile/trace hooks or related monitoring tools
    cause a pre-call rejection.  Only CPython 3.14.7 is enabled by this first
    capture slice; other runtimes need their own event-order verification.
    """

    def __init__(self, function, *, semantic=None, source_semantics=None, source_texts=None,
                 object_observer: PythonObjectObserver | None = None,
                 max_calls: int = 128, allow_strong_leases: bool = False,
                 max_strong_leases: int = 0):
        if type(max_calls) is not int or max_calls < 1:
            raise ValueError("max_calls must be a positive integer")
        if type(allow_strong_leases) is not bool:
            raise TypeError("allow_strong_leases must be bool")
        if type(max_strong_leases) is not int or max_strong_leases < 0:
            raise ValueError("max_strong_leases must be non-negative")
        if not allow_strong_leases and max_strong_leases:
            raise ValueError("max_strong_leases requires allow_strong_leases=True")

        if (semantic is None) != (source_semantics is None):
            raise ValueError("semantic and source_semantics must be supplied together")
        if semantic is None:
            filename = getattr(getattr(function, "__code__", None), "co_filename", None)
            if not filename or filename.startswith("<"):
                raise ValueError("automatic source capture requires a filesystem-backed function")
            frontend = build_semantic(Path(filename))
            semantic = frontend.graph
            source_semantics = extract_source_semantics(semantic)

        self.function = function
        self.semantic = semantic
        self.source_semantics = source_semantics
        self.source_texts = source_texts
        self.source_model: IdentityFunctionSource = prepare_identity_source(
            semantic, source_semantics, function, source_texts=source_texts)
        self.source_model.assert_valid(semantic, source_semantics, function,
                                       source_texts=source_texts)
        self._code = function.__code__
        self._code_id = self.source_model.loaded_code_id
        self._source_fingerprint = self.source_model.source.fingerprint
        self._max_calls = max_calls
        self._attempt_count = 0
        self._closed = False
        self._busy = threading.Lock()
        self._calls: list[IdentityExecutionCall] = []
        self._events: list[IdentityRuntimeEvent] = []
        self._private_events: list[tuple[IdentityRuntimeEvent, ...]] = []
        self._private_calls: list[IdentityExecutionCall] = []
        self._private_bundle_digests: list[str] = []
        self._private_object_digests: list[str] = []
        self._last_rejection: str | None = None

        self.object_observer = object_observer or PythonObjectObserver(
            scope="identity-execution", allow_strong_leases=allow_strong_leases,
            max_strong_leases=max_strong_leases)
        if type(self.object_observer) is not PythonObjectObserver:
            raise TypeError("object_observer must be PythonObjectObserver")
        self.scope = self.object_observer.model.scope
        self.namespace = self.object_observer.model.namespace
        self.process_id = os.getpid()
        if self.object_observer.model.process_id != self.process_id:
            raise ValueError("object observer belongs to another process")

        self.bundle = IRBundle(semantic, EvidenceGraph(), self.object_observer.graph,
                               source_semantics=source_semantics)
        self._instructions = tuple(self.source_model.instructions)
        self._instruction_by_offset = {item.offset: item for item in self._instructions}
        if len(self._instruction_by_offset) != len(self._instructions):
            raise ValueError("source witness contains duplicate bytecode offsets")
        self._expected_instructions = tuple(
            item for item in self._instructions if item.opname != "RESUME")
        self._load_offsets: dict[int, list[tuple[int, int]]] = {}
        for operand in self.source_model.operands:
            self._load_offsets.setdefault(operand.load_offset, []).append(
                (operand.index, operand.load_subindex))
        self._operator_instruction, = tuple(
            item for item in self._instructions if item.opname == "IS_OP")
        self._return_instruction, = tuple(
            item for item in self._instructions if item.opname == "RETURN_VALUE")
        if self.source_model.opcode.value not in {"is", "is_not"}:
            raise ValueError("source identity opcode is outside the capture rule")
        self._monitor_name = f"scar_identity_{uuid.uuid4().hex}"
        self._last_environment: tuple[Any, ...] = ()
        self._last_cleanup_ok = True

    @property
    def calls(self) -> tuple[IdentityExecutionCall, ...]:
        return tuple(self._calls)

    @property
    def events(self) -> tuple[IdentityRuntimeEvent, ...]:
        return tuple(self._events)

    @property
    def last_rejection(self) -> str | None:
        return self._last_rejection

    def call(self, *args, **kwargs):
        """Execute the target exactly once and return its actual result.

        A successful target result is returned even if event collection was
        incomplete; in that case no positive call record is added and
        ``last_rejection`` names the missing evidence.  Preflight conflicts
        raise before the target function is entered.
        """
        self._ensure_open()
        if not self._busy.acquire(blocking=False):
            raise RuntimeError("identity collector call is concurrent or reentrant")
        self._last_rejection = None
        try:
            if self._attempt_count >= self._max_calls:
                raise RuntimeError("identity execution call budget exhausted")
            self._check_source_and_runtime()
            monitoring = self._preflight_monitoring()
            self._attempt_count += 1
            attempt = _Attempt(
                self._attempt_count - 1,
                threading.get_ident(),
                [], [], {}, {}, {},
                operand_events={},
            )
            try:
                result, cleanup_ok = self._run_once(monitoring, attempt, args, kwargs)
            except BaseException as error:
                self._last_rejection = (
                    f"target call raised {type(error).__name__}; no successful return slice was accepted")
                raise
            self._last_cleanup_ok = cleanup_ok
            if not cleanup_ok:
                attempt.failure.append("profile or monitoring cleanup did not restore the preflight state")
            failure = self._validate_attempt(attempt, result)
            if failure:
                self._last_rejection = "; ".join(dict.fromkeys(failure))
                return result
            self._commit(attempt)
            return result
        finally:
            self._busy.release()

    def validate(self) -> dict[str, Any]:
        """Validate current source, graph and historical capture structure."""
        errors: list[str] = []
        source_report = validate_identity_source(
            self.source_model, self.semantic, self.source_semantics, self.function,
            source_texts=self.source_texts)
        errors.extend("source: " + item for item in source_report["errors"])
        object_report = self.object_observer.model.validate()
        errors.extend("objects: " + item for item in object_report["errors"])
        bundle_report = self.bundle.validate()
        errors.extend("bundle: " + item for item in bundle_report["errors"])
        snapshot_report = self.snapshot().validate_structure()
        errors.extend("snapshot: " + item for item in snapshot_report["errors"])
        return {"valid": not errors, "errors": errors,
                "scope": self.scope, "calls": len(self._calls),
                "events": len(self._events),
                "authority": "structural history only; call attest() for active capture"}

    def attest(self) -> bool:
        """Check successful records against this active collector's private log."""
        if self._closed or not self._last_cleanup_ok or not self._private_calls:
            return False
        if self.function.__code__ is not self._code:
            return False
        if self.source_model.validate(self.semantic, self.source_semantics, self.function,
                                      source_texts=self.source_texts)["valid"] is not True:
            return False
        if tuple(self._calls) != tuple(self._private_calls):
            return False
        if tuple(self._events) != tuple(
            event for attempt_events in self._private_events for event in attempt_events
        ):
            return False
        if len(self._private_events) != len(self._private_calls):
            return False
        if len(self._private_bundle_digests) != len(self._private_calls):
            return False
        if len(self._private_object_digests) != len(self._private_calls):
            return False
        if not self.bundle.validate()["valid"]:
            return False
        if not self.object_observer.model.validate()["valid"]:
            return False
        if self._digest_bundle() != self._private_bundle_digests[-1]:
            return False
        if self._digest_object_model() != self._private_object_digests[-1]:
            return False
        for call, raw_events in zip(self._private_calls, self._private_events):
            if not self._call_events_match(call, raw_events):
                return False
            for operand in call.operands:
                if not self.object_observer.attest_observation(
                    operand.handle, operand.entry_event, operand.entry_observation_id):
                    return False
            result = call.result_occurrence
            if not self.object_observer.attest_observation(
                result.handle, result.observed_at,
                result.reference_observation_id):
                return False
        return True

    def snapshot(self) -> IdentityExecutionSnapshot:
        runtime_version = tuple(sys.version_info[:3])
        result = IdentityExecutionSnapshot(
            self.scope, self.namespace, self.process_id,
            sys.implementation.name, runtime_version,
            self._code_id, self._source_fingerprint,
            self.source_model.function_definition, self.source_model.identity_operation,
            self.source_model.return_use.operation,
            tuple(self._calls), tuple(self._events),
        )
        return result

    def close(self) -> None:
        if self._closed:
            return
        if self._busy.locked():
            raise RuntimeError("cannot close identity collector during a call")
        self._closed = True
        self.object_observer.close()

    def __enter__(self):
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("identity execution observer is closed")

    def _check_source_and_runtime(self) -> None:
        if sys.implementation.name != "cpython" or tuple(sys.version_info[:3]) != _MONITOR_VERSION:
            raise RuntimeError(
                "identity event sequence is verified only on CPython 3.14.7")
        if not callable(getattr(sys, "monitoring", None)) and not hasattr(sys, "monitoring"):
            raise RuntimeError("sys.monitoring is unavailable")
        report = validate_identity_source(
            self.source_model, self.semantic, self.source_semantics, self.function,
            source_texts=self.source_texts)
        if not report["valid"]:
            raise RuntimeError("identity source/code witness changed: " + "; ".join(report["errors"]))
        if self.function.__code__ is not self._code:
            raise RuntimeError("function code object changed after source preparation")
        if self.object_observer.model.process_id != os.getpid():
            raise RuntimeError("object observer process context changed")
        adaptive = {item.offset: item for item in dis.get_instructions(
            self._code, show_caches=False, adaptive=True)}
        for expected in self._expected_instructions:
            actual = adaptive.get(expected.offset)
            if actual is None or actual.opname != expected.opname or actual.arg != expected.arg:
                raise RuntimeError(
                    f"adaptive instruction at offset {expected.offset} differs from source witness")

    def _preflight_monitoring(self):
        if sys.getprofile() is not None:
            raise RuntimeError("current thread already has a profile hook")
        if sys.gettrace() is not None:
            raise RuntimeError("current thread already has a trace hook")
        monitoring = sys.monitoring
        events = monitoring.events
        mask = events.PY_START | events.INSTRUCTION | events.PY_RETURN
        for tool_id in range(6):
            tool = monitoring.get_tool(tool_id)
            if tool is None:
                continue
            if tool == self._monitor_name:
                raise RuntimeError("monitoring tool name is already in use")
            global_events = monitoring.get_events(tool_id)
            local_events = monitoring.get_local_events(tool_id, self._code)
            if (global_events | local_events) & mask:
                raise RuntimeError("another monitoring tool observes target execution events")
        tool_id = next((item for item in range(6) if monitoring.get_tool(item) is None), None)
        if tool_id is None:
            raise RuntimeError("no free sys.monitoring tool ID")
        environment = self._monitor_environment(monitoring)
        self._last_environment = environment
        return monitoring, tool_id, mask, environment

    def _monitor_environment(self, monitoring):
        rows = []
        for tool_id in range(6):
            name = monitoring.get_tool(tool_id)
            if name is None:
                continue
            rows.append((tool_id, name, monitoring.get_events(tool_id),
                         monitoring.get_local_events(tool_id, self._code)))
        return tuple(rows)

    def _run_once(self, preflight, attempt: _Attempt, args, kwargs):
        monitoring, tool_id, mask, environment = preflight
        events = monitoring.events
        callbacks = {}
        profile = None
        installed = False
        cleanup_ok = True

        def add_event(kind, code, *, offset=None, actual_result=None):
            if code is not self._code:
                attempt.failure.append("runtime hook received a different code object")
            actual_thread = threading.get_ident()
            if actual_thread != attempt.thread_id:
                attempt.failure.append("target code emitted an event on a foreign thread")
            bool_result = (PythonBoolSingleton.from_actual(actual_result)
                           if actual_result is not None else None)
            event_id = f"identity:{self.scope}:attempt:{attempt.number}:event:{len(attempt.raw_events)}"
            raw_ref = f"profile-or-monitor-callback:{event_id}"
            event = IdentityRuntimeEvent(
                event_id, kind, len(attempt.raw_events), os.getpid(), actual_thread,
                CodeID.from_code(code).key(), raw_ref, offset, bool_result)
            attempt.raw_events.append(event)
            return event

        def profile_callback(frame, event_name, arg):
            nonlocal profile
            try:
                if frame.f_code is not self._code:
                    return
                if event_name == "call":
                    if attempt.profile_call_reference is not None:
                        attempt.failure.append("target profile call was duplicated")
                        return
                    event = add_event(IdentityRuntimeEventKind.PROFILE_CALL, frame.f_code)
                    attempt.profile_call_reference = event.event_id
                    values = frame.f_locals.copy()
                    required_names = {item.parameter_name for item in self.source_model.operands}
                    if not required_names <= set(values):
                        attempt.failure.append("profile frame lacks a source operand parameter")
                        return
                    attempt.locals_by_parameter = {
                        name: values[name] for name in required_names
                    }
                    entry = self.object_observer.event(f"call-entry:{attempt.number}")
                    attempt.entry_event = entry
                    for name in sorted(required_names):
                        handle = self.object_observer.observe(
                            attempt.locals_by_parameter[name], at=entry)
                        observation = self.object_observer.model.observations[-1]
                        attempt.input_handles[name] = handle
                        attempt.input_observations[name] = observation.observation_id
                elif event_name == "return":
                    event = add_event(IdentityRuntimeEventKind.PROFILE_RETURN, frame.f_code,
                                      actual_result=arg)
                    if attempt.profile_return_reference is not None:
                        attempt.failure.append("target profile return was duplicated")
                    attempt.profile_return_reference = event.event_id
                    if type(arg) is not bool:
                        attempt.failure.append("profile return was not an exact Python bool")
                    else:
                        attempt.profile_return_result = PythonBoolSingleton.from_actual(arg)
                # sys.setprofile intentionally has no ordinary Python
                # exception event. An exception cannot satisfy the required
                # monitor PY_RETURN and is propagated by the wrapper.
            except Exception as error:
                attempt.failure.append(
                    f"profile callback failed: {type(error).__name__}: {str(error)}")

        def monitor_start(code, offset):
            try:
                event = add_event(IdentityRuntimeEventKind.MONITOR_START, code, offset=offset)
                if attempt.monitor_start_reference is not None:
                    attempt.failure.append("PY_START event was duplicated")
                attempt.monitor_start_reference = event.event_id
                if attempt.profile_call_reference is None:
                    attempt.failure.append("PY_START preceded the target profile call")
                if offset != 0:
                    attempt.failure.append("PY_START offset differs from verified entry offset")
                if threading.get_ident() == attempt.thread_id:
                    attempt.monitor_start_event = self.object_observer.event(
                        f"py-start:{attempt.number}")
            except Exception as error:
                attempt.failure.append(f"PY_START callback failed: {type(error).__name__}")

        def monitor_instruction(code, offset):
            try:
                event = add_event(IdentityRuntimeEventKind.MONITOR_INSTRUCTION,
                                  code, offset=offset)
                expected = self._expected_instructions
                if attempt.instruction_index >= len(expected):
                    attempt.failure.append("monitoring emitted an extra instruction event")
                    return
                instruction = expected[attempt.instruction_index]
                attempt.instruction_index += 1
                if instruction.offset != offset:
                    attempt.failure.append(
                        f"instruction event offset {offset} differs from expected {instruction.offset}")
                if threading.get_ident() != attempt.thread_id:
                    return
                point = self.object_observer.event(f"instruction:{offset}")
                if offset in self._load_offsets:
                    for index, _subindex in self._load_offsets[offset]:
                        attempt.operand_events[index] = (point, event.event_id)
                if instruction.opname == "IS_OP":
                    attempt.operator_event = point
                    attempt.operator_event_reference = event.event_id
                if instruction.opname == "RETURN_VALUE":
                    attempt.return_instruction_event = point
            except Exception as error:
                attempt.failure.append(f"INSTRUCTION callback failed: {type(error).__name__}")

        def monitor_return(code, offset, retval):
            try:
                event = add_event(IdentityRuntimeEventKind.MONITOR_RETURN, code,
                                  offset=offset, actual_result=retval)
                if attempt.monitor_return_reference is not None:
                    attempt.failure.append("PY_RETURN event was duplicated")
                attempt.monitor_return_reference = event.event_id
                if type(retval) is not bool:
                    attempt.failure.append("PY_RETURN value was not an exact Python bool")
                else:
                    attempt.monitor_return_result = PythonBoolSingleton.from_actual(retval)
                if attempt.profile_return_result is None:
                    attempt.failure.append("PY_RETURN had no preceding profile return")
                elif attempt.profile_return_result is not attempt.monitor_return_result:
                    attempt.failure.append("profile and monitoring return bools differ")
                if offset != self._return_instruction.offset:
                    attempt.failure.append("PY_RETURN offset differs from RETURN_VALUE")
                if threading.get_ident() == attempt.thread_id and type(retval) is bool:
                    attempt.return_event = self.object_observer.event(
                        f"py-return:{attempt.number}")
                    attempt.result_handle = self.object_observer.observe(
                        retval, at=attempt.return_event)
                    attempt.result_observation_id = self.object_observer.model.observations[-1].observation_id
            except Exception as error:
                attempt.failure.append(f"PY_RETURN callback failed: {type(error).__name__}")

        callback_specs = (
            (events.PY_START, monitor_start),
            (events.INSTRUCTION, monitor_instruction),
            (events.PY_RETURN, monitor_return),
        )
        try:
            monitoring.use_tool_id(tool_id, self._monitor_name)
            installed = True
            for event, callback in callback_specs:
                monitoring.register_callback(tool_id, event, callback)
                callbacks[event] = callback
            monitoring.set_local_events(tool_id, self._code, mask)
            profile = profile_callback
            sys.setprofile(profile)
            actual = self.function(*args, **kwargs)
        except BaseException:
            # The target exception is deliberately allowed to propagate.  A
            # call which raises has no valid PY_RETURN observation.
            raise
        finally:
            if sys.getprofile() is profile:
                sys.setprofile(None)
            else:
                cleanup_ok = False
            if sys.gettrace() is not None:
                cleanup_ok = False
            if installed and monitoring.get_tool(tool_id) == self._monitor_name:
                try:
                    monitoring.set_local_events(tool_id, self._code, 0)
                    for event, _callback in callback_specs:
                        monitoring.register_callback(tool_id, event, None)
                    monitoring.set_events(tool_id, 0)
                    monitoring.free_tool_id(tool_id)
                except Exception:
                    cleanup_ok = False
            elif installed:
                cleanup_ok = False
            try:
                if self._monitor_environment(monitoring) != environment:
                    cleanup_ok = False
            except Exception:
                cleanup_ok = False
            self._last_cleanup_ok = cleanup_ok
        return actual, cleanup_ok

    def _validate_attempt(self, attempt: _Attempt, actual_result: Any) -> list[str]:
        errors = list(attempt.failure)
        if self.function.__code__ is not self._code:
            errors.append("function code object changed during target call")
        if sys.getprofile() is not None or sys.gettrace() is not None:
            errors.append("profile/trace hooks remain active after cleanup")
        expected_count = len(self._expected_instructions)
        if attempt.profile_call_reference is None:
            errors.append("target profile call was not observed")
        if attempt.monitor_start_reference is None or attempt.monitor_start_event is None:
            errors.append("target PY_START was not observed")
        if attempt.instruction_index != expected_count:
            errors.append("monitoring instruction stream was incomplete")
        if attempt.profile_return_reference is None or attempt.profile_return_result is None:
            errors.append("successful profile return was not observed")
        if attempt.monitor_return_reference is None or attempt.monitor_return_result is None:
            errors.append("successful monitoring PY_RETURN was not observed")
        if (attempt.operator_event is None or attempt.operator_event_reference is None):
            errors.append("IS_OP instruction event was not observed")
        if attempt.return_instruction_event is None:
            errors.append("RETURN_VALUE instruction event was not observed")
        if attempt.return_event is None or attempt.result_handle is None or not attempt.result_observation_id:
            errors.append("actual result reference was not observed")
        if type(actual_result) is not bool:
            errors.append("actual target result is not an exact Python bool")
        elif (attempt.monitor_return_result is not None
              and PythonBoolSingleton.from_actual(actual_result) is not attempt.monitor_return_result):
            errors.append("wrapper result differs from observed target bool")
        if attempt.instruction_index == expected_count and attempt.raw_events:
            offsets = [event.offset for event in attempt.raw_events
                       if event.kind is IdentityRuntimeEventKind.MONITOR_INSTRUCTION]
            if offsets != [item.offset for item in self._expected_instructions]:
                errors.append("monitoring instruction offsets are extra, missing, or out of order")
        if any(event.thread_id != attempt.thread_id for event in attempt.raw_events):
            errors.append("runtime callback stream contains a foreign-thread event")
        if any(event.code_id != self._code_id for event in attempt.raw_events):
            errors.append("runtime callback stream changed code identity")
        if self.function.__code__ is not self._code:
            errors.append("target code object no longer matches source witness")
        expected_refs = {attempt.profile_call_reference, attempt.monitor_start_reference,
                         attempt.profile_return_reference, attempt.monitor_return_reference}
        if None in expected_refs:
            errors.append("runtime event references are incomplete")
        # The runtime hook order was experimentally checked on the supported
        # interpreter.  This exact event-kind sequence rejects missing, extra,
        # or reordered callbacks before a public sample is made.
        expected_kinds = [IdentityRuntimeEventKind.PROFILE_CALL,
                          IdentityRuntimeEventKind.MONITOR_START]
        expected_kinds += [IdentityRuntimeEventKind.MONITOR_INSTRUCTION] * expected_count
        expected_kinds += [IdentityRuntimeEventKind.PROFILE_RETURN,
                           IdentityRuntimeEventKind.MONITOR_RETURN]
        if [event.kind for event in attempt.raw_events] != expected_kinds:
            errors.append("profile/monitor callback sequence is incomplete or reordered")
        return errors

    def _commit(self, attempt: _Attempt) -> None:
        call_sequence = len(self._calls)
        base = len(self._events)
        finalized = tuple(replace(event, sequence=base + index)
                          for index, event in enumerate(attempt.raw_events))
        by_ref = {event.event_id: event for event in finalized}
        source_operands = self.source_model.operands
        input_value_observations: dict[str, str] = {}
        read_instances: list[OperationInstanceID] = []
        operands: list[IdentityOperandOccurrence] = []

        function_instance = self._instance_id(call_sequence, "function")
        operator_instance = self._instance_id(call_sequence, "identity")
        return_instance = self._instance_id(call_sequence, "return")
        for index, source_operand in enumerate(source_operands):
            read_instance = self._instance_id(call_sequence, f"read:{index}")
            read_instances.append(read_instance)
        for index, source_operand in enumerate(source_operands):
            point, event_reference = attempt.operand_events[index]
            handle = attempt.input_handles[source_operand.parameter_name]
            observation_id = attempt.input_observations[source_operand.parameter_name]
            claim = EvidenceClaim(
                EvidenceKind.INFERRED,
                references=(source_operand.source.atom_id.wire,
                            event_reference, self._code_id),
                scope=self.scope,
                confidence=1.0,
                assumptions=_OPERAND_ASSUMPTION,
            )
            operands.append(IdentityOperandOccurrence(
                index, source_operand.role, source_operand.read_operation,
                source_operand.binding_use, source_operand.slot,
                source_operand.read_output_slot, source_operand.value,
                source_operand.parameter_name, handle, observation_id,
                attempt.entry_event, point, source_operand.load_offset,
                source_operand.load_subindex, read_instances[index], event_reference,
                source_operand.source, claim,
            ))

        result = attempt.monitor_return_result
        result_id = f"identity-result:{self.namespace}:{call_sequence}"
        result_observation_id = f"identity-value-observation:{self.namespace}:{call_sequence}"
        result_claim = EvidenceClaim(
            EvidenceKind.INFERRED,
            references=(attempt.operator_event_reference,
                        attempt.profile_return_reference,
                        attempt.monitor_return_reference,
                        self.source_model.source.atom_id.wire),
            scope=self.scope,
            confidence=1.0,
            assumptions=_RESULT_ASSUMPTION,
        )
        result_occurrence = IdentityResultOccurrence(
            result_id, operator_instance, return_instance, result_observation_id,
            attempt.result_observation_id, attempt.result_handle, result,
            self.source_model.return_use,
            attempt.return_event, attempt.operator_event_reference,
            attempt.profile_return_reference, attempt.monitor_return_reference,
            result_claim,
        )
        call = IdentityExecutionCall(
            call_sequence, self.process_id, attempt.thread_id,
            function_instance, tuple(read_instances), operator_instance,
            return_instance, self.source_model.function_definition,
            self.source_model.identity_operation, self.source_model.return_use.operation,
            self.source_model.opcode.value, self._code_id, self._source_fingerprint,
            attempt.entry_event, attempt.monitor_start_event, attempt.operator_event,
            attempt.return_instruction_event, attempt.return_event,
            self._operator_instruction.offset, self._return_instruction.offset,
            tuple(operands), result_occurrence,
            attempt.profile_call_reference, attempt.monitor_start_reference,
            tuple(event.event_id for event in finalized
                  if event.kind is IdentityRuntimeEventKind.MONITOR_INSTRUCTION),
            attempt.profile_return_reference, attempt.monitor_return_reference,
        )

        original_evidence = deepcopy(self.bundle.evidence)
        try:
            self._project_call(call, by_ref, attempt)
        except Exception as error:
            self.bundle.evidence = original_evidence
            self._last_rejection = (
                f"could not project captured call into EEG: {type(error).__name__}: {error}")
            return
        if not self.bundle.validate()["valid"]:
            self.bundle.evidence = original_evidence
            self._last_rejection = "projected EEG/ValueGraph bundle failed validation"
            return
        self._events.extend(finalized)
        self._calls.append(call)
        self._private_events.append(finalized)
        self._private_calls.append(call)
        self._private_bundle_digests.append(self._digest_bundle())
        self._private_object_digests.append(self._digest_object_model())

    def _project_call(self, call, by_ref, attempt):
        evidence = self.bundle.evidence
        all_instances = [
            OperationInstance(call.function_instance, call.function_definition,
                call.process_id, call.thread_id, control_scope=self.scope,
                status=EvidenceStatus.OBSERVED,
                metadata={"identity_capture_sequence": call.sequence}),
            *(OperationInstance(instance, operand.read_operation,
                call.process_id, call.thread_id, parent=call.function_instance,
                control_scope=self.scope, status=EvidenceStatus.OBSERVED,
                metadata={"identity_operand_index": operand.index,
                          "runtime_event": operand.runtime_event_reference})
              for instance, operand in zip(call.read_instances, call.operands)),
            OperationInstance(call.operator_instance, call.identity_operation,
                call.process_id, call.thread_id, parent=call.function_instance,
                control_scope=self.scope, status=EvidenceStatus.OBSERVED,
                metadata={"runtime_event": call.result_occurrence.operator_event_reference}),
            OperationInstance(call.return_instance, call.return_operation,
                call.process_id, call.thread_id, parent=call.function_instance,
                control_scope=self.scope, status=EvidenceStatus.OBSERVED,
                metadata={"runtime_event": call.instruction_references[-1]}),
        ]
        for instance in all_instances:
            evidence.add_instance(instance)

        source_inputs: dict[str, str] = {}
        for operand in call.operands:
            if operand.parameter_name in source_inputs:
                continue
            input_id = f"identity-input:{self.namespace}:{call.sequence}:{operand.parameter_name}"
            source_inputs[operand.parameter_name] = input_id
            evidence.add_observation(ValueObservation(
                input_id, operand.handle.version,
                operation=call.function_instance,
                materialization=operand.handle.materialization,
                role=f"parameter:{operand.parameter_name}",
                status=EvidenceStatus.OBSERVED,
                metadata={"reference_observation": operand.entry_observation_id,
                          "event": _event_as_dict(operand.entry_event)},
            ))
        for operand in call.operands:
            observation_id = source_inputs[operand.parameter_name]
            edge_claim = EvidenceClaim(
                EvidenceKind.INFERRED,
                references=(operand.entry_observation_id,
                            operand.runtime_event_reference,
                            operand.source.atom_id.wire),
                scope=self.scope,
                confidence=1.0,
                assumptions=_OPERAND_ASSUMPTION,
            )
            evidence.add_edge(EvidenceEdge(
                self._edge_id(call.sequence, f"read:{operand.index}"),
                EvidenceRelation.OBSERVED_READ,
                EvidenceEndpoint(EvidenceNodeKind.OPERATION_INSTANCE, operand.read_instance),
                EvidenceEndpoint(EvidenceNodeKind.VALUE_OBSERVATION, observation_id),
                edge_claim,
            ))

        result = call.result_occurrence
        result_obs = self.object_observer.model.observations
        result_reference = next(item for item in reversed(result_obs)
                                if item.observation_id == result.reference_observation_id)
        evidence.add_observation(ValueObservation(
            result.observation_id,
            result.handle.version,
            operation=call.operator_instance,
            materialization=result.handle.materialization,
            role=f"identity-result:{result.result_id}",
            status=EvidenceStatus.OBSERVED,
            metadata={"result_occurrence": result.result_id,
                      "reference_observation": result_reference.observation_id,
                      "event": _event_as_dict(result.observed_at),
                      "producer_to_return_mapping": "Inferred"},
        ))
        evidence.add_edge(EvidenceEdge(
            self._edge_id(call.sequence, "produces-result"), EvidenceRelation.PRODUCES,
            EvidenceEndpoint(EvidenceNodeKind.OPERATION_INSTANCE, call.operator_instance),
            EvidenceEndpoint(EvidenceNodeKind.VALUE_OBSERVATION, result.observation_id),
            result.evidence,
        ))
        evidence.add_edge(EvidenceEdge(
            self._edge_id(call.sequence, "return-reads-result"), EvidenceRelation.OBSERVED_READ,
            EvidenceEndpoint(EvidenceNodeKind.OPERATION_INSTANCE, call.return_instance),
            EvidenceEndpoint(EvidenceNodeKind.VALUE_OBSERVATION, result.observation_id),
            result.evidence,
        ))

    def _call_events_match(self, call, raw_events) -> bool:
        expected = [call.profile_call_reference, call.monitor_start_reference,
                    *call.instruction_references, call.profile_return_reference,
                    call.monitor_return_reference]
        if tuple(event.event_id for event in raw_events) != tuple(expected):
            return False
        public_by_id = {event.event_id: event for event in self._events}
        return all(public_by_id.get(event.event_id) == event for event in raw_events)

    def _digest_bundle(self) -> str:
        payload = canonical_json(self.bundle)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _digest_object_model(self) -> str:
        payload = canonical_json(self.object_observer.model)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _instance_id(self, sequence: int, label: str) -> OperationInstanceID:
        return OperationInstanceID(f"{self.namespace}:call:{sequence}:{label}")

    def _edge_id(self, sequence: int, label: str) -> str:
        return f"identity-edge:{self.namespace}:{sequence}:{label}"

def _event_as_dict(event: EventPoint) -> dict[str, Any]:
    return {"scope": event.scope, "ordinal": event.ordinal, "label": event.label}


__all__ = ["IdentityExecutionObserver"]
