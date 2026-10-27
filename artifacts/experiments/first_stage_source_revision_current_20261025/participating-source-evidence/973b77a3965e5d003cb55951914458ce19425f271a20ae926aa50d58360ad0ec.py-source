"""Conservative candidate discovery over a static source graph.

Static syntax can point to work that may be hoisted from a loop, but it cannot
prove runtime aliasing, hidden state, exceptions, or cost.  This module emits
an explicit ``Inferred`` candidate and rejects it until dynamic evidence and a
contract guard refine the hypothesis.
"""
from __future__ import annotations

from collections import defaultdict

from scar.ir import NodeKind, Opportunity, ProgramGraph, ProofStatus, proof


def loop_invariant_candidates(graph: ProgramGraph) -> list[Opportunity]:
    """Find states read inside a loop without a visible loop-local write.

    The graph builder adds ``control_depends`` edges from loop nodes to their
    descendants and variable ``reads``/``writes`` edges through static state
    nodes.  A missing write is only a syntactic fact; the candidate remains
    rejected because calls, aliases, callbacks, exceptions, and loop control
    are not proven safe by source syntax alone.
    """
    loops = {
        node.node_id: node for node in graph.nodes.values()
        if node.kind == NodeKind.CONTROL and node.label in {"For", "AsyncFor", "While"}
    }
    if not loops:
        return []

    controlled: dict[str, set[str]] = defaultdict(set)
    for edge in graph.edges:
        if edge.relation == "control_depends" and edge.source in loops:
            controlled[edge.source].add(edge.target)

    reads: dict[str, set[str]] = defaultdict(set)
    writes: dict[str, set[str]] = defaultdict(set)
    for edge in graph.edges:
        if edge.relation == "reads" and edge.source.startswith("static_state:"):
            reads[edge.source].add(edge.target)
        elif edge.relation == "writes" and edge.target.startswith("static_state:"):
            writes[edge.target].add(edge.source)

    result: list[Opportunity] = []
    seen: set[tuple[str, str]] = set()
    for loop_id, descendants in controlled.items():
        for state_id, read_nodes in reads.items():
            inside_reads = read_nodes & descendants
            if not inside_reads or writes.get(state_id, set()) & descendants:
                continue
            key = (loop_id, state_id)
            if key in seen:
                continue
            seen.add(key)
            result.append(Opportunity(
                kind="LoopInvariantCandidate",
                code_id=loop_id,
                evidence="Inferred",
                applicability="state_read_inside_loop_without_visible_loop_write",
                guard=("runtime alias, hidden effects, exception behavior, loop control, "
                       "consumer escape, and measured cost must be proven"),
                reason=f"static state {state_id} is read in loop {loop_id} without a visible write",
                decision="rejected",
                rejection_reason="static graph is insufficient to prove legal hoisting",
                proof_obligations=[
                    proof(
                        "syntactic_loop_invariance", "applicability",
                        "the state is read in the loop and has no statically visible loop-local write",
                        ProofStatus.PROVEN, evidence="Inferred",
                        reason="source AST/data-flow graph has a read and no visible write",
                        supporting_nodes=[loop_id, state_id] + sorted(inside_reads),
                    ),
                    proof(
                        "runtime_loop_invariance", "applicability",
                        "all dynamic iterations read the same logical version and aliased regions",
                        ProofStatus.UNKNOWN, evidence="UNKNOWN",
                        reason="static syntax has no runtime logical versions",
                        supporting_nodes=[loop_id, state_id],
                    ),
                    proof(
                        "hoisting_preserves_effects", "legality",
                        "hoisting preserves hidden state, alias writes, RNG, exceptions, control, consumers and ordering",
                        ProofStatus.UNKNOWN, evidence="UNKNOWN",
                        reason="static calls and aliases retain opaque effects",
                        supporting_nodes=[loop_id, state_id],
                    ),
                ],
            ))
    return result


def dead_expression_candidates(graph: ProgramGraph) -> list[Opportunity]:
    """Find discarded call expressions as static dead-work hypotheses.

    ``Expr(Call(...))`` proves only that the return value is syntactically
    discarded. It does not prove that the call is pure, cannot raise, or has no
    external/ordering effect. The candidate is therefore always rejected at
    this stage and can be enabled only by a closed-world, reviewed contract.
    """
    children: dict[str, list[str]] = defaultdict(list)
    for edge in graph.edges:
        if edge.relation == "ast_contains":
            children.setdefault(edge.source, []).append(edge.target)
    result: list[Opportunity] = []
    for expr_id, child_ids in children.items():
        expr = graph.nodes.get(expr_id)
        if expr is None or expr.label != "Expr":
            continue
        calls = [graph.nodes[child] for child in child_ids
                 if child in graph.nodes and graph.nodes[child].label == "Call"]
        for call in calls:
            result.append(Opportunity(
                kind="DeadExpressionCandidate", code_id=call.node_id,
                evidence="Inferred", applicability="call_result_discarded_statically",
                guard=("closed-world consumer scope, reviewed pure/no-raise contract, "
                       "and no external or ordering effects must be supplied"),
                reason=(f"call result is discarded at {call.source}:{call.line}; "
                        "static syntax does not prove the call removable"),
                decision="rejected", backend="dead_expression_elimination",
                rejection_reason="static graph cannot prove purity or closed-world effects",
                proof_obligations=[
                    proof(
                        "call_result_discarded", "applicability",
                        "the source statement discards the call's return value",
                        ProofStatus.PROVEN, evidence="Inferred",
                        reason="the versioned AST contains Expr(Call(...))",
                        supporting_nodes=[expr_id, call.node_id],
                    ),
                    proof(
                        "call_is_removable", "legality",
                        "the call has no visible effects, cannot raise, and its evaluation is not observable",
                        ProofStatus.UNKNOWN, evidence="UNKNOWN",
                        reason="static call behavior remains opaque",
                        supporting_nodes=[call.node_id],
                    ),
                    proof(
                        "consumer_scope_closed", "legality",
                        "all consumers, callbacks and escapes are included in the analyzed scope",
                        ProofStatus.UNKNOWN, evidence="UNKNOWN",
                        reason="ordinary source modeling is open world",
                        supporting_nodes=[call.node_id],
                    ),
                ],
            ))
    return result


__all__ = ["dead_expression_candidates", "loop_invariant_candidates"]
