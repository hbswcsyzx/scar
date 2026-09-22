"""Execution evidence records that refer to v2 semantic/value identities."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .common import EvidenceClaim
from .contracts import MeasurementRecord
from .ids import (
    Identifier,
    MaterializationID,
    MeasurementID,
    ObjectID,
    OperationDefinitionID,
    OperationInstanceID,
    ResourceID,
    StorageAllocationID,
    StorageRegionID,
    ValueVersionID,
)


class EvidenceStatus(str, Enum):
    OBSERVED = "Observed"
    INFERRED = "Inferred"
    UNKNOWN = "UNKNOWN"


@dataclass(slots=True)
class OperationInstance:
    id: OperationInstanceID
    definition: OperationDefinitionID
    process_id: int | str
    thread_id: int | str
    parent: OperationInstanceID | None = None
    control_scope: str | None = None
    iteration: dict[str, Any] = field(default_factory=dict)
    start_ns: int | None = None
    end_ns: int | None = None
    status: EvidenceStatus = EvidenceStatus.OBSERVED
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id.as_dict(),
            "definition": self.definition.as_dict(),
            "process_id": self.process_id,
            "thread_id": self.thread_id,
            "parent": self.parent.as_dict() if self.parent else None,
            "control_scope": self.control_scope,
            "iteration": self.iteration,
            "start_ns": self.start_ns,
            "end_ns": self.end_ns,
            "status": self.status.value,
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class ValueObservation:
    observation_id: str
    version: ValueVersionID
    operation: OperationInstanceID | None = None
    materialization: MaterializationID | None = None
    role: str = "value"
    status: EvidenceStatus = EvidenceStatus.OBSERVED
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "version": self.version.as_dict(),
            "operation": self.operation.as_dict() if self.operation else None,
            "materialization": self.materialization.as_dict() if self.materialization else None,
            "role": self.role,
            "status": self.status.value,
            "metadata": self.metadata,
        }


class EvidenceNodeKind(str, Enum):
    OPERATION_INSTANCE = "operation_instance"
    VALUE_OBSERVATION = "value_observation"
    VALUE_VERSION = "value_version"
    MATERIALIZATION = "materialization"
    OBJECT = "object"
    ALLOCATION = "allocation"
    STORAGE_REGION = "storage_region"
    RESOURCE = "resource"
    MEASUREMENT = "measurement"
    CONTROL_EVENT = "control_event"


_TYPED_EVIDENCE_ENDPOINTS: dict[EvidenceNodeKind, type] = {
    EvidenceNodeKind.OPERATION_INSTANCE: OperationInstanceID,
    EvidenceNodeKind.VALUE_VERSION: ValueVersionID,
    EvidenceNodeKind.MATERIALIZATION: MaterializationID,
    EvidenceNodeKind.OBJECT: ObjectID,
    EvidenceNodeKind.ALLOCATION: StorageAllocationID,
    EvidenceNodeKind.STORAGE_REGION: StorageRegionID,
    EvidenceNodeKind.RESOURCE: ResourceID,
    EvidenceNodeKind.MEASUREMENT: MeasurementID,
}


@dataclass(frozen=True, slots=True)
class EvidenceEndpoint:
    kind: EvidenceNodeKind
    reference: Identifier | ValueVersionID | str

    def __post_init__(self) -> None:
        expected = _TYPED_EVIDENCE_ENDPOINTS.get(self.kind, str)
        if not isinstance(self.reference, expected):
            raise TypeError(f"{self.kind.value} endpoint requires {expected.__name__}")
        if isinstance(self.reference, str) and not self.reference:
            raise ValueError("evidence endpoint reference cannot be empty")

    @property
    def wire(self) -> str:
        return self.reference if isinstance(self.reference, str) else self.reference.wire

    def as_dict(self) -> dict[str, Any]:
        value: Any = self.reference
        if not isinstance(value, str):
            value = value.as_dict()
        return {"kind": self.kind.value, "reference": value}


class EvidenceRelation(str, Enum):
    INSTANCE_OF = "instance_of"
    OBSERVED_READ = "observed_read"
    OBSERVED_WRITE = "observed_write"
    PRODUCES = "produces"
    MATERIALIZES = "materializes"
    ALIASES = "aliases"
    OVERWRITES = "overwrites"
    ESCAPES = "escapes"
    HAPPENS_BEFORE = "happens_before"
    CONTROLS_INSTANCE = "controls_instance"
    USES_STORAGE = "uses_storage"
    MEASURED_BY = "measured_by"
    USES_RESOURCE = "uses_resource"


@dataclass(frozen=True, slots=True)
class EvidenceEdge:
    edge_id: str
    relation: EvidenceRelation
    source: EvidenceEndpoint
    target: EvidenceEndpoint
    evidence: EvidenceClaim

    def __post_init__(self) -> None:
        if not self.edge_id:
            raise ValueError("evidence edge ID is required")

    def as_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "relation": self.relation.value,
            "source": self.source.as_dict(),
            "target": self.target.as_dict(),
            "evidence": self.evidence.as_dict(),
        }


class EvidenceGraph:
    """Normalized execution records; no optimization selection is performed."""

    SCHEMA = "scar.ir.v2.evidence"
    SCHEMA_VERSION = 2

    def __init__(self) -> None:
        self.instances: dict[OperationInstanceID, OperationInstance] = {}
        self.observations: dict[str, ValueObservation] = {}
        self.measurements: dict[MeasurementID, MeasurementRecord] = {}
        self.control_events: set[str] = set()
        self.external_references: set[tuple[EvidenceNodeKind, str]] = set()
        self.edges: dict[str, EvidenceEdge] = {}

    def add_instance(self, instance: OperationInstance) -> None:
        if instance.id in self.instances:
            raise ValueError(f"duplicate operation instance: {instance.id.wire}")
        if instance.parent is not None and instance.parent not in self.instances:
            raise ValueError(f"unknown parent operation instance: {instance.parent.wire}")
        self.instances[instance.id] = instance

    def add_observation(self, observation: ValueObservation) -> None:
        if observation.observation_id in self.observations:
            raise ValueError(f"duplicate value observation: {observation.observation_id}")
        if (observation.operation is not None
                and observation.operation not in self.instances):
            raise ValueError(f"unknown observation operation: {observation.operation.wire}")
        self.observations[observation.observation_id] = observation

    def add_measurement(self, measurement: MeasurementRecord) -> None:
        if measurement.id in self.measurements:
            raise ValueError(f"duplicate measurement: {measurement.id.wire}")
        self.measurements[measurement.id] = measurement

    def add_control_event(self, control_event_id: str) -> None:
        if not control_event_id:
            raise ValueError("control event ID cannot be empty")
        if control_event_id in self.control_events:
            raise ValueError(f"duplicate control event: {control_event_id}")
        self.control_events.add(control_event_id)

    def register_external(self, endpoint: EvidenceEndpoint) -> None:
        """Register a typed node owned by ValueGraph or a resource registry."""
        if endpoint.kind in {
            EvidenceNodeKind.OPERATION_INSTANCE,
            EvidenceNodeKind.VALUE_OBSERVATION,
            EvidenceNodeKind.MEASUREMENT,
            EvidenceNodeKind.CONTROL_EVENT,
        }:
            raise ValueError(f"{endpoint.kind.value} is owned by EvidenceGraph")
        self.external_references.add((endpoint.kind, endpoint.wire))

    def add_edge(self, edge: EvidenceEdge) -> None:
        if edge.edge_id in self.edges:
            raise ValueError(f"duplicate evidence edge: {edge.edge_id}")
        if not self._endpoint_exists(edge.source):
            raise ValueError(f"unknown evidence edge source: {edge.source.wire}")
        if not self._endpoint_exists(edge.target):
            raise ValueError(f"unknown evidence edge target: {edge.target.wire}")
        self.edges[edge.edge_id] = edge

    def _endpoint_exists(self, endpoint: EvidenceEndpoint) -> bool:
        if endpoint.kind is EvidenceNodeKind.OPERATION_INSTANCE:
            return endpoint.reference in self.instances
        if endpoint.kind is EvidenceNodeKind.VALUE_OBSERVATION:
            return endpoint.reference in self.observations
        if endpoint.kind is EvidenceNodeKind.MEASUREMENT:
            return endpoint.reference in self.measurements
        if endpoint.kind is EvidenceNodeKind.CONTROL_EVENT:
            return endpoint.reference in self.control_events
        if endpoint.kind is EvidenceNodeKind.VALUE_VERSION:
            return (
                any(item.version == endpoint.reference for item in self.observations.values())
                or (endpoint.kind, endpoint.wire) in self.external_references
            )
        if endpoint.kind is EvidenceNodeKind.MATERIALIZATION:
            return (
                any(item.materialization == endpoint.reference
                    for item in self.observations.values())
                or (endpoint.kind, endpoint.wire) in self.external_references
            )
        return (endpoint.kind, endpoint.wire) in self.external_references

    def children_of(self, instance: OperationInstanceID) -> tuple[OperationInstance, ...]:
        """Return direct dynamic children for recursive execution expansion."""
        if instance not in self.instances:
            raise KeyError(f"unknown operation instance: {instance.wire}")
        return tuple(item for item in self.instances.values()
                     if item.parent == instance)

    def validate(self) -> dict[str, Any]:
        errors: list[str] = []
        for instance in self.instances.values():
            if instance.parent is not None and instance.parent not in self.instances:
                errors.append(f"instance {instance.id.wire} references unknown parent")
        for observation in self.observations.values():
            if observation.operation is not None and observation.operation not in self.instances:
                errors.append(f"observation {observation.observation_id} references unknown operation")
        for edge in self.edges.values():
            if not self._endpoint_exists(edge.source):
                errors.append(f"edge {edge.edge_id} has unknown source")
            if not self._endpoint_exists(edge.target):
                errors.append(f"edge {edge.edge_id} has unknown target")
        return {"schema": self.SCHEMA, "schema_version": self.SCHEMA_VERSION,
                "valid": not errors, "errors": errors,
                "counts": {"instances": len(self.instances),
                            "observations": len(self.observations),
                            "measurements": len(self.measurements),
                            "control_events": len(self.control_events),
                            "external_references": len(self.external_references),
                            "edges": len(self.edges)}}

    def assert_valid(self) -> dict[str, Any]:
        report = self.validate()
        if not report["valid"]:
            raise ValueError("invalid v2 EvidenceGraph: " + "; ".join(report["errors"]))
        return report

    def to_dict(self) -> dict[str, Any]:
        self.assert_valid()
        return {
            "schema": self.SCHEMA,
            "schema_version": self.SCHEMA_VERSION,
            "instances": [self.instances[key].as_dict()
                          for key in sorted(self.instances, key=lambda item: item.wire)],
            "observations": [self.observations[key].as_dict()
                             for key in sorted(self.observations)],
            "measurements": [self.measurements[key].as_dict()
                             for key in sorted(self.measurements, key=lambda item: item.wire)],
            "control_events": sorted(self.control_events),
            "external_references": [
                {"kind": kind.value, "wire": wire}
                for kind, wire in sorted(self.external_references,
                                         key=lambda item: (item[0].value, item[1]))
            ],
            "edges": [self.edges[key].as_dict() for key in sorted(self.edges)],
            "validation": self.validate(),
        }


__all__ = [
    "EvidenceEdge", "EvidenceEndpoint", "EvidenceGraph", "EvidenceNodeKind",
    "EvidenceRelation", "EvidenceStatus", "OperationInstance", "ValueObservation",
]
