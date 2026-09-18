from __future__ import annotations

import torch

from scar.backends.reuse import inferred_exact_reuse
from scar.trace.optimizer import RuntimeOptimizer


def test_inferred_reuse_validates_first_repeat_before_cache_hit():
    module = torch.nn.Linear(4, 4).eval()
    wrapper = inferred_exact_reuse(
        module, lambda *args, **kwargs: module.forward(*args, **kwargs),
        max_bytes=1024 * 1024,
    )
    value = torch.ones(2, 4)
    with torch.inference_mode():
        first = wrapper(value)
        probe = wrapper(value)
        hit = wrapper(value)
    assert torch.equal(first, probe)
    assert torch.equal(first, hit)
    assert wrapper.validated_probes == 1
    assert wrapper.hits == 1


def test_runtime_optimizer_only_accepts_exact_reviewed_module_classes():
    optimizer = RuntimeOptimizer(torch)
    with torch.inference_mode():
        eligible, reason = optimizer.eligible(torch.nn.Linear(2, 2))
    assert eligible is True
    assert "reviewed" in reason

    class UserModule(torch.nn.Module):
        def forward(self, value):
            return value

    eligible, reason = optimizer.eligible(UserModule())
    assert eligible is False
    assert "no reviewed" in reason
