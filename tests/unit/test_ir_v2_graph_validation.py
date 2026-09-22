"""Corruptions at graph trust boundaries must fail before reaching a planner."""
import pytest

from scar.ir.v2 import (
    ControlRegion, ControlRegionID, EvidenceClaim, EvidenceEdge,
    EvidenceEndpoint, EvidenceGraph, EvidenceKind, EvidenceNodeKind,
    EvidenceRelation, LogicalValue, LogicalValueID, Materialization,
    MaterializationID, ObjectID, OperationDefinition, OperationDefinitionID,
    OperationInstance, OperationInstanceID, OperationKind, ProvenanceID,
    ProvenanceRecord, ProvenanceRelation, SemanticEdge, SemanticEndpoint,
    SemanticGraph, SemanticNodeKind, SemanticRelation, SourceAtomID,
    StorageAllocation, StorageAllocationID, StorageRegion, StorageRegionID,
    ValueGraph, ValueObservation, ValueSlot, ValueSlotID, ValueVersion,
    ValueVersionID,
)


CLAIM = EvidenceClaim(EvidenceKind.DECLARED)


def semantic_pair():
    graph = SemanticGraph()
    outer = OperationDefinition(OperationDefinitionID("outer"), OperationKind.FUNCTION, "outer")
    inner = OperationDefinition(OperationDefinitionID("inner"), OperationKind.FUNCTION, "inner",
                                parent_id=outer.id)
    graph.add_definition(outer)
    graph.add_definition(inner)
    return graph, outer, inner


def execution_pair():
    graph = EvidenceGraph()
    outer = OperationInstance(OperationInstanceID("outer"), OperationDefinitionID("fn"), 1, 1)
    inner = OperationInstance(OperationInstanceID("inner"), OperationDefinitionID("fn"), 1, 1,
                              parent=outer.id)
    graph.add_instance(outer)
    graph.add_instance(inner)
    return graph, outer, inner


def value_fixture():
    graph = ValueGraph()
    value = LogicalValue(LogicalValueID("tensor"), "tensor")
    version = ValueVersion(ValueVersionID(value.id, 0))
    allocation = StorageAllocation(StorageAllocationID("cpu"), "cpu", 16)
    region = StorageRegion(StorageRegionID("view"), allocation.id, 0, (4,), (1,), "float32", "cpu")
    materialization = Materialization(MaterializationID("tensor"), version.id, "dense", "cpu", region.id)
    graph.add_logical_value(value)
    graph.add_version(version)
    graph.add_allocation(allocation)
    graph.add_region(region)
    graph.add_materialization(materialization)
    return graph, version, allocation, region, materialization


def rejects(graph, message):
    report = graph.validate()
    assert not report["valid"], report
    assert any(message in error for error in report["errors"]), report
    with pytest.raises(ValueError):
        graph.to_dict()


def test_semantic_parent_and_mixed_containment_cycles_are_rejected():
    graph, outer, inner = semantic_pair()
    outer.parent_id = inner.id
    rejects(graph, "cyclic")
    with pytest.raises(ValueError, match="cyclic"):
        graph.descendants_of(outer.id)
    outer.parent_id = None
    graph.add_edge(SemanticEdge(
        "reverse-containment", SemanticRelation.CONTAINS,
        SemanticEndpoint(SemanticNodeKind.OPERATION, inner.id),
        SemanticEndpoint(SemanticNodeKind.OPERATION, outer.id), CLAIM))
    rejects(graph, "cyclic")


def test_recursive_semantic_calls_are_valid_not_containment_cycles():
    graph, outer, _ = semantic_pair()
    endpoint = SemanticEndpoint(SemanticNodeKind.OPERATION, outer.id)
    graph.add_edge(SemanticEdge("recursion", SemanticRelation.CALLS, endpoint, endpoint, CLAIM))
    assert graph.assert_valid()["valid"]


