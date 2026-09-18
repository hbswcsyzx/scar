"""Versioned SCAR IR v2 building blocks.

This package is intentionally isolated from the v1 graph and planner.  It
defines identities, semantic definitions, execution evidence and value
provenance; it does not select or apply an optimization backend.
"""

from .ids import (
    ControlRegionID,
    MaterializationID,
    ObjectID,
    OperationDefinitionID,
    OperationInstanceID,
    OptimizationRegionID,
    ProvenanceID,
    LogicalValueID,
    StorageAllocationID,
    StorageRegionID,
    ValueVersionID,
)
from .values import (
    BindingRelation,
    EquivalenceClaim,
    LogicalValue,
    Materialization,
    ObjectBinding,
    ProvenanceRecord,
    ProvenanceRelation,
    StorageAllocation,
    StorageRegion,
    ValueGraph,
    ValueVersion,
)
from .semantic import (
    OperationDefinition,
    OperationKind,
    SemanticGraph,
    ValueSlot,
)
from .evidence import (
    EvidenceGraph,
    EvidenceStatus,
    OperationInstance,
    ValueObservation,
)

__all__ = [
    "ControlRegionID", "MaterializationID", "ObjectID",
    "OperationDefinitionID", "OperationInstanceID", "OptimizationRegionID",
    "ProvenanceID", "LogicalValueID", "StorageAllocationID",
    "StorageRegionID", "ValueVersionID", "BindingRelation",
    "EquivalenceClaim", "LogicalValue", "Materialization", "ObjectBinding",
    "ProvenanceRecord", "ProvenanceRelation", "StorageAllocation",
    "StorageRegion", "ValueGraph", "ValueVersion", "OperationDefinition",
    "OperationKind", "SemanticGraph", "ValueSlot", "EvidenceGraph",
    "EvidenceStatus", "OperationInstance", "ValueObservation",
]
