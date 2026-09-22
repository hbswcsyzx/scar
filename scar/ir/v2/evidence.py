"""Execution evidence records that refer to v2 semantic/value identities."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
import re

from .common import EvidenceClaim
from ._validation import cycle_errors, mapping_errors, record_errors
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

    def __post_init__(self) -> None:
        if self.start_ns is not None and self.start_ns < 0:
            raise ValueError("instance start time cannot be negative")
        if self.end_ns is not None and self.end_ns < 0:
            raise ValueError("instance end time cannot be negative")
        if self.start_ns is not None and self.end_ns is not None and self.end_ns < self.start_ns:
            raise ValueError("instance ends before it starts")

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
    OBSERVED_CONTROL = "observed_control"
    USES_STORAGE = "uses_storage"
    MEASURED_BY = "measured_by"
    USES_RESOURCE = "uses_resource"


_E = EvidenceNodeKind
_DATA_NODES = (_E.VALUE_OBSERVATION, _E.VALUE_VERSION, _E.MATERIALIZATION,
               _E.OBJECT, _E.ALLOCATION, _E.STORAGE_REGION)
_EVENT_NODES = (_E.OPERATION_INSTANCE, _E.CONTROL_EVENT)
_EVIDENCE_RELATION_ENDPOINTS = {
    # A definition is owned by SG, so instance_of is stored in
    # OperationInstance.definition / CorrespondenceGraph, not as an EEG edge.
    EvidenceRelation.INSTANCE_OF: set(),
    **{relation: {(_E.OPERATION_INSTANCE, target) for target in _DATA_NODES}
       for relation in (EvidenceRelation.OBSERVED_READ, EvidenceRelation.OBSERVED_WRITE,
                        EvidenceRelation.PRODUCES)},
    EvidenceRelation.MATERIALIZES: {
        (source, _E.MATERIALIZATION) for source in (_E.OPERATION_INSTANCE, _E.VALUE_VERSION)},
    EvidenceRelation.ALIASES: {(source, target) for source in (
        _E.OBJECT, _E.STORAGE_REGION, _E.MATERIALIZATION) for target in (
            _E.OBJECT, _E.STORAGE_REGION, _E.MATERIALIZATION)},
    EvidenceRelation.OVERWRITES: {(_E.OPERATION_INSTANCE, target) for target in _DATA_NODES},
    EvidenceRelation.ESCAPES: {
        (source, target) for source in _DATA_NODES
        for target in (_E.OPERATION_INSTANCE, _E.OBJECT, _E.RESOURCE)},
    EvidenceRelation.HAPPENS_BEFORE: {
        (source, target) for source in _EVENT_NODES for target in _EVENT_NODES},
    EvidenceRelation.CONTROLS_INSTANCE: {
        (source, _E.OPERATION_INSTANCE) for source in _EVENT_NODES},
    # A line/back-edge event was observed inside an invocation. This is
    # ownership, not a claim that it controls the already-running invocation.
    EvidenceRelation.OBSERVED_CONTROL: {(_E.OPERATION_INSTANCE, _E.CONTROL_EVENT)},
    EvidenceRelation.USES_STORAGE: {
        (source, target) for source in (_E.OPERATION_INSTANCE, _E.MATERIALIZATION, _E.OBJECT)
        for target in (_E.ALLOCATION, _E.STORAGE_REGION)},
    EvidenceRelation.MEASURED_BY: {
        (source, _E.MEASUREMENT) for source in EvidenceNodeKind if source is not _E.MEASUREMENT},
    EvidenceRelation.USES_RESOURCE: {
        (source, _E.RESOURCE) for source in (_E.OPERATION_INSTANCE, _E.MATERIALIZATION, _E.ALLOCATION)},
}


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
        if self.relation is EvidenceRelation.INSTANCE_OF:
            raise ValueError("instance_of belongs in OperationInstance.definition or correspondence")
        if (self.source.kind, self.target.kind) not in _EVIDENCE_RELATION_ENDPOINTS[self.relation]:
            raise ValueError(f"invalid endpoints for evidence relation {self.relation.value}")

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
    SCHEMA_VERSION = 3

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
        for mapping, key_type, record_type, name, key_field in (
            (self.instances, OperationInstanceID, OperationInstance, "instances", "id"),
            (self.observations, str, ValueObservation, "observations", "observation_id"),
            (self.measurements, MeasurementID, MeasurementRecord, "measurements", "id"),
            (self.edges, str, EvidenceEdge, "edges", "edge_id"),
        ):
            errors.extend(mapping_errors(mapping, key_type, record_type, name, key_field))
        errors.extend(record_errors(self.control_events, set[str], "control_events"))
        errors.extend(record_errors(self.external_references, set[tuple[EvidenceNodeKind, str]],
                                    "external_references"))
        if errors:
            return self._validation_report(errors)
        for kind, wire in sorted(self.external_references, key=lambda item: (item[0].value, item[1])):
            expected = _TYPED_EVIDENCE_ENDPOINTS.get(kind)
            if kind in (_E.OPERATION_INSTANCE, _E.VALUE_OBSERVATION, _E.CONTROL_EVENT, _E.MEASUREMENT):
                errors.append(f"external reference {wire} has EEG-owned kind {kind.value}")
            elif expected is ValueVersionID:
                if re.fullmatch(r"lv:.+@v(?:0|[1-9][0-9]*)", wire) is None:
                    errors.append(f"external reference {wire} is not a value version wire ID")
            elif expected is None or not wire.startswith(expected.prefix + ":") or not wire[len(expected.prefix) + 1:]:
                errors.append(f"external reference {wire} has wrong ID kind for {kind.value}")
        if "" in self.control_events:
            errors.append("control event ID cannot be empty")
        for instance in self.instances.values():
            if instance.parent is not None and instance.parent not in self.instances:
                errors.append(f"instance {instance.id.wire} references unknown parent")
        for observation in self.observations.values():
            if not observation.observation_id:
                errors.append("observation ID cannot be empty")
            if observation.operation is not None and observation.operation not in self.instances:
                errors.append(f"observation {observation.observation_id} references unknown operation")
        for edge in self.edges.values():
            if not self._endpoint_exists(edge.source):
                errors.append(f"edge {edge.edge_id} has unknown source")
            if not self._endpoint_exists(edge.target):
                errors.append(f"edge {edge.edge_id} has unknown target")
        errors.extend(cycle_errors(
            ((item.parent, item.id) for item in self.instances.values() if item.parent is not None),
            "operation instance ancestry"))
        errors.extend(cycle_errors(
            (((edge.source.kind, edge.source.wire), (edge.target.kind, edge.target.wire))
             for edge in self.edges.values()
             if edge.relation is EvidenceRelation.HAPPENS_BEFORE), "happens-before relation"))
        # Parentage is containment, not completion order: never combine parent
        # edges with happens-before edges to invent a temporal relation.
        return self._validation_report(errors)

    def _validation_report(self, errors: list[str]) -> dict[str, Any]:
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
