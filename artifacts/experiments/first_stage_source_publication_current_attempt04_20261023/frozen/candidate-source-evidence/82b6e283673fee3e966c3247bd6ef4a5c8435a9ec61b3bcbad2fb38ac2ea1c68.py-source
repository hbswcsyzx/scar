"""Bounded public projection of program/trace regions, with explicit selection."""
from __future__ import annotations

from collections import Counter, defaultdict
import time

from scar.ir.frontend_v2 import build_semantic
from scar.ir.v2 import EvidenceGraph, IRBundle, ValueGraph
from scar.trace.normalize_v2 import normalize_trace
from .regions_v2 import build_regions
from .runtime_effects_v2 import ingest_runtime_effects


def ranked_roots(nodes, allowed, *, dynamic):
    """One forest walk; only selected-scope parentage contributes to ranking."""
    children = defaultdict(list)
    roots = []
    for identity in allowed:
        node = nodes[identity]
        parent = node.parent if dynamic else node.parent_id
        if parent in allowed:
            children[parent].append(identity)
        else:
            roots.append(identity)
    sizes = {}
    for root in roots:
        stack = [(root, False)]
        while stack:
            node, finish = stack.pop()
            if finish:
                sizes[node] = 1 + sum(sizes[child] for child in children[node])
            else:
                stack.append((node, True))
                stack.extend((child, False) for child in children[node])
    roots.sort(key=lambda identity: (-sizes[identity], identity.wire))
    return roots, sizes


def report_regions(source, *, view="semantic", project_root=None, root_ids=(),
                   max_depth=0, root_limit=8, scope=None):
    """Build a bounded, disclosed projection; omitted regions remain available."""
    if view not in {"semantic", "execution"}:
        raise ValueError("view must be semantic or execution")
    if type(max_depth) is not int or max_depth < 0:
        raise ValueError("max-depth must be a nonnegative integer")
    if type(root_limit) is not int or root_limit <= 0:
        raise ValueError("root-limit must be a positive integer")
    started = time.perf_counter()
    effects = None
    scope_counts = {}
    if view == "semantic":
        frontend = build_semantic(source, project_root=project_root)
        bundle = IRBundle(frontend.graph, EvidenceGraph(), ValueGraph())
        nodes = bundle.semantic.definitions
        allowed = set(nodes)
        coverage = {key: value for key, value in frontend.coverage.items()
                    if key not in {"owners", "diagnostics"}}
        ranked, sizes = ranked_roots(nodes, allowed, dynamic=False)
    else:
        if project_root is not None:
            raise ValueError("execution view accepts a trace; project-root belongs to semantic view")
        normalized = normalize_trace(source)
        bundle = normalized.bundle
        runtime = ingest_runtime_effects(bundle)
        effects = runtime.engine
        coverage = {key: value for key, value in normalized.coverage.items() if key != "records"}
        nodes = bundle.evidence.instances
        groups = defaultdict(set)
        for identity, scope_id in runtime.instance_scopes.items():
            groups[scope_id].add(identity)
        scope_counts = {key: len(value) for key, value in sorted(groups.items())}
        rankings = {key: ranked_roots(nodes, group, dynamic=True) for key, group in groups.items()}
        if scope is None and root_ids:
            by_wire = {identity.wire: identity for identity in nodes}
            if any(wire not in by_wire for wire in root_ids):
                raise ValueError("unknown root identity")
            requested_scopes = {runtime.instance_scopes[by_wire[wire]] for wire in root_ids}
            if len(requested_scopes) != 1:
                raise ValueError("execution roots span observation scopes; request one scope per report")
            scope = requested_scopes.pop()
        elif scope is None and groups:
            scope = min(groups, key=lambda key: (-max(rankings[key][1].values(), default=0), key))
        if scope not in groups:
            raise ValueError("unknown or empty runtime scope; available: " + ", ".join(sorted(groups)))
        allowed = groups[scope]
        ranked, sizes = rankings[scope]
    by_wire = {identity.wire: identity for identity in allowed}
    if root_ids:
        if len(set(root_ids)) != len(root_ids) or any(wire not in by_wire for wire in root_ids):
            raise ValueError("roots must be unique existing identities in the selected scope")
        selected = tuple(by_wire[wire] for wire in root_ids)
        selection = "explicit roots"
    else:
        selected = tuple(ranked[:root_limit])
        selection = "largest observed/lexical subtrees, then stable identity"
    if not selected:
        raise ValueError("no operation roots available for region construction")
    inventory = build_regions(bundle, view=view, roots=selected, max_depth=max_depth,
                              effects=effects, scope=scope)
    scope = inventory.scope
    document = inventory.to_dict()
    return {
        "schema": "scar.region-report", "schema_version": 1,
        "input": str(source), "view": view, "scope": scope,
        "selection": {"policy": selection, "selected_roots": [item.wire for item in selected],
                      "available_roots": len(ranked), "root_limit": root_limit,
                      "max_depth": max_depth, "available_scopes": scope_counts,
                      "selected_scope_members": len(allowed),
                      "selected_root_sizes": {item.wire: sizes[item] for item in selected},
                      "omission_means": "unexpanded evidence, never dead or safe to delete"},
        "input_coverage": coverage, "inventory": document,
        "summary": {"regions": len(inventory.graph.regions), "ports": len(inventory.graph.ports),
                    "construction_gaps": dict(sorted(Counter(
                        gap.facet.value for item in inventory.constructions.values() for gap in item.gaps).items())),
                    "original_alternatives": len(inventory.graph.alternatives),
                    "selected_transformations": 0},
        "measurement": {"analysis_seconds": time.perf_counter() - started,
                        "scope": "offline region construction, not workload speedup"},
    }


__all__ = ["report_regions", "ranked_roots"]
