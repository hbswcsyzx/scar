"""Navigate existing provider/native declarations without proving equivalence.

Every endpoint is an original core ID.  External element keys, signature
positions and logical exits remain evidence coordinates, not invented nodes.
These are structural declaration edges; no argument, alias, effect, native
dispatch or runtime implementation is inferred from a provider mapping.
"""
from __future__ import annotations

from dataclasses import replace

from scar.ir.program.dependencies import (
    DependencyEdge, DependencyEvidence, DependencyFrontier,
    DependencyKind as K, DependencyMeaning as M, DependencyPoint,
)
from scar.ir.program.native import EntryPortRef


def native_declaration_relations(namespace, index):
    """Project already validated records into the common graph vocabulary."""
    graph = index.graph
    if not (graph.provider_envelopes or graph.native_boundaries):
        return (), ()
    edges, notes = {}, {}

    def point(node):
        return DependencyPoint(namespace, node)

    def evidence(rule, paths, anchors):
        return (DependencyEvidence(rule, tuple(replace(namespace.graph,
            pointer=namespace.graph.pointer + '/' + path) for path in paths),
            tuple(point(node) for node in anchors)),)

    def emit(source, target, kind, rule, *paths):
        edge = DependencyEdge(point(source), point(target), kind, M.STRUCTURE,
            evidence(rule, paths, (source, target)))
        edges[edge] = edge

    def note(node, kind, detail):
        frontier = DependencyFrontier(point(node), kind, detail)
        notes[frontier] = frontier

    provider_paths = {row.id: 'provider_envelopes/' + str(i)
        for i, row in enumerate(graph.provider_envelopes)}
    for row in graph.provider_envelopes:
        note(row.id, 'PROVIDER_DECLARATION_AUTHORITY_OPEN',
            'Provider version, source receipts and coverage declarations are retained; '
            'their presence is not independent artifact replay, active runtime identity '
            'or a closed implementation/effect proof.')
    for ordinal, row in enumerate(graph.provider_regions):
        emit(row.provider, row.region, K.IMPLEMENTATION,
            'CANONICAL_PROVIDER_REGION_DECLARATION_V1',
            'provider_regions/' + str(ordinal), provider_paths[row.provider])
    for ordinal, row in enumerate(graph.provider_bindings):
        # ProviderElement paths are provenance coordinates, not executable
        # operands.  Unlike an ARGUMENT edge this never copies value facts.
        emit(row.provider, row.target, K.IMPLEMENTATION,
            'CANONICAL_PROVIDER_ELEMENT_DECLARATION_V1',
            'provider_bindings/' + str(ordinal), provider_paths[row.provider])

    boundary_paths = {row.id: 'native_boundaries/' + str(i)
        for i, row in enumerate(graph.native_boundaries)}

    def port_nodes(port):
        if type(port) is EntryPortRef:
            return (index.entry_port(port).id,)
        return tuple(site.use.id for site in index.exit_port_uses(port))

    for row in graph.native_boundaries:
        path = boundary_paths[row.id]
        emit(row.provider, row.id, K.CONTAINS,
            'CANONICAL_NATIVE_PROVIDER_DECLARATION_V1', path, provider_paths[row.provider])
        emit(row.id, row.region, K.IMPLEMENTATION,
            'CANONICAL_NATIVE_REGION_DECLARATION_V1', path)
        for field in ('inputs', 'outputs', 'core_inputs', 'core_outputs'):
            for ordinal, slot in enumerate(getattr(row, field)):
                slot_path = path + '/' + field + '/' + str(ordinal)
                nodes = port_nodes(slot.port)
                for node in nodes:
                    emit(row.id, node, K.CONTAINS,
                        'CANONICAL_NATIVE_PORT_DECLARATION_V1', slot_path)
                # Logical exit declarations can legitimately have no Return
                # occurrence (e.g. an intercepted cleanup or nonreturning body).
                # Keep that original slot without creating an output Value.
                if not nodes:
                    emit(row.id, row.region, K.CONTAINS,
                        'CANONICAL_NATIVE_EXIT_WITHOUT_TERMINAL_USE_V1', slot_path)
        note(row.id, 'NATIVE_SIGNATURE_BINDING_OPEN',
            'Ordered native/core-only slots resolve original entry Values and all '
            'declared normal/raise exit Uses.  Signature roles and trees do not '
            'prove Python/native ABI binding, alias identity, effects or dispatch.')

    for ordinal, row in enumerate(graph.boundary_relations):
        path = 'boundary_relations/' + str(ordinal)
        emit(row.left, row.right, K.IMPLEMENTATION,
            'CANONICAL_NATIVE_CORRESPONDENCE_DECLARATION_V1', path,
            boundary_paths[row.left], boundary_paths[row.right])
        # Pair declarations may relate unlike types and unlike exit kinds.
        # Preserve their coordinates as STRUCTURE, never as VALUE transfer or
        # equivalence.  All original conditions/obligations remain at `path`.
        for position in range(len(row.ports)):
            # A logical exit can have many Return sites.  Do not manufacture
            # a Cartesian product of sites from two independent bodies.  The
            # original pair record is the compact logical-port correspondence;
            # boundary membership above resolves each side's sites separately.
            emit(row.left, row.right, K.IMPLEMENTATION,
                'CANONICAL_NATIVE_PORT_PAIR_DECLARATION_V1', path,
                path + '/ports/' + str(position))
        for boundary in (row.left, row.right):
            domains = ', '.join(item.domain.value for item in row.obligations)
            note(boundary, 'NATIVE_CORRESPONDENCE_OBLIGATIONS_OPEN',
                path + ' is an unproved declaration, not equivalence; original '
                'conditions and obligations remain open: ' + domains + '.')
    return tuple(edges), tuple(notes)


__all__ = ['native_declaration_relations']
