import torch

from scar.validate import validate_levels


def test_layered_validation_requires_every_requested_contract_level():
    baseline = {1: torch.ones(2), 2: {"action": [1, 2]}}
    optimized = {1: torch.ones(2), 2: {"action": [1, 2]}}
    result = validate_levels(baseline, optimized)
    assert not result.passed
    assert [check.level for check in result.checks if not check.passed] == [3, 4]


def test_layered_validation_detects_trajectory_difference():
    baseline = {1: torch.ones(1), 2: "same", 3: {"action": 1}, 4: [0, 1, 2]}
    optimized = {1: torch.ones(1), 2: "same", 3: {"action": 1}, 4: [0, 1, 3]}
    result = validate_levels(baseline, optimized)
    assert not result.passed
    assert result.checks[-1].level == 4 and not result.checks[-1].passed
