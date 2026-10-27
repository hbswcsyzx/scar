"""Static interface tests; no dynamic resources, purity or readiness are certified."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from scar.ir.program import (
    Behavior, Block, BlockID, CapacityConstraint, CreatedResource, ExitKind,
    ExitPort, ExternalResource, LiteralOrigin, LocationID, Operation,
    OperationID, ProgramGraph, ReferenceValue, Region, RegionID,
    RequirementRelation, ResourceDefinition, ResourceDefinitionID,
    ResourceKind, ResourceLocation, ResourceRelationConstraint,
    ResourceRequirement, ResourceRequirementID, ResourceRole, ResourceUse,
    StateLocation, Terminator, TerminatorKind, Use, UseID, UseRole,
    ValueID, ValueKind, ValueType, dumps, loads,
)
from scar.ir.program.validation import require_valid, validate


def base_graph():
    root = RegionID("root")
    reference = ReferenceValue(ValueID("handle"), root, LiteralOrigin(None), targets=())
    argument = Use(UseID("consume.handle"), reference.id, UseRole.REFERENCE)
    consume = Operation(OperationID("consume"), "consume", (Behavior.CONTROL,),
                        (argument,), terminator=Terminator(
                            TerminatorKind.RETURN, exit="done", values=(argument.id,)))
    block = Block(BlockID("entry"), (), (consume.id,))
    region = Region(root, "root", block.id, (block,), (
        ExitPort("done", ExitKind.NORMAL, (ValueType(ValueKind.REFERENCE),)),
    ))
    return ProgramGraph(root, (region,), (consume,), (reference,))


def resource_graph():
    graph = base_graph()
    definition = ResourceDefinition(ResourceDefinitionID("queue"), ResourceKind.STREAM,
                                    ResourceRole.QUEUE, ExternalResource(graph.root, "queue"))
    requirement = ResourceRequirement(ResourceRequirementID("queue"), graph.operations[0].id,
                                      ResourceKind.STREAM, ResourceRole.QUEUE)
    use = ResourceUse(graph.operations[0].id, requirement.id, definition.id,
                      graph.operations[0].uses[0].id)
    return replace(graph, resources=(definition,), resource_requirements=(requirement,),
                   resource_uses=(use,))


def codes(graph):
    return {issue.code for issue in validate(graph)}


def test_resource_interfaces_live_in_canonical_graph_and_roundtrip():
    graph = resource_graph()
    require_valid(graph)
    payload = dumps(graph)
    assert json.loads(payload)["schema_version"] == 4
    assert loads(payload) == graph
    assert graph.resource_uses[0].handle == graph.operations[0].uses[0].id


def test_plain_graph_retains_exact_legacy_v2_shape():
    graph = base_graph()
    document = json.loads(dumps(graph))
    assert document["schema_version"] == 2
    assert set(document) == {"schema", "schema_version", "root", "regions", "operations",
                             "values", "locations", "ordering"}
    assert loads(json.dumps(document)) == graph


def test_binding_graph_retains_original_frozen_v3_wire():
    from tests.unit.test_program_bindings import _bound_graph

    graph = _bound_graph()
    original = (Path(__file__).parents[1] / "fixtures/program_graph_v3_frozen.json").read_text().rstrip("\n")
    assert dumps(graph) == original
    assert loads(original) == graph


def test_requirement_can_remain_unresolved_without_fabricating_instance():
    graph = resource_graph()
    graph = replace(graph, resources=(),
                    resource_uses=(replace(graph.resource_uses[0], definition=None),))
    require_valid(graph)
    assert loads(dumps(graph)) == graph
    assert graph.resource_uses[0].definition is None


def test_distinct_requirements_can_reference_one_definition_and_one_handle():
    graph = resource_graph()
    second = replace(graph.resource_requirements[0], id=ResourceRequirementID("second"))
    graph = replace(graph, resource_requirements=(*graph.resource_requirements, second),
                    resource_uses=(*graph.resource_uses,
                                   replace(graph.resource_uses[0], requirement=second.id)))
    require_valid(graph)
    assert graph.resource_uses[0].definition == graph.resource_uses[1].definition


@pytest.mark.parametrize("which,expected", [
    ("origin", "resource_origin"), ("owner", "resource_requirement_owner"),
    ("requirement", "resource_use"), ("definition", "resource_target"),
    ("handle", "resource_handle"), ("kind", "resource_target"),
])
def test_missing_or_mistyped_cross_record_endpoints_are_rejected(which, expected):
    graph = resource_graph()
    if which == "origin":
        graph = replace(graph, resources=(replace(graph.resources[0],
                        origin=CreatedResource(OperationID("absent"))),))
    elif which == "owner":
        graph = replace(graph, resource_requirements=(replace(graph.resource_requirements[0],
                        owner=OperationID("absent")),))
    elif which in ("requirement", "definition", "handle"):
        target = {"requirement": ResourceRequirementID("absent"),
                  "definition": ResourceDefinitionID("absent"),
                  "handle": UseID("absent")}[which]
        graph = replace(graph, resource_uses=(replace(graph.resource_uses[0], **{which: target}),))
    else:
        graph = replace(graph, resource_requirements=(replace(graph.resource_requirements[0],
                        kind=ResourceKind.OTHER),))
    assert expected in codes(graph)
    with pytest.raises(ValueError):
        dumps(graph)


def test_resource_state_binding_is_not_a_second_state_version_store():
    graph = resource_graph()
    location = StateLocation(LocationID("queue.state"), "queue state")
    graph = replace(graph, locations=(location,), resource_locations=(
        ResourceLocation(location.id, graph.resources[0].id),))
    require_valid(graph)
    assert loads(dumps(graph)) == graph
    bad = replace(graph, resource_locations=(replace(graph.resource_locations[0],
                  location=LocationID("absent")),))
    assert "resource_location" in codes(bad)


def test_region_owned_requirement_is_not_owned_by_an_unrelated_operation():
    graph = resource_graph()
    requirement = replace(graph.resource_requirements[0], owner=graph.root)
    require_valid(replace(graph, resource_requirements=(requirement,)))
    extra = Operation(OperationID("other"), "other", (Behavior.COMPUTE,))
    region = replace(graph.regions[0], blocks=(replace(graph.regions[0].blocks[0],
                     operations=(extra.id, graph.operations[0].id)),))
    wrong_owner = replace(requirement, owner=extra.id)
    bad = replace(graph, regions=(region,), operations=(extra, *graph.operations),
                  resource_requirements=(wrong_owner,))
    assert "resource_use_owner" in codes(bad)


def test_handle_is_an_exact_use_owned_by_the_resource_consumer():
    graph = resource_graph()
    extra_use = Use(UseID("other.handle"), graph.values[0].id, UseRole.REFERENCE)
    extra = Operation(OperationID("other"), "other", (Behavior.COMPUTE,), (extra_use,))
    region = replace(graph.regions[0], blocks=(replace(graph.regions[0].blocks[0],
                     operations=(extra.id, graph.operations[0].id)),))
    bad = replace(graph, regions=(region,), operations=(extra, *graph.operations),
                  resource_uses=(replace(graph.resource_uses[0], handle=extra_use.id),))
    assert "resource_handle" in codes(bad)


def test_requirement_identity_cannot_be_used_as_a_resource_definition():
    graph = resource_graph()
    with pytest.raises(TypeError):
        replace(graph.resource_uses[0], definition=graph.resource_requirements[0].id)
    with pytest.raises(TypeError):
        replace(graph.resource_uses[0], handle=graph.values[0].id)


def test_constraint_references_and_direct_contradictions_are_checked():
    graph = resource_graph()
    one = graph.resource_requirements[0]
    two = replace(one, id=ResourceRequirementID("two"))
    missing = replace(one, relations=(ResourceRelationConstraint(
        RequirementRelation.SAME_RESOURCE, ResourceRequirementID("missing")),))
    assert "resource_constraint" in codes(replace(graph, resource_requirements=(missing,)))
    conflicting = replace(one, relations=(
        ResourceRelationConstraint(RequirementRelation.SAME_RESOURCE, two.id),
        ResourceRelationConstraint(RequirementRelation.DISTINCT_RESOURCE, two.id),
    ))
    assert "resource_constraint" in codes(replace(graph, resource_requirements=(conflicting, two)))


def test_strict_child_and_distinct_are_compatible():
    graph = resource_graph()
    one = graph.resource_requirements[0]
    two = replace(one, id=ResourceRequirementID("two"))
    child = replace(one, relations=(
        ResourceRelationConstraint(RequirementRelation.CHILD_RESOURCE, two.id),
        ResourceRelationConstraint(RequirementRelation.DISTINCT_RESOURCE, two.id),
    ))
    require_valid(replace(graph, resource_requirements=(child, two)))


def test_same_closure_rejects_indirect_distinct_or_role_conflict():
    graph = resource_graph()
    one = graph.resource_requirements[0]
    two = replace(one, id=ResourceRequirementID("two"))
    three = replace(one, id=ResourceRequirementID("three"))
    one = replace(one, relations=(ResourceRelationConstraint(
        RequirementRelation.SAME_RESOURCE, two.id),))
    two = replace(two, relations=(ResourceRelationConstraint(
        RequirementRelation.SAME_RESOURCE, three.id),))
    three = replace(three, relations=(ResourceRelationConstraint(
        RequirementRelation.DISTINCT_RESOURCE, one.id),))
    assert "resource_constraint" in codes(replace(graph, resource_requirements=(one, two, three)))
    three = replace(three, relations=(), role=ResourceRole.OPAQUE_RESOURCE)
    assert "resource_constraint" in codes(replace(graph, resource_requirements=(one, two, three)))


def test_resource_relations_do_not_merge_independent_call_contexts():
    graph = resource_graph()
    one = graph.resource_requirements[0]
    other = replace(one, id=ResourceRequirementID("other"), owner=graph.root)
    one = replace(one, relations=(ResourceRelationConstraint(
        RequirementRelation.SAME_RESOURCE, other.id),))
    assert "resource_constraint_scope" in codes(replace(graph, resource_requirements=(one, other)))


def test_requirements_obey_the_same_kind_role_contract_as_definitions():
    graph = resource_graph()
    with pytest.raises(ValueError, match="incompatible"):
        replace(graph.resource_requirements[0], kind=ResourceKind.CPU,
                role=ResourceRole.MEMORY_POOL)


@pytest.mark.parametrize("minimum,maximum", [(None, None), (True, None),
                                           (-1, None), (1, 0), (1, float("inf"))])
def test_invalid_capacity_contracts_do_not_become_measurements(minimum, maximum):
    with pytest.raises((TypeError, ValueError)):
        CapacityConstraint("capacity", "bytes", minimum, maximum)


def test_v4_has_exact_fields_and_cannot_relabel_a_legacy_graph():
    graph = resource_graph()
    document = json.loads(dumps(graph))
    del document["resource_locations"]
    with pytest.raises(ValueError):
        loads(json.dumps(document))
    document = json.loads(dumps(base_graph()))
    document["schema_version"] = 4
    for name in ("resources", "resource_requirements", "resource_uses", "resource_locations",
                 "binding_definitions", "binding_reads"):
        document[name] = []
    with pytest.raises(ValueError, match="requires explicit resource"):
        loads(json.dumps(document))
