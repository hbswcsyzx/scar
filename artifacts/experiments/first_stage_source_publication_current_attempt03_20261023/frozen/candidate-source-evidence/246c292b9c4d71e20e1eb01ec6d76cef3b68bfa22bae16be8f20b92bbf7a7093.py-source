"""Complete action inventory for the unified program graph.

Candidate detectors are intentionally partial: an action with no matching
rule is not evidence that the action is safe to keep.  This module gives
every Action node an auditable disposition and a family derived from its
multi-label taxonomy.  It is a reporting layer, not a new rewrite rule.
"""
from __future__ import annotations

from collections import Counter
from typing import Iterable

from scar.ir import NodeKind, ProgramGraph


_FAMILY_LABELS = (
    ("compute", "VAL"),
    ("representation", "REP"),
    ("memory", "MEM"),
    ("transfer", "XFER"),
    ("state", "STATE"),
    ("control", "CTRL"),
    ("ordering", "ORDER"),
    ("external_io", "IO"),
    ("opaque", "OPAQUE"),
)


def _event_index(node_id: str) -> int | None:
    if not node_id.startswith("invocation:"):
        return None
    try:
        return int(node_id.split(":", 2)[1])
    except (IndexError, ValueError):
        return None


def _families(labels: Iterable[str]) -> list[str]:
    present = set(labels)
    return [family for family, label in _FAMILY_LABELS if label in present]


def summarize_action_inventory(graph: ProgramGraph, candidates=(), selection=None) -> dict:
    """Summarize every Action with a conservative disposition.

    ``selection`` is the :class:`SelectionResult` for ``candidates``.  An
    action supported by a selected candidate is ``TRANSFORM``; an understood
    rejected candidate is ``REJECT``; a known non-applicable candidate is
    ``KEEP``.  Actions with no candidate, static-only evidence, or any
    unresolved candidate remain ``UNKNOWN``.  In particular, no detector
    coverage is interpreted as proof that an action is harmless.
    """
    items = list(candidates)
    decisions = list(getattr(selection, "decisions", ()) or ())
    by_event: dict[int, list[object]] = {}
    for index, candidate in enumerate(items):
        decision = decisions[index] if index < len(decisions) else None
        for event_index in getattr(candidate, "supporting_events", ()) or ():
            by_event.setdefault(int(event_index), []).append(decision or candidate)

    action_nodes = [node for node in graph.nodes.values() if node.kind == NodeKind.ACTION]
    by_label = Counter()
    by_family = Counter()
    by_status = Counter()
    evidence = Counter()
    dynamic_actions = 0
    static_actions = 0
    unknown_effects = 0
    records: list[dict] = []
    for node in action_nodes:
        event_index = _event_index(node.node_id)
        dynamic = event_index is not None
        if dynamic:
            dynamic_actions += 1
        else:
            static_actions += 1
        labels = list(node.labels)
        families = _families(labels)
        by_label.update(labels)
        by_family.update(families or ["unclassified"])
        evidence[str(node.attrs.get("evidence", "UNKNOWN"))] += 1
        if dynamic:
            effect = node.attrs.get("effect", {}) or {}
            knowledge = effect.get("collection_knowledge", {})
            scalar = (effect.get("rng_effect"), effect.get("may_raise"),
                      effect.get("external_effect"), effect.get("ordering_effect"))
            if (any(value in {None, "UNKNOWN"} for value in scalar)
                    or any(knowledge.get(name) in {None, "UNKNOWN"}
                           for name in ("reads", "writes", "allocates", "frees",
                                        "aliases", "escapes"))):
                unknown_effects += 1
        supported = by_event.get(event_index, []) if dynamic else []
        statuses = [str(getattr(item, "action", getattr(item, "decision", "UNKNOWN")))
                    for item in supported]
        if "TRANSFORM" in statuses:
            status = "TRANSFORM"
            reason = "a selected candidate supports this dynamic action"
        elif statuses and all(item == "REJECT" for item in statuses):
            status = "REJECT"
            reason = "all supporting candidates were rejected by proof, cost or backend policy"
        elif statuses and all(item == "KEEP" for item in statuses):
            status = "KEEP"
            reason = "all supporting candidates prove non-applicability or were superseded"
        else:
            status = "UNKNOWN"
            reason = ("static syntax is only an inferred hint" if not dynamic else
                      "no complete candidate disposition covers this action" if not statuses else
                      "at least one supporting candidate remains unresolved")
        by_status[status] += 1
        records.append({
            "node_id": node.node_id,
            "event_index": event_index,
            "label": node.label,
            "labels": labels,
            "families": families,
            "dynamic": dynamic,
            "evidence": node.attrs.get("evidence", "UNKNOWN"),
            "status": status,
            "reason": reason,
            "candidate_count": len(supported),
        })
    return {
        "actions": len(action_nodes),
        "dynamic_actions": dynamic_actions,
        "static_actions": static_actions,
        "by_label": dict(sorted(by_label.items())),
        "by_family": dict(sorted(by_family.items())),
        "by_status": dict(sorted(by_status.items())),
        "evidence": dict(sorted(evidence.items())),
        "dynamic_actions_with_unknown_effects": unknown_effects,
        # The detailed records are useful for small traces.  Large traces can
        # omit them at the CLI while retaining this complete count summary.
        "records": records,
    }


__all__ = ["summarize_action_inventory"]
