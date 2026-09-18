import torch

from scar.analysis import detect
from scar.backends import apply_candidates, pure
from scar.ir import (Effect, Event, ExecutionGraph, Knowledge, Opportunity,
                     ProofStatus, proof)
from scar.planner import plan_candidates


def _pure_effect():
    return Effect(
        rng_effect=Knowledge.NONE, may_raise=Knowledge.NONE,
        external_effect=Knowledge.NONE, ordering_effect=Knowledge.NONE,
        collection_knowledge={name: Knowledge.KNOWN for name in
                              ("reads", "writes", "allocates", "frees", "aliases", "escapes")})


def _graph():
    value = {"storage_id": "s", "logical_version": "s:v0", "shape": [2],
             "strides": [1], "dtype": "torch.float32", "device": "cpu"}
    return ExecutionGraph([
        Event(kind="module_call", code_id="test:f:v1", inputs=[value],
              duration_ns=10, effect=_pure_effect()),
        Event(kind="module_call", code_id="test:f:v1", inputs=[value],
              duration_ns=100, effect=_pure_effect()),
    ])


def test_graph_candidate_is_planned_and_applied_by_generic_dispatch():
    candidates = detect(_graph())
    assert len(candidates) == 1
    candidate = candidates[0]
    candidate.guard_cost_ns = 5
    candidate.lookup_cost_ns = 5

    @pure
    def function(x):
        return x.square()

    [planned] = plan_candidates(candidates)
    assert planned.decision == "accepted"
    result = apply_candidates([planned], {"test:f:v1": function})["test:f:v1"]
    assert result.applied and result.reason == "exact_reuse backend applied"
    with torch.inference_mode():
        value = torch.ones(2)
        first = result.value(value)
        second = result.value(value)
    assert torch.equal(first, second)
    assert result.value.hits == 1


def test_rejected_plan_is_an_explicit_noop():
    candidates = detect(_graph())
    [planned] = plan_candidates(candidates)

    @pure
    def function(x):
        return x.square()

    result = apply_candidates([planned], {"test:f:v1": function})["test:f:v1"]
    assert not result.applied and result.value is function


def test_dispatcher_rechecks_proof_ledger_against_manual_acceptance():
    candidate = Opportunity(
        kind="ReuseCandidate", code_id="test:f:v1", evidence="Observed",
        applicability="same", guard="all proofs", reason="manual acceptance",
        decision="accepted", backend="exact_reuse", proof_obligations=[
            proof("same_versions", "applicability", "inputs match",
                  ProofStatus.PROVEN, evidence="Observed"),
            proof("effects", "legality", "effects absent",
                  ProofStatus.UNKNOWN, reason="escape evidence is incomplete"),
            proof("cost_profitable", "cost", "benefit exceeds overhead",
                  ProofStatus.PROVEN, evidence="Measured"),
        ])

    @pure
    def function(x):
        return x.square()

    result = apply_candidates([candidate], {candidate.code_id: function})[candidate.code_id]
    assert not result.applied and result.value is function
    assert "effects is UNKNOWN" in result.reason
