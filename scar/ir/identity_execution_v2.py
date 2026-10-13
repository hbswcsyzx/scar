"""Small typed records for one captured identity-comparison execution.

The records keep raw profile/monitoring events separate from the static
source-to-bytecode mapping.  They are historical evidence only; live capture
authority belongs to :mod:`scar.trace.identity_v2`.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from typing import Any

from scar.analysis.identity_source_v2 import ReturnValueUse
from scar.ir.provenance import EventPoint
from scar.ir.record_codec import decode, encode, loads
from scar.ir.v2 import (
    BindingUseID, EvidenceClaim, OperationDefinitionID, OperationInstanceID,
    StaticValueID, ValueSlotID,
)
from scar.ir.v2.common import SourceReference
from scar.ir.python_objects_v2 import PythonObjectHandle


class IdentityRuntimeEventKind(str, Enum):
    MONITOR_START = "MONITOR_START"
    MONITOR_INSTRUCTION = "MONITOR_INSTRUCTION"
    MONITOR_RETURN = "MONITOR_RETURN"


class PythonBoolSingleton(str, Enum):
    TRUE = "TRUE"
    FALSE = "FALSE"

    @classmethod
    def from_actual(cls, value: Any) -> "PythonBoolSingleton":
        if type(value) is not bool:
            raise TypeError("captured identity result must be an exact Python bool")
        return cls.TRUE if value else cls.FALSE

    @property
    def as_bool(self) -> bool:
        return self is PythonBoolSingleton.TRUE


@dataclass(frozen=True, slots=True)
class IdentityRuntimeEvent:
    """An actual callback sample; opcode meaning is joined separately."""

    event_id: str
    kind: IdentityRuntimeEventKind
    sequence: int
    process_id: int
    thread_id: int
    code_id: str
    raw_reference: str
    offset: int | None = None
    bool_result: PythonBoolSingleton | None = None

    def __post_init__(self) -> None:
        if not self.event_id or not self.code_id or not self.raw_reference:
            raise ValueError("runtime event requires event, code, and raw references")
        if not isinstance(self.kind, IdentityRuntimeEventKind):
            raise TypeError("runtime event kind must be IdentityRuntimeEventKind")
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("runtime event sequence must be non-negative")
        if type(self.process_id) is not int or self.process_id < 0:
            raise ValueError("runtime event process ID must be non-negative")
        if type(self.thread_id) is not int or self.thread_id < 0:
            raise ValueError("runtime event thread ID must be non-negative")
        monitor_event = self.kind in {
            IdentityRuntimeEventKind.MONITOR_START,
            IdentityRuntimeEventKind.MONITOR_INSTRUCTION,
            IdentityRuntimeEventKind.MONITOR_RETURN,
        }
        if monitor_event != (type(self.offset) is int and self.offset >= 0):
            raise ValueError("monitoring events require an instruction offset")
        return_event = self.kind is IdentityRuntimeEventKind.MONITOR_RETURN
        if return_event != isinstance(self.bool_result, PythonBoolSingleton):
            raise ValueError("only successful return events carry an exact bool result")


@dataclass(frozen=True, slots=True)
class IdentityOperandOccurrence:
    """One ordered source READ, including repeated reads of the same name."""

    index: int
    role: str
    read_operation: OperationDefinitionID
    binding_use: BindingUseID
    slot: ValueSlotID
    read_output_slot: ValueSlotID
    static_value: StaticValueID
    parameter_name: str
    handle: PythonObjectHandle
    entry_observation_id: str
    entry_event: EventPoint
    read_event: EventPoint
    load_offset: int
    load_subindex: int
    read_instance: OperationInstanceID
    runtime_event_reference: str
    source: SourceReference
    evidence: EvidenceClaim

    def __post_init__(self) -> None:
        if type(self.index) is not int or self.index not in (0, 1):
            raise ValueError("operand occurrence index must be 0 or 1")
        if self.role != ("left" if self.index == 0 else "right"):
            raise ValueError("operand occurrence role/index mismatch")
        if not self.parameter_name or not self.entry_observation_id:
            raise ValueError("operand occurrence requires its parameter binding sample")
        if not all(isinstance(value, expected) for value, expected in (
            (self.read_operation, OperationDefinitionID),
            (self.binding_use, BindingUseID), (self.slot, ValueSlotID),
            (self.read_output_slot, ValueSlotID),
            (self.static_value, StaticValueID), (self.handle, PythonObjectHandle),
            (self.entry_event, EventPoint), (self.read_event, EventPoint),
            (self.read_instance, OperationInstanceID),
            (self.source, SourceReference), (self.evidence, EvidenceClaim),
        )):
            raise TypeError("operand occurrence contains an incorrectly typed field")
        if type(self.load_offset) is not int or self.load_offset < 0:
            raise ValueError("operand load offset must be non-negative")
        if type(self.load_subindex) is not int or self.load_subindex not in (0, 1):
            raise ValueError("operand load subindex must be 0 or 1")
        if not self.runtime_event_reference:
            raise ValueError("operand occurrence requires a raw instruction reference")


@dataclass(frozen=True, slots=True)
class IdentityResultOccurrence:
    """One producer-to-Return use, distinct even for shared bool singletons."""

    result_id: str
    producer_instance: OperationInstanceID
    consumer_instance: OperationInstanceID
    observation_id: str
    reference_observation_id: str
    handle: PythonObjectHandle
    result: PythonBoolSingleton
    return_use: ReturnValueUse
    observed_at: EventPoint
    operator_event_reference: str
    profile_return_reference: str
    monitor_return_reference: str
    evidence: EvidenceClaim

    def __post_init__(self) -> None:
        if not self.result_id or not self.observation_id or not self.reference_observation_id:
            raise ValueError("result occurrence needs unique result and observation IDs")
        if not all(isinstance(value, expected) for value, expected in (
            (self.producer_instance, OperationInstanceID),
            (self.consumer_instance, OperationInstanceID),
            (self.handle, PythonObjectHandle),
            (self.result, PythonBoolSingleton), (self.return_use, ReturnValueUse),
            (self.observed_at, EventPoint), (self.evidence, EvidenceClaim),
        )):
            raise TypeError("result occurrence contains an incorrectly typed field")
        if not all((self.operator_event_reference, self.profile_return_reference,
                    self.monitor_return_reference)):
            raise ValueError("result occurrence requires observed operator and return events")


@dataclass(frozen=True, slots=True)
class IdentityExecutionCall:
    """A complete successful call of the exact source-backed function."""

    sequence: int
    process_id: int
    thread_id: int
    function_instance: OperationInstanceID
    read_instances: tuple[OperationInstanceID, OperationInstanceID]
    operator_instance: OperationInstanceID
    return_instance: OperationInstanceID
    function_definition: OperationDefinitionID
    identity_operation: OperationDefinitionID
    return_operation: OperationDefinitionID
    opcode: str
    code_id: str
    source_fingerprint: str
    call_entry: EventPoint
    monitor_start_event: EventPoint
    operator_event: EventPoint
    return_instruction_event: EventPoint
    return_event: EventPoint
    operator_offset: int
    return_offset: int
    operands: tuple[IdentityOperandOccurrence, IdentityOperandOccurrence]
    result_occurrence: IdentityResultOccurrence
    profile_call_reference: str
    monitor_start_reference: str
    instruction_references: tuple[str, ...]
    monitor_return_reference: str

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("call sequence must be non-negative")
        if type(self.process_id) is not int or self.process_id < 0:
            raise ValueError("call process ID must be non-negative")
        if type(self.thread_id) is not int or self.thread_id < 0:
            raise ValueError("call thread ID must be non-negative")
        for value, expected in (
            (self.function_instance, OperationInstanceID),
            (self.operator_instance, OperationInstanceID),
            (self.return_instance, OperationInstanceID),
            (self.function_definition, OperationDefinitionID),
            (self.identity_operation, OperationDefinitionID),
            (self.return_operation, OperationDefinitionID),
        ):
            if not isinstance(value, expected):
                raise TypeError(f"call field must be {expected.__name__}")
        if (type(self.read_instances) is not tuple or len(self.read_instances) != 2
                or any(not isinstance(item, OperationInstanceID) for item in self.read_instances)):
            raise TypeError("call requires two ordered READ instances")
        if (type(self.operands) is not tuple or len(self.operands) != 2
                or tuple(item.index for item in self.operands) != (0, 1)):
            raise ValueError("call must retain both ordered operand occurrences")
        if self.opcode not in {"is", "is_not"}:
            raise ValueError("call opcode must be is or is_not")
        if not self.code_id or not self.source_fingerprint:
            raise ValueError("call requires source and code witnesses")
        if type(self.operator_offset) is not int or self.operator_offset < 0:
            raise ValueError("operator offset must be non-negative")
        if type(self.return_offset) is not int or self.return_offset < 0:
            raise ValueError("return offset must be non-negative")
        if not all(isinstance(value, EventPoint) for value in (
            self.call_entry, self.monitor_start_event, self.operator_event,
            self.return_instruction_event, self.return_event)):
            raise TypeError("call event bounds must use EventPoint")
        points = (self.call_entry, self.monitor_start_event,
                  *(item.read_event for item in self.operands), self.operator_event,
                  self.return_instruction_event, self.return_event)
        if len({item.scope for item in points}) != 1:
            raise ValueError("call event points must share one collector scope")
        if tuple(item.ordinal for item in points) != tuple(sorted(item.ordinal for item in points)):
            raise ValueError("operand/operator/return event points must be ordered")
        if any(item.entry_event != self.call_entry for item in self.operands):
            raise ValueError("operand bindings must be sampled at this invocation entry")
        if any(item.read_event.scope != self.call_entry.scope for item in self.operands):
            raise ValueError("operand READ event belongs to another capture scope")
        if self.result_occurrence.producer_instance != self.operator_instance:
            raise ValueError("result occurrence producer differs from this call")
        if self.result_occurrence.consumer_instance != self.return_instance:
            raise ValueError("result occurrence Return consumer differs from this call")
        if self.result_occurrence.return_use.operation != self.return_operation:
            raise ValueError("result occurrence source Return differs from this call")
        if self.result_occurrence.observed_at != self.return_event:
            raise ValueError("result occurrence is not observed at this call's Return event")
        references = (self.profile_call_reference, self.monitor_start_reference,
                      *self.instruction_references, self.profile_return_reference,
                      self.monitor_return_reference)
        if any(type(value) is not str or not value for value in references):
            raise ValueError("call requires complete raw event references")


@dataclass(frozen=True, slots=True)
class IdentityExecutionSnapshot:
    """Portable historical evidence; decoding creates no live authority."""

    scope: str
    namespace: str
    process_id: int
    runtime_implementation: str
    runtime_version: tuple[int, int, int]
    code_id: str
    source_fingerprint: str
    function_definition: OperationDefinitionID
    identity_operation: OperationDefinitionID
    return_operation: OperationDefinitionID
    calls: tuple[IdentityExecutionCall, ...]
    events: tuple[IdentityRuntimeEvent, ...]

    SCHEMA = "scar.identity-execution.v2"
    SCHEMA_VERSION = 2

    def __post_init__(self) -> None:
        if not all((self.scope, self.namespace, self.runtime_implementation,
                    self.code_id, self.source_fingerprint)):
            raise ValueError("snapshot requires capture, runtime, source, and code context")
        if type(self.process_id) is not int or self.process_id < 0:
            raise ValueError("snapshot process ID must be non-negative")
        if (type(self.runtime_version) is not tuple or len(self.runtime_version) != 3
                or any(type(item) is not int or item < 0 for item in self.runtime_version)):
            raise ValueError("snapshot runtime version must contain three non-negative integers")
        if any(not isinstance(item, OperationDefinitionID) for item in (
            self.function_definition, self.identity_operation, self.return_operation)):
            raise TypeError("snapshot source IDs must be OperationDefinitionID")
        if type(self.calls) is not tuple or any(
            not isinstance(item, IdentityExecutionCall) for item in self.calls
        ):
            raise TypeError("snapshot calls must be IdentityExecutionCall records")
        if type(self.events) is not tuple or any(
            not isinstance(item, IdentityRuntimeEvent) for item in self.events
        ):
            raise TypeError("snapshot events must be IdentityRuntimeEvent records")

    def validate_structure(self) -> dict[str, Any]:
        errors: list[str] = []
        if tuple(item.sequence for item in self.calls) != tuple(range(len(self.calls))):
            errors.append("call sequence is not contiguous")
        if tuple(item.sequence for item in self.events) != tuple(range(len(self.events))):
            errors.append("runtime event sequence is not contiguous")
        event_ids = [item.event_id for item in self.events]
        if len(set(event_ids)) != len(event_ids):
            errors.append("runtime event IDs are not unique")
        by_id = {item.event_id: item for item in self.events}
        if any(item.process_id != self.process_id for item in self.events):
            errors.append("runtime event crosses process boundary")
        for call in self.calls:
            if (call.process_id != self.process_id
                    or call.code_id != self.code_id
                    or call.source_fingerprint != self.source_fingerprint
                    or call.function_definition != self.function_definition
                    or call.identity_operation != self.identity_operation
                    or call.return_operation != self.return_operation):
                errors.append(f"call {call.sequence} differs from snapshot context")
                continue
            references = (
                (call.profile_call_reference, IdentityRuntimeEventKind.PROFILE_CALL),
                (call.monitor_start_reference, IdentityRuntimeEventKind.MONITOR_START),
                *((ref, IdentityRuntimeEventKind.MONITOR_INSTRUCTION)
                  for ref in call.instruction_references),
                (call.profile_return_reference, IdentityRuntimeEventKind.PROFILE_RETURN),
                (call.monitor_return_reference, IdentityRuntimeEventKind.MONITOR_RETURN),
            )
            matched = []
            for reference, kind in references:
                event = by_id.get(reference)
                if event is None:
                    errors.append(f"call {call.sequence} references missing event {reference}")
                elif (event.kind is not kind or event.process_id != call.process_id
                      or event.thread_id != call.thread_id or event.code_id != call.code_id):
                    errors.append(f"call {call.sequence} has a mismatched event {reference}")
                else:
                    matched.append(event.sequence)
            if matched and matched != sorted(matched):
                errors.append(f"call {call.sequence} event references are out of order")
            if len(matched) != len(set(matched)):
                errors.append(f"call {call.sequence} repeats a runtime event reference")
            if tuple(item.read_instance for item in call.operands) != call.read_instances:
                errors.append(f"call {call.sequence} READ occurrences differ from EEG instances")
            for operand in call.operands:
                event = by_id.get(operand.runtime_event_reference)
                if (event is None or event.kind is not IdentityRuntimeEventKind.MONITOR_INSTRUCTION
                        or event.offset != operand.load_offset
                        or event.thread_id != call.thread_id):
                    errors.append(f"call {call.sequence} operand {operand.index} has no exact load event")
                if operand.entry_event.scope != self.scope or operand.read_event.scope != self.scope:
                    errors.append(f"call {call.sequence} operand uses another event scope")
            operator_event = by_id.get(call.result_occurrence.operator_event_reference)
            result_profile = by_id.get(call.result_occurrence.profile_return_reference)
            result_monitor = by_id.get(call.result_occurrence.monitor_return_reference)
            if (operator_event is None or operator_event.offset != call.operator_offset
                    or operator_event.kind is not IdentityRuntimeEventKind.MONITOR_INSTRUCTION):
                errors.append(f"call {call.sequence} result has no exact IS_OP instruction event")
            if (result_profile is None or result_profile.bool_result is not call.result_occurrence.result):
                errors.append(f"call {call.sequence} result disagrees with profile return")
            if (result_monitor is None or result_monitor.bool_result is not call.result_occurrence.result
                    or result_monitor.offset != call.return_offset):
                errors.append(f"call {call.sequence} result disagrees with monitor return")
        accepted_refs = {
            reference
            for call in self.calls
            for reference in (
                call.profile_call_reference, call.monitor_start_reference,
                *call.instruction_references, call.profile_return_reference,
                call.monitor_return_reference,
            )
        }
        if accepted_refs != set(event_ids):
            errors.append("runtime event table contains unreferenced or missing events")
        return {"valid": not errors, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {"schema": self.SCHEMA, "schema_version": self.SCHEMA_VERSION,
                **encode(self)}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False)

    @classmethod
    def from_dict(cls, document: dict[str, Any]) -> "IdentityExecutionSnapshot":
        if (type(document) is not dict or document.get("schema") != cls.SCHEMA
                or type(document.get("schema_version")) is not int
                or document.get("schema_version") != cls.SCHEMA_VERSION):
            raise ValueError("unsupported identity execution snapshot schema")
        payload = {key: value for key, value in document.items()
                   if key not in {"schema", "schema_version"}}
        result = decode(cls, payload)
        if result.to_dict() != document:
            raise ValueError("identity execution snapshot is not canonical")
        report = result.validate_structure()
        if not report["valid"]:
            raise ValueError("invalid identity execution snapshot: " + "; ".join(report["errors"]))
        return result

    @classmethod
    def from_json(cls, payload: str) -> "IdentityExecutionSnapshot":
        return cls.from_dict(loads(payload))


__all__ = [
    "IdentityExecutionCall", "IdentityExecutionSnapshot", "IdentityOperandOccurrence",
    "IdentityResultOccurrence", "IdentityRuntimeEvent", "IdentityRuntimeEventKind",
    "PythonBoolSingleton",
]
