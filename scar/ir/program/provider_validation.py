"""Check declared external provenance against the canonical core.

No artifact is opened and no provider claim is promoted to a semantic proof.
Actual producers, use owners and state flow are always read from ProgramGraph.
"""
from __future__ import annotations

from .ids import OperationID, UseID, ValueID
from .model import (
    CompletionResult, DataValue, LocalBindingValue, OperationResult, ProtocolValue, ReferenceValue,
    StateVersionValue,
)
from .control import PendingPayload
from .providers import ProviderArtifactKind, ProviderElementKind, ProviderRegionRelation


def provider_errors(graph, operation_region, uses):
    if not (graph.provider_envelopes or graph.provider_regions or graph.provider_bindings):
        return ()
    errors = []

    def error(code, path, message):
        errors.append((code, str(path), message))

    envelopes = {row.id: row for row in graph.provider_envelopes}
    regions = {row.id for row in graph.regions}
    values = {row.id: row for row in graph.values}
    owners = {}
    region_coordinates = set()
    definitions = set()
    for index, row in enumerate(graph.provider_regions):
        path = f"provider_regions[{index}]"
        envelope = envelopes.get(row.provider)
        if envelope is None:
            error("provider_reference", path, "provider envelope does not exist")
        if row.region not in regions:
            error("provider_region", path, "core region does not exist")
        if row.relation is ProviderRegionRelation.DEFINES_REPRESENTATION:
            coordinate = row.provider, row.external_region
            if coordinate in region_coordinates:
                error("provider_region_coordinate", path, "external definition region is already represented")
            region_coordinates.add(coordinate)
            if envelope is not None and envelope.kind is not ProviderArtifactKind.DEFINITION_GRAPH:
                error("provider_region_kind", path, "only a definition graph can own a representation")
            if row.region in owners:
                error("provider_representation_owner", path, "core region already has a representation owner")
            owners[row.region] = row.provider
            definitions.add((row.provider, row.region))
        elif envelope is not None and envelope.kind is not ProviderArtifactKind.EXECUTION_EVIDENCE:
            error("provider_region_kind", path, "observation scope requires execution evidence")

    value_classes = {
        ProviderElementKind.DATA_VALUE: DataValue,
        ProviderElementKind.REFERENCE_VALUE: ReferenceValue,
        ProviderElementKind.STATE_VALUE: StateVersionValue,
        ProviderElementKind.BINDING_VALUE: LocalBindingValue,
        ProviderElementKind.PROTOCOL_VALUE: ProtocolValue,
    }
    external_coordinates = set()
    canonical_targets = set()
    operation_bindings = {}
    blocks = {block.id: block for region in graph.regions for block in region.blocks}
    edge_producers = {}
    incoming = {block: [] for block in blocks}
    for operation in graph.operations:
        if operation.terminator is not None:
            for edge in operation.terminator.successors:
                incoming[edge.block].append((operation.id, edge))
    for block, edges in incoming.items():
        # Multiple real edges make this a phi, even when one incoming edge
        # projects a payload. Never choose a producer by record iteration order.
        if len(edges) != 1:
            continue
        operation, edge = edges[0]
        for actual, formal in zip(edge.arguments, blocks[block].arguments):
            if isinstance(actual, (CompletionResult, PendingPayload)):
                edge_producers[formal] = operation
    for index, row in enumerate(graph.provider_bindings):
        path = f"provider_bindings[{index}]"
        envelope = envelopes.get(row.provider)
        if envelope is None:
            error("provider_reference", path, "provider envelope does not exist")
        elif envelope.kind is not ProviderArtifactKind.DEFINITION_GRAPH:
            error("provider_binding_kind", path, "execution evidence cannot bind to a static definition")
        if (row.provider, row.region) not in definitions:
            error("provider_binding_scope", path, "binding needs this provider's explicit representation ownership")

        kind = row.external.kind
        group = "VALUE" if kind in value_classes else kind.value
        coordinate = row.provider, row.region, group, row.external.key, row.external.path
        if coordinate in external_coordinates:
            error("provider_endpoint_conflict", path, "external endpoint has more than one binding")
        external_coordinates.add(coordinate)
        target = row.provider, row.target
        if target in canonical_targets:
            error("provider_target_conflict", path, "canonical target folds multiple external endpoints")
        canonical_targets.add(target)

        actual_region = None
        if type(row.target) is OperationID:
            actual_region = operation_region.get(row.target)
            operation_bindings[(row.provider, row.target)] = row
        elif type(row.target) is UseID:
            site = uses.get(row.target)
            if site is not None:
                actual_region = operation_region.get(site[0])
        elif type(row.target) is ValueID:
            value = values.get(row.target)
            if value is not None:
                actual_region = value.region
                if not isinstance(value, value_classes[kind]):
                    error("provider_value_kind", path, "external value category disagrees with the canonical value")
        if actual_region is None:
            error("provider_target", path, "canonical target does not exist")
        elif actual_region != row.region:
            error("provider_target_region", path, "canonical target belongs to another region")

    for index, row in enumerate(graph.provider_bindings):
        path = f"provider_bindings[{index}]"
        producer = None
        if type(row.target) is UseID:
            site = uses.get(row.target)
            if site is not None:
                producer = site[0]  # Here this is the use's owning operation.
        elif type(row.target) is ValueID:
            value = values.get(row.target)
            if value is not None and isinstance(value.origin, OperationResult):
                producer = value.origin.operation
            else:
                producer = edge_producers.get(row.target)
            if producer is not None and not row.external.path:
                error("provider_result_projection", path, "produced result needs an explicit external result path")
        if producer is not None:
            binding = operation_bindings.get((row.provider, producer))
            if (binding is None or binding.region != row.region
                    or binding.external.key != row.external.key):
                error("provider_binding_owner", path,
                      "external node key does not match the canonical use owner or result producer")
    return tuple(errors)


__all__ = ["provider_errors"]
