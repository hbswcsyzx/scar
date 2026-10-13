"""Capture direct Python object-reference samples without reading contents."""
from __future__ import annotations

from dataclasses import dataclass
import os
import uuid
import weakref
from typing import Any

from scar.ir.provenance import EventPoint
from scar.ir.python_objects_v2 import (
    ObjectTrackingKind, PythonObjectHandle, PythonObjectModel,
    PythonObjectRecord, PythonObjectRepresentation, ReferenceObservation,
)
from scar.ir.v2 import (
    BindingRelation, EquivalenceClaim, LogicalValue, LogicalValueID,
    Materialization, MaterializationID, ObjectBinding, ObjectID,
    ProvenanceID, ProvenanceRecord, ProvenanceRelation, ValueVersion,
    ValueVersionID,
)


_DEAD = object()


@dataclass(frozen=True, slots=True)
class _ProjectionSnapshot:
    record: PythonObjectRecord
    provenance_id: ProvenanceID
    binding_index: int


@dataclass(slots=True)
class _RuntimeReference:
    projection: _ProjectionSnapshot
    runtime_id: int
    weak_reference: weakref.ReferenceType[Any] | None = None
    strong_lease: Any | None = None

    @property
    def record(self) -> PythonObjectRecord:
        return self.projection.record

    def resolve(self) -> Any:
        if self.record.tracking is ObjectTrackingKind.BOOL_SINGLETON:
            return self.record.representation is PythonObjectRepresentation.BOOL_TRUE
        if self.record.tracking is ObjectTrackingKind.NONE_SINGLETON:
            return None
        if self.strong_lease is not None:
            return self.strong_lease
        if self.weak_reference is not None:
            value = self.weak_reference()
            return _DEAD if value is None else value
        return _DEAD


@dataclass(frozen=True, slots=True)
class _CapturedSample:
    observation: ReferenceObservation
    observation_index: int
    projection: _ProjectionSnapshot


