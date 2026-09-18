"""Candidate discovery over the unified K/Σ/A/R/Q/M graph.

The execution detector works directly on event payloads because that is the
most precise representation for a single pass.  This module deliberately
rebuilds a small amount of evidence from :class:`ProgramGraph` instead.  It
is the graph-level checkpoint: an action is reusable only when the graph
shows the same observed state reads, no observed invalidation between calls,
and a complete exact-reuse effect contract.  Missing edges never become a
claim that a dependency is absent.
"""
from __future__ import annotations

import re
from bisect import bisect_right
from collections import defaultdict

from scar.ir import NodeKind, Opportunity, ProgramGraph, ProofStatus, proof


_INDEX = re.compile(r"^invocation:(\d+):")
_EFFECT_COLLECTIONS = ("reads", "writes", "allocates", "frees", "aliases", "escapes")


def _index(node_id: str) -> int | None:
    match = _INDEX.match(node_id)
    return int(match.group(1)) if match else None


def _dynamic_actions(graph: ProgramGraph):
    for node in graph.nodes.values():
        if node.kind != NodeKind.ACTION or not node.node_id.startswith("invocation:"):
            continue
        if not node.source:
            continue
        index = _index(node.node_id)
        if index is not None:
            yield node, index


def _effect_proof_status(effect: dict) -> ProofStatus:
    """Separate a known visible effect from missing effect evidence."""
    knowledge = effect.get("collection_knowledge", {})
    if any(effect.get(name) for name in
           ("writes", "allocates", "frees", "aliases", "escapes")):
        return ProofStatus.DISPROVEN
    scalar = [effect.get(name) for name in
              ("rng_effect", "may_raise", "external_effect", "ordering_effect")]
    if any(value not in {None, "NONE", "UNKNOWN"} for value in scalar):
        return ProofStatus.DISPROVEN
    if (any(knowledge.get(name) != "KNOWN" for name in _EFFECT_COLLECTIONS)
            or any(value != "NONE" for value in scalar)):
        return ProofStatus.UNKNOWN
    return ProofStatus.PROVEN


