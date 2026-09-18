"""Loop candidates discovered from the unified program graph.

``loop_controls`` is an observed control relation.  It is deliberately kept
separate from record order and from the event-level loop detector so a graph
consumer can ask which actions occurred in different iterations without
assuming that every serialized event belongs to the same loop body.
"""
from __future__ import annotations

from collections import defaultdict

from scar.ir import NodeKind, Opportunity, ProgramGraph, ProofStatus, proof
from .graph_candidates import _effect_proof_status, _index


def _read_signature(graph: ProgramGraph, action_id: str,
                    state_by_id: dict[str, object],
                    reads_by_action: dict[str, set[str]]) -> tuple:
    """Return a region-aware signature for the states read by an action."""
    signature = []
    for state_id in sorted(reads_by_action.get(action_id, ())):
        state = state_by_id.get(state_id)
        attrs = getattr(state, "attrs", {}) if state is not None else {}
        signature.append((
            state_id,
            attrs.get("storage_id"),
            attrs.get("offset", 0),
            tuple(attrs.get("shape", [])),
            tuple(attrs.get("strides", [])),
            attrs.get("dtype"),
            attrs.get("device"),
        ))
    return tuple(signature)


def graph_loop_candidates(graph: ProgramGraph) -> list[Opportunity]:
    """Find repeated actions attached to distinct observed loop iterations.

    The result is a *candidate*, never an automatic transformation.  A loop
    action must have a non-empty, equal region-aware read signature in at
    least two iterations.  Effects are checked from the graph contract, while
    loop exits, exceptions, consumers, and hoisting cost remain proof
    obligations for the planner/backend.
    """
    state_by_id = {
        node.node_id: node for node in graph.nodes.values()
        if node.kind == NodeKind.STATE
    }
    reads_by_action: dict[str, set[str]] = defaultdict(set)
    for edge in graph.edges:
        if edge.relation == "reads" and edge.target in graph.nodes:
            reads_by_action[edge.target].add(edge.source)

    # One record per observed marker-to-action edge.  Include the marker's
    # process/thread scope because InvocationID counters can restart after a
    # fork and a worker thread may execute the same source independently.
    grouped: dict[tuple, list[tuple[object, object, object]]] = defaultdict(list)
    for edge in graph.edges:
        if edge.relation != "loop_controls":
            continue
        marker = graph.nodes.get(edge.source)
        action = graph.nodes.get(edge.target)
        if marker is None or action is None:
            continue
        if marker.kind != NodeKind.ACTION or marker.label != "loop_iteration":
            continue
        if action.kind != NodeKind.ACTION or action.label == "loop_iteration":
            continue
        if not action.node_id.startswith("invocation:") or not action.source:
            continue
        marker_attrs = marker.attrs
        action_attrs = action.attrs
        process = marker_attrs.get("process_id", "unknown")
        thread = marker_attrs.get("thread_id", "unknown")
        scope = (process, thread, marker_attrs.get("invocation_id"),
                 edge.attrs.get("loop_target_offset"), action.source,
                 action.label)
        grouped[scope].append((marker, action, edge))

    result: list[Opportunity] = []
    for (process, thread, invocation, loop_offset, code_id, action_label), records in grouped.items():
        # A marker can have more than one action in its body.  Distinct marker
        # node IDs, rather than record order, define the iteration count.
        by_marker: dict[str, list[tuple[object, object]]] = defaultdict(list)
        for marker, action, edge in records:
            by_marker[marker.node_id].append((action, edge))
        if len(by_marker) < 2:
            continue

        ambiguous_actions = any(len(items) > 1 for items in by_marker.values())
        actions = [items[0][0] for _marker_id, items in sorted(by_marker.items())]
        signatures = [_read_signature(graph, action.node_id, state_by_id,
                                      reads_by_action) for action in actions]
        if not signatures or not signatures[0] or any(sig != signatures[0]
                                                      for sig in signatures[1:]):
            same_inputs = False
        else:
            same_inputs = True

        effect_statuses = [
            _effect_proof_status(action.attrs.get("effect", {}))
            for action in actions
        ]
        effect_status = (
            ProofStatus.DISPROVEN
            if ProofStatus.DISPROVEN in effect_statuses else
            ProofStatus.PROVEN
            if all(item == ProofStatus.PROVEN for item in effect_statuses) else
            ProofStatus.UNKNOWN
        )
        supporting_events = [index for action in actions
                             if (index := _index(action.node_id)) is not None]
        duration = sum(int(action.attrs.get("duration_ns") or 0)
                       for action in actions[1:])
        eligible = (not ambiguous_actions and same_inputs
                    and effect_status == ProofStatus.PROVEN)
        if ambiguous_actions:
            rejection = "multiple same-code actions occur under one marker; graph alignment is ambiguous"
        elif not same_inputs:
            rejection = "graph read regions or logical versions changed across iterations"
        elif effect_status == ProofStatus.DISPROVEN:
            rejection = "graph loop action has a visible mutation or external effect"
        elif effect_status == ProofStatus.UNKNOWN:
            rejection = "graph loop action effect contract is incomplete"
        else:
            rejection = None
        supporting_nodes = [action.node_id for action in actions]
        result.append(Opportunity(
            kind="GraphLoopInvariantCandidate", code_id=code_id,
            evidence="Observed",
            applicability=("ambiguous_graph_loop_actions" if ambiguous_actions else
                           "same_inputs_across_graph_loop_iterations"
                           if same_inputs else
                           "changing_inputs_across_graph_loop_iterations"),
            guard=("observed loop_controls, region-aware logical versions, aliases, effects, "
                   "loop exits, exceptions, consumers and measured hoisting cost must be proven"),
            reason=(f"{action_label} occurred in {len(by_marker)} observed loop iterations"
                    + (" with ambiguous same-code action alignment" if ambiguous_actions
                       else " with the same graph read regions" if same_inputs
                       else " with changing graph read regions")),
            supporting_events=supporting_events,
            expected_savings_ns=duration,
            decision="proposed" if eligible else "rejected",
            backend="exact_reuse" if eligible else None,
            rejection_reason=rejection,
            proof_obligations=[
                proof(
                    "repeated_graph_loop_scope", "applicability",
                    "the same action is attached to at least two distinct observed loop markers",
                    ProofStatus.PROVEN, evidence="Observed",
                    reason=f"{len(by_marker)} marker nodes in one process/thread/scope",
                    supporting_events=supporting_events,
                    supporting_nodes=supporting_nodes,
                    details={"process_id": process, "thread_id": thread,
                             "loop_invocation_id": invocation,
                             "loop_target_offset": loop_offset},
                ),
                proof(
                    "same_graph_read_regions", "applicability",
                    "all loop actions read the same logical versions and physical regions",
                    (ProofStatus.UNKNOWN if ambiguous_actions else
                     ProofStatus.PROVEN if same_inputs else ProofStatus.DISPROVEN),
                    evidence=("UNKNOWN" if ambiguous_actions else "Observed"),
                    reason=("multiple same-code actions prevent observed ordinal alignment"
                            if ambiguous_actions else
                            "region-aware graph signatures are identical"
                            if same_inputs else
                            "at least one iteration reads a different graph region"),
                    supporting_events=supporting_events,
                    supporting_nodes=supporting_nodes,
                ),
                proof(
                    "aligned_graph_loop_actions", "applicability",
                    "each marker contributes one unambiguous dynamic action at the analyzed loop position",
                    (ProofStatus.UNKNOWN if ambiguous_actions else ProofStatus.PROVEN),
                    evidence=("UNKNOWN" if ambiguous_actions else "Observed"),
                    reason=("one marker has multiple actions with the same CodeID/label"
                            if ambiguous_actions else "one action is observed per marker for this CodeID/label"),
                    supporting_events=supporting_events,
                    supporting_nodes=supporting_nodes,
                ),
                proof(
                    "effects_allow_exact_reuse", "legality",
                    "loop actions have complete effects with no visible mutation, RNG, exception, escape or ordering effect",
                    effect_status,
                    evidence=("Observed" if effect_status != ProofStatus.UNKNOWN else "UNKNOWN"),
                    reason=("complete exact-reuse effect contracts"
                            if effect_status == ProofStatus.PROVEN else rejection or ""),
                    supporting_events=supporting_events,
                    supporting_nodes=supporting_nodes,
                ),
                proof(
                    "hoisting_preserves_graph_control", "legality",
                    "moving the action across loop controls preserves exits, exceptions, ordering and consumers",
                    ProofStatus.UNKNOWN, evidence="UNKNOWN",
                    reason="loop_controls proves iteration membership, not hoisting equivalence",
                    supporting_events=supporting_events,
                    supporting_nodes=supporting_nodes,
                ),
            ],
        ))
    return result


__all__ = ["graph_loop_candidates"]
