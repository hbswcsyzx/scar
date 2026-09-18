from scar.ir.v2 import (
    BindingRelation,
    EquivalenceClaim,
    EvidenceGraph,
    LogicalValue,
    LogicalValueID,
    Materialization,
    MaterializationID,
    ObjectBinding,
    ObjectID,
    OperationDefinition,
    OperationDefinitionID,
    OperationInstance,
    OperationInstanceID,
    OperationKind,
    ProvenanceID,
    ProvenanceRecord,
    ProvenanceRelation,
    SemanticGraph,
    StorageAllocation,
    StorageAllocationID,
    StorageRegion,
    StorageRegionID,
    ValueGraph,
    ValueObservation,
    ValueSlot,
    ValueVersion,
    ValueVersionID,
)


def _base_value_graph():
    graph = ValueGraph()
    logical = LogicalValue(LogicalValueID("observation"), "image")
    graph.add_logical_value(logical)
    v0 = ValueVersion(ValueVersionID(logical.id, 0), semantic_type="image")
    graph.add_version(v0)
    return graph, logical, v0


def test_storage_and_logical_identity_are_independent():
    graph, logical, v0 = _base_value_graph()
    allocation = StorageAllocation(StorageAllocationID("a0"), "cpu", nbytes=16)
    graph.add_allocation(allocation)
    region = StorageRegion(StorageRegionID("r0"), allocation.id, 0,
                           (4,), (1,), "float32", "cpu")
    graph.add_region(region)
    sibling = StorageRegion(StorageRegionID("r1"), allocation.id, 1,
                            (3,), (1,), "float32", "cpu")
    graph.add_region(sibling)
    graph.add_materialization(Materialization(
        MaterializationID("m0"), v0.id, "dense", "cpu", region=region.id))
    graph.add_materialization(Materialization(
        MaterializationID("m1"), v0.id, "dense", "cuda:0"))
    assert len(graph.materializations) == 2
    assert region.allocation == sibling.allocation
    assert region.id != sibling.id


def test_allocator_reuse_has_new_allocation_identity():
    graph, _logical, v0 = _base_value_graph()
    old = StorageAllocation(StorageAllocationID("old"), "cuda:0",
                            nbytes=16, allocator_token="allocator-address-7")
    new = StorageAllocation(StorageAllocationID("new"), "cuda:0",
                            nbytes=16, allocator_token="allocator-address-7")
    graph.add_allocation(old)
    graph.add_allocation(new)
    old_region = StorageRegion(StorageRegionID("old-region"), old.id, 0,
                               (4,), (1,), "float32", "cuda:0")
    new_region = StorageRegion(StorageRegionID("new-region"), new.id, 0,
                               (4,), (1,), "float32", "cuda:0")
    graph.add_region(old_region)
    graph.add_region(new_region)
    graph.add_materialization(Materialization(
        MaterializationID("old-mat"), v0.id, "dense", "cuda:0",
        region=old_region.id))
    # A pointer/allocator token may be reused, but the allocation identity and
    # materialization remain distinct until a provenance claim connects them.
    assert old.id != new.id
    assert old_region.id != new_region.id
    assert graph.assert_valid()["valid"]
    assert graph.assert_valid()["valid"]


def test_in_place_mutation_creates_new_version_and_provenance():
    graph, logical, v0 = _base_value_graph()
    v1 = ValueVersion(ValueVersionID(logical.id, 1),
                      provenance_id=ProvenanceID("mut1"),
                      parent_versions=(v0.id,), semantic_type="image")
    graph.add_version(v1)
    graph.add_provenance(ProvenanceRecord(
        ProvenanceID("mut1"), ProvenanceRelation.MUTATE,
        (v0.id,), (v1.id,), equivalence=EquivalenceClaim.UNKNOWN))
    assert v1.id != v0.id
    assert v1.id.logical_value == v0.id.logical_value
    assert graph.ancestors(v1.id) == (v0.id,)
    assert graph.assert_valid()["valid"]


