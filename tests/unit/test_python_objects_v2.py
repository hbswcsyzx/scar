import gc
from dataclasses import replace
import weakref

import pytest

from scar.ir.provenance import EventPoint
from scar.ir.python_objects_v2 import (
    ObjectTrackingKind, PythonObjectHandle, PythonObjectModel,
    PythonObjectRepresentation,
)
from scar.ir.record_codec import decode
from scar.ir.v2 import (
    LogicalValue, LogicalValueID, Materialization, MaterializationID,
    OperationInstanceID, ProvenanceID, ValueVersion, ValueVersionID,
)
from scar.trace.python_objects_v2 import PythonObjectObserver


class IdentityOnly:
    def __init__(self, content):
        self.content = content

    def __eq__(self, other):
        raise AssertionError("object equality must not be called")

    def __hash__(self):
        raise AssertionError("object hashing must not be called")

    def __repr__(self):
        raise AssertionError("object repr must not be called")


def test_one_reference_has_one_materialization_and_many_sample_records():
    observer = PythonObjectObserver(scope="fixture")
    event = observer.event("arguments")
    value = IdentityOnly([1])

    first = observer.observe(value, at=event)
    first_sample = observer.model.observations[-1]
    value.content.append(2)
    second = observer.observe(value, at=event)
    second_sample = observer.model.observations[-1]

    assert first == second
    assert first.materialization == second.materialization
    assert first.version == second.version
    assert first_sample.observation_id != second_sample.observation_id
    assert len(observer.model.objects) == 1
    assert len(observer.model.observations) == 2
    assert len(observer.graph.materializations) == 1
    assert observer.model.validate()["valid"]
    assert observer.attest_observation(first, event, first_sample.observation_id)
    assert observer.attest_observation(second, event, second_sample.observation_id)


def test_repeated_sample_uses_private_handle_index_not_full_model_validation(monkeypatch):
    observer = PythonObjectObserver()
    event = observer.event("many-operands")
    values = [IdentityOnly(index) for index in range(32)]
    handles = [observer.observe(value, at=event) for value in values]
    full_validation_calls = 0
    original_validate = observer.model.validate

    def count_validation_calls():
        nonlocal full_validation_calls
        full_validation_calls += 1
        return original_validate()

    monkeypatch.setattr(observer.model, "validate", count_validation_calls)
    for _ in range(8):
        assert observer.observe(values[0], at=event) == handles[0]

    assert full_validation_calls == 0
    assert len(observer.model.objects) == 32
    assert len(observer.model.observations) == 40


def test_equal_but_distinct_objects_keep_distinct_capture_ids_without_dispatch():
    observer = PythonObjectObserver()
    event = observer.event("operands")
    left = IdentityOnly("same")
    right = IdentityOnly("same")

    left_handle = observer.observe(left, at=event)
    right_handle = observer.observe(right, at=event)

    assert left_handle.object_id != right_handle.object_id
    assert left_handle.version != right_handle.version
    assert left_handle.materialization != right_handle.materialization
    assert observer.model.validate()["valid"]


def test_user_metaclass_type_properties_are_not_read_for_type_category():
    property_calls = []

    class Meta(type):
        @property
        def __module__(cls):
            property_calls.append("module")
            return "untrusted.module"

    class UserValue(metaclass=Meta):
        pass

    class SpoofedBoolName:
        pass

    SpoofedBoolName.__module__ = "builtins"
    SpoofedBoolName.__qualname__ = "bool"

    observer = PythonObjectObserver()
    handle = observer.observe(UserValue())
    sample = observer.model.observations[-1]
    spoof_handle = observer.observe(SpoofedBoolName())
    spoof_sample = observer.model.observations[-1]

    assert property_calls == []
    assert sample.type_category == "opaque.python-object"
    assert observer.attest_observation(handle, sample.at, sample.observation_id)
    assert spoof_sample.type_category == "opaque.python-object"
    assert observer.model.objects[spoof_handle.object_id].representation is PythonObjectRepresentation.IDENTITY_REFERENCE
    assert observer.model.validate()["valid"]


def test_true_false_use_actual_singleton_representations_and_stable_handles():
    observer = PythonObjectObserver()
    event = observer.event("bool-operands")

    true_handle = observer.observe(True, at=event)
    true_sample = observer.model.observations[-1]
    assert observer.observe(True, at=event) == true_handle
    false_handle = observer.observe(False, at=event)
    false_sample = observer.model.observations[-1]

    assert true_handle.object_id != false_handle.object_id
    assert true_handle.materialization == observer.model.observations[-2].handle.materialization
    assert observer.model.objects[true_handle.object_id].representation is PythonObjectRepresentation.BOOL_TRUE
    assert observer.model.objects[false_handle.object_id].representation is PythonObjectRepresentation.BOOL_FALSE
    assert observer.model.objects[true_handle.object_id].tracking is ObjectTrackingKind.BOOL_SINGLETON
    assert true_sample.type_category == false_sample.type_category == "builtins.bool"
    assert len(observer.graph.materializations) == 2
    assert len(observer.model.observations) == 3