@pytest.mark.parametrize("field,value,expected", [
    ("parent_id", ControlRegionID("missing"), "unknown parent"),
    ("owner", OperationDefinitionID("missing"), "unknown owner"),
    ("source_atoms", (SourceAtomID("missing"),), "unknown source"),
])
def test_semantic_control_references_are_revalidated(field, value, expected):
    graph, outer, _ = semantic_pair()
    control = ControlRegion(ControlRegionID("loop"), "loop", owner=outer.id)
    graph.add_control(control)
    setattr(control, field, value)
    rejects(graph, expected)


def test_semantic_control_cycles_and_slot_ownership_are_rejected():
    graph, outer, inner = semantic_pair()
    control = ControlRegion(ControlRegionID("loop"), "loop")
    graph.add_control(control)
    control.parent_id = control.id
    rejects(graph, "cyclic")
    control.parent_id = None
    slot = ValueSlot(ValueSlotID("input"), "x", "input", owner=inner.id)
    graph.add_slot(slot)
    outer.input_slots = (slot.slot_id,)
    rejects(graph, "owned by another")
    outer.input_slots = ()
    slot.owner = OperationDefinitionID("deleted")
    rejects(graph, "unknown owner")


def test_wrong_semantic_relation_endpoints_are_rejected():
    graph, outer, _ = semantic_pair()
    slot = ValueSlot(ValueSlotID("x"), "x", "input", owner=outer.id)
    graph.add_slot(slot)
    with pytest.raises(ValueError, match="invalid endpoints"):
        SemanticEdge("nonsense", SemanticRelation.CALLS,
                     SemanticEndpoint(SemanticNodeKind.VALUE_SLOT, slot.slot_id),
                     SemanticEndpoint(SemanticNodeKind.OPERATION, outer.id), CLAIM)


@pytest.mark.parametrize("corruption", ["wrong-key", "wrong-type", "wrong-record"])
def test_graph_registry_corruption_is_reported_without_crashing(corruption):
    graph, outer, _ = semantic_pair()
    if corruption == "wrong-key":
        graph.definitions[OperationDefinitionID("other")] = outer
    elif corruption == "wrong-type":
        outer.id = ObjectID("outer")
    else:
        graph.definitions[OperationDefinitionID("other")] = "not a definition"
    rejects(graph, "definitions")


def test_evidence_parent_and_happens_before_cycles_are_rejected():
    graph, outer, inner = execution_pair()
    outer.parent = inner.id
    rejects(graph, "cyclic operation instance ancestry")
    outer.parent = None
    for edge_id, source, target in (("forward", outer.id, inner.id), ("backward", inner.id, outer.id)):
        graph.add_edge(EvidenceEdge(
            edge_id, EvidenceRelation.HAPPENS_BEFORE,
            EvidenceEndpoint(EvidenceNodeKind.OPERATION_INSTANCE, source),
            EvidenceEndpoint(EvidenceNodeKind.OPERATION_INSTANCE, target), CLAIM))
    rejects(graph, "cyclic happens-before")


def test_evidence_containment_does_not_invent_completion_order():
    graph, outer, inner = execution_pair()
    graph.add_edge(EvidenceEdge(
        "child-completes-before-parent", EvidenceRelation.HAPPENS_BEFORE,
        EvidenceEndpoint(EvidenceNodeKind.OPERATION_INSTANCE, inner.id),
        EvidenceEndpoint(EvidenceNodeKind.OPERATION_INSTANCE, outer.id), CLAIM))
    assert graph.assert_valid()["valid"]


def test_evidence_cycle_detection_keeps_typed_endpoint_namespaces_separate():
    graph, outer, _ = execution_pair()
    graph.add_control_event(outer.id.wire)
    graph.add_edge(EvidenceEdge(
        "distinct-nodes", EvidenceRelation.HAPPENS_BEFORE,
        EvidenceEndpoint(EvidenceNodeKind.CONTROL_EVENT, outer.id.wire),
        EvidenceEndpoint(EvidenceNodeKind.OPERATION_INSTANCE, outer.id), CLAIM))
    assert graph.assert_valid()["valid"]


def test_evidence_invalid_relation_endpoints_are_rejected():
    graph, outer, inner = execution_pair()
    with pytest.raises(ValueError, match="invalid endpoints"):
        EvidenceEdge("bad", EvidenceRelation.MATERIALIZES,
                     EvidenceEndpoint(EvidenceNodeKind.OPERATION_INSTANCE, outer.id),
                     EvidenceEndpoint(EvidenceNodeKind.OPERATION_INSTANCE, inner.id), CLAIM)


