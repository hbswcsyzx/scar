from scar.ir import Opportunity
from scar.planner import select_candidates


def _candidate(**changes):
    values = dict(
        kind="ReuseCandidate", code_id="user:work", evidence="Observed",
        applicability="same_input_logical_versions", guard="guard",
        reason="repeated work", supporting_events=[1, 2],
        expected_savings_ns=100, decision="rejected", backend="exact_reuse",
        rejection_reason="effect knowledge is incomplete or input versions changed",
    )
    values.update(changes)
    return Opportunity(**values)


def test_selector_keeps_unknown_evidence_visible():
    result = select_candidates([_candidate()])
    decision = result.decisions[0]
    assert decision.action == "UNKNOWN"
    assert decision.legality == "unknown"
    assert result.selected_indices == []


def test_selector_distinguishes_unprofitable_from_unknown():
    candidate = _candidate(
        decision="rejected", rejection_reason="not profitable: guard cost exceeds saved work",
        cost_assessment={"reason": "not profitable: guard and lookup cost meet or exceed saved work"},
    )
    result = select_candidates([candidate])
    assert result.decisions[0].action == "REJECT"
    assert result.decisions[0].cost == "unprofitable"


def test_selector_marks_changing_input_as_known_non_applicability():
    candidate = _candidate(
        applicability="changing_input_logical_versions",
        rejection_reason="effect knowledge is incomplete or input logical versions changed",
    )
    result = select_candidates([candidate])
    assert result.decisions[0].action == "KEEP"
    assert result.decisions[0].legality == "violated"
    assert result.decisions[0].cost == "not_applicable"


def test_selector_selects_one_conflicting_transform_and_records_supersession():
    first = _candidate(decision="accepted", rejection_reason=None, expected_savings_ns=10,
                       supporting_events=[1], evidence="Inferred")
    second = _candidate(decision="accepted", rejection_reason=None, expected_savings_ns=20,
                        supporting_events=[2], evidence="Observed")
    result = select_candidates([first, second])
    assert result.selected_indices == [1]
    assert result.decisions[1].action == "TRANSFORM"
    assert result.decisions[1].selected
    assert result.decisions[1].supersedes == [0]
    assert result.decisions[0].action == "KEEP"
    assert result.decisions[0].cost == "duplicate"


def test_selector_does_not_select_unsupported_backend():
    candidate = _candidate(decision="accepted", rejection_reason=None, backend="future_backend")
    result = select_candidates([candidate])
    assert result.selected_indices == []
    assert result.decisions[0].action == "REJECT"
    assert result.decisions[0].legality == "proven"


def test_selector_applies_transformation_limit_without_mutating_candidate():
    candidates = [
        _candidate(code_id="user:a", decision="accepted", rejection_reason=None,
                   supporting_events=[1], expected_savings_ns=10),
        _candidate(code_id="user:b", decision="accepted", rejection_reason=None,
                   supporting_events=[2], expected_savings_ns=20),
    ]
    result = select_candidates((item for item in candidates), max_transformations=1)
    assert result.selected_indices == [0]
    assert result.decisions[1].action == "REJECT"
    assert result.decisions[1].cost == "selection_limit"
    assert candidates[1].decision == "accepted"
