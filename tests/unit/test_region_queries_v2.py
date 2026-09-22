"""Origin identity is scoped provenance; call depth alone never licenses motion."""
from dataclasses import replace

import pytest

from scar.analysis.region_queries_v2 import (
    MotionQuery, OriginPlacement, OriginQuery, OriginStatus, PlacementRelation, RegionOriginQuery, RegionQueries,
)
from scar.ir.provenance import EventPoint, ExactContract, ProvenanceRegistry
import scar.ir.v2 as ir


def claim(scope="run"):
    return ir.EvidenceClaim(ir.EvidenceKind.OBSERVED, ("fixture:reviewed-event",), scope=scope)


def edge(bundle, identity, relation, operation, value):
    target = ir.EvidenceEndpoint(ir.EvidenceNodeKind.VALUE_VERSION, value)
    bundle.evidence.register_external(target)
    bundle.evidence.add_edge(ir.EvidenceEdge(identity, relation,
        ir.EvidenceEndpoint(ir.EvidenceNodeKind.OPERATION_INSTANCE, operation), target, claim()))


def region(registry, label="source", device="cpu"):
    allocation = registry.allocation(device, 16, token=label, lifetime=label + ":generation1")
    return registry.region(allocation, 0, (4,), (1,), "float32")


def fixture(*, logical_edge=True):
    semantic, evidence = ir.SemanticGraph(), ir.EvidenceGraph()
    definitions, instances, slots = [], [], []
    for depth in range(1, 9):
        definition = ir.OperationDefinitionID(f"function:{depth}")
        instance = ir.OperationInstanceID(f"invocation:{depth}")
        slot = ir.ValueSlotID(f"argument:{depth}")
        semantic.add_definition(ir.OperationDefinition(definition, ir.OperationKind.FUNCTION,
            f"function {depth}", input_slots=(slot,)))
        semantic.add_slot(ir.ValueSlot(slot, "argument", "input", owner=definition))
        evidence.add_instance(ir.OperationInstance(instance, definition, 1, 2,
            parent=instances[-1] if instances else None, control_scope="run"))
        definitions.append(definition)
        instances.append(instance)
        slots.append(slot)
    registry = ProvenanceRegistry(scope="run", namespace="fixture")
    source_region = region(registry)
    handle = registry.origin(ir.ObjectID("source"), source_region, claim(), coverage=ir.Completeness.COMPLETE)
    for depth in range(3, 9):
        registry.bind_slot(slots[depth - 1], handle, claim(), scope=instances[depth - 1].wire)
    bundle = ir.IRBundle(semantic, evidence, registry.graph)
    if logical_edge:
        edge(bundle, "source-at-layer3", ir.EvidenceRelation.PRODUCES, instances[2], handle.version)
    edge(bundle, "input-at-layer8", ir.EvidenceRelation.OBSERVED_READ, instances[7], handle.version)
    bundle.assert_valid()
    return bundle, registry, handle, instances, slots


def bound_origin(bundle, registry, instances, slots, **kwargs):
    return RegionQueries(bundle, registry, **kwargs).origin(slots[-1], instances[-1], registry.current_event)


def test_eight_layer_binding_traces_exact_version_to_third_layer_without_moving():
    bundle, registry, handle, instances, slots = fixture()
    result = bound_origin(bundle, registry, instances, slots)
    assert result.status is OriginStatus.LOCATED
    assert result.handle == handle
    assert {site.producer for site in result.value_sites} == {instances[2]}
    assert not result.ancestor_sites
    assert len({binding.handle.version for binding in registry.bindings}) == 1
    assert not bundle.optimization


def test_first_output_observation_is_not_a_logical_origin():
    bundle, registry, handle, instances, slots = fixture(logical_edge=False)
    observation = ir.ValueObservation("earliest", handle.version, operation=instances[0],
                                     materialization=handle.materialization, role="output")
    bundle.evidence.add_observation(observation)
    bundle.evidence.add_edge(ir.EvidenceEdge("merely-a-return", ir.EvidenceRelation.PRODUCES,
        ir.EvidenceEndpoint(ir.EvidenceNodeKind.OPERATION_INSTANCE, instances[0]),
        ir.EvidenceEndpoint(ir.EvidenceNodeKind.VALUE_OBSERVATION, "earliest"), claim()))
    result = bound_origin(bundle, registry, instances, slots)
    assert result.status is OriginStatus.UNRESOLVED
    assert not result.value_sites
    assert any("observation order is not origin" in gap for gap in result.gaps)


