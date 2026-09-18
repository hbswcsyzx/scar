from scar.ir import Opportunity, ProofStatus, proof
from scar.planner import plan_candidates, select_candidates


def _candidate(*, obligations, decision="proposed"):
    return Opportunity(
        kind="GenericCandidate", code_id="user:work", evidence="Observed",
        applicability="generic", guard="all proof obligations",
        reason="test candidate", expected_savings_ns=100,
        guard_cost_ns=5, lookup_cost_ns=5, decision=decision,
        backend="exact_reuse", proof_obligations=obligations,
    )


def test_opportunity_serializes_machine_readable_proof_ledger():
    candidate = _candidate(obligations=[
        proof("same_versions", "applicability", "inputs match",
              ProofStatus.PROVEN, evidence="Observed"),
        proof("no_effects", "legality", "effects are absent",
              ProofStatus.UNKNOWN, reason="escape set is incomplete"),
    ])
    value = candidate.as_dict()
    assert value["proof_obligations"][0]["status"] == "PROVEN"
    assert value["proof_obligations"][1]["status"] == "UNKNOWN"
    assert value["proof_summary"]["counts"] == {
        "PROVEN": 1, "DISPROVEN": 0, "UNKNOWN": 1,
    }
    assert value["proof_summary"]["all_proven"] is False


def test_optional_obligations_do_not_make_an_empty_required_ledger_complete():
    candidate = _candidate(obligations=[
        proof("future_validation", "validation", "future comparison",
              ProofStatus.PROVEN, required=False),
    ])
    summary = candidate.as_dict()["proof_summary"]
    assert summary["required"] == 0
    assert summary["complete"] is False
    assert summary["all_proven"] is False


def test_cost_planner_cannot_accept_unknown_legality():
    candidate = _candidate(obligations=[
        proof("same_versions", "applicability", "inputs match",
              ProofStatus.PROVEN, evidence="Observed"),
        proof("no_effects", "legality", "effects are absent",
              ProofStatus.UNKNOWN, reason="effect set is incomplete"),
    ])
    [planned] = plan_candidates([candidate])
    assert planned.cost_assessment["accepted"] is True
    assert planned.decision == "rejected"
    assert "no_effects is UNKNOWN" in planned.rejection_reason
    assert next(item for item in planned.proof_obligations
                if item.name == "cost_profitable").status == ProofStatus.PROVEN


def test_selector_uses_structural_proofs_before_human_text():
    candidate = _candidate(obligations=[
        proof("same_versions", "applicability", "inputs match",
              ProofStatus.DISPROVEN, reason="observed input version changed"),
    ], decision="rejected")
    candidate.rejection_reason = "arbitrary wording with no legacy marker"
    decision = select_candidates([candidate]).decisions[0]
    assert decision.action == "KEEP"
    assert decision.legality == "violated"
    assert decision.reason == "observed input version changed"


def test_all_proven_preconditions_and_cost_can_be_accepted():
    candidate = _candidate(obligations=[
        proof("same_versions", "applicability", "inputs match",
              ProofStatus.PROVEN, evidence="Observed"),
        proof("no_effects", "legality", "effects are absent",
              ProofStatus.PROVEN, evidence="Observed"),
    ])
    [planned] = plan_candidates([candidate])
    assert planned.decision == "accepted"
    selected = select_candidates([planned])
    assert selected.selected_indices == [0]
    assert selected.decisions[0].proof_summary["all_proven"] is True


def test_selector_cannot_bypass_unknown_proof_with_manual_acceptance():
    candidate = _candidate(obligations=[
        proof("same_versions", "applicability", "inputs match",
              ProofStatus.PROVEN, evidence="Observed"),
        proof("no_effects", "legality", "effects absent",
              ProofStatus.UNKNOWN, reason="effect set is incomplete"),
    ], decision="accepted")
    selected = select_candidates([candidate])
    assert selected.selected_indices == []
    assert selected.decisions[0].action == "UNKNOWN"
    assert selected.decisions[0].reason == "effect set is incomplete"


def test_selector_requires_cost_proof_for_structured_accepted_candidate():
    candidate = _candidate(obligations=[
        proof("same_versions", "applicability", "inputs match",
              ProofStatus.PROVEN, evidence="Observed"),
        proof("no_effects", "legality", "effects absent",
              ProofStatus.PROVEN, evidence="Observed"),
    ], decision="accepted")
    selected = select_candidates([candidate])
    assert selected.selected_indices == []
    assert selected.decisions[0].action == "UNKNOWN"
    assert "no required cost proof" in selected.decisions[0].reason