def test_unweakrefable_values_need_a_bounded_opt_in_lease_and_close_releases_it():
    finalized = []

    class NoWeakReference:
        __slots__ = ()

        def __del__(self):
            finalized.append(True)

    default_observer = PythonObjectObserver()
    with pytest.raises(TypeError, match="not weak-referenceable"):
        default_observer.observe([])
    assert not default_observer.model.objects
    default_observer.close()

    observer = PythonObjectObserver(allow_strong_leases=True, max_strong_leases=1)
    value = NoWeakReference()
    handle = observer.observe(value)
    assert observer.model.objects[handle.object_id].tracking is ObjectTrackingKind.STRONG_LEASE
    del value
    gc.collect()
    assert finalized == []
    with pytest.raises(RuntimeError, match="lease budget"):
        observer.observe([])
    observer.close()
    gc.collect()
    assert finalized == [True]
    assert observer.attest_observation(handle, observer.model.observations[0].at)


def test_weak_collection_keeps_history_but_a_later_object_gets_a_new_id():
    observer = PythonObjectObserver()
    event = observer.event("sample")
    value = IdentityOnly("first")
    dead_reference = weakref.ref(value)
    first = observer.observe(value, at=event)
    first_sample = observer.model.observations[-1]
    del value
    gc.collect()

    assert dead_reference() is None
    assert observer.attest_observation(first, event, first_sample.observation_id)
    replacement = IdentityOnly("replacement")
    second = observer.observe(replacement, at=event)
    assert second.object_id != first.object_id
    assert observer.model.validate()["valid"]


def test_namespace_scope_and_event_points_are_capture_local_and_monotone():
    first = PythonObjectObserver(scope="same", namespace="user-label")
    second = PythonObjectObserver(scope="same", namespace="user-label")
    assert first.model.scope != second.model.scope
    assert first.model.namespace != second.model.namespace

    event = first.event("sample")
    value = IdentityOnly(1)
    handle = first.observe(value, at=event)
    other_handle = second.observe(value)
    assert handle.object_id != other_handle.object_id
    with pytest.raises(ValueError, match="current observer event"):
        first.observe(value, at=EventPoint(first.current_event.scope, 0, "start"))
    with pytest.raises(ValueError, match="previously issued"):
        first.observe(value, at=EventPoint(first.current_event.scope, 20, "future"))
    with pytest.raises(ValueError, match="previously issued"):
        first.observe(value, at=second.current_event)
    assert not second.attest_observation(handle, event)


def test_loaded_model_is_history_and_does_not_restore_private_attestation():
    observer = PythonObjectObserver()
    event = observer.event("sample")
    value = IdentityOnly("value")
    handle = observer.observe(value, at=event)
    sample = observer.model.observations[-1]

    loaded = PythonObjectModel.from_json(observer.model.to_json())
    assert loaded.validate()["valid"]
    assert loaded.observations == observer.model.observations
    other = PythonObjectObserver()
    assert not other.attest_observation(handle, event, sample.observation_id)

    observer.model.observations[0] = replace(sample, type_category="forged.Type")
    assert not observer.attest_observation(handle, event, sample.observation_id)
    observer.model.observations[0] = sample
    observer.graph.bindings[0].evidence = "forged"
    assert not observer.attest_observation(handle, event, sample.observation_id)


def test_provenance_mutation_breaks_model_validation_and_private_attestation():
    observer = PythonObjectObserver()
    event = observer.event("bool-source")
    handle = observer.observe(True, at=event)
    sample = observer.model.observations[-1]
    version = observer.graph.versions[handle.version]
    provenance = observer.graph.provenance[version.provenance_id]

    assert observer.attest_observation(handle, event, sample.observation_id)
    provenance.producer = OperationInstanceID("injected-producer")
    assert not observer.model.validate()["valid"]
    assert not observer.attest_observation(handle, event, sample.observation_id)

    provenance.producer = None
    assert observer.model.validate()["valid"]
    provenance.id = ProvenanceID("injected-provenance-id")
    assert not observer.model.validate()["valid"]
    assert not observer.attest_observation(handle, event, sample.observation_id)


def test_unannotated_regionless_materialization_is_not_an_object_record():
    observer = PythonObjectObserver()
    graph = observer.graph
    logical_id = LogicalValueID("legacy-regionless")
    version_id = ValueVersionID(logical_id, 1)
    graph.add_logical_value(LogicalValue(logical_id, "legacy.value"))
    graph.add_version(ValueVersion(version_id, semantic_type="legacy.value"))
    graph.add_materialization(Materialization(
        MaterializationID("legacy-regionless"), version_id,
        representation="snapshot_only", device="unknown", region=None,
    ))

    assert observer.model.validate()["valid"]
    assert not observer.model.objects
    assert not observer.model.handles


def test_model_decoder_uses_strict_typed_record_codec():
    observer = PythonObjectObserver()
    event = observer.event("sample")
    handle = observer.observe(IdentityOnly(1), at=event)
    assert decode(PythonObjectHandle, handle.as_dict()) == handle

    document = observer.model.to_dict()
    document["objects"][0]["tracking"] = "MADE_UP"
    with pytest.raises(ValueError):
        PythonObjectModel.from_dict(document)

    document = observer.model.to_dict()
    document["extra"] = True
    with pytest.raises(ValueError, match="fields"):
        PythonObjectModel.from_dict(document)
