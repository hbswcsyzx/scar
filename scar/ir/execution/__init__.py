"""Typed execution occurrences and resource associations over canonical program IR."""

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

__all__ = [
    "BytePrefixWrite", "EvidenceInventoryBinding", "ExternalEstablishment",
    "HostWrite", "InventorySourceRef", "OutcomeProduction", "RawRecordRef",
    "SourceEdgeRef", "SourceEndpointBridge", "SourceEndpointRef",
    "SourceEndpointTarget", "StateProduction", "ValueProduction", "WorkWrite",
    "WriteActor", "WriteAssociation", "WritePlacement", "WriteStage",
    "ProductionTarget",
]
