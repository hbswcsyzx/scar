"""Validate static resource interfaces, not dynamic realization or readiness."""
from __future__ import annotations

from scar.ir.program.ids import OperationID
from scar.ir.program.model import ReferenceValue
from scar.ir.program.resources import CreatedResource, RequirementRelation
from scar.ir.v2._validation import cycle_errors


def resource_errors(graph, operation_region, uses):
    errors = []

    def error(code, path, message):
        errors.append((code, path, message))

    definitions = {row.id: row for row in graph.resources}
    requirements = {row.id: row for row in graph.resource_requirements}
    operations = {row.id for row in graph.operations}
    regions = {row.id: row for row in graph.regions}
    locations = {row.id for row in graph.locations}
    values = {row.id: row for row in graph.values}

    for resource in graph.resources:
        origin = resource.origin
        if isinstance(origin, CreatedResource):
            if origin.operation not in operations:
                error("resource_origin", resource.id, "creation operation does not exist")
        elif origin.region not in regions:
            error("resource_origin", resource.id, "external resource region does not exist")

    same_parent = {key: key for key in requirements}

    def representative(key):
        while same_parent[key] != key:
            same_parent[key] = same_parent[same_parent[key]]
            key = same_parent[key]
        return key

    valid_relations = []
    for requirement in graph.resource_requirements:
        owners = operations if isinstance(requirement.owner, OperationID) else regions
        if requirement.owner not in owners:
            error("resource_requirement_owner", requirement.id, "requirement owner does not exist")
        for relation in requirement.relations:
            other = requirements.get(relation.other)
            if other is None:
                error("resource_constraint", requirement.id, "related requirement does not exist")
                continue
            if requirement.owner != other.owner:
                error("resource_constraint_scope", requirement.id,
                      "related requirements need the same owner/activation scope")
                continue
            valid_relations.append((requirement, relation))
            if relation.relation is RequirementRelation.SAME_RESOURCE:
                same_parent[representative(requirement.id)] = representative(other.id)

    component_types = {}
    for requirement in graph.resource_requirements:
        root = representative(requirement.id)
        kind_role = requirement.kind, requirement.role
        if root in component_types and component_types[root] != kind_role:
            error("resource_constraint", requirement.id, "same-resource kinds/roles disagree")
        component_types[root] = kind_role
    child_edges = []
    for requirement, relation in valid_relations:
        left, right = representative(requirement.id), representative(relation.other)
        if relation.relation is not RequirementRelation.SAME_RESOURCE and left == right:
            error("resource_constraint", requirement.id, "same-resource closure contradicts relation")
        if relation.relation is RequirementRelation.CHILD_RESOURCE:
            child_edges.append((left, right))
    for message in cycle_errors(child_edges, "strict resource containment"):
        error("resource_constraint", "resource_requirements", message)

    def region_contains(ancestor, child):
        visited = set()
        while child in regions and child not in visited:
            if child == ancestor:
                return True
            visited.add(child)
            child = regions[child].parent
        return False

    used_keys = set()
    for index, use in enumerate(graph.resource_uses):
        path = f"resource_uses[{index}]"
        key = use.operation, use.requirement
        if key in used_keys:
            error("resource_use", path, "one operation/requirement has conflicting bindings")
        used_keys.add(key)
        if use.operation not in operations:
            error("resource_use", path, "operation does not exist")
        requirement = requirements.get(use.requirement)
        if requirement is None:
            error("resource_use", path, "requirement does not exist")
        elif isinstance(requirement.owner, OperationID):
            if requirement.owner != use.operation:
                error("resource_use_owner", path, "operation uses another operation's requirement")
        elif not region_contains(requirement.owner, operation_region.get(use.operation)):
            error("resource_use_owner", path, "operation is outside the owning region")
        if use.definition is not None:
            definition = definitions.get(use.definition)
            if definition is None:
                error("resource_target", path, "definition does not exist")
            elif requirement is not None and (definition.kind is not requirement.kind
                                              or definition.role is not requirement.role):
                error("resource_target", path, "definition does not meet kind/role requirement")
        if use.handle is not None:
            occurrence = uses.get(use.handle)
            if (occurrence is None or occurrence[0] != use.operation
                    or not isinstance(values.get(occurrence[1].value), ReferenceValue)):
                error("resource_handle", path, "handle is not this operation's reference Use")

    for index, binding in enumerate(graph.resource_locations):
        if binding.location not in locations or binding.resource not in definitions:
            error("resource_location", f"resource_locations[{index}]",
                  "resource state binding needs existing location and definition")
    return tuple(errors)


__all__ = ["resource_errors"]