def test_explicit_scoped_origin_witness_supplies_missing_logical_producer():
    bundle, registry, handle, instances, slots = fixture(logical_edge=False)
    placement = OriginPlacement("reviewed-input", handle.version, instances[2], "run", claim())
    result = bound_origin(bundle, registry, instances, slots, placements=(placement,))
    assert result.status is OriginStatus.LOCATED
    assert result.value_sites[0].mechanism == "explicit_origin_placement"
    with pytest.raises(ValueError, match="duplicate origin"):
        RegionQueries(bundle, registry, (placement, placement))
    with pytest.raises(ValueError, match="scope mismatch"):
        RegionQueries(bundle, registry, (replace(placement, scope="other", evidence=claim("other")),))
    with pytest.raises(ValueError, match="unknown version"):
        RegionQueries(bundle, registry, (replace(placement, version=ir.ValueVersionID(ir.LogicalValueID("missing"), 0)),))


@pytest.mark.parametrize("operation", ["copy", "transform", "mutate", "view"])
def test_derived_version_has_lineage_without_inheriting_ancestor_origin(operation):
    bundle, registry, source, instances, slots = fixture()
    if operation == "copy":
        result = registry.copy(source, ir.ObjectID("copy"), region(registry, "copy"), claim())
    elif operation == "transform":
        result = registry.transform((source,), ir.ObjectID("result"), region(registry, "result"),
                                    claim(), producer=instances[6])
    elif operation == "mutate":
        result = registry.mutate(source, registry.graph.materializations[source.materialization].region, claim())
    else:
        allocation = registry.graph.regions[registry.graph.materializations[source.materialization].region].allocation
        subset = registry.region(allocation, 0, (2,), (2,), "float32")
        result = registry.view(source, ir.ObjectID("strided-subset"), subset, claim())
    registry.bind_slot(slots[-1], result, claim(), scope=instances[-1].wire)
    origin = bound_origin(bundle, registry, instances, slots)
    assert result.version != source.version
    assert {site.producer for site in origin.ancestor_sites} == {instances[2]}
    assert any(step.relation.value == operation for step in origin.steps)
    assert all(site.producer != instances[2] for site in origin.value_sites)
    assert any("ancestor lineage" in gap for gap in origin.gaps)
    if operation == "transform":
        assert origin.status is OriginStatus.LOCATED
        assert {site.producer for site in origin.value_sites} == {instances[6]}
    else:
        assert origin.status is OriginStatus.UNRESOLVED


def test_exact_materialization_retains_value_origin_without_becoming_a_new_logical_producer():
    bundle, registry, source, instances, slots = fixture()
    contract = ExactContract("fixture:exact-copy", ir.ProofStatus.PROVEN, "run", claim())
    copied = registry.materialize(source, ir.ObjectID("gpu-copy"), region(registry, "gpu", "cuda:0"),
                                 claim(), contract=contract, coverage=ir.Completeness.COMPLETE)
    registry.bind_slot(slots[-1], copied, claim(), scope=instances[-1].wire)
    origin = bound_origin(bundle, registry, instances, slots)
    assert copied.version == source.version
    assert copied.materialization != source.materialization
    assert {site.producer for site in origin.value_sites} == {instances[2]}
    assert set(origin.materializations) == {copied.materialization, source.materialization}
    assert any(step.relation is ir.ProvenanceRelation.MATERIALIZE for step in origin.steps)


def test_ambiguous_producers_remain_ambiguous_even_with_equal_values():
    bundle, registry, handle, instances, slots = fixture()
    placement = OriginPlacement("second-producer", handle.version, instances[5], "run", claim())
    origin = bound_origin(bundle, registry, instances, slots, placements=(placement,))
    assert origin.status is OriginStatus.AMBIGUOUS
    assert {site.producer for site in origin.value_sites} == {instances[2], instances[5]}


def test_missing_or_expired_binding_is_not_recovered_by_object_or_storage_identity():
    bundle, registry, handle, instances, slots = fixture()
    registry.finish_binding(slots[-1], scope=instances[-1].wire)
    origin = bound_origin(bundle, registry, instances, slots)
    assert origin.status is OriginStatus.UNRESOLVED and origin.handle is None
    assert not origin.value_sites
    # A binding in a different invocation is never substituted, despite equal value IDs.
    registry.bind_slot(slots[-1], handle, claim(), scope=instances[-2].wire)
    assert bound_origin(bundle, registry, instances, slots).handle is None


