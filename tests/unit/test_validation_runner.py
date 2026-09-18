import torch

from scar.backends import exact_reuse, pure
from scar.validate import validate_callables


def test_validation_runner_executes_all_four_generic_contract_levels():
    state = {"seed": 0}

    @pure
    def region(x):
        return x.square()

    optimized_region = exact_reuse(region)

    def reset():
        state["seed"] = 0
        torch.manual_seed(7)

    def scopes(fn):
        x = torch.tensor([1.0, 2.0])
        level1 = fn(x)
        level2 = {"chosen": int(level1.argmax()), "cost": float(level1.sum())}
        state["seed"] += 1
        level3 = {"action": level2["chosen"], "state": state["seed"]}
        trajectory = []
        for _ in range(3):
            trajectory.append((level3["action"], level3["state"]))
        return {1: level1, 2: level2, 3: level3, 4: trajectory}

    result = validate_callables(region, optimized_region, scopes, reset=reset)
    assert result.validation.passed
    assert [check.level for check in result.validation.checks] == [1, 2, 3, 4]
    assert result.baseline_s >= 0 and result.optimized_s >= 0


def test_validation_runner_exposes_missing_requested_scope():
    result = validate_callables(lambda: 1, lambda: 1,
                                lambda fn: {1: fn()}, levels=(1, 2), reset=lambda: None)
    assert not result.validation.passed
    assert result.validation.checks[-1].detail == "contract snapshot missing"
