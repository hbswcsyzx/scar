"""Scoped source-to-core production associations.

These records name existing evidence endpoints, execution effects and content
selectors.  They do not create producers, prove capture completeness, or grant
runtime/readiness authority; cross-record resolution belongs to validators.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias
import re

from scar.ir.program.providers import ProviderArtifact
from scar.ir.v2.evidence import EvidenceEndpoint, EvidenceNodeKind
from scar.ir.v2.ids import (
    LogicalValueID,
    MaterializationID,
    MeasurementID,
    ObjectID,
    OperationInstanceID,
    ResourceID,
    StorageAllocationID,
    StorageRegionID,
    ValueVersionID,
)

from .common import EvidencePoint, FactSource, MissingEvidence, Unresolved
from .content import (
    EndpointContent,
    NativeOutputRef,
    ProtocolSelector,
    StorageContent,
    VersionRef,
    ObjectRef,
)
from .coordinates import AccessRef, OperationOccurrenceID, ValueOccurrenceID
from .coverage import RegionRef
from .ids import (
    EvidenceInventoryID,
    OutcomeProductionID,
    RunID,
    SourceBridgeID,
    WorkOutcomeID,
    WriteAssociationID,
    WorkTicketID,
)
from .resources import AllocationTarget, _exact, _id, _record, _source, _variant
from .work import InvokeBoundaryStateEffect, MaterializationRef


def _text(value: object, name: str) -> None:
    _exact(value, str, name)
    if not value:
        raise ValueError(f"{name} must be nonempty")


def _index(value: object, name: str, *, minimum: int = 0) -> None:
    _exact(value, int, name)
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")


def _sha256(value: object, name: str) -> None:
    _exact(value, str, name)
    if re.fullmatch(r"[0-9a-fA-F]{64}", value) is None:
        raise ValueError(f"{name} must be 64 hexadecimal characters")


@dataclass(frozen=True, slots=True)
class EvidenceInventoryBinding:
    id: EvidenceInventoryID
    run: RunID
    manifest: ProviderArtifact
    index: ProviderArtifact
    source: FactSource

    def __post_init__(self) -> None:
        _id(self.id, EvidenceInventoryID, "evidence inventory ID")
        _id(self.run, RunID, "evidence inventory run")
        _record(self.manifest, ProviderArtifact, "evidence inventory manifest")
        _record(self.index, ProviderArtifact, "evidence inventory index")
        _source(self.source, "evidence inventory source")


@dataclass(frozen=True, slots=True)
class InventorySourceRef:
    inventory: EvidenceInventoryID
    stream: str

    def __post_init__(self) -> None:
        _id(self.inventory, EvidenceInventoryID, "inventory source ID")
        _text(self.stream, "inventory source stream")


@dataclass(frozen=True, slots=True)
class SourceEndpointRef:
    source: InventorySourceRef
    endpoint: EvidenceEndpoint

    def __post_init__(self) -> None:
        _record(self.source, InventorySourceRef, "source endpoint inventory")
        _record(self.endpoint, EvidenceEndpoint, "source evidence endpoint")
        _exact(self.endpoint.kind, EvidenceNodeKind, "source evidence endpoint kind")
        _validate_evidence_reference(self.endpoint.kind, self.endpoint.reference)


@dataclass(frozen=True, slots=True)
class SourceEdgeRef:
    source: InventorySourceRef
    edge: str

    def __post_init__(self) -> None:
        _record(self.source, InventorySourceRef, "source edge inventory")
        _text(self.edge, "source evidence edge ID")


@dataclass(frozen=True, slots=True)
class RawRecordRef:
    source: InventorySourceRef
    line: int
    sha256: str

    def __post_init__(self) -> None:
        _record(self.source, InventorySourceRef, "raw-record inventory")
        _index(self.line, "raw-record line", minimum=1)
        _sha256(self.sha256, "raw-record SHA256")


def _validate_value_version(value: object, name: str) -> None:
    _exact(value, ValueVersionID, name)
    _id(value.logical_value, LogicalValueID, name + " logical value")
    _exact(value.version, int, name + " revision")
    if value.version < 0:
        raise ValueError(name + " revision must be nonnegative")


def _validate_evidence_reference(kind: EvidenceNodeKind, reference: object) -> None:
    """Strictly recheck the nested endpoint; EvidenceEndpoint uses isinstance."""
    if kind is EvidenceNodeKind.PROVIDER_REFERENCE:
        raise ValueError("provider reference tokens do not establish a source content endpoint")
    expected = {
        EvidenceNodeKind.OPERATION_INSTANCE: OperationInstanceID,
        EvidenceNodeKind.VALUE_OBSERVATION: str,
        EvidenceNodeKind.VALUE_VERSION: ValueVersionID,
        EvidenceNodeKind.MATERIALIZATION: MaterializationID,
        EvidenceNodeKind.OBJECT: ObjectID,
        EvidenceNodeKind.ALLOCATION: StorageAllocationID,
        EvidenceNodeKind.STORAGE_REGION: StorageRegionID,
        EvidenceNodeKind.RESOURCE: ResourceID,
        EvidenceNodeKind.MEASUREMENT: MeasurementID,
        EvidenceNodeKind.CONTROL_EVENT: str,
    }[kind]
    _exact(reference, expected, "source evidence endpoint reference")
    if expected is ValueVersionID:
        _validate_value_version(reference, "source value-version endpoint")
    elif expected is str:
        _text(reference, "source evidence string endpoint")
    else:
        _id(reference, expected, "source evidence typed endpoint")


SourceEndpointTarget: TypeAlias = VersionRef | MaterializationRef | ObjectRef | RegionRef | AllocationTarget


@dataclass(frozen=True, slots=True)
class SourceEndpointBridge:
    id: SourceBridgeID
    endpoint: SourceEndpointRef
    target: SourceEndpointTarget
    source: FactSource

    def __post_init__(self) -> None:
        _id(self.id, SourceBridgeID, "source bridge ID")
        _record(self.endpoint, SourceEndpointRef, "source bridge endpoint")
        _variant(self.target, (VersionRef, MaterializationRef, ObjectRef, RegionRef,
                               AllocationTarget), "source bridge target")
        _source(self.source, "source bridge source")


@dataclass(frozen=True, slots=True)
class WorkWrite:
    ticket: WorkTicketID

    def __post_init__(self) -> None:
        _id(self.ticket, WorkTicketID, "work-write ticket")


@dataclass(frozen=True, slots=True)
class HostWrite:
    operation: OperationOccurrenceID

    def __post_init__(self) -> None:
        _id(self.operation, OperationOccurrenceID, "host-write occurrence")


@dataclass(frozen=True, slots=True)
class ExternalEstablishment:
    point: EvidencePoint

    def __post_init__(self) -> None:
        _record(self.point, EvidencePoint, "external-establishment point")


@dataclass(frozen=True, slots=True)
class ValueProduction:
    value: ValueOccurrenceID

    def __post_init__(self) -> None:
        _id(self.value, ValueOccurrenceID, "value-production occurrence")


@dataclass(frozen=True, slots=True)
class StateProduction:
    effect: AccessRef | InvokeBoundaryStateEffect

    def __post_init__(self) -> None:
        _variant(self.effect, (AccessRef, InvokeBoundaryStateEffect), "state-production effect")


WriteActor: TypeAlias = WorkWrite | HostWrite | ExternalEstablishment | Unresolved
ProductionTarget: TypeAlias = ValueProduction | StateProduction | Unresolved
WritePlacement: TypeAlias = StorageContent | EndpointContent | Unresolved
WriteStage: TypeAlias = RawRecordRef | SourceEdgeRef | NativeOutputRef | Unresolved


@dataclass(frozen=True, slots=True)
class BytePrefixWrite:
    """Fixed selector profile for a byte-prefix write declaration."""

    def __post_init__(self) -> None:
        return None


@dataclass(frozen=True, slots=True)
class WriteAssociation:
    id: WriteAssociationID
    stage: WriteStage
    writer: WriteActor
    production: ProductionTarget
    placement: WritePlacement
    evidence: tuple[SourceEdgeRef, ...]
    source: FactSource

    def __post_init__(self) -> None:
        _id(self.id, WriteAssociationID, "write association ID")
        _variant(self.stage, (RawRecordRef, SourceEdgeRef, NativeOutputRef, Unresolved),
                 "write-association stage")
        _variant(self.writer, (WorkWrite, HostWrite, ExternalEstablishment, Unresolved),
                 "write-association writer")
        _variant(self.production, (ValueProduction, StateProduction, Unresolved),
                 "write-association production")
        _variant(self.placement, (StorageContent, EndpointContent, Unresolved),
                 "write-association placement")
        _exact(self.evidence, tuple, "write-association evidence")
        for edge in self.evidence:
            _record(edge, SourceEdgeRef, "write-association evidence edge")
        if len(self.evidence) != len(set(self.evidence)):
            raise ValueError("write-association evidence edges must be unique")
        _source(self.source, "write-association source")


@dataclass(frozen=True, slots=True)
class OutcomeProduction:
    id: OutcomeProductionID
    write: WriteAssociationID
    outcome: WorkOutcomeID
    frontier: int | Unresolved | None
    actual: RegionRef | ProtocolSelector | Unresolved
    rule: BytePrefixWrite | Unresolved
    source: FactSource

    def __post_init__(self) -> None:
        _id(self.id, OutcomeProductionID, "outcome production ID")
        _id(self.write, WriteAssociationID, "outcome-production write association")
        _id(self.outcome, WorkOutcomeID, "outcome-production work outcome")
        if type(self.frontier) is int:
            _index(self.frontier, "outcome effect frontier")
        elif type(self.frontier) is Unresolved:
            _record(self.frontier, Unresolved, "outcome effect frontier")
        elif self.frontier is not None:
            raise TypeError("outcome effect frontier must be int, Unresolved, or None")
        _variant(self.actual, (RegionRef, ProtocolSelector, Unresolved),
                 "outcome-production actual selector")
        _variant(self.rule, (BytePrefixWrite, Unresolved), "outcome-production write rule")
        _source(self.source, "outcome-production source")


__all__ = [
    "BytePrefixWrite", "EvidenceInventoryBinding", "ExternalEstablishment",
    "HostWrite", "InventorySourceRef", "OutcomeProduction", "RawRecordRef",
    "SourceEdgeRef", "SourceEndpointBridge", "SourceEndpointRef",
    "SourceEndpointTarget", "StateProduction", "ValueProduction", "WorkWrite",
    "WriteActor", "WriteAssociation", "WritePlacement", "WriteStage",
    "ProductionTarget",
]
