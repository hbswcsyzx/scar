"""Control dependencies over original Region CFGs, without executing targets.

NetworkX's immediate_dominators on the reversed graph supplies postdominators:
https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.dominance.immediate_dominators.html

Every cyclic SCC and every INVOKE with no termination contract gets internal
may-diverge exit candidates. The virtual exit is an analysis-only object; no
program ID is created. Results are CD in that explicitly extended CFG, not a
proof of termination-sensitive motion legality in the original program. Open
termination/resumption scope is retained as query frontiers.
"""
from __future__ import annotations

from collections import OrderedDict, defaultdict
from dataclasses import replace

import networkx as nx

from scar.ir.program.dependencies import (
    DependencyCondition, DependencyEdge, DependencyEvidence, DependencyFrontier,
    DependencyKind, DependencyMeaning, DependencyNeighborhood, DependencyPoint, DependencyStrength,
)
from scar.ir.program.ids import BlockID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import TerminatorKind


RULE = "CFG_POSTDOM_DIVERGENCE_EXTENDED_CONTROL_V1"


class ControlDependencyProvider:
    """Lazy, bounded local CD projection; all endpoints keep their context.

    The analysis considers declared normal/raise successors and explicit
    control alternatives, independently of whether a runtime took them.
    Abstract divergence edges and the virtual exit are never exported.
    An empty neighborhood is not an absence-of-control proof when a frontier
    remains. No call is assumed terminating merely from effects_complete.
    """
    relation_kinds = frozenset((DependencyKind.CONTROL,))

    def __init__(self, load_index, *, max_cached_records=250000, max_cfg_nodes=200000,
                 max_control_edges=200000):
        if not callable(load_index):
            raise TypeError("control dependency provider needs the shared graph loader")
        if any(type(n) is not int or n < 1 for n in (max_cached_records, max_cfg_nodes, max_control_edges)):
            raise ValueError("control dependency budgets must be positive integers")
        self.load_index = load_index
        self.max_cached_records, self.max_cfg_nodes, self.max_control_edges = (
            max_cached_records, max_cfg_nodes, max_control_edges)
        self._cache, self._cache_records = OrderedDict(), 0

    def incoming(self, point):
        return self._neighborhood(point, incoming=True)

    def outgoing(self, point):
        return self._neighborhood(point, incoming=False)

    def _tables(self, namespace):
        # Validate every supplied declaration through the one owning session,
        # even when its immutable namespace already has derived cache entries.
        index = self.load_index(namespace)
        if namespace in self._cache:
            self._cache.move_to_end(namespace)
            return index, self._cache[namespace]
        rows = self._build(namespace, index)
        if rows[3] <= self.max_cached_records:
            while self._cache and self._cache_records + rows[3] > self.max_cached_records:
                _, old = self._cache.popitem(last=False)
                self._cache_records -= old[3]
            self._cache[namespace] = rows
            self._cache_records += rows[3]
        return index, rows

    @staticmethod
    def _owner(index, node):
        if type(node) is RegionID:
            return node if node in index.regions else None
        if type(node) is BlockID:
            return index._blocks.get(node)
        if type(node) is OperationID:
            block = index._operation_blocks.get(node)
            return index._blocks.get(block)
        if type(node) is UseID:
            site = index._uses.get(node)
            return ControlDependencyProvider._owner(index, site.operation) if site is not None else None
        if type(node) is ValueID:
            value = index.values.get(node)
            return value.region if value is not None else None
        return None

    def _neighborhood(self, point, *, incoming):
        if type(point) is not DependencyPoint:
            raise TypeError("control query needs a qualified original dependency point")
        index, (before, after, notes, _) = self._tables(point.namespace)

        def contextual(endpoint):
            return replace(endpoint, context=point.context)

        edges = tuple(replace(edge, source=contextual(edge.source), target=contextual(edge.target),
            evidence=tuple(replace(e, anchors=tuple(contextual(a) for a in e.anchors)) for e in edge.evidence),
            conditions=tuple(replace(c, subject=contextual(c.subject) if c.subject is not None else None,
                             operands=tuple(contextual(operand) for operand in c.operands))
                             for c in edge.conditions))
            for edge in (before if incoming else after).get(point.node, ()))
        owner = self._owner(index, point.node)
        frontiers = tuple(DependencyFrontier(point, kind, detail) for kind, detail in notes.get(owner, ()))
        incomplete = {"CONTROL_CFG_NODE_BUDGET", "CONTROL_EDGE_DOMINANCE_NODE_BUDGET",
                      "CONTROL_EDGE_BUDGET", "CONTROL_RESUMPTION_OPEN", "CONTROL_TERMINATOR_UNAVAILABLE"}
        return DependencyNeighborhood(edges, frontiers,
            enumerated=not any(item.kind in incomplete for item in frontiers))

    def _build(self, namespace, index):
        before, after, notes = defaultdict(list), defaultdict(list), defaultdict(list)
        edge_count, cfg_count = 0, 0
        emitted = set()

        def point(node):
            return DependencyPoint(namespace, node)

        for region in index.graph.regions:
            if cfg_count + len(region.blocks) > self.max_cfg_nodes:
                notes[region.id].append(("CONTROL_CFG_NODE_BUDGET",
                    "This Region's original CFG remains available; its postdom analysis exceeded the explicit node budget."))
                continue
            cfg_count += len(region.blocks)
            cfg = nx.DiGraph()
            cfg.add_nodes_from(b.id for b in region.blocks)
            original_edges, exits, invokes, temporal = [], set(), set(), set()
            for block in region.blocks:
                if any(index.operations[identity].callee is not None for identity in block.operations):
                    invokes.add(block.id)
                term_op = index.operations[block.operations[-1]]
                term = term_op.terminator
                if term is None:
                    notes[region.id].append(("CONTROL_TERMINATOR_UNAVAILABLE", "Original block has no declared control terminator."))
                    continue
                if term.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE):
                    exits.add(block.id)
                if term.kind is TerminatorKind.INVOKE:
                    invokes.add(block.id)
                if term.kind in (TerminatorKind.SUSPEND, TerminatorKind.BODY_DRIVE):
                    temporal.add(block.id)
                for ordinal, successor in enumerate(term.successors):
                    if successor.block not in cfg:
                        temporal.add(block.id)
                        continue
                    cfg.add_edge(block.id, successor.block)
                    original_edges.append((block.id, term_op.id, ordinal, successor.block))

            cyclic = set()
            for component in nx.strongly_connected_components(cfg):
                if len(component) > 1 or any(cfg.has_edge(node, node) for node in component):
                    cyclic.update(component)
            if cyclic:
                notes[region.id].append(("CONTROL_TERMINATION_OPEN",
                    "Cyclic CFG: CD uses explicit may-diverge exits; no termination-sensitive motion or absence-of-dependence proof is established."))
            if invokes:
                notes[region.id].append(("CONTROL_INVOKE_TERMINATION_OPEN",
                    "INVOKE normal/raise signatures do not prove that their callees complete; may-diverge alternatives remain."))
            if temporal:
                notes[region.id].append(("CONTROL_RESUMPTION_OPEN",
                    "Suspend/drive boundaries retain declared successors but do not guarantee resumption or completion."))
            native = any(boundary.region == region.id for boundary in index.graph.native_boundaries)
            if native:
                notes[region.id].append(("CONTROL_NATIVE_TERMINATION_OPEN",
                    "A native signature/port boundary does not establish termination of its implementation."))

            # This object never leaves NetworkX or enters a canonical record.
            virtual_exit = object()
            cfg.add_node(virtual_exit)
            for block in exits | cyclic | invokes | temporal | ({region.entry} if native else set()):
                cfg.add_edge(block, virtual_exit)
            postdom = nx.immediate_dominators(cfg.reverse(copy=False), virtual_exit)
            unrooted = set(b.id for b in region.blocks) - set(postdom)
            if unrooted:
                notes[region.id].append(("CONTROL_POSTDOM_SCOPE_OPEN",
                    "Some original blocks have no path to a declared or explicit may-diverge boundary."))

            original_successors = defaultdict(set)
            for source, _, _, target in original_edges:
                original_successors[source].add(target)
            augmented = bool(cyclic or invokes or temporal or native)
            bounded = False

            def emit(controller, ordinal, block, rule, scope, *, necessary=False):
                nonlocal edge_count, bounded
                for controlled in (block.id, *block.operations):
                    # A possible postdom influence and an entry-reachability
                    # prerequisite are different facts, even at the same IDs.
                    key = controller, ordinal, controlled, rule
                    if key in emitted:
                        continue
                    if edge_count >= self.max_control_edges:
                        bounded = True
                        return
                    evidence = DependencyEvidence(rule, (namespace.graph,),
                        (point(controller), point(block.id), point(region.id)))
                    conditions = (
                        DependencyCondition("canonical", "SUCCESSOR_SELECTED", point(controller), ordinal),
                        DependencyCondition("control.analysis", scope, point(region.id)),
                    )
                    edge = DependencyEdge(point(controller), point(controlled), DependencyKind.CONTROL,
                        DependencyMeaning.DEPENDENCE, (evidence,), conditions,
                        strength=DependencyStrength.MAY if augmented and not necessary else DependencyStrength.EXACT)
                    before[controlled].append(edge)
                    after[controller].append(edge)
                    emitted.add(key)
                    edge_count += 1

            for source, controller, ordinal, target in original_edges:
                if source not in postdom or target not in postdom:
                    continue
                # A single CFG jump does not become a source branch merely
                # because the analysis introduced a divergence candidate.
                if len(original_successors[source]) < 2:
                    continue
                runner, stop, visited = target, postdom[source], set()
                while runner is not virtual_exit and runner != stop:
                    if runner in visited:
                        raise ValueError("postdominator library returned a cyclic parent chain")
                    visited.add(runner)
                    block = index._block_records[runner]
                    emit(controller, ordinal, block, RULE, "DIVERGENCE_EXTENDED_CFG")
                    if bounded:
                        break
                    runner = postdom[runner]
                if bounded:
                    break

            # Postdom influence (especially with may-diverge exits) is not a
            # necessary path predicate. Separately retain an original edge
            # that dominates entry reachability, including acyclic INVOKEs and
            # ordinary diamonds. Split vertices never become program IDs.
            # Scope is explicitly original-entry reachability: this neither
            # guarantees completion nor closes protocol/resumption entrances.
            if not bounded:
                if cfg_count + len(original_edges) > self.max_cfg_nodes:
                    notes[region.id].append(("CONTROL_EDGE_DOMINANCE_NODE_BUDGET",
                        "Additional entry-edge dominance relations exceeded the explicit analysis node budget."))
                else:
                    cfg_count += len(original_edges)
                    forward, selections = nx.DiGraph(), {}
                    forward.add_nodes_from(b.id for b in region.blocks)
                    for source, controller, ordinal, target in original_edges:
                        selected = object()
                        forward.add_edge(source, selected)
                        forward.add_edge(selected, target)
                        if len(original_successors[source]) >= 2:
                            selections[selected] = controller, ordinal
                    dominators = nx.immediate_dominators(forward, region.entry)
                    children = defaultdict(list)
                    for node, parent in dominators.items():
                        if node != parent:
                            children[parent].append(node)
                    # One walk of the dominator tree avoids quadratic climbs
                    # in long straight-line CFGs. Keep only the nearest
                    # selection; its controller has its own prerequisite.
                    pending = [(region.entry, None)]
                    while pending and not bounded:
                        node, nearest = pending.pop()
                        nearest = selections.get(node, nearest)
                        if type(node) is BlockID and nearest is not None:
                            controller, ordinal = nearest
                            emit(controller, ordinal, index._block_records[node],
                                "CFG_ENTRY_EDGE_DOMINANCE_CONTROL_NECESSITY_V1",
                                "ORIGINAL_EDGE_REQUIRED_FOR_ENTRY_REACHABILITY", necessary=True)
                        pending.extend((child, nearest) for child in children[node])
            if bounded:
                notes[region.id].append(("CONTROL_EDGE_BUDGET",
                    "Additional control dependencies in this Region were not materialized within the explicit edge budget."))

        # Count original nodes as well as emitted edges and notes. In
        # particular a giant graph with no CD edges cannot occupy free cache.
        nodes = sum(len(rows) for rows in (index.values, index.operations, index._uses, index._blocks,
            index.regions, index.locations, index.graph.resources, index.graph.resource_requirements,
            index.graph.environments, index.graph.control_ports, index.graph.provider_envelopes,
            index.graph.native_boundaries))
        records = nodes + edge_count + sum(len(v) for v in notes.values())
        return dict(before), dict(after), dict(notes), records