def test_evidence_mutated_timing_and_observation_types_are_rejected():
    graph, outer, _ = execution_pair()
    outer.start_ns, outer.end_ns = 10, 5
    rejects(graph, "ends before")
    outer.end_ns = 15
    observation = ValueObservation("x", ValueVersionID(LogicalValueID("x"), 0), outer.id)
    graph.add_observation(observation)
    observation.version = ObjectID("x")
    rejects(graph, "ValueVersionID")


@pytest.mark.parametrize("kind,wire,expected", [
    (EvidenceNodeKind.OBJECT, "alloc:x", "wrong ID kind"),
    (EvidenceNodeKind.OPERATION_INSTANCE, "opinst:missing", "EEG-owned"),
    (EvidenceNodeKind.VALUE_VERSION, "lv:x@v-1", "not a value version"),
])
def test_evidence_direct_external_registration_is_validated(kind, wire, expected):
    graph = EvidenceGraph()
    graph.external_references.add((kind, wire))
    rejects(graph, expected)


@pytest.mark.parametrize("field,value,expected", [
    ("shape", (5,), "beyond allocation"),
    ("strides", (-1,), "before its allocation"),
    ("strides", (1, 1), "equal rank"),
    ("offset", -1, "non-negative"),
    ("device", "cuda:0", "device disagrees"),
    ("shape", (True,), "must be int"),
])
def test_mutated_storage_geometry_is_revalidated(field, value, expected):
    graph, _, _, region, _ = value_fixture()
    setattr(region, field, value)
    rejects(graph, expected)


def test_zero_stride_negative_stride_empty_and_scalar_regions_are_valid():
    graph, _, allocation, _, _ = value_fixture()
    for name, offset, shape, strides in (
        ("broadcast", 0, (1000000,), (0,)),
        ("reverse", 3, (4,), (-1,)),
        ("empty", 0, (0,), (1,)),
        ("scalar", 0, (), ()),
    ):
        graph.add_region(StorageRegion(StorageRegionID(name), allocation.id, offset,
                                       shape, strides, "float32", "cpu"))
    assert graph.assert_valid()["valid"]


def test_materialization_device_and_missing_logical_owner_are_rejected():
    graph, version, _, _, materialization = value_fixture()
    materialization.device = "cuda:0"
    rejects(graph, "device disagrees")
    materialization.device = "cpu"
    graph.logical_values.clear()
    rejects(graph, "unknown logical value")


def test_provenance_must_agree_with_version_ancestry_and_producer():
    graph, source, _, _, _ = value_fixture()
    provenance_id = ProvenanceID("mutation")
    output = ValueVersion(ValueVersionID(source.id.logical_value, 1), provenance_id)
    graph.add_version(output)
    graph.add_provenance(ProvenanceRecord(provenance_id, ProvenanceRelation.MUTATE,
                                          (source.id,), (output.id,)))
    rejects(graph, "inputs disagree")
    output.parent_versions = (source.id,)
    assert graph.assert_valid()["valid"]
    output.provenance_id = None
    rejects(graph, "inconsistent producer")


def test_physical_materialization_does_not_create_semantic_version_cycle():
    graph, version, _, _, _ = value_fixture()
    graph.add_provenance(ProvenanceRecord(
        ProvenanceID("copy-to-device"), ProvenanceRelation.MATERIALIZE,
        (version.id,), (version.id,)))
    assert graph.assert_valid()["valid"]


def test_large_version_chain_validation_does_not_depend_on_python_recursion_limit():
    graph = ValueGraph()
    logical = LogicalValueID("iterations")
    graph.add_logical_value(LogicalValue(logical, "tensor"))
    previous = None
    for index in range(1500):
        current = ValueVersionID(logical, index)
        graph.add_version(ValueVersion(current, parent_versions=(previous,) if previous else ()))
        previous = current
    assert graph.assert_valid()["valid"]
