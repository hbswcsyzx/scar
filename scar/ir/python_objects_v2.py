"""Typed, storage-free records for observed Python object references.

These records name a reference within one capture.  They do not describe the
referenced object's contents or lifetime outside the sampled events.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from typing import Any

from scar.ir.provenance import EventPoint
from scar.ir.record_codec import decode, encode, loads
from scar.ir.v2 import (
    BindingRelation, EquivalenceClaim, LogicalValue, LogicalValueID,
    Materialization, MaterializationID, ObjectBinding, ObjectID,
    ProvenanceID, ProvenanceRecord, ProvenanceRelation, ValueGraph,
    ValueVersion, ValueVersionID,
)
from scar.ir.v2.codec import values_from_dict
from scar.ir.v2._validation import record_errors


class PythonObjectRepresentation(str, Enum):
    IDENTITY_REFERENCE = "IDENTITY_REFERENCE"
    BOOL_TRUE = "BOOL_TRUE"
    BOOL_FALSE = "BOOL_FALSE"


class ObjectTrackingKind(str, Enum):
    WEAK_REFERENCE = "WEAK_REFERENCE"
    STRONG_LEASE = "STRONG_LEASE"
    BOOL_SINGLETON = "BOOL_SINGLETON"
    NONE_SINGLETON = "NONE_SINGLETON"


@dataclass(frozen=True, slots=True)
class PythonObjectHandle:
    """One observed reference token and its single reference materialization."""

    object_id: ObjectID
    version: ValueVersionID
    materialization: MaterializationID

    def __post_init__(self) -> None:
        if not isinstance(self.object_id, ObjectID):
            raise TypeError("object_id must be ObjectID")
        if not isinstance(self.version, ValueVersionID):
            raise TypeError("version must be ValueVersionID")
        if not isinstance(self.materialization, MaterializationID):
            raise TypeError("materialization must be MaterializationID")

    def as_dict(self) -> dict[str, Any]:
        return encode(self)


@dataclass(frozen=True, slots=True)
class PythonObjectRecord:
    """Object table row; tracking says how this capture observed the reference."""

    handle: PythonObjectHandle
    representation: PythonObjectRepresentation
    tracking: ObjectTrackingKind

    def __post_init__(self) -> None:
        if not isinstance(self.handle, PythonObjectHandle):
            raise TypeError("object record handle must be PythonObjectHandle")
        if not isinstance(self.representation, PythonObjectRepresentation):
            raise TypeError("object record representation is invalid")
        if not isinstance(self.tracking, ObjectTrackingKind):
            raise TypeError("object record tracking kind is invalid")


@dataclass(frozen=True, slots=True)
class ReferenceObservation:
    """One direct sample of an object reference at an observer event."""

    observation_id: str
    handle: PythonObjectHandle
    at: EventPoint
    representation: PythonObjectRepresentation
    type_category: str

    def __post_init__(self) -> None:
        if type(self.observation_id) is not str or not self.observation_id:
            raise ValueError("observation_id is required")
        if not isinstance(self.handle, PythonObjectHandle):
            raise TypeError("observation handle must be PythonObjectHandle")
        if not isinstance(self.at, EventPoint):
            raise TypeError("observation event must be EventPoint")
        if not isinstance(self.representation, PythonObjectRepresentation):
            raise TypeError("observation representation is invalid")
        if type(self.type_category) is not str or not self.type_category:
            raise ValueError("observation type category is required")


class PythonObjectModel:
    """A compact object table, its reference samples and ValueGraph projection."""

    SCHEMA = "scar.ir.python-object-identity.v2"
    SCHEMA_VERSION = 2

    def __init__(self, *, scope: str, namespace: str, process_id: int,
                 current_event: EventPoint, graph: ValueGraph | None = None,
                 objects: dict[ObjectID, PythonObjectRecord] | None = None,
                 observations: list[ReferenceObservation] | None = None):
        self.scope = scope
        self.namespace = namespace
        self.process_id = process_id
        self.current_event = current_event
        self.graph = graph if graph is not None else ValueGraph()
        self.objects = dict(objects or {})
        self.observations = list(observations or ())

    @property
    def handles(self) -> dict[ObjectID, PythonObjectHandle]:
        return {identity: record.handle for identity, record in self.objects.items()}

    def validate(self) -> dict[str, Any]:
        errors: list[str] = []
        if type(self.scope) is not str or not self.scope:
            errors.append("scope is required")
        if type(self.namespace) is not str or not self.namespace:
            errors.append("namespace is required")
        if type(self.process_id) is not int or self.process_id < 0:
            errors.append("process_id must be a non-negative integer")
        if not isinstance(self.current_event, EventPoint):
            errors.append("current_event must be EventPoint")
        elif self.current_event.scope != self.scope:
            errors.append("current_event belongs to another capture scope")
        if not isinstance(self.graph, ValueGraph):
            errors.append("graph must be ValueGraph")
            graph_report = None
        else:
            graph_report = self.graph.validate()
            errors.extend("graph: " + error for error in graph_report["errors"])
        if not isinstance(self.objects, dict):
            errors.append("objects must be an object table")
            objects = {}
        else:
            objects = self.objects
        if not isinstance(self.observations, list):
            errors.append("observations must be an array")
            observations = []
        else:
            observations = self.observations

        seen_versions: set[ValueVersionID] = set()
        seen_materializations: set[MaterializationID] = set()
        singleton_ids: dict[PythonObjectRepresentation | ObjectTrackingKind, ObjectID] = {}
        binding_index: dict[tuple[ObjectID, ValueVersionID, str | None], list[ObjectBinding]] = {}
        if isinstance(self.graph, ValueGraph):
            for binding in self.graph.bindings:
                if (isinstance(binding, ObjectBinding)
                        and isinstance(binding.object_id, ObjectID)
                        and isinstance(binding.value_version, ValueVersionID)
                        and (binding.scope is None or type(binding.scope) is str)):
                    key = (binding.object_id, binding.value_version, binding.scope)
                    binding_index.setdefault(key, []).append(binding)
        for identity, record in objects.items():
            row_errors = record_errors(identity, ObjectID, "object table key")
            row_errors.extend(record_errors(record, PythonObjectRecord, "object table record"))
            if row_errors:
                errors.extend(row_errors)
                errors.append("object table contains an invalid identity or record")
                continue
            handle = record.handle
            if identity != handle.object_id:
                errors.append("object table key differs from handle ObjectID")
            if not identity.value.startswith(self.namespace + ":object:"):
                errors.append(f"object {identity.wire} is outside this capture namespace")
            if handle.version.version != 1:
                errors.append(f"object {identity.wire} must have one reference version")
            if handle.version in seen_versions:
                errors.append(f"object {identity.wire} shares a logical version with another object")
            seen_versions.add(handle.version)
            if handle.materialization in seen_materializations:
                errors.append(f"object {identity.wire} shares a materialization with another object")
            seen_materializations.add(handle.materialization)
            singleton_key = (record.representation if record.representation in (
                PythonObjectRepresentation.BOOL_TRUE, PythonObjectRepresentation.BOOL_FALSE)
                else record.tracking if record.tracking is ObjectTrackingKind.NONE_SINGLETON
                else None)
            if singleton_key is not None:
                if singleton_key in singleton_ids:
                    errors.append("Python singleton has more than one object-table identity")
                singleton_ids[singleton_key] = identity
            if isinstance(self.graph, ValueGraph):
                self._validate_projection(record, errors, binding_index)

        seen_observations: set[str] = set()
        observed_objects: set[ObjectID] = set()
        previous_event_ordinal = -1
        for observation in observations:
            observation_errors = record_errors(
                observation, ReferenceObservation, "reference observation")
            if observation_errors:
                errors.extend(observation_errors)
                errors.append("observations contains an invalid record")
                continue
            if observation.observation_id in seen_observations:
                errors.append("duplicate observation_id")
            seen_observations.add(observation.observation_id)
            if observation.at.scope != self.scope:
                errors.append("observation belongs to another capture scope")
            elif isinstance(self.current_event, EventPoint) and observation.at.ordinal > self.current_event.ordinal:
                errors.append("observation is later than current_event")
            if observation.at.ordinal < previous_event_ordinal:
                errors.append("observations are not in event order")
            previous_event_ordinal = observation.at.ordinal
            record = objects.get(observation.handle.object_id)
            if record is None or record.handle != observation.handle:
                errors.append("observation has no matching object table handle")
                continue
            if record.representation is not observation.representation:
                errors.append("observation representation differs from object record")
            observed_objects.add(observation.handle.object_id)
            if (observation.representation in (PythonObjectRepresentation.BOOL_TRUE,
                                               PythonObjectRepresentation.BOOL_FALSE)
                    and observation.type_category != "builtins.bool"):
                errors.append("bool singleton observation has the wrong type category")
            if (observation.representation is PythonObjectRepresentation.IDENTITY_REFERENCE
                    and observation.type_category == "builtins.bool"):
                errors.append("exact bool observation must identify its singleton")
            if (record.tracking is ObjectTrackingKind.NONE_SINGLETON
                    and observation.type_category != "builtins.NoneType"):
                errors.append("None singleton observation has the wrong type category")
            if (observation.type_category == "builtins.NoneType"
                    and record.tracking is not ObjectTrackingKind.NONE_SINGLETON):
                errors.append("None object must use the singleton tracking kind")

        if set(objects) != observed_objects:
            errors.append("object table contains an object with no reference observation")

        if graph_report is not None:
            overlaid_materializations = {
                record.handle.materialization for record in objects.values()
                if isinstance(record, PythonObjectRecord)
            }
            if not overlaid_materializations <= set(self.graph.materializations):
                errors.append("object table references missing graph materializations")
            if any(materialization.representation == "python_object_identity"
                   and materialization.id not in overlaid_materializations
                   for materialization in self.graph.materializations.values()):
                errors.append("orphan python_object_identity materialization has no object record")
        return {
            "schema": self.SCHEMA,
            "schema_version": self.SCHEMA_VERSION,
            "valid": not errors,
            "errors": errors,
            "counts": {"objects": len(objects), "observations": len(observations)},
        }

    def _validate_projection(self, record: PythonObjectRecord, errors: list[str],
                             binding_index: dict[tuple[ObjectID, ValueVersionID, str | None],
                                                 list[ObjectBinding]]) -> None:
        handle = record.handle
        graph = self.graph
        materialization = graph.materializations.get(handle.materialization)
        if materialization is None:
            errors.append(f"missing reference materialization {handle.materialization.wire}")
        elif (materialization.value_version != handle.version
              or materialization.id != handle.materialization
              or materialization.region is not None
              or materialization.representation != "python_object_identity"
              or materialization.device != "python"
              or materialization.producer is not None
              or materialization.ready_event is not None
              or materialization.validity_scope != self.scope
              or materialization.evidence != "Observed"
              or type(materialization.metadata) is not dict
              or materialization.metadata):
            errors.append(f"invalid object-only projection {handle.materialization.wire}")
        version = graph.versions.get(handle.version)
        if version is None or version.semantic_type != "python.object_reference":
            errors.append(f"missing python.object_reference version {handle.version.wire}")
        elif (version.id != handle.version or version.parent_versions
              or version.provenance_id is None or version.control_scope != self.scope
              or type(version.metadata) is not dict or version.metadata):
            errors.append(f"object reference version {handle.version.wire} has invalid provenance")
        else:
            provenance = graph.provenance.get(version.provenance_id)
            if (provenance is None or provenance.id != version.provenance_id
                    or provenance.relation is not ProvenanceRelation.ORIGIN
                    or provenance.inputs or provenance.outputs != (handle.version,)
                    or provenance.equivalence is not EquivalenceClaim.UNKNOWN
                    or provenance.producer is not None or provenance.evidence != "Observed"
                    or type(provenance.metadata) is not dict or provenance.metadata):
                errors.append(f"invalid origin provenance for {handle.version.wire}")
        logical = graph.logical_values.get(handle.version.logical_value)
        if (logical is None or logical.id != handle.version.logical_value
                or logical.semantic_type != "python.object_reference"
                or logical.description != "Capture-local Python object reference token."
                or type(logical.metadata) is not dict or logical.metadata):
            errors.append(f"missing python.object_reference value {handle.version.logical_value.wire}")
        bindings = binding_index.get((handle.object_id, handle.version, self.scope), [])
        if (len(bindings) != 1 or bindings[0].relation is not BindingRelation.REFERENCES
                or bindings[0].evidence != "Observed"
                or type(bindings[0].metadata) is not dict or bindings[0].metadata):
            errors.append(f"missing unique ObjectBinding for {handle.object_id.wire}")
        if record.representation in (PythonObjectRepresentation.BOOL_TRUE,
                                     PythonObjectRepresentation.BOOL_FALSE):
            if record.tracking is not ObjectTrackingKind.BOOL_SINGLETON:
                errors.append("bool singleton has the wrong tracking kind")
        elif record.tracking is ObjectTrackingKind.BOOL_SINGLETON:
            errors.append("bool tracking requires BOOL_TRUE or BOOL_FALSE")
        if record.tracking is ObjectTrackingKind.NONE_SINGLETON:
            if record.representation is not PythonObjectRepresentation.IDENTITY_REFERENCE:
                errors.append("None singleton must use IDENTITY_REFERENCE")

    def assert_valid(self) -> dict[str, Any]:
        report = self.validate()
        if not report["valid"]:
            raise ValueError("invalid Python object model: " + "; ".join(report["errors"]))
        return report

    def to_dict(self) -> dict[str, Any]:
        self.assert_valid()
        return {
            "schema": self.SCHEMA,
            "schema_version": self.SCHEMA_VERSION,
            "scope": self.scope,
            "namespace": self.namespace,
            "process_id": self.process_id,
            "current_event": encode(self.current_event),
            "graph": self.graph.to_dict(),
            "objects": encode(tuple(self.objects[key] for key in sorted(
                self.objects, key=lambda item: item.wire))),
            "observations": encode(tuple(self.observations)),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False)

    @classmethod
    def from_dict(cls, document: dict[str, Any]) -> "PythonObjectModel":
        fields = {"schema", "schema_version", "scope", "namespace", "process_id",
                  "current_event", "graph", "objects", "observations"}
        if type(document) is not dict or set(document) != fields:
            raise ValueError("invalid Python object model fields")
        if (document["schema"] != cls.SCHEMA
                or type(document["schema_version"]) is not int
                or document["schema_version"] != cls.SCHEMA_VERSION):
            raise ValueError("unsupported Python object model schema")
        event = decode(EventPoint, document["current_event"])
        objects_list = decode(tuple[PythonObjectRecord, ...], document["objects"])
        observations = list(decode(tuple[ReferenceObservation, ...], document["observations"]))
        objects: dict[ObjectID, PythonObjectRecord] = {}
        for record in objects_list:
            if record.handle.object_id in objects:
                raise ValueError("duplicate object table identity")
            objects[record.handle.object_id] = record
        graph = values_from_dict(document["graph"])
        model = cls(scope=decode(str, document["scope"]),
                    namespace=decode(str, document["namespace"]),
                    process_id=decode(int, document["process_id"]),
                    current_event=event, graph=graph, objects=objects,
                    observations=observations)
        model.assert_valid()
        return model

    @classmethod
    def from_json(cls, payload: str) -> "PythonObjectModel":
        return cls.from_dict(loads(payload))


def _handle_from_dict(value: Any) -> PythonObjectHandle:
    """Legacy internal hook for the narrow identity-execution record codec."""
    return decode(PythonObjectHandle, value)


__all__ = [
    "ObjectTrackingKind", "PythonObjectHandle", "PythonObjectModel",
    "PythonObjectRecord", "PythonObjectRepresentation", "ReferenceObservation",
]
