"""Declared contribution support, causal links and exact target lifetimes.

These are associations to canonical operations and original evidence. A valid
record is not proof of capture closure, visibility or permission to transform.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

from scar.ir.program.providers import ProviderFactReference
from .common import EvidencePoint, FactSource, Unresolved
from .coordinates import AccessRef, ExecutionPoint, OccurrencePoint, UseRef
from .coverage import RegionRef
from .ids import (
    ContentReadID, ContributionSupportID, EstablishedProductionID,
    HostThreadInstanceID, OrderAssociationID, OutcomeProductionID,
    ResourceInstanceID, TargetLifetimeEventID, ValueOccurrenceID,
    WriteAssociationID,
)
from .order import EventSignal, PrefixEnd, WorkEnd, WorkStart
from .production import BytePrefixWrite, RawRecordRef, SourceEdgeRef
from .content import ProtocolSelector
from .resources import (
    ResourceTarget, _exact, _id, _point, _record, _source, _target, _variant,
)
from .work import InvokeBoundaryStateEffect


ValidityPoint: TypeAlias = ExecutionPoint | WorkStart | WorkEnd | PrefixEnd | EventSignal
ValidityBasis: TypeAlias = (
    RawRecordRef | SourceEdgeRef | UseRef | AccessRef | InvokeBoundaryStateEffect | Unresolved
)


def _validity_point(value: object, name: str) -> None:
    _variant(value, (OccurrencePoint, EvidencePoint, WorkStart, WorkEnd, PrefixEnd, EventSignal), name)


def _basis(value: object, name: str) -> None:
    _variant(value, (RawRecordRef, SourceEdgeRef, UseRef, AccessRef,
                     InvokeBoundaryStateEffect, Unresolved), name)


@dataclass(frozen=True, slots=True)
class EstablishedProduction:
    id: EstablishedProductionID
    write: WriteAssociationID
    established: ExecutionPoint
    actual: RegionRef | ProtocolSelector | Unresolved
    result: ValueOccurrenceID | ProviderFactReference | Unresolved
    rule: BytePrefixWrite | Unresolved
    source: FactSource

    def __post_init__(self):
        _id(self.id, EstablishedProductionID, "established production ID")
        _id(self.write, WriteAssociationID, "established production write")
        _point(self.established, "established production point")
        _variant(self.actual, (RegionRef, ProtocolSelector, Unresolved), "established actual selector")
        if type(self.result) is ValueOccurrenceID:
            _id(self.result, ValueOccurrenceID, "established result occurrence")
        else:
            _variant(self.result, (ProviderFactReference, Unresolved), "established result")
        _variant(self.rule, (BytePrefixWrite, Unresolved), "established production rule")
        _source(self.source, "established production source")


class LifetimeEventKind(str, Enum):
    LIVE = "live"
    RETIRED = "retired"


@dataclass(frozen=True, slots=True)
class TargetLifetimeEvent:
    id: TargetLifetimeEventID
    target: ResourceTarget
    kind: LifetimeEventKind
    at: ValidityPoint | Unresolved
    stage: RawRecordRef | SourceEdgeRef | Unresolved
    effect: AccessRef | InvokeBoundaryStateEffect | Unresolved | None
    protocol: ProviderFactReference
    source: FactSource

    def __post_init__(self):
        _id(self.id, TargetLifetimeEventID, "target lifetime event ID")
        _target(self.target, "lifetime event target")
        _exact(self.kind, LifetimeEventKind, "lifetime event kind")
        if type(self.at) is Unresolved:
            _record(self.at, Unresolved, "lifetime event point")
        else:
            _validity_point(self.at, "lifetime event point")
        _variant(self.stage, (RawRecordRef, SourceEdgeRef, Unresolved), "lifetime event source stage")
        if self.effect is not None:
            _variant(self.effect, (AccessRef, InvokeBoundaryStateEffect, Unresolved), "lifetime event effect")
        _record(self.protocol, ProviderFactReference, "lifetime event protocol")
        _source(self.source, "lifetime event source")


@dataclass(frozen=True, slots=True)
class OrderAssociation:
    id: OrderAssociationID
    before: ValidityPoint
    after: ValidityPoint
    basis: ValidityBasis
    protocol: ProviderFactReference
    source: FactSource

    def __post_init__(self):
        _id(self.id, OrderAssociationID, "order association ID")
        _validity_point(self.before, "order association before")
        _validity_point(self.after, "order association after")
        _basis(self.basis, "order association basis")
        _record(self.protocol, ProviderFactReference, "order association protocol")
        _source(self.source, "order association source")
        if self.before == self.after:
            raise ValueError("strict order association cannot order a point before itself")


@dataclass(frozen=True, slots=True)
class HostDomain:
    thread: HostThreadInstanceID

    def __post_init__(self):
        _id(self.thread, HostThreadInstanceID, "visibility host thread")


@dataclass(frozen=True, slots=True)
class QueueDomain:
    queue: ResourceInstanceID

    def __post_init__(self):
        _id(self.queue, ResourceInstanceID, "visibility queue")


@dataclass(frozen=True, slots=True)
class EndpointDomain:
    target: ResourceTarget

    def __post_init__(self):
        _target(self.target, "visibility endpoint")


VisibilityDomain: TypeAlias = HostDomain | QueueDomain | EndpointDomain | Unresolved


@dataclass(frozen=True, slots=True)
class CompletedVisibility:
    established: ValidityPoint
    basis: ValidityBasis
    domain: VisibilityDomain
    protocol: ProviderFactReference

    def __post_init__(self):
        _validity_point(self.established, "completed visibility established point")
        _basis(self.basis, "completed visibility basis")
        _variant(self.domain, (HostDomain, QueueDomain, EndpointDomain, Unresolved), "visibility domain")
        _record(self.protocol, ProviderFactReference, "completed visibility protocol")


@dataclass(frozen=True, slots=True)
class OrderedVisibility:
    protocol: ProviderFactReference

    def __post_init__(self):
        _record(self.protocol, ProviderFactReference, "ordered visibility protocol")


@dataclass(frozen=True, slots=True)
class ContributionSupport:
    id: ContributionSupportID
    read: ContentReadID
    write: WriteAssociationID
    production: OutcomeProductionID | EstablishedProductionID | Unresolved | None
    visibility: CompletedVisibility | OrderedVisibility | Unresolved
    source: FactSource

    def __post_init__(self):
        _id(self.id, ContributionSupportID, "contribution support ID")
        _id(self.read, ContentReadID, "contribution support read")
        _id(self.write, WriteAssociationID, "contribution support write")
        if type(self.production) in (OutcomeProductionID, EstablishedProductionID):
            _id(self.production, type(self.production), "contribution support production")
        elif self.production is not None:
            _record(self.production, Unresolved, "contribution support production")
        _variant(self.visibility, (CompletedVisibility, OrderedVisibility, Unresolved),
                 "contribution visibility")
        if self.production is None and type(self.visibility) is not OrderedVisibility:
            raise ValueError("only pending ordered visibility may omit an established production")
        _source(self.source, "contribution support source")


__all__ = [
    "ValidityPoint", "ValidityBasis", "EstablishedProduction", "LifetimeEventKind",
    "TargetLifetimeEvent", "OrderAssociation", "HostDomain", "QueueDomain",
    "EndpointDomain", "VisibilityDomain", "CompletedVisibility", "OrderedVisibility",
    "ContributionSupport",
]