class PythonObjectObserver:
    """Build a capture-local object table and one regionless graph projection.

    Every observer receives a random internal scope and namespace.  An
    explicit namespace is only a label and cannot make IDs collide across
    captures.  Weak references are preferred; strong leases are opt-in and
    bounded by object count.
    """

    def __init__(self, scope: str = "python-objects", namespace: str | None = None,
                 max_strong_leases: int = 0, max_observations: int = 100_000,
                 allow_strong_leases: bool = False):
        if type(scope) is not str or not scope:
            raise ValueError("scope must be a non-empty string")
        if namespace is not None and (type(namespace) is not str or not namespace):
            raise ValueError("namespace must be None or a non-empty string")
        if type(max_strong_leases) is not int or max_strong_leases < 0:
            raise ValueError("max_strong_leases must be a non-negative integer")
        if type(max_observations) is not int or max_observations < 1:
            raise ValueError("max_observations must be a positive integer")
        if type(allow_strong_leases) is not bool:
            raise TypeError("allow_strong_leases must be bool")
        if max_strong_leases and not allow_strong_leases:
            raise ValueError("max_strong_leases requires allow_strong_leases=True")

        capture_id = uuid.uuid4().hex
        self._scope = f"{scope}:{capture_id}"
        self._namespace = f"{namespace or scope}:{capture_id}"
        self._process_id = os.getpid()
        self._max_strong_leases = max_strong_leases
        self._max_observations = max_observations
        self._allow_strong_leases = allow_strong_leases
        self._closed = False
        self._next_object = 0
        self._next_event = 0
        self._observation_count = 0
        self._strong_lease_count = 0
        start = EventPoint(self._scope, 0, "start")
        self._current_event = start
        self._issued_events: set[EventPoint] = {start}
        self._runtime_objects: dict[ObjectID, _RuntimeReference] = {}
        self._runtime_ids: dict[int, list[_RuntimeReference]] = {}
        self._samples: dict[str, _CapturedSample] = {}
        self._samples_by_key: dict[tuple[PythonObjectHandle, EventPoint], list[_CapturedSample]] = {}
        self._model = PythonObjectModel(
            scope=self._scope,
            namespace=self._namespace,
            process_id=self._process_id,
            current_event=start,
        )

    @property
    def model(self) -> PythonObjectModel:
        return self._model

    @property
    def graph(self):
        return self._model.graph

    @property
    def current_event(self) -> EventPoint:
        return self._current_event

    def event(self, label: str) -> EventPoint:
        """Issue the next point on this capture's shared event clock."""
        self._ensure_open()
        if type(label) is not str:
            raise TypeError("event label must be a string")
        self._next_event += 1
        point = EventPoint(self._scope, self._next_event, label)
        self._issued_events.add(point)
        self._current_event = point
        self._model.current_event = point
        return point

    def observe(self, value: Any, *, at: EventPoint | None = None) -> PythonObjectHandle:
        """Append one actual reference sample and return its stable handle."""
        self._ensure_open()
        if self._observation_count >= self._max_observations:
            raise RuntimeError("Python object observation budget exhausted")
        if self._model.current_event != self._current_event:
            raise ValueError("Python object model event clock was modified")
        if at is None:
            at = self._current_event
        if not isinstance(at, EventPoint) or at not in self._issued_events:
            raise ValueError("at must be an EventPoint previously issued by this observer")
        if at != self._current_event:
            raise ValueError("observations must use the current observer event")

        representation = self._representation(value)
        type_category = self._type_category(value)
        runtime_id = id(value)
        runtime_reference = self._find_reference(value, runtime_id)
        if runtime_reference is not None and not self._projection_is_intact(runtime_reference.projection):
            raise ValueError("Python object graph projection was modified")
        if runtime_reference is None:
            runtime_reference = self._new_reference(value, runtime_id, representation)

        observation = ReferenceObservation(
            observation_id=f"python-reference-sample:{uuid.uuid4().hex}",
            handle=runtime_reference.record.handle,
            at=at,
            representation=representation,
            type_category=type_category,
        )
        observation_index = len(self._model.observations)
        self._model.observations.append(observation)
        sample = _CapturedSample(observation, observation_index, runtime_reference.projection)
        self._samples[observation.observation_id] = sample
        self._samples_by_key.setdefault((observation.handle, at), []).append(sample)
        self._observation_count += 1
        return runtime_reference.record.handle

    def attest_observation(self, handle: PythonObjectHandle, at: EventPoint,
                           observation_id: str | None = None) -> bool:
        """Check a historical sample against this collector's private record.

        This does not inspect current liveness and does not create a guard for
        future calls.  Loaded models have no private sample record.
        """
        if not isinstance(handle, PythonObjectHandle) or not isinstance(at, EventPoint):
            return False
        if observation_id is not None:
            samples = [self._samples.get(observation_id)]
        else:
            samples = self._samples_by_key.get((handle, at), ())
        return any(sample is not None
                   and sample.observation.handle == handle
                   and sample.observation.at == at
                   and sample.observation_index < len(self._model.observations)
                   and self._model.observations[sample.observation_index] == sample.observation
                   and self._model.objects.get(handle.object_id) == sample.projection.record
                   and self._model.current_event == self._current_event
                   and self._projection_is_intact(sample.projection)
                   for sample in samples)

    def close(self) -> None:
        """Release all strong leases. Historical records remain non-live data."""
        if self._closed:
            return
        self._closed = True
        for reference in self._runtime_objects.values():
            reference.strong_lease = None
        self._strong_lease_count = 0
        self._runtime_ids.clear()
        self._runtime_objects.clear()

    def _new_reference(self, value: Any, runtime_id: int,
                       representation: PythonObjectRepresentation) -> _RuntimeReference:
        tracking, weak_reference, strong_lease = self._tracking(value, representation)
        self._next_object += 1
        object_id = ObjectID(f"{self._namespace}:object:{self._next_object}")
        logical_value = LogicalValueID(f"{self._namespace}:reference:{self._next_object}")
        version = ValueVersionID(logical_value, 1)
        provenance_id = ProvenanceID(f"{self._namespace}:origin:{self._next_object}")
        materialization_id = MaterializationID(
            f"{self._namespace}:materialization:{self._next_object}")
        handle = PythonObjectHandle(object_id, version, materialization_id)
        record = PythonObjectRecord(handle, representation, tracking)

        self._model.graph.add_logical_value(LogicalValue(
            logical_value,
            semantic_type="python.object_reference",
            description="Capture-local Python object reference token.",
        ))
        self._model.graph.add_provenance(ProvenanceRecord(
            provenance_id,
            relation=ProvenanceRelation.ORIGIN,
            inputs=(),
            outputs=(version,),
            equivalence=EquivalenceClaim.UNKNOWN,
            evidence="Observed",
        ))
        self._model.graph.add_version(ValueVersion(
            version,
            provenance_id=provenance_id,
            semantic_type="python.object_reference",
            control_scope=self._scope,
        ))
        self._model.graph.add_binding(ObjectBinding(
            object_id, version, relation=BindingRelation.REFERENCES,
            scope=self._scope, evidence="Observed",
        ))
        binding_index = len(self._model.graph.bindings) - 1
        self._model.graph.add_materialization(Materialization(
            materialization_id,
            value_version=version,
            representation="python_object_identity",
            device="python",
            region=None,
            validity_scope=self._scope,
            evidence="Observed",
        ))
        self._model.objects[object_id] = record
        projection = _ProjectionSnapshot(record, provenance_id, binding_index)
        runtime_reference = _RuntimeReference(
            projection, runtime_id,
            weak_reference=weak_reference, strong_lease=strong_lease,
        )
        self._runtime_objects[object_id] = runtime_reference
        self._runtime_ids.setdefault(runtime_id, []).append(runtime_reference)
        if tracking is ObjectTrackingKind.STRONG_LEASE:
            self._strong_lease_count += 1
        return runtime_reference

    def _projection_is_intact(self, projection: _ProjectionSnapshot) -> bool:
        record = projection.record
        handle = record.handle
        if self._model.objects.get(handle.object_id) != record:
            return False
        graph = self._model.graph
        logical = graph.logical_values.get(handle.version.logical_value)
        if (logical is None or logical.id != handle.version.logical_value
                or logical.semantic_type != "python.object_reference"
                or logical.description != "Capture-local Python object reference token."
                or type(logical.metadata) is not dict or logical.metadata):
            return False
        version = graph.versions.get(handle.version)
        if (version is None or version.id != handle.version
                or version.provenance_id != projection.provenance_id
                or version.parent_versions != ()
                or version.semantic_type != "python.object_reference"
                or version.control_scope != self._scope
                or type(version.metadata) is not dict or version.metadata):
            return False
        provenance = graph.provenance.get(projection.provenance_id)
        if (provenance is None or provenance.id != projection.provenance_id
                or provenance.relation is not ProvenanceRelation.ORIGIN
                or provenance.inputs != () or provenance.outputs != (handle.version,)
                or provenance.equivalence is not EquivalenceClaim.UNKNOWN
                or provenance.producer is not None
                or provenance.evidence != "Observed"
                or type(provenance.metadata) is not dict or provenance.metadata):
            return False
        materialization = graph.materializations.get(handle.materialization)
        if (materialization is None or materialization.id != handle.materialization
                or materialization.value_version != handle.version
                or materialization.representation != "python_object_identity"
                or materialization.device != "python" or materialization.region is not None
                or materialization.producer is not None or materialization.ready_event is not None
                or materialization.validity_scope != self._scope
                or materialization.evidence != "Observed"
                or type(materialization.metadata) is not dict or materialization.metadata):
            return False
        index = projection.binding_index
        if index >= len(graph.bindings):
            return False
        binding = graph.bindings[index]
        return (isinstance(binding, ObjectBinding)
                and binding.object_id == handle.object_id
                and binding.value_version == handle.version
                and binding.relation is BindingRelation.REFERENCES
                and binding.scope == self._scope
                and binding.evidence == "Observed"
                and type(binding.metadata) is dict and not binding.metadata)

    def _tracking(self, value: Any, representation: PythonObjectRepresentation):
        if representation in (PythonObjectRepresentation.BOOL_TRUE,
                              PythonObjectRepresentation.BOOL_FALSE):
            return ObjectTrackingKind.BOOL_SINGLETON, None, None
        if value is None:
            return ObjectTrackingKind.NONE_SINGLETON, None, None
        try:
            return ObjectTrackingKind.WEAK_REFERENCE, weakref.ref(value), None
        except TypeError:
            if not self._allow_strong_leases:
                raise TypeError(
                    "object is not weak-referenceable; bounded strong leases are disabled")
            if self._strong_lease_count >= self._max_strong_leases:
                raise RuntimeError("Python object strong-lease budget exhausted")
            return ObjectTrackingKind.STRONG_LEASE, None, value

    def _find_reference(self, value: Any, runtime_id: int) -> _RuntimeReference | None:
        bucket = self._runtime_ids.get(runtime_id, [])
        live: list[_RuntimeReference] = []
        match = None
        for entry in bucket:
            candidate = entry.resolve()
            if candidate is _DEAD:
                continue
            live.append(entry)
            if candidate is value:
                match = entry
        if live:
            self._runtime_ids[runtime_id] = live
        else:
            self._runtime_ids.pop(runtime_id, None)
        return match

    @staticmethod
    def _representation(value: Any) -> PythonObjectRepresentation:
        if type(value) is bool:
            return (PythonObjectRepresentation.BOOL_TRUE if value is True
                    else PythonObjectRepresentation.BOOL_FALSE)
        return PythonObjectRepresentation.IDENTITY_REFERENCE

    @staticmethod
    def _type_category(value: Any) -> str:
        # Reading special attributes from a user-defined type can invoke a
        # descriptor on its metaclass.  These are the only categories needed
        # by the object-reference schema; everything else stays opaque.
        if value is None:
            return "builtins.NoneType"
        if type(value) is bool:
            return "builtins.bool"
        return "opaque.python-object"

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("PythonObjectObserver is closed")


__all__ = ["PythonObjectObserver"]