def graph_candidates(graph: ProgramGraph) -> list[Opportunity]:
    """Find repeated actions from graph edges, retaining proof uncertainty.

    Aggregate profiler actions have no dynamic invocation and are excluded.
    Actions with no observed reads are also excluded: an empty read set may
    mean allocation, RNG, or an unobserved dependency, so it cannot support
    exact reuse.  The result is intentionally a separate candidate kind from
    event-level ``ReuseCandidate`` so reports show which view supplied the
    evidence.
    """
    actions = list(_dynamic_actions(graph))
    action_by_index = {index: node for node, index in actions}
    # Build adjacency once. Scanning every graph edge for every action turns
    # the detector quadratic on real traces with hundreds of thousands of
    # edges; these maps keep the graph pass linear in its input size.
    reads_by_action: dict[str, set[str]] = defaultdict(set)
    writes_by_state: dict[str, list[int]] = defaultdict(list)
    for edge in graph.edges:
        if edge.relation == "reads":
            reads_by_action[edge.target].add(edge.source)
        elif edge.relation == "writes":
            index = _index(edge.source)
            if index is not None:
                writes_by_state[edge.target].append(index)
    for values in writes_by_state.values():
        values.sort()
    grouped: dict[tuple[str, str, tuple[str, ...]], list[tuple[object, int]]] = defaultdict(list)
    for node, index in actions:
        reads = reads_by_action[node.node_id]
        if not reads:
            continue
        grouped[(str(node.source), node.label, tuple(sorted(reads)))].append((node, index))

    result: list[Opportunity] = []
    for (code_id, action_label, read_signature), calls in grouped.items():
        if len(calls) < 2:
            continue
        calls.sort(key=lambda item: item[1])
        first_index = calls[0][1]
        support = [index for _node, index in calls]
        effect_statuses = [_effect_proof_status(node.attrs.get("effect", {}))
                           for node, _index_value in calls]
        effects_complete = all(status == ProofStatus.PROVEN
                               for status in effect_statuses)
        effect_status = (ProofStatus.DISPROVEN
                         if ProofStatus.DISPROVEN in effect_statuses else
                         ProofStatus.PROVEN if effects_complete else ProofStatus.UNKNOWN)
        writes_between = False
        last_index = calls[-1][1]
        for state in read_signature:
            state_writes = writes_by_state.get(state, [])
            position = bisect_right(state_writes, first_index)
            if position < len(state_writes) and state_writes[position] <= last_index:
                # A write emitted by one of the repeated actions is part of
                # its own effect contract and is checked above. Only an
                # intervening action invalidates the reuse hypothesis.
                intervening = False
                for index in state_writes[position:]:
                    if index > last_index:
                        break
                    if not any(call_index == index for call_index in support):
                        intervening = True
                        break
                if intervening:
                    writes_between = True
                    break
        # Missing write edges cannot prove the absence of a mutation.  Every
        # intervening action must say its write collection is complete before
        # the indexed search can become a negative proof.
        intervening_indices = [
            index for index in range(first_index + 1, last_index)
            if index not in support
        ]
        intervening_writes_complete = all(
            action_by_index.get(index) is not None and
            action_by_index[index].attrs.get("effect", {}).get(
                "collection_knowledge", {}).get("writes") == "KNOWN"
            for index in intervening_indices
        )
        write_status = (ProofStatus.DISPROVEN if writes_between else
                        ProofStatus.PROVEN if intervening_writes_complete else
                        ProofStatus.UNKNOWN)
        duration = sum(int(node.attrs.get("duration_ns") or 0) for node, _ in calls[1:])
        if not effects_complete:
            decision = "rejected"
            rejection = ("graph effect contract has a visible effect"
                         if effect_status == ProofStatus.DISPROVEN else
                         "graph effect contract is incomplete")
            backend = None
        elif writes_between:
            decision = "rejected"
            rejection = "graph shows an intervening write to a reused input state"
            backend = None
        elif write_status == ProofStatus.UNKNOWN:
            decision = "rejected"
            rejection = "graph has incomplete intervening write evidence"
            backend = None
        else:
            decision = "proposed"
            rejection = None
            backend = "exact_reuse"
        supporting_nodes = [node.node_id for node, _ in calls]
        result.append(Opportunity(
            kind="GraphReuseCandidate", code_id=code_id, evidence="Observed",
            applicability="same_graph_read_state_set",
            guard=("all graph reads, writes, aliases, escapes, ordering and exact contract "
                   "must be complete; runtime input snapshots remain required"),
            reason=(f"{len(calls)} {action_label} actions share the same observed graph read states"),
            supporting_events=support, expected_savings_ns=duration,
            decision=decision, backend=backend, rejection_reason=rejection,
            proof_obligations=[
                proof(
                    "same_read_versions", "applicability",
                    "all repeated actions read the same logical state versions",
                    ProofStatus.PROVEN, evidence="Observed", reason=(
                        f"{len(calls)} actions share {len(read_signature)} graph read states"),
                    supporting_events=support, supporting_nodes=supporting_nodes,
                ),
                proof(
                    "effects_allow_exact_reuse", "legality",
                    "all invocations have complete effects with no visible mutation, RNG, exception, escape or ordering effect",
                    effect_status, evidence=("Observed" if effect_status != ProofStatus.UNKNOWN
                                             else "UNKNOWN"),
                    reason=("complete exact-reuse effect contracts"
                            if effect_status == ProofStatus.PROVEN else rejection or ""),
                    supporting_events=support, supporting_nodes=supporting_nodes,
                ),
                proof(
                    "no_intervening_input_write", "legality",
                    "no action between repeated calls writes a reused input version",
                    write_status,
                    evidence=("Observed" if write_status != ProofStatus.UNKNOWN else "UNKNOWN"),
                    reason=(
                        "graph contains an intervening write" if writes_between else
                        "all intervening write sets are complete and contain no input write"
                        if intervening_writes_complete else
                        "one or more intervening write sets are incomplete"),
                    supporting_events=support, supporting_nodes=supporting_nodes,
                ),
            ],
        ))
    return result


__all__ = ["graph_candidates"]
