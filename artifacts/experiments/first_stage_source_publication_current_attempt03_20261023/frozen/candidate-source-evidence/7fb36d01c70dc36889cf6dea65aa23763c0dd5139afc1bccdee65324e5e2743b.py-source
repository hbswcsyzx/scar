"""Canonical boundary references, without interpreting a provider artifact.

Only the existing entry/exit/Use interfaces supply program facts. Native roles,
trees, conditions and correspondence evidence remain unverified declarations.
"""
from __future__ import annotations

from .native import EntryPortRef, ExitPortRef
from .providers import ProviderArtifactKind, ProviderRegionRelation


def port_key(port):
    """Keep original typed IDs; neither normalize nor join by their text."""
    if type(port) is EntryPortRef:
        return port.region, port.value
    if type(port) is ExitPortRef:
        return port.region, port.exit_name, port.index
    raise TypeError("port_key requires an exact EntryPortRef or ExitPortRef")


def region_port_keys(region):
    """Index canonical ports without imposing new record types on legacy IDs."""
    entry = next(block for block in region.blocks if block.id == region.entry)
    return (
        tuple((region.id, value) for value in entry.arguments),
        tuple((region.id, port.name, index)
              for port in region.exits for index in range(len(port.types))),
    )


def native_errors(graph):
    if not (graph.native_boundaries or graph.boundary_relations):
        return ()
    errors = []

    def error(code, path, message):
        errors.append((code, str(path), message))

    regions = {row.id: row for row in graph.regions}
    providers = {row.id: row for row in graph.provider_envelopes}
    owners = {row.region: row.provider for row in graph.provider_regions
              if row.relation is ProviderRegionRelation.DEFINES_REPRESENTATION}
    expected = {identity: region_port_keys(region) for identity, region in regions.items()}
    boundaries = {row.id: row for row in graph.native_boundaries}
    seen_regions = set()

    for index, row in enumerate(graph.native_boundaries):
        path = f"native_boundaries[{index}]"
        provider = providers.get(row.provider)
        if provider is None:
            error("native_provider", path, "provider envelope does not exist")
        elif provider.kind is not ProviderArtifactKind.DEFINITION_GRAPH:
            error("native_provider_kind", path, "native boundary requires a definition provider")
        if owners.get(row.region) != row.provider:
            error("native_owner", path, "native boundary needs its explicit representation owner")
        if row.region in seen_regions:
            error("native_region_conflict", path, "region already has a native boundary")
        seen_regions.add(row.region)
        if row.region not in regions:
            error("native_region", path, "native boundary region does not exist")
            continue

        for direction, slots, auxiliary, required in (
                ("input", row.inputs, row.core_inputs, expected[row.region][0]),
                ("output", row.outputs, row.core_outputs, expected[row.region][1])):
            ports = tuple(item.port for item in (*slots, *auxiliary))
            coordinates = tuple(port_key(port) for port in ports)
            required_set = set(required)
            if len(set(ports)) != len(ports):
                error("native_port_duplicate", path + "." + direction,
                      "native and core-only ports must be disjoint without duplicates")
            if set(coordinates) != required_set:
                error("native_port_partition", path + "." + direction,
                      "declared ports must cover exactly the canonical entry or exit slots")
            for port in ports:
                if port.region != row.region:
                    error("native_port_region", path + "." + direction,
                          "port belongs to a different region")
                elif port_key(port) not in required_set:
                    error("native_port", path + "." + direction,
                          "port does not identify a canonical entry argument or logical exit slot")

    for index, row in enumerate(graph.boundary_relations):
        path = f"boundary_relations[{index}]"
        left, right = boundaries.get(row.left), boundaries.get(row.right)
        if left is None or right is None:
            error("boundary_reference", path, "both native boundaries must exist")
            continue
        if left.region == right.region:
            error("boundary_region", path, "correspondence requires different representation regions")
        for side, boundary in (("left", left), ("right", right)):
            ports = expected.get(boundary.region)
            if ports is None:
                continue  # The invalid native boundary already has a precise error.
            for pair_index, pair in enumerate(row.ports):
                port = getattr(pair, side)
                required = ports[0] if type(port) is EntryPortRef else ports[1]
                if port_key(port) not in required:
                    error("boundary_port", f"{path}.ports[{pair_index}].{side}",
                          "pair endpoint must belong to its corresponding boundary")
    return tuple(errors)


__all__ = ["native_errors", "port_key", "region_port_keys"]
