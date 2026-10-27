"""Occurrence denotations and content-read associations.

These immutable records connect existing execution coordinates to scoped
value/evidence artifacts.  They do not create producers, uses, states,
materializations, or runtime authority; cross-record resolution belongs to
the execution validator.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from scar.ir.program.ids import NativeBoundaryID
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.v2.ids import LogicalValueID, ObjectID, OperationInstanceID, ValueVersionID

from .common import FactSource, Unresolved
from .coordinates import (
    AccessRef,
    BlockVisitID,
    ExecutionPoint,
    OccurrencePoint,
    OperationOccurrenceID,
    UseRef,
    ValueOccurrenceID,
)
from .coverage import RegionRef
from .ids import (
    ContentReadID,
    DenotationID,
    ObservationRootID,
    WorkEvidenceBindingID,
    WorkTicketID,
)
from .resources import (
    ResourceTarget,
    _exact,
    _id,
    _point,
    _record,
    _source,
    _support,
    _target,
    _variant,
)
from .work import InvokeBoundaryStateEffect, MaterializationRef


def _text(value: object, name: str) -> None:
    _exact(value, str, name)
    if not value:
        raise ValueError(f"{name} must be nonempty")


def _index(value: object, name: str) -> None:
    _exact(value, int, name)
    if value < 0:
        raise ValueError(f"{name} must be nonnegative")


@dataclass(frozen=True, slots=True)
class VersionRef:
    """A ValueVersionID scoped to the exact artifact that defines it."""

    artifact: ProviderArtifact
    version: ValueVersionID

    def __post_init__(self) -> None:
        _record(self.artifact, ProviderArtifact, "value-version artifact")
        _exact(self.version, ValueVersionID, "scoped value version")
        self.version.__post_init__()
        _exact(self.version.logical_value, LogicalValueID, "value-version logical value")
        self.version.logical_value.__post_init__()
        _exact(self.version.version, int, "value-version revision")
        if self.version.version < 0:
            raise ValueError("value-version revision must be nonnegative")


@dataclass(frozen=True, slots=True)
class ObjectRef:
    """An ObjectID scoped to the exact artifact that defines it."""

    artifact: ProviderArtifact
    object: ObjectID

    def __post_init__(self) -> None:
        _record(self.artifact, ProviderArtifact, "object artifact")
        _id(self.object, ObjectID, "scoped object ID")


@dataclass(frozen=True, slots=True)
class EvidenceEdgeRef:
    artifact: ProviderArtifact
    edge: str

    def __post_init__(self) -> None:
        _record(self.artifact, ProviderArtifact, "evidence-edge artifact")
        _text(self.edge, "evidence-edge ID")


@dataclass(frozen=True, slots=True)
class EvidenceObservationRef:
    artifact: ProviderArtifact
    observation: str

    def __post_init__(self) -> None:
        _record(self.artifact, ProviderArtifact, "evidence-observation artifact")
        _text(self.observation, "evidence-observation ID")


@dataclass(frozen=True, slots=True)
class NativeInputRef:
    """A declared native input position at one actual initial block visit."""

    boundary: NativeBoundaryID
    entry: BlockVisitID
    position: int

    def __post_init__(self) -> None:
        _id(self.boundary, NativeBoundaryID, "native input boundary")
        _id(self.entry, BlockVisitID, "native input entry visit")
        _index(self.position, "native input position")


@dataclass(frozen=True, slots=True)
class NativeOutputRef:
    """A declared native output position at one actual Return/Raise occurrence."""

    boundary: NativeBoundaryID
    operation: OperationOccurrenceID
    position: int

    def __post_init__(self) -> None:
        _id(self.boundary, NativeBoundaryID, "native output boundary")
        _id(self.operation, OperationOccurrenceID, "native output occurrence")
        _index(self.position, "native output position")


DenotationBasis: TypeAlias = (
    EvidenceEdgeRef | EvidenceObservationRef | NativeInputRef | NativeOutputRef | Unresolved
)


def _denotation_basis(value: object, name: str) -> None:
    _variant(value, (EvidenceEdgeRef, EvidenceObservationRef, NativeInputRef,
                     NativeOutputRef, Unresolved), name)


@dataclass(frozen=True, slots=True)
class DataIdentity:
    version: VersionRef

    def __post_init__(self) -> None:
        _record(self.version, VersionRef, "data identity version")


@dataclass(frozen=True, slots=True)
class ObjectIdentity:
    object: ObjectRef

    def __post_init__(self) -> None:
        _record(self.object, ObjectRef, "object identity reference")


@dataclass(frozen=True, slots=True)
class ValueDenotation:
    id: DenotationID
    value: ValueOccurrenceID
    identity: DataIdentity | ObjectIdentity | Unresolved
    basis: DenotationBasis
    source: FactSource

    def __post_init__(self) -> None:
        _id(self.id, DenotationID, "denotation ID")
        _id(self.value, ValueOccurrenceID, "denotation value occurrence")
        _variant(self.identity, (DataIdentity, ObjectIdentity, Unresolved),
                 "value denotation identity")
        _denotation_basis(self.basis, "value denotation basis")
        _source(self.source, "value denotation source")


@dataclass(frozen=True, slots=True)
class WorkEvidenceBinding:
    id: WorkEvidenceBindingID
    ticket: WorkTicketID
    artifact: ProviderArtifact
    instance: OperationInstanceID
    source: FactSource

    def __post_init__(self) -> None:
        _id(self.id, WorkEvidenceBindingID, "work evidence binding ID")
        _id(self.ticket, WorkTicketID, "work evidence ticket")
        _record(self.artifact, ProviderArtifact, "work evidence artifact")
        _id(self.instance, OperationInstanceID, "legacy operation instance")
        _source(self.source, "work evidence binding source")


@dataclass(frozen=True, slots=True)
class ProtocolInterval:
    start: ExecutionPoint
    end: ExecutionPoint
    protocol: ProviderFactReference
    source: FactSource

    def __post_init__(self) -> None:
        _point(self.start, "protocol interval start")
        _point(self.end, "protocol interval end")
        _record(self.protocol, ProviderFactReference, "protocol interval protocol")
        _source(self.source, "protocol interval source")


@dataclass(frozen=True, slots=True)
class WholeWorkRead:
    ticket: WorkTicketID

    def __post_init__(self) -> None:
        _id(self.ticket, WorkTicketID, "whole-work read ticket")


@dataclass(frozen=True, slots=True)
class NativeWorkRead:
    ticket: WorkTicketID
    interval: ProtocolInterval

    def __post_init__(self) -> None:
        _id(self.ticket, WorkTicketID, "native-work read ticket")
        _record(self.interval, ProtocolInterval, "native-work read interval")


WorkRead: TypeAlias = WholeWorkRead | NativeWorkRead
ContentSubject: TypeAlias = UseRef | AccessRef


def _content_subject(value: object, name: str) -> None:
    _variant(value, (UseRef, AccessRef), name)


@dataclass(frozen=True, slots=True)
class HostConsumer:
    subject: ContentSubject
    interval: ProtocolInterval

    def __post_init__(self) -> None:
        _content_subject(self.subject, "host consumer subject")
        _record(self.interval, ProtocolInterval, "host consumer interval")


@dataclass(frozen=True, slots=True)
class ResourceConsumer:
    subject: ContentSubject
    read: WorkRead
    input: NativeInputRef | EvidenceEdgeRef | Unresolved

    def __post_init__(self) -> None:
        _content_subject(self.subject, "resource consumer subject")
        _variant(self.read, (WholeWorkRead, NativeWorkRead), "resource consumer read")
        _variant(self.input, (NativeInputRef, EvidenceEdgeRef, Unresolved),
                 "resource consumer input")


@dataclass(frozen=True, slots=True)
class ObservationConsumer:
    root: ObservationRootID

    def __post_init__(self) -> None:
        _id(self.root, ObservationRootID, "observation consumer root")


ContentConsumer: TypeAlias = HostConsumer | ResourceConsumer | ObservationConsumer


@dataclass(frozen=True, slots=True)
class ProtocolSelector:
    reference: ProviderFactReference

    def __post_init__(self) -> None:
        _record(self.reference, ProviderFactReference, "protocol selector reference")


@dataclass(frozen=True, slots=True)
class StorageContent:
    materialization: MaterializationRef
    selector: RegionRef | None

    def __post_init__(self) -> None:
        _record(self.materialization, MaterializationRef, "storage content materialization")
        if self.selector is not None:
            _record(self.selector, RegionRef, "storage content selector")


@dataclass(frozen=True, slots=True)
class EndpointContent:
    materialization: MaterializationRef
    target: ResourceTarget
    selector: UseRef | AccessRef | ProtocolSelector | Unresolved

    def __post_init__(self) -> None:
        _record(self.materialization, MaterializationRef, "endpoint content materialization")
        _target(self.target)
        _variant(self.selector, (UseRef, AccessRef, ProtocolSelector, Unresolved),
                 "endpoint content selector")


ContentPlacement: TypeAlias = StorageContent | EndpointContent | Unresolved
ContentEffect: TypeAlias = AccessRef | InvokeBoundaryStateEffect | Unresolved | None


@dataclass(frozen=True, slots=True)
class ContentRead:
    id: ContentReadID
    consumer: ContentConsumer
    placement: ContentPlacement
    effect: ContentEffect
    anchor: OccurrencePoint | Unresolved
    support: tuple[ValueOccurrenceID, ...]
    basis: DenotationBasis
    source: FactSource

    def __post_init__(self) -> None:
        _id(self.id, ContentReadID, "content read ID")
        _variant(self.consumer, (HostConsumer, ResourceConsumer, ObservationConsumer),
                 "content read consumer")
        _variant(self.placement, (StorageContent, EndpointContent, Unresolved),
                 "content read placement")
        if self.effect is not None:
            _variant(self.effect, (AccessRef, InvokeBoundaryStateEffect, Unresolved),
                     "content read effect")
        _variant(self.anchor, (OccurrencePoint, Unresolved), "content read anchor")
        _support(self.support, "content read state support")
        _denotation_basis(self.basis, "content read basis")
        _source(self.source, "content read source")


__all__ = [
    "ContentConsumer", "ContentEffect", "ContentPlacement", "ContentRead",
    "ContentSubject", "DataIdentity", "DenotationBasis", "EndpointContent",
    "EvidenceEdgeRef", "EvidenceObservationRef", "HostConsumer", "NativeInputRef",
    "NativeOutputRef", "NativeWorkRead", "ObjectIdentity", "ObjectRef",
    "ObservationConsumer", "ProtocolInterval", "ProtocolSelector", "ResourceConsumer",
    "StorageContent", "ValueDenotation", "VersionRef", "WholeWorkRead", "WorkEvidenceBinding",
    "WorkRead",
]
