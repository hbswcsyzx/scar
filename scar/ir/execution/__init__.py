"""Typed execution occurrences and resource associations over canonical program IR."""

from .calls import CallActivation
from .composition import CompositionScope
from .ids import CallActivationID
from .production import (
    BytePrefixWrite,
    EvidenceInventoryBinding,
    ExternalEstablishment,
    HostWrite,
    InventorySourceRef,
    OutcomeProduction,
    RawRecordRef,
    SourceEdgeRef,
    SourceEndpointBridge,
    SourceEndpointRef,
    SourceEndpointTarget,
    StateProduction,
    ValueProduction,
    WorkWrite,
    WriteActor,
    WriteAssociation,
    WritePlacement,
    WriteStage,
    ProductionTarget,
)
from .validity import (
    CompletedVisibility, ContributionSupport, EndpointDomain, EstablishedProduction,
    HostDomain, LifetimeEventKind, OrderAssociation, OrderedVisibility, QueueDomain,
    TargetLifetimeEvent, ValidityBasis, ValidityPoint, VisibilityDomain,
)

__all__ = [
    "CompositionScope",
    "CallActivation", "CallActivationID",
    "BytePrefixWrite", "EvidenceInventoryBinding", "ExternalEstablishment",
    "HostWrite", "InventorySourceRef", "OutcomeProduction", "RawRecordRef",
    "SourceEdgeRef", "SourceEndpointBridge", "SourceEndpointRef",
    "SourceEndpointTarget", "StateProduction", "ValueProduction", "WorkWrite",
    "WriteActor", "WriteAssociation", "WritePlacement", "WriteStage",
    "ProductionTarget",
    "CompletedVisibility", "ContributionSupport", "EndpointDomain", "EstablishedProduction",
    "HostDomain", "LifetimeEventKind", "OrderAssociation", "OrderedVisibility", "QueueDomain",
    "TargetLifetimeEvent", "ValidityBasis", "ValidityPoint", "VisibilityDomain",
]
