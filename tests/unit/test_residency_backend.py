import pytest
import torch

from scar.backends import (apply_candidates, persistent_residency,
                           residency_safe)
from scar.ir import Opportunity
from scar.planner import plan_candidates


def _candidate():
    return Opportunity(
        kind="ResidencyCandidate", code_id="transfer:cpu_to_gpu",
        evidence="Observed", applicability="same_logical_version_repeated_transfer",
        guard="read-only residency contract", reason="same source materialized twice",
        expected_savings_ns=1000, guard_cost_ns=10, lookup_cost_ns=10,
        estimated_memory_bytes=16, decision="proposed",
        backend="persistent_residency")


@pytest.mark.skipif(not torch.cuda.is_available(), reason="requires CUDA")
def test_persistent_residency_caches_transfer_and_detects_resident_mutation():
    calls = {"n": 0}

    @residency_safe
    def transfer(x):
        calls["n"] += 1
        return x.to("cuda")

    wrapped = persistent_residency(transfer, target_device="cuda")
    x = torch.ones(4)
    with torch.inference_mode():
        first = wrapped(x)
        second = wrapped(x)
        assert first is second
        assert calls["n"] == 1 and wrapped.hits == 1
        second.add_(1)
        third = wrapped(x)
    assert calls["n"] == 2
    assert torch.equal(third.cpu(), torch.ones(4))
    assert wrapped.last_fallback == "source or resident snapshot changed"


def test_residency_requires_explicit_contract_and_dispatcher_supports_backend():
    def transfer(x):
        return x.clone()

    [candidate] = plan_candidates([_candidate()])
    result = apply_candidates([candidate], {candidate.code_id: transfer})[candidate.code_id]
    assert not result.applied and result.value is transfer
    assert "explicit read-only contract" in result.reason

    @residency_safe
    def safe_transfer(x):
        return x.clone()

    [candidate] = plan_candidates([_candidate()])
    result = apply_candidates([candidate], {candidate.code_id: safe_transfer})[candidate.code_id]
    assert result.applied
    with torch.inference_mode():
        x = torch.ones(2)
        assert torch.equal(result.value(x), x)
        assert torch.equal(result.value(x), x)
    assert result.value.hits == 1


def test_persistent_residency_invalidates_after_source_write():
    @residency_safe
    def materialize(x):
        return x.clone()

    wrapped = persistent_residency(materialize)
    x = torch.ones(2)
    with torch.inference_mode():
        first = wrapped(x)
        x.add_(2)
        second = wrapped(x)
    assert torch.equal(first, torch.ones(2))
    assert torch.equal(second, torch.full((2,), 3.0))
    assert wrapped.hits == 0
