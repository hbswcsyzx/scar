"""Runtime loop-instance candidates for arbitrary traced Python programs."""
from __future__ import annotations

from collections import defaultdict

from scar.ir import ExecutionGraph, Opportunity, ProofStatus, proof
from .repetition import _effect_status, _input_signature, _reuse_proofs


def loop_invariant_candidates(graph: ExecutionGraph) -> list[Opportunity]:
    """Suggest repeated module work observed across a bytecode loop back-edge.

    Line tracing only labels actions after a back-edge, so this detector is
    deliberately conservative and may see a suffix of the loop rather than
    every iteration. It emits a candidate only when at least two distinct
    observed iterations contain the same module CodeID. Hoisting is not
    assumed legal: effects, aliases, exceptions, loop control and consumers
    still require a backend-specific proof.
    """
    grouped = defaultdict(list)
    for idx, event in enumerate(graph.events):
        if event.kind != "module_call" or not event.code_id:
            continue
        metadata = event.metadata
        if metadata.get("loop_iteration") is None:
            continue
        key = (metadata.get("loop_parent_invocation_id",
                           metadata.get("parent_invocation_id")),
               metadata.get("loop_target_offset"), event.code_id)
        grouped[key].append((idx, event))

    result: list[Opportunity] = []
    for (parent, offset, code_id), calls in grouped.items():
        iterations = {event.metadata.get("loop_iteration") for _, event in calls}
        if len(iterations) < 2:
            continue
        signatures = {_input_signature(event) for _, event in calls}
        same_inputs = len(signatures) == 1 and () not in signatures
        duration = sum(event.duration_ns or 0 for _, event in calls[1:])
        effect_status = _effect_status(calls)
        effects_known = effect_status == ProofStatus.PROVEN
        eligible = same_inputs and effects_known
        if not same_inputs:
            rejection = "input logical versions or region signatures changed across iterations"
        elif not effects_known:
            rejection = "loop effects or invalidation guard is incomplete"
        else:
            rejection = "planner must measure exact-reuse guard and lookup cost"
        result.append(Opportunity(
            kind="LoopInvariantCandidate", code_id=code_id, evidence="Observed",
            applicability=("same_inputs_across_loop_iterations" if same_inputs
                           else "changing_inputs_across_loop_iterations"),
            guard=("loop control, input logical versions, aliases, effects, exceptions, "
                   "consumer/escape ordering and measured hoisting cost must be proven"),
            reason=(f"module executed in {len(iterations)} observed loop iterations"
                    + (" with the same input region signature" if same_inputs else
                       " with changing input region signatures")),
            supporting_events=[idx for idx, _ in calls],
            expected_savings_ns=duration,
            decision="proposed" if eligible else "rejected",
            backend="exact_reuse" if eligible else None,
            rejection_reason=None if eligible else rejection,
            proof_obligations=(
                [proof(
                    "repeated_loop_scope", "applicability",
                    "the same action occurs in at least two observed iterations of one dynamic loop",
                    ProofStatus.PROVEN, evidence="Observed",
                    reason=f"observed in {len(iterations)} loop iterations",
                    supporting_events=[idx for idx, _ in calls],
                    details={"parent_invocation_id": parent,
                             "loop_target_offset": offset},
                )]
                + _reuse_proofs(calls, same_inputs=same_inputs,
                                effects=effect_status)
                + [proof(
                    "hoisting_preserves_loop_control", "legality",
                    "moving the action outside the loop preserves exceptions, branches, ordering and consumers",
                    ProofStatus.UNKNOWN, evidence="UNKNOWN",
                    reason="dynamic repetition does not prove control equivalence",
                    supporting_events=[idx for idx, _ in calls],
                )]
            ),
        ))
    return result
