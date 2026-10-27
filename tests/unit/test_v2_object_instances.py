"""Object identity registration must not manufacture logical contents."""
from copy import deepcopy
import json

import pytest

import scar.ir.v2 as ir
from scar.ir.v2.codec import values_from_dict


SCOPE = "capture:example/process:41"
CLAIM = ir.EvidenceClaim(
    ir.EvidenceKind.OBSERVED, ("calls.jsonl#/events/7",), scope=SCOPE)


def _object_graph():
    graph = ir.ValueGraph()
    instance = ir.ObjectInstance(
        ir.ObjectID("capture:example/weak:41:7"), SCOPE, (CLAIM,),
        {"collector": "weakref", "token": "weak:41:7"})
    graph.add_object(instance)
    return graph, instance


def _legacy_document():
    """The pre-directory Values1 document, including its original counts."""
    return {
        "schema": "scar.ir.v2.values", "schema_version": 1,
        "logical_values": [{
            "id": {"kind": "lv", "value": "payload", "wire": "lv:payload"},
            "semantic_type": "opaque", "description": "", "metadata": {},
        }],
        "versions": [{
            "id": {
                "logical_value": {"kind": "lv", "value": "payload", "wire": "lv:payload"},
                "version": 0, "wire": "lv:payload@v0",
            },
            "provenance_id": None, "parent_versions": [],
            "semantic_type": None, "control_scope": None, "metadata": {},
        }],
        "provenance": [], "allocations": [], "regions": [], "materializations": [],
        "bindings": [{
            "object_id": {"kind": "object", "value": "legacy", "wire": "object:legacy"},
            "value_version": {
                "logical_value": {"kind": "lv", "value": "payload", "wire": "lv:payload"},
                "version": 0, "wire": "lv:payload@v0",
            },
            "relation": "references", "scope": None,
            "evidence": "Observed", "metadata": {},
        }],
        "validation": {
            "schema": "scar.ir.v2.values", "schema_version": 1,
            "valid": True, "errors": [],
            "counts": {
                "logical_values": 1, "versions": 1, "provenance": 0,
                "allocations": 0, "regions": 0, "materializations": 0, "bindings": 1,
            },
        },
    }


def test_metadata_only_object_round_trip_needs_no_content_or_lifetime():
    graph, instance = _object_graph()
    document = graph.to_dict()
    assert document["schema_version"] == 2
    assert document["validation"]["counts"]["objects"] == 1
    assert document["objects"] == [instance.as_dict()]
    assert graph.object_ids() == {instance.id}
    assert graph.has_object(instance.id)
    assert not graph.has_object(ir.ObjectID("absent"))
    assert graph.logical_values == graph.versions == graph.materializations == {}
    assert graph.bindings == []
    assert set(document["objects"][0]) == {"id", "scope", "evidence", "metadata"}
    restored = values_from_dict(json.loads(ir.canonical_json(document)))
    assert restored.objects[instance.id] == instance
    assert ir.canonical_json(restored) == ir.canonical_json(document)


def test_empty_values1_canonical_bytes_are_unchanged():
    expected = (
        '{"allocations":[],"bindings":[],"logical_values":[],"materializations":[],'
        '"provenance":[],"regions":[],"schema":"scar.ir.v2.values","schema_version":1,'
        '"validation":{"counts":{"allocations":0,"bindings":0,"logical_values":0,'
        '"materializations":0,"provenance":0,"regions":0,"versions":0},"errors":[],'
        '"schema":"scar.ir.v2.values","schema_version":1,"valid":true},"versions":[]}'
    )
    assert ir.canonical_json(ir.ValueGraph()).encode("utf8") == expected.encode("utf8")
    restored = values_from_dict(json.loads(expected))
    assert ir.canonical_json(restored) == expected


def test_legacy_binding_document_and_implicit_owner_are_unchanged():
    document = _legacy_document()
    graph = values_from_dict(deepcopy(document))
    legacy = ir.ObjectID("legacy")
    assert graph.objects == {}
    assert graph.object_ids() == {legacy}
    assert graph.has_object(legacy)
    assert graph.to_dict() == document
    assert ir.canonical_json(graph) == ir.canonical_json(document)
    # Adding an independent identity does not invalidate historical bindings.
    _, instance = _object_graph()
    graph.add_object(instance)
    assert graph.object_ids() == {legacy, instance.id}
    assert graph.has_object(legacy)
    assert graph.assert_valid()["valid"]
    assert graph.to_dict()["schema_version"] == 2
    del graph.objects[instance.id]
    assert graph.to_dict() == document


