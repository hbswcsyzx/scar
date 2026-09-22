"""Logical value, provenance and physical materialization IR for v2."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from .ids import (
    MaterializationID,
    ObjectID,
    OperationInstanceID,
    LogicalValueID,
    ProvenanceID,
    StorageAllocationID,
    StorageRegionID,
    ValueVersionID,
)


class ProvenanceRelation(str, Enum):
    ORIGIN = "origin"
    COPY = "copy"
    VIEW = "view"
    TRANSFORM = "transform"
    AGGREGATE = "aggregate"
    MUTATE = "mutate"
    MATERIALIZE = "materialize"
    UNKNOWN = "unknown"


class EquivalenceClaim(str, Enum):
    EXACT_LOGICAL = "exact_logical"
    EXACT_CONTENT_AT_TIME = "exact_content_at_time"
    REPRESENTATION_ONLY = "representation_only"
    APPROXIMATE = "approximate"
    UNKNOWN = "unknown"


class BindingRelation(str, Enum):
    OWNS = "owns"
    REFERENCES = "references"
    VIEW = "view"
    COPY = "copy"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class LogicalValue:
    id: LogicalValueID
    semantic_type: str
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id.as_dict(), "semantic_type": self.semantic_type,
                "description": self.description, "metadata": self.metadata}


@dataclass(slots=True)
class ValueVersion:
    id: ValueVersionID
    provenance_id: ProvenanceID | None = None
    parent_versions: tuple[ValueVersionID, ...] = ()
    semantic_type: str | None = None
    control_scope: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id.as_dict(),
            "provenance_id": self.provenance_id.as_dict()
            if self.provenance_id else None,
            "parent_versions": [item.as_dict() for item in self.parent_versions],
            "semantic_type": self.semantic_type,
            "control_scope": self.control_scope,
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class ProvenanceRecord:
    id: ProvenanceID
    relation: ProvenanceRelation
    inputs: tuple[ValueVersionID, ...]
    outputs: tuple[ValueVersionID, ...]
    producer: OperationInstanceID | None = None
    equivalence: EquivalenceClaim = EquivalenceClaim.UNKNOWN
    evidence: str = "Observed"
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id.as_dict(),
            "relation": self.relation.value,
            "inputs": [item.as_dict() for item in self.inputs],
            "outputs": [item.as_dict() for item in self.outputs],
            "producer": self.producer.as_dict() if self.producer else None,
            "equivalence": self.equivalence.value,
            "evidence": self.evidence,
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class StorageAllocation:
    id: StorageAllocationID
    device: str
    nbytes: int | None = None
    allocator_token: str | None = None
    lifetime_scope: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self) | {"id": self.id.as_dict()}


@dataclass(slots=True)
class StorageRegion:
    id: StorageRegionID
    allocation: StorageAllocationID
    offset: int
    shape: tuple[int, ...]
    strides: tuple[int, ...]
    dtype: str
    device: str
    layout: str = "strided"
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id.as_dict(),
            "allocation": self.allocation.as_dict(),
            "offset": self.offset,
            "shape": list(self.shape),
            "strides": list(self.strides),
            "dtype": self.dtype,
            "device": self.device,
            "layout": self.layout,
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class Materialization:
    id: MaterializationID
    value_version: ValueVersionID
    representation: str
    device: str
    region: StorageRegionID | None = None
    producer: OperationInstanceID | None = None
    ready_event: str | None = None
    validity_scope: str | None = None
    evidence: str = "Observed"
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id.as_dict(),
            "value_version": self.value_version.as_dict(),
            "representation": self.representation,
            "device": self.device,
            "region": self.region.as_dict() if self.region else None,
            "producer": self.producer.as_dict() if self.producer else None,
            "ready_event": self.ready_event,
            "validity_scope": self.validity_scope,
            "evidence": self.evidence,
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class ObjectBinding:
    object_id: ObjectID
    value_version: ValueVersionID
    relation: BindingRelation = BindingRelation.REFERENCES
    scope: str | None = None
    evidence: str = "Observed"
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id.as_dict(),
            "value_version": self.value_version.as_dict(),
            "relation": self.relation.value,
            "scope": self.scope,
            "evidence": self.evidence,
            "metadata": self.metadata,
        }


class ValueGraph:
    """A validated v2 value/provenance graph.

    This graph deliberately contains no optimization decision.  It answers
    which logical versions, provenance records and physical representations
    were declared or observed.
    """

    SCHEMA = "scar.ir.v2.values"
    SCHEMA_VERSION = 1

    def __init__(self) -> None:
        self.logical_values: dict[LogicalValueID, LogicalValue] = {}
        self.versions: dict[ValueVersionID, ValueVersion] = {}
        self.provenance: dict[ProvenanceID, ProvenanceRecord] = {}
        self.allocations: dict[StorageAllocationID, StorageAllocation] = {}
        self.regions: dict[StorageRegionID, StorageRegion] = {}
        self.materializations: dict[MaterializationID, Materialization] = {}
        self.bindings: list[ObjectBinding] = []

    def add_logical_value(self, value: LogicalValue) -> None:
        self._insert(self.logical_values, value.id, value, "logical value")

    def add_version(self, version: ValueVersion) -> None:
        if version.id.logical_value not in self.logical_values:
            raise ValueError(f"unknown logical value: {version.id.logical_value.wire}")
        self._insert(self.versions, version.id, version, "value version")

    def add_provenance(self, record: ProvenanceRecord) -> None:
        self._insert(self.provenance, record.id, record, "provenance")

    def add_allocation(self, allocation: StorageAllocation) -> None:
        if allocation.nbytes is not None and allocation.nbytes < 0:
            raise ValueError("allocation nbytes cannot be negative")
        self._insert(self.allocations, allocation.id, allocation, "allocation")

    def add_region(self, region: StorageRegion) -> None:
        if region.allocation not in self.allocations:
            raise ValueError(f"unknown allocation: {region.allocation.wire}")
        if region.offset < 0 or any(size < 0 for size in region.shape):
            raise ValueError("region offset and shape must be non-negative")
        if len(region.shape) != len(region.strides):
            raise ValueError("region shape and strides must have equal rank")
        self._insert(self.regions, region.id, region, "storage region")

    def add_materialization(self, materialization: Materialization) -> None:
        if materialization.value_version not in self.versions:
            raise ValueError(f"unknown materialized version: {materialization.value_version.wire}")
        if (materialization.region is not None
                and materialization.region not in self.regions):
            raise ValueError(f"unknown materialization region: {materialization.region.wire}")
        self._insert(self.materializations, materialization.id, materialization,
                     "materialization")

    def add_binding(self, binding: ObjectBinding) -> None:
        if binding.value_version not in self.versions:
            raise ValueError(f"unknown bound version: {binding.value_version.wire}")
        self.bindings.append(binding)

    def ancestors(self, version: ValueVersionID) -> tuple[ValueVersionID, ...]:
        """Return transitive logical parents in deterministic order."""
        if version not in self.versions:
            raise KeyError(f"unknown version: {version.wire}")
        found: set[ValueVersionID] = set()
        pending = list(self.versions[version].parent_versions)
        while pending:
            parent = pending.pop()
            if parent in found:
                continue
            found.add(parent)
            pending.extend(self.versions[parent].parent_versions)
        return tuple(sorted(found, key=lambda item: item.wire))

    @staticmethod
    def _insert(mapping, key, value, label: str) -> None:
        if key in mapping:
            raise ValueError(f"duplicate {label} identity: {key}")
        mapping[key] = value

    def validate(self) -> dict[str, Any]:
        errors: list[str] = []
        for version in self.versions.values():
            for parent in version.parent_versions:
                if parent not in self.versions:
                    errors.append(f"version {version.id.wire} has unknown parent {parent.wire}")
            if version.provenance_id is not None and version.provenance_id not in self.provenance:
                errors.append(f"version {version.id.wire} has unknown provenance {version.provenance_id.wire}")
                continue
            if (version.provenance_id is not None
                    and version.id not in self.provenance[version.provenance_id].outputs):
                errors.append(
                    f"version {version.id.wire} is not an output of {version.provenance_id.wire}")
        for record in self.provenance.values():
            for item in record.inputs + record.outputs:
                if item not in self.versions:
                    errors.append(f"provenance {record.id.wire} references unknown version {item.wire}")
        # A provenance DAG must not contain a cycle.  Cycles would make a
        # version appear to derive from itself and invalidate lifetime and
        # invalidation reasoning.
        visiting: set[ValueVersionID] = set()
        visited: set[ValueVersionID] = set()

        def visit(version_id: ValueVersionID) -> None:
            if version_id in visiting:
                errors.append(f"cyclic value-version ancestry at {version_id.wire}")
                return
            if version_id in visited or version_id not in self.versions:
                return
            visiting.add(version_id)
            for parent in self.versions[version_id].parent_versions:
                visit(parent)
            visiting.remove(version_id)
            visited.add(version_id)

        for version_id in self.versions:
            visit(version_id)
        for region in self.regions.values():
            if region.allocation not in self.allocations:
                errors.append(f"region {region.id.wire} references unknown allocation {region.allocation.wire}")
        for materialization in self.materializations.values():
            if materialization.value_version not in self.versions:
                errors.append(f"materialization {materialization.id.wire} references unknown version")
            if materialization.region is not None and materialization.region not in self.regions:
                errors.append(f"materialization {materialization.id.wire} references unknown region")
        for binding in self.bindings:
            if binding.value_version not in self.versions:
                errors.append(f"binding references unknown version {binding.value_version.wire}")
        return {
            "schema": self.SCHEMA,
            "schema_version": self.SCHEMA_VERSION,
            "valid": not errors,
            "errors": errors,
            "counts": {
                "logical_values": len(self.logical_values),
                "versions": len(self.versions),
                "provenance": len(self.provenance),
                "allocations": len(self.allocations),
                "regions": len(self.regions),
                "materializations": len(self.materializations),
                "bindings": len(self.bindings),
            },
        }

    def assert_valid(self) -> dict[str, Any]:
        report = self.validate()
        if not report["valid"]:
            raise ValueError("invalid v2 ValueGraph: " + "; ".join(report["errors"]))
        return report

    def to_dict(self) -> dict[str, Any]:
        self.assert_valid()
        ordered = lambda mapping: [mapping[key].as_dict() for key in sorted(
            mapping, key=lambda item: item.wire)]
        return {
            "schema": self.SCHEMA,
            "schema_version": self.SCHEMA_VERSION,
            "logical_values": ordered(self.logical_values),
            "versions": ordered(self.versions),
            "provenance": ordered(self.provenance),
            "allocations": ordered(self.allocations),
            "regions": ordered(self.regions),
            "materializations": ordered(self.materializations),
            "bindings": [item.as_dict() for item in sorted(
                self.bindings,
                key=lambda item: (item.object_id.wire, item.value_version.wire,
                                  item.relation.value))],
            "validation": self.validate(),
        }


__all__ = [
    "ProvenanceRelation", "EquivalenceClaim", "BindingRelation",
    "LogicalValue", "ValueVersion", "ProvenanceRecord", "StorageAllocation",
    "StorageRegion", "Materialization", "ObjectBinding", "ValueGraph",
]