def test_foreign_write_coverage_and_expired_materialization_are_explicit_gaps():
    bundle, registry, handle, instances, slots = fixture()
    registry.escape(handle, "unknown external owner", claim())
    origin = bound_origin(bundle, registry, instances, slots)
    assert origin.status is OriginStatus.LOCATED  # Location does not certify current bits.
    assert any("freshness" in gap for gap in origin.gaps)
    registry.invalidate(handle, "lifetime ended", claim())
    expired = bound_origin(bundle, registry, instances, slots)
    assert any("outside its validity interval" in gap for gap in expired.gaps)


def test_motion_reports_both_removed_input_and_added_output_crossings_without_approval():
    bundle, registry, source, instances, slots = fixture()
    output = registry.transform((source,), ir.ObjectID("output"), region(registry, "output"),
                                claim(), producer=instances[7])
    edge(bundle, "produced-at-layer8", ir.EvidenceRelation.PRODUCES, instances[7], output.version)
    edge(bundle, "consumed-at-layer7", ir.EvidenceRelation.OBSERVED_READ, instances[6], output.version)
    queries = RegionQueries(bundle, registry)
    origin = queries.origin(slots[-1], instances[-1], registry.current_event)
    result = queries.motion((instances[-1],), instances[2], scope="run", origins=(origin,))
    assert result.control_path == tuple(reversed(instances[2:7]))
    assert len(result.boundary_deltas) == 4
    assert all({edge.edge_id for edge in delta.removed} == {"input-at-layer8"} for delta in result.boundary_deltas)
    assert all({edge.edge_id for edge in delta.added} == {"consumed-at-layer7"} for delta in result.boundary_deltas)
    assert result.inputs[0].placement_relation is PlacementRelation.AT_TARGET
    assert result.inputs[0].available_at_target is ir.ProofStatus.UNKNOWN
    assert set(result.lifetime_extensions) == {source.materialization, output.materialization}
    assert result.mode == "dynamic_path" and result.decision == "REPORT_ONLY"
    assert all(item.status is ir.ProofStatus.UNKNOWN for item in result.obligations)
    assert {"autograd_and_hooks", "effect_and_exception_order", "control_dominance_and_zero_iteration"} <= {
        item.obligation for item in result.obligations}
    assert queries.validate_result(result)


def test_transform_origin_below_target_is_not_replaced_by_its_ancestor_in_motion():
    bundle, registry, source, instances, slots = fixture()
    derived = registry.transform((source,), ir.ObjectID("derived"), region(registry, "derived"),
                                 claim(), producer=instances[6])
    registry.bind_slot(slots[-1], derived, claim(), scope=instances[-1].wire)
    queries = RegionQueries(bundle, registry)
    origin = queries.origin(slots[-1], instances[-1], registry.current_event)
    result = queries.motion((instances[-1],), instances[2], scope="run", origins=(origin,))
    assert result.inputs[0].producers == (instances[6],)
    assert result.inputs[0].placement_relation is PlacementRelation.BELOW_TARGET
    assert result.inputs[0].available_at_target is ir.ProofStatus.UNKNOWN


def test_motion_rejects_wrong_scope_unrelated_target_and_unknown_ids():
    bundle, registry, _, instances, _ = fixture()
    queries = RegionQueries(bundle, registry)
    with pytest.raises(ValueError, match="scope mismatch"):
        queries.motion((instances[-1],), instances[2], scope="different")
    with pytest.raises(ValueError, match="dynamic ancestor"):
        queries.motion((instances[2],), instances[-1], scope="run")
    with pytest.raises(ValueError, match="unknown typed"):
        queries.motion((ir.OperationInstanceID("absent"),), instances[2], scope="run")
    with pytest.raises(ValueError, match="unique members"):
        queries.motion((instances[-1], instances[-1]), instances[2], scope="run")


def test_query_wire_roundtrip_is_strict_deterministic_and_requires_current_references():
    bundle, registry, _, instances, slots = fixture()
    queries = RegionQueries(bundle, registry)
    origin = queries.origin(slots[-1], instances[-1], registry.current_event)
    motion = queries.motion((instances[-1],), instances[2], scope="run", origins=(origin,))
    assert OriginQuery.from_json(origin.to_json()) == origin
    assert MotionQuery.from_json(motion.to_json()) == motion
    assert queries.validate_result(OriginQuery.from_json(origin.to_json()))
    assert queries.validate_result(MotionQuery.from_json(motion.to_json()))
    assert queries.motion((instances[-1],), instances[2], scope="run", origins=(origin,)).to_json() == motion.to_json()
    document = motion.to_dict()
    document["record"]["decision"] = "MOVE"
    with pytest.raises(ValueError, match="cannot authorize MOVE"):
        MotionQuery.from_dict(document)
    with pytest.raises(ValueError, match="duplicate JSON"):
        OriginQuery.from_json('{"schema":"a","schema":"b"}')
    document = origin.to_dict()
    document["record"]["consumer"]["wire"] = "op:wrong-kind"
    with pytest.raises(ValueError, match="namespace/wire mismatch"):
        OriginQuery.from_dict(document)
    with pytest.raises(ValueError, match="no longer matches"):
        queries.validate_result(replace(motion, control_path=(instances[0],)))
    del bundle.evidence.edges["source-at-layer3"]
    with pytest.raises(ValueError, match="no longer matches"):
        queries.validate_result(origin)