def test_transform_and_deepcopy_keep_lineage_without_merging_objects():
    graph, _logical, v0 = _base_value_graph()
    normalized = LogicalValue(LogicalValueID("normalized_observation"), "tensor")
    graph.add_logical_value(normalized)
    v_norm = ValueVersion(ValueVersionID(normalized.id, 0),
                          provenance_id=ProvenanceID("normalize"),
                          parent_versions=(v0.id,), semantic_type="tensor")
    graph.add_version(v_norm)
    graph.add_provenance(ProvenanceRecord(
        ProvenanceID("normalize"), ProvenanceRelation.TRANSFORM,
        (v0.id,), (v_norm.id,), equivalence=EquivalenceClaim.UNKNOWN))

    copied = LogicalValue(LogicalValueID("copied_observation"), "image")
    graph.add_logical_value(copied)
    v_copy = ValueVersion(ValueVersionID(copied.id, 0),
                          provenance_id=ProvenanceID("copy"),
                          parent_versions=(v0.id,), semantic_type="image")
    graph.add_version(v_copy)
    graph.add_provenance(ProvenanceRecord(
        ProvenanceID("copy"), ProvenanceRelation.COPY,
        (v0.id,), (v_copy.id,), equivalence=EquivalenceClaim.EXACT_CONTENT_AT_TIME))
    graph.add_binding(ObjectBinding(ObjectID("source"), v0.id, BindingRelation.OWNS))
    graph.add_binding(ObjectBinding(ObjectID("copy"), v_copy.id, BindingRelation.COPY))
    assert graph.assert_valid()["valid"]
    assert v_norm.id.logical_value != v0.id.logical_value
    assert v_copy.id.logical_value != v0.id.logical_value


def test_unknown_custom_transform_is_not_implicitly_equivalent():
    graph, _logical, v0 = _base_value_graph()
    custom = LogicalValue(LogicalValueID("custom_result"), "opaque")
    graph.add_logical_value(custom)
    result = ValueVersion(ValueVersionID(custom.id, 0),
                          provenance_id=ProvenanceID("custom"),
                          parent_versions=(v0.id,))
    graph.add_version(result)
    graph.add_provenance(ProvenanceRecord(
        ProvenanceID("custom"), ProvenanceRelation.UNKNOWN,
        (v0.id,), (result.id,), equivalence=EquivalenceClaim.UNKNOWN,
        evidence="UNKNOWN"))
    assert result.id.logical_value != v0.id.logical_value
    assert graph.provenance[ProvenanceID("custom")].equivalence == EquivalenceClaim.UNKNOWN
    assert graph.assert_valid()["valid"]


def test_value_graph_reports_provenance_output_mismatch_and_cycles():
    graph, logical, v0 = _base_value_graph()
    v1 = ValueVersion(ValueVersionID(logical.id, 1),
                      provenance_id=ProvenanceID("wrong"),
                      parent_versions=(v0.id,))
    graph.add_version(v1)
    graph.add_provenance(ProvenanceRecord(
        ProvenanceID("wrong"), ProvenanceRelation.MUTATE,
        (v0.id,), (v0.id,)))
    report = graph.validate()
    assert not report["valid"]
    assert any("not an output" in error for error in report["errors"])

    cyclic = ValueGraph()
    cyclic.add_logical_value(LogicalValue(LogicalValueID("cycle"), "tensor"))
    a = ValueVersionID(LogicalValueID("cycle"), 1)
    b = ValueVersionID(LogicalValueID("cycle"), 2)
    cyclic.add_version(ValueVersion(a, parent_versions=(b,)))
    cyclic.add_version(ValueVersion(b, parent_versions=(a,)))
    cycle_report = cyclic.validate()
    assert not cycle_report["valid"]
    assert any("cyclic" in error for error in cycle_report["errors"])


def test_semantic_and_evidence_graphs_keep_definition_and_instance_distinct():
    semantic = SemanticGraph()
    definition = OperationDefinition(OperationDefinitionID("policy.get_action"),
                                     OperationKind.FUNCTION, "get_action",
                                     code_id="code:policy.get_action")
    semantic.add_definition(definition)
    child = OperationDefinition(OperationDefinitionID("policy.prepare"),
                                OperationKind.METHOD, "prepare",
                                parent_id=definition.id)
    semantic.add_definition(child)
    semantic.add_slot(ValueSlot("input:observation", "observation", "input",
                                owner=definition.id))
    semantic.add_slot(ValueSlot("output:action", "action", "output",
                                owner=definition.id))
    definition.input_slots = ("input:observation",)
    definition.output_slots = ("output:action",)
    assert semantic.assert_valid()["valid"]
    assert semantic.children_of(definition.id) == (child,)
    assert semantic.descendants_of(definition.id) == (child,)

    evidence = EvidenceGraph()
    instance = OperationInstance(OperationInstanceID("call:1"), definition.id,
                                 process_id=1, thread_id=2)
    evidence.add_instance(instance)
    nested = OperationInstance(OperationInstanceID("call:2"), definition.id,
                               process_id=1, thread_id=2, parent=instance.id)
    evidence.add_instance(nested)
    evidence.add_observation(ValueObservation("obs:1", ValueVersionID(
        LogicalValueID("observation"), 0), operation=instance.id))
    assert evidence.assert_valid()["valid"]
    assert evidence.children_of(instance.id) == (nested,)
    assert str(definition.id) != str(instance.id)
