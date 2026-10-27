"""Canonical coordinates connecting runtime occurrences to the static graph.

The records here carry exact typed IDs only. Static producer, use, state, and
successor facts remain in their canonical graph and are not duplicated.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

from scar.ir.program.ids import BlockID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from .common import EvidencePoint, FactSource, MissingEvidence, Unresolved
from .ids import (
    BlockVisitID,
    ExecutionSegmentID,
    HostThreadInstanceID,
    OperationOccurrenceID,
    ProcessInstanceID,
    RegionActivationID,
    RunID,
    ValueOccurrenceID,
)


def _exact(value, expected, name):
    if type(value) is not expected:
        raise TypeError(f"{name} must be {expected.__name__}")


def _integer(value, name, *, minimum=0):
    _exact(value, int, name)
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")


def _identifier(value, expected, name):
    _exact(value, expected, name)
    value.__post_init__()
    if type(value.value) is not str or not value.value:
        raise ValueError(f"{name} must contain a nonempty exact string")


def _record(value, expected, name):
    _exact(value, expected, name)
    value.__post_init__()


def _nested_id(value, expected, name):
    _identifier(value, expected, name)


@dataclass(frozen=True, slots=True)
class ProgramSnapshot:
    artifact: ProviderArtifact
    schema_version: int

    def __post_init__(self):
        _record(self.artifact, ProviderArtifact, "program snapshot artifact")
        _integer(self.schema_version, "program snapshot schema version", minimum=1)


@dataclass(frozen=True, slots=True)
class ExecutionRun:
    id: RunID
    source: FactSource

    def __post_init__(self):
        _nested_id(self.id, RunID, "execution run ID")
        _fact_source(self.source, "execution run source")


@dataclass(frozen=True, slots=True)
class ProcessInstance:
    id: ProcessInstanceID
    run: RunID
    pid: int | None
    source: FactSource

    def __post_init__(self):
        _nested_id(self.id, ProcessInstanceID, "process-instance ID")
        _nested_id(self.run, RunID, "process-instance run")
        if self.pid is not None:
            _integer(self.pid, "process ID")
        _fact_source(self.source, "process-instance source")


@dataclass(frozen=True, slots=True)
class HostThreadInstance:
    id: HostThreadInstanceID
    process: ProcessInstanceID
    tid: int | None
    source: FactSource

    def __post_init__(self):
        _nested_id(self.id, HostThreadInstanceID, "host-thread-instance ID")
        _nested_id(self.process, ProcessInstanceID, "host-thread process")
        if self.tid is not None:
            _integer(self.tid, "thread ID")
        _fact_source(self.source, "host-thread source")


def _fact_source(value, name):
    if type(value) is ProviderFactReference:
        _record(value, ProviderFactReference, name)
    elif type(value) is MissingEvidence:
        _record(value, MissingEvidence, name)
    else:
        raise TypeError(f"{name} must be ProviderFactReference or MissingEvidence")


@dataclass(frozen=True, slots=True)
class RegionActivation:
    id: RegionActivationID
    region: RegionID
    process: ProcessInstanceID
    entry: EvidencePoint

    def __post_init__(self):
        _nested_id(self.id, RegionActivationID, "region-activation ID")
        _nested_id(self.region, RegionID, "region-activation region")
        _nested_id(self.process, ProcessInstanceID, "region-activation process")
        _record(self.entry, EvidencePoint, "region-activation entry")


@dataclass(frozen=True, slots=True)
class InitialEntry:
    source: EvidencePoint

    def __post_init__(self):
        _record(self.source, EvidencePoint, "initial-entry source")


@dataclass(frozen=True, slots=True)
class ResumeIngress:
    suspension: OperationOccurrenceID
    successor_index: int
    source: EvidencePoint

    def __post_init__(self):
        _nested_id(self.suspension, OperationOccurrenceID, "resume suspension occurrence")
        _integer(self.successor_index, "resume successor index")
        _record(self.source, EvidencePoint, "resume-ingress source")


@dataclass(frozen=True, slots=True)
class CaptureIngress:
    source: EvidencePoint
    reason: str

    def __post_init__(self):
        _record(self.source, EvidencePoint, "capture-ingress source")
        _exact(self.reason, str, "capture-ingress reason")
        if not self.reason:
            raise ValueError("capture-ingress reason must be nonempty")


@dataclass(frozen=True, slots=True)
class UnresolvedHostThread:
    reason: str
    point: EvidencePoint

    def __post_init__(self):
        _exact(self.reason, str, "unresolved host-thread reason")
        if not self.reason:
            raise ValueError("unresolved host-thread reason must be nonempty")
        _record(self.point, EvidencePoint, "unresolved host-thread point")


@dataclass(frozen=True, slots=True)
class ExecutionSegment:
    id: ExecutionSegmentID
    activation: RegionActivationID
    host_thread: HostThreadInstanceID | UnresolvedHostThread
    ingress: InitialEntry | ResumeIngress | CaptureIngress

    def __post_init__(self):
        _nested_id(self.id, ExecutionSegmentID, "execution-segment ID")
        _nested_id(self.activation, RegionActivationID, "execution-segment activation")
        if type(self.host_thread) is HostThreadInstanceID:
            _nested_id(self.host_thread, HostThreadInstanceID, "execution-segment host thread")
        elif type(self.host_thread) is UnresolvedHostThread:
            _record(self.host_thread, UnresolvedHostThread, "execution-segment host thread")
        else:
            raise TypeError("execution-segment host_thread must be HostThreadInstanceID or UnresolvedHostThread")
        if type(self.ingress) in (InitialEntry, ResumeIngress, CaptureIngress):
            _record(self.ingress, type(self.ingress), "execution-segment ingress")
        else:
            raise TypeError("execution-segment ingress must be InitialEntry, ResumeIngress, or CaptureIngress")


@dataclass(frozen=True, slots=True)
class BlockVisit:
    id: BlockVisitID
    segment: ExecutionSegmentID
    block: BlockID

    def __post_init__(self):
        _nested_id(self.id, BlockVisitID, "block-visit ID")
        _nested_id(self.segment, ExecutionSegmentID, "block-visit segment")
        _nested_id(self.block, BlockID, "block-visit block")


@dataclass(frozen=True, slots=True)
class OperationOccurrence:
    id: OperationOccurrenceID
    visit: BlockVisitID
    operation: OperationID

    def __post_init__(self):
        _nested_id(self.id, OperationOccurrenceID, "operation-occurrence ID")
        _nested_id(self.visit, BlockVisitID, "operation-occurrence visit")
        _nested_id(self.operation, OperationID, "operation-occurrence operation")


@dataclass(frozen=True, slots=True)
class ValueOccurrence:
    id: ValueOccurrenceID
    value: ValueID
    origin: OperationOccurrenceID | BlockVisitID | RegionActivationID

    def __post_init__(self):
        _nested_id(self.id, ValueOccurrenceID, "value-occurrence ID")
        _nested_id(self.value, ValueID, "value-occurrence value")
        expected = (OperationOccurrenceID, BlockVisitID, RegionActivationID)
        if type(self.origin) not in expected:
            raise TypeError("value-occurrence origin must be an operation occurrence, block visit, or activation")
        self.origin.__post_init__()
        if type(self.origin.value) is not str or not self.origin.value:
            raise ValueError("value-occurrence origin ID must contain a nonempty exact string")


@dataclass(frozen=True, slots=True)
class UseOccurrence:
    operation: OperationOccurrenceID
    use: UseID
    value: ValueOccurrenceID | Unresolved

    def __post_init__(self):
        _nested_id(self.operation, OperationOccurrenceID, "use-occurrence operation")
        _nested_id(self.use, UseID, "use-occurrence static use")
        if type(self.value) is ValueOccurrenceID:
            _nested_id(self.value, ValueOccurrenceID, "use-occurrence value")
        elif type(self.value) is Unresolved:
            _record(self.value, Unresolved, "use-occurrence value")
        else:
            raise TypeError("use-occurrence value must be ValueOccurrenceID or Unresolved")


@dataclass(frozen=True, slots=True)
class ControlTransfer:
    operation: OperationOccurrenceID
    successor_index: int
    target: BlockVisitID

    def __post_init__(self):
        _nested_id(self.operation, OperationOccurrenceID, "control-transfer operation")
        _integer(self.successor_index, "control-transfer successor index")
        _nested_id(self.target, BlockVisitID, "control-transfer target")


@dataclass(frozen=True, slots=True)
class AccessRef:
    operation: OperationOccurrenceID
    index: int

    def __post_init__(self):
        _nested_id(self.operation, OperationOccurrenceID, "access reference operation")
        _integer(self.index, "access reference index")


class OccurrencePhase(str, Enum):
    BEFORE = "BEFORE"
    AFTER = "AFTER"
    EDGE = "EDGE"


@dataclass(frozen=True, slots=True)
class OccurrencePoint:
    operation: OperationOccurrenceID
    phase: OccurrencePhase
    successor_index: int | None = None

    def __post_init__(self):
        _nested_id(self.operation, OperationOccurrenceID, "occurrence-point operation")
        _exact(self.phase, OccurrencePhase, "occurrence-point phase")
        if self.phase is OccurrencePhase.EDGE:
            if self.successor_index is None:
                raise ValueError("EDGE occurrence point requires a successor index")
            _integer(self.successor_index, "occurrence-point successor index")
        elif self.successor_index is not None:
            raise ValueError("non-EDGE occurrence point must not have a successor index")


ExecutionPoint: TypeAlias = OccurrencePoint | EvidencePoint


@dataclass(frozen=True, slots=True)
class UseRef:
    operation: OperationOccurrenceID
    use: UseID

    def __post_init__(self):
        _nested_id(self.operation, OperationOccurrenceID, "use reference operation")
        _nested_id(self.use, UseID, "use reference static use")


__all__ = [
    "ProgramSnapshot", "ExecutionRun", "ProcessInstance", "HostThreadInstance",
    "RegionActivation", "InitialEntry", "ResumeIngress", "CaptureIngress",
    "UnresolvedHostThread", "ExecutionSegment", "BlockVisit", "OperationOccurrence",
    "ValueOccurrence", "UseOccurrence", "ControlTransfer", "AccessRef",
    "OccurrencePhase", "OccurrencePoint", "ExecutionPoint", "UseRef",
]