def test_query_event_cannot_reuse_another_registry_scope_or_future_event():
    bundle, registry, _, instances, slots = fixture()
    queries = RegionQueries(bundle, registry)
    for point in (EventPoint("other", 0), EventPoint("run", registry.current_event.ordinal + 1)):
        with pytest.raises(ValueError, match="outside registry"):
            queries.origin(slots[-1], instances[-1], point)


@pytest.mark.parametrize("missing", ["provenance_kind", "source_reference"])
def test_unwitnessed_provenance_producer_cannot_become_located(missing):
    bundle, registry, source, instances, slots = fixture()
    initial = claim() if missing == "provenance_kind" else ir.EvidenceClaim(ir.EvidenceKind.OBSERVED, (), scope="run")
    derived = registry.transform((source,), ir.ObjectID("derived"), region(registry, "derived"),
                                 initial, producer=instances[6])
    if missing == "provenance_kind":
        provenance = registry.graph.versions[derived.version].provenance_id
        registry.graph.provenance[provenance].evidence = "UNKNOWN"
    # This later genuine observation cannot certify the previous producer.
    registry.escape(derived, "later external escape", claim())
    registry.bind_slot(slots[-1], derived, claim(), scope=instances[-1].wire)
    queries = RegionQueries(bundle, registry)
    origin = queries.origin(slots[-1], instances[-1], registry.current_event)
    assert origin.status is OriginStatus.UNRESOLVED
    assert origin.value_sites and all(site.evidence.kind is ir.EvidenceKind.UNKNOWN for site in origin.value_sites)
    motion = queries.motion((instances[-1],), instances[2], scope="run", origins=(origin,))
    assert not motion.inputs[0].producers
    assert motion.inputs[0].placement_relation is PlacementRelation.UNKNOWN


def test_known_clock_conflict_is_rejected_and_missing_clock_has_a_gap():
    bundle, registry, _, instances, _ = fixture()
    queries = RegionQueries(bundle, registry)
    result = queries.motion((instances[-1],), instances[2], scope="run")
    assert any("runtime clock is unknown" in gap for gap in result.gaps)
    bundle.evidence.instances[instances[-1]].metadata["clock_domain"] = "gpu-clock"
    bundle.evidence.instances[instances[2]].metadata["clock_domain"] = "host-clock"
    with pytest.raises(ValueError, match="different known clock"):
        queries.motion((instances[-1],), instances[2], scope="run")


def test_motion_batch_validates_full_bundle_once_not_once_per_input(monkeypatch):
    bundle, registry, _, instances, slots = fixture()
    queries = RegionQueries(bundle, registry)
    origin = queries.origin(slots[-1], instances[-1], registry.current_event)
    calls = []
    original = ir.IRBundle.assert_valid

    def counted(self):
        calls.append(self)
        return original(self)

    monkeypatch.setattr(ir.IRBundle, "assert_valid", counted)
    queries.motion((instances[-1],), instances[2], scope="run", origins=(origin,))
    assert calls == [bundle]


def test_origin_query_attaches_to_actual_region_and_rejects_membership_or_scope_forgery():
    from scar.analysis.regions_v2 import build_regions

    bundle, registry, _, instances, slots = fixture()
    inventory = build_regions(bundle, view="execution", roots=(instances[-1],), scope="run")
    region_id = next(iter(inventory.graph.regions))
    queries = RegionQueries(bundle, registry)
    result = queries.origin_for_region(inventory, region_id, slots[-1], instances[-1], registry.current_event)
    assert result.region == region_id and result.origin.status is OriginStatus.LOCATED
    assert RegionOriginQuery.from_json(result.to_json()) == result
    assert queries.validate_region_result(result, inventory)
    with pytest.raises(ValueError, match="must belong"):
        queries.origin_for_region(inventory, region_id, slots[2], instances[2], registry.current_event)
    with pytest.raises(ValueError, match="region scope"):
        queries.validate_region_result(replace(result, region_scope="other"), inventory)
