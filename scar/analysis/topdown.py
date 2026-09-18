"""Top-down region summaries for cross-layer optimization reasoning.

The v1 candidate detectors group leaves by ``CodeID``.  That is useful for
accounting, but it cannot answer where a repeated operation belongs in a call
tree.  This module is an evidence projection, not a transformation backend:
it reconstructs dynamic control regions, summarizes child effects upward and
reports the highest boundary that *could* own a candidate if its value
provenance is complete.

Unknown parent, write or effect evidence stays unknown.  In particular, a
leaf operation is never moved merely because it is repeated.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable
from collections.abc import Mapping

from scar.ir import NodeKind, ProgramGraph


def _event_index(node_id: str) -> int | None:
    if not node_id.startswith("invocation:"):
        return None
    try:
        return int(node_id.split(":", 2)[1])
    except (IndexError, ValueError):
        return None


def _is_dynamic_action(node) -> bool:
    return node.kind == NodeKind.ACTION and _event_index(node.node_id) is not None


def _candidate_get(candidate: Any, name: str, default: Any = None) -> Any:
    if isinstance(candidate, Mapping):
        return candidate.get(name, default)
    return getattr(candidate, name, default)


def _effect_complete(node) -> bool:
    effect = node.attrs.get("effect", {}) or {}
    knowledge = effect.get("collection_knowledge", {}) or {}
    collections = ("reads", "writes", "allocates", "frees", "aliases", "escapes")
    scalars = ("rng_effect", "may_raise", "external_effect", "ordering_effect")
    return (all(knowledge.get(name) == "KNOWN" for name in collections)
            and all(effect.get(name) == "NONE" for name in scalars))


@dataclass(slots=True)
class RegionSummary:
    """A dynamic operation and the evidence inherited from its descendants."""

    region_id: str
    parent_id: str | None
    label: str
    code_id: str | None
    process_id: Any
    start_event: int | None
    direct_reads: tuple[str, ...] = ()
    direct_writes: tuple[str, ...] = ()
    reads: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()
    children: tuple[str, ...] = ()
    duration_ns: int = 0
    effect_complete: bool = False
    descendant_effect_complete: bool = False
    unknown_reasons: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "region_id": self.region_id,
            "parent_id": self.parent_id,
            "label": self.label,
            "code_id": self.code_id,
            "process_id": self.process_id,
            "start_event": self.start_event,
            "direct_reads": list(self.direct_reads),
            "direct_writes": list(self.direct_writes),
            "reads": list(self.reads),
            "writes": list(self.writes),
            "children": list(self.children),
            "duration_ns": self.duration_ns,
            "effect_complete": self.effect_complete,
            "descendant_effect_complete": self.descendant_effect_complete,
            "unknown_reasons": list(self.unknown_reasons),
        }


@dataclass(slots=True)
class PlacementEvidence:
    """A report-only top-down placement hypothesis for one candidate."""

    candidate_kind: str
    candidate_code_id: str | None
    support_events: tuple[int, ...]
    current_region: str | None
    proposed_region: str | None
    status: str
    reason: str
    input_states: tuple[str, ...] = ()
    input_origins: dict[str, tuple[str, ...]] = field(default_factory=dict)
    unknown_reasons: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_kind": self.candidate_kind,
            "candidate_code_id": self.candidate_code_id,
            "support_events": list(self.support_events),
            "current_region": self.current_region,
            "proposed_region": self.proposed_region,
            "status": self.status,
            "reason": self.reason,
            "input_states": list(self.input_states),
            "input_origins": {
                key: list(value) for key, value in self.input_origins.items()
            },
            "unknown_reasons": list(self.unknown_reasons),
        }


class DynamicRegionIndex:
    """Control-tree and state summaries reconstructed from a ProgramGraph."""

    SCHEMA = "scar.topdown_regions"
    SCHEMA_VERSION = 1

    def __init__(self, graph: ProgramGraph):
        self.graph = graph
        self.node_by_event: dict[int, str] = {
            index: node.node_id
            for node in graph.nodes.values()
            if _is_dynamic_action(node)
            for index in [_event_index(node.node_id)]
            if index is not None
        }
        self.parent: dict[str, str] = {}
        self.children: dict[str, list[str]] = defaultdict(list)
        self.reads: dict[str, set[str]] = defaultdict(set)
        self.writes: dict[str, set[str]] = defaultdict(set)
        self.write_nodes: dict[str, list[str]] = defaultdict(list)
        self._build()
        self.summaries: dict[str, RegionSummary] = {}
        for node_id in self._dynamic_ids():
            self._summarize(node_id)

    def _dynamic_ids(self) -> tuple[str, ...]:
        return tuple(node.node_id for node in self.graph.nodes.values()
                     if _is_dynamic_action(node))

    def _build(self) -> None:
        dynamic = set(self._dynamic_ids())
        for edge in self.graph.edges:
            if edge.relation == "controls_dynamic" and edge.source in dynamic and edge.target in dynamic:
                # The trace's call stack should be a tree.  Keep the first
                # observed parent if malformed input contains duplicates.
                self.parent.setdefault(edge.target, edge.source)
                if self.parent[edge.target] == edge.source:
                    self.children[edge.source].append(edge.target)
            if edge.relation == "reads" and edge.target in dynamic:
                self.reads[edge.target].add(edge.source)
            elif edge.relation == "writes" and edge.source in dynamic:
                self.writes[edge.source].add(edge.target)
                self.write_nodes[edge.target].append(edge.source)
        for value in self.children.values():
            value[:] = list(dict.fromkeys(value))
        for value in self.write_nodes.values():
            value[:] = sorted(set(value), key=lambda item: _event_index(item) or -1)

    def ancestors(self, region_id: str, *, include_self: bool = True) -> tuple[str, ...]:
        if region_id not in self.graph.nodes or not _is_dynamic_action(self.graph.nodes[region_id]):
            raise KeyError(f"unknown dynamic region: {region_id}")
        result: list[str] = [region_id] if include_self else []
        seen = {region_id}
        current = region_id
        while current in self.parent:
            current = self.parent[current]
            if current in seen:
                break
            seen.add(current)
            result.append(current)
        return tuple(result)

    def descendants(self, region_id: str, *, include_self: bool = False) -> tuple[str, ...]:
        if region_id not in self.graph.nodes:
            raise KeyError(f"unknown region: {region_id}")
        result: list[str] = [region_id] if include_self else []
        pending = list(self.children.get(region_id, ()))
        while pending:
            child = pending.pop(0)
            result.append(child)
            pending.extend(self.children.get(child, ()))
        return tuple(result)

    def common_ancestor(self, regions: Iterable[str]) -> str | None:
        items = list(dict.fromkeys(regions))
        if not items:
            return None
        chains = [self.ancestors(item) for item in items]
        first = chains[0]
        for candidate in first:
            if all(candidate in chain for chain in chains[1:]):
                return candidate
        return None

    def _summarize(self, region_id: str) -> RegionSummary:
        cached = self.summaries.get(region_id)
        if cached is not None:
            return cached
        node = self.graph.nodes[region_id]
        direct_reads = tuple(sorted(self.reads.get(region_id, set())))
        direct_writes = tuple(sorted(self.writes.get(region_id, set())))
        child_ids = tuple(self.children.get(region_id, ()))
        descendants = [self._summarize(child) for child in child_ids]
        all_reads = set(direct_reads)
        all_writes = set(direct_writes)
        duration = int(node.attrs.get("duration_ns") or 0)
        unknown = []
        complete = _effect_complete(node)
        if not complete:
            unknown.append("direct_effect_contract_incomplete")
        for child in descendants:
            all_reads.update(child.reads)
            all_writes.update(child.writes)
            duration += child.duration_ns
            if not child.descendant_effect_complete:
                unknown.extend(child.unknown_reasons)
        unknown = sorted(set(unknown))
        summary = RegionSummary(
            region_id=region_id,
            parent_id=self.parent.get(region_id),
            label=node.label,
            code_id=node.source,
            process_id=node.attrs.get("process_id"),
            start_event=_event_index(region_id),
            direct_reads=direct_reads,
            direct_writes=direct_writes,
            reads=tuple(sorted(all_reads)),
            writes=tuple(sorted(all_writes)),
            children=child_ids,
            duration_ns=duration,
            effect_complete=complete,
            descendant_effect_complete=not unknown,
            unknown_reasons=tuple(unknown),
        )
        self.summaries[region_id] = summary
        return summary

    def input_origins(self, state_ids: Iterable[str], before_event: int | None = None) -> dict[str, tuple[str, ...]]:
        """Return observed action writers for each input state.

        The index can only use explicit ``writes`` edges.  An absent writer is
        therefore represented by an empty tuple and handled as unknown by the
        placement analysis; it is never interpreted as an immutable constant.
        """
        result: dict[str, tuple[str, ...]] = {}
        for state in state_ids:
            writers = self.write_nodes.get(state, [])
            if before_event is not None:
                writers = [item for item in writers
                           if (_event_index(item) is not None and
                               _event_index(item) < before_event)]
            result[state] = tuple(writers[-1:])
        return result

    def place(self, candidate) -> PlacementEvidence:
        support_events = tuple(int(value) for value in
                              (_candidate_get(candidate, "supporting_events", ()) or ()))
        support_nodes = tuple(self.node_by_event[event]
                              for event in support_events
                              if event in self.node_by_event)
        current = self.common_ancestor(support_nodes)
        if current is None:
            return PlacementEvidence(
                candidate_kind=str(_candidate_get(candidate, "kind", "UNKNOWN")),
                candidate_code_id=_candidate_get(candidate, "code_id"),
                support_events=support_events, current_region=None,
                proposed_region=None, status="UNKNOWN",
                reason="supporting actions have no common observed control region",
                unknown_reasons=("control_correspondence_missing",),
            )
        input_states = tuple(sorted(set().union(*(self.reads.get(node, set())
                                                   for node in support_nodes))))
        origins = self.input_origins(input_states,
                                     before_event=min(support_events) if support_events else None)
        unknown: list[str] = []
        if not input_states:
            unknown.append("supporting_actions_have_no_observed_input_states")
        if any(not value for value in origins.values()):
            unknown.append("input_provenance_origin_not_observed")
        # A candidate's own operations need a complete contract.  Do not
        # reject it merely because an unrelated sibling in the parent call has
        # an unknown effect: the whole point of this pass is to find a smaller
        # composite region before flattening a function's entire body.
        if any(not self.summaries[node].effect_complete for node in support_nodes):
            unknown.append("candidate_effect_contract_incomplete")

        # A write inside the common region invalidates the claim that its
        # inputs are invariant there.  The supporting action's own write is
        # included deliberately: a mutating leaf cannot be hoisted as pure.
        origin_inside = any(
            current in self.ancestors(writer)
            for writers in origins.values() for writer in writers
        )
        if origin_inside:
            unknown.append("input_origin_inside_candidate_region")
        if unknown:
            return PlacementEvidence(
                candidate_kind=str(_candidate_get(candidate, "kind", "UNKNOWN")),
                candidate_code_id=_candidate_get(candidate, "code_id"),
                support_events=support_events, current_region=current,
                proposed_region=None, status="UNKNOWN",
                reason="top-down placement needs complete control/effect/provenance evidence",
                input_states=input_states, input_origins=origins,
                unknown_reasons=tuple(sorted(set(unknown))),
            )
        origin_nodes = [writer for writers in origins.values() for writer in writers]
        availability = self.common_ancestor(tuple(support_nodes) + tuple(origin_nodes))
        if availability is None or availability == current:
            return PlacementEvidence(
                candidate_kind=str(_candidate_get(candidate, "kind", "UNKNOWN")),
                candidate_code_id=_candidate_get(candidate, "code_id"),
                support_events=support_events, current_region=current,
                proposed_region=None, status="KEEP",
                reason=("inputs and repeated actions meet at the current region; "
                        "there is no observed higher placement boundary"),
                input_states=input_states, input_origins=origins,
            )
        return PlacementEvidence(
            candidate_kind=str(_candidate_get(candidate, "kind", "UNKNOWN")),
            candidate_code_id=_candidate_get(candidate, "code_id"),
            support_events=support_events, current_region=current,
            proposed_region=availability, status="PROPOSED",
            reason=("input provenance and repeated actions meet at a higher region; "
                    "the operation may be considered for placement there"),
            input_states=input_states, input_origins=origins,
        )

    def report(self, candidates: Iterable = ()) -> dict[str, Any]:
        placements = [self.place(candidate) for candidate in candidates]
        return {
            "schema": self.SCHEMA,
            "schema_version": self.SCHEMA_VERSION,
            "regions": [item.as_dict() for item in self.summaries.values()],
            "placements": [item.as_dict() for item in placements],
            "counts": {
                "regions": len(self.summaries),
                "placements": len(placements),
                "proposed": sum(item.status == "PROPOSED" for item in placements),
                "unknown": sum(item.status == "UNKNOWN" for item in placements),
                "keep": sum(item.status == "KEEP" for item in placements),
            },
        }


def topdown_report(graph: ProgramGraph, candidates: Iterable = ()) -> dict[str, Any]:
    """Build a top-down region report over an existing evidence graph."""
    return DynamicRegionIndex(graph).report(candidates)


__all__ = ["RegionSummary", "PlacementEvidence", "DynamicRegionIndex",
           "topdown_report"]