def test_one_object_can_have_two_content_links_without_selecting_a_current_version():
    graph, instance = _object_graph()
    logical = ir.LogicalValueID("mutable")
    graph.add_logical_value(ir.LogicalValue(logical, "opaque"))
    versions = (ir.ValueVersionID(logical, 0), ir.ValueVersionID(logical, 1))
    for version in versions:
        graph.add_version(ir.ValueVersion(version))
        graph.add_binding(ir.ObjectBinding(instance.id, version))
    assert graph.object_ids() == {instance.id}
    restored = values_from_dict(graph.to_dict())
    assert restored.objects == graph.objects
    assert tuple(binding.value_version for binding in restored.bindings) == versions
    assert len(restored.versions) == 2


def test_duplicate_object_registration_and_wire_ids_are_rejected():
    graph, instance = _object_graph()
    with pytest.raises(ValueError, match="duplicate object"):
        graph.add_object(instance)
    document = graph.to_dict()
    document["objects"].append(deepcopy(document["objects"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        values_from_dict(document)


@pytest.mark.parametrize("objects", ([], "populated"))
def test_values1_rejects_the_objects_field_even_when_empty(objects):
    graph, _ = _object_graph()
    document = _legacy_document()
    document["objects"] = [] if objects == [] else graph.to_dict()["objects"]
    with pytest.raises(ValueError, match="unknown fields.*objects"):
        values_from_dict(document)


def test_values2_requires_a_directory_but_empty_directory_normalizes_to_values1():
    document = _legacy_document()
    document["schema_version"] = 2
    with pytest.raises(ValueError, match="missing required field objects"):
        values_from_dict(document)
    document["objects"] = []
    graph = values_from_dict(document)
    assert graph.to_dict() == _legacy_document()


@pytest.mark.parametrize("version", (True, 0, 3, "2", None))
def test_object_directory_rejects_unsupported_or_coerced_wire_versions(version):
    graph, _ = _object_graph()
    document = graph.to_dict()
    document["schema_version"] = version
    with pytest.raises(ValueError, match="schema_version"):
        values_from_dict(document)


@pytest.mark.parametrize("field,value", (
    ("id", ir.LogicalValueID("wrong-kind")),
    ("scope", ""),
    ("scope", None),
    ("evidence", ()),
    ("evidence", [CLAIM]),
    ("evidence", ("not-a-claim",)),
    ("metadata", []),
    ("metadata", {1: "not-a-string-key"}),
))
def test_mutated_object_records_are_rechecked_at_the_graph_boundary(field, value):
    graph, instance = _object_graph()
    setattr(instance, field, value)
    report = graph.validate()
    assert not report["valid"]
    assert any(field in error for error in report["errors"])
    with pytest.raises(ValueError, match="invalid v2 ValueGraph"):
        graph.to_dict()


@pytest.mark.parametrize("field,value", (
    ("scope", ""), ("evidence", []), ("metadata", []),
))
def test_reader_rejects_invalid_object_fields(field, value):
    graph, _ = _object_graph()
    document = graph.to_dict()
    document["objects"][0][field] = value
    with pytest.raises(ValueError):
        values_from_dict(document)


def test_reader_rejects_unknown_object_record_fields():
    graph, _ = _object_graph()
    document = graph.to_dict()
    document["objects"][0]["birth"] = "not-an-observation"
    with pytest.raises(ValueError, match="unknown fields.*birth"):
        values_from_dict(document)


def test_nested_claims_and_registry_keys_are_rechecked_without_content_links():
    graph, instance = _object_graph()
    instance.evidence = (ir.EvidenceClaim(ir.EvidenceKind.OBSERVED, (7,)),)
    report = graph.validate()
    assert not report["valid"]
    assert any("evidence" in error for error in report["errors"])
    instance.evidence = (CLAIM,)
    graph.objects = {ir.ObjectID("wrong-key"): instance}
    report = graph.validate()
    assert not report["valid"]
    assert any("key does not match" in error for error in report["errors"])
