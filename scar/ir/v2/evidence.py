"""Execution evidence records that refer to v2 semantic/value identities."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .ids import (
    MaterializationID,
    OperationDefinitionID,
    OperationInstanceID,
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


class EvidenceGraph:
    """Normalized execution records; no optimization selection is performed."""

    SCHEMA = "scar.ir.v2.evidence"
    SCHEMA_VERSION = 1

    def __init__(self) -> None:
        self.instances: dict[OperationInstanceID, OperationInstance] = {}
        self.observations: dict[str, ValueObservation] = {}

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
        return {"schema": self.SCHEMA, "schema_version": self.SCHEMA_VERSION,
                "valid": not errors, "errors": errors,
                "counts": {"instances": len(self.instances),
                            "observations": len(self.observations)}}

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
            "instances": [item.as_dict() for item in self.instances.values()],
            "observations": [item.as_dict() for item in self.observations.values()],
            "validation": self.validate(),
        }


__all__ = ["EvidenceStatus", "OperationInstance", "ValueObservation", "EvidenceGraph"]
