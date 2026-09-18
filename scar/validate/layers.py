"""Contract validation at progressively larger execution scopes."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .compare import compare


@dataclass(slots=True)
class LevelCheck:
    level: int
    passed: bool
    detail: str


@dataclass(slots=True)
class LayeredValidation:
    checks: list[LevelCheck] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(check.passed for check in self.checks)

    def as_dict(self) -> dict[str, Any]:
        return {"passed": self.passed,
                "levels": [{"level": c.level, "passed": c.passed, "detail": c.detail}
                           for c in self.checks]}


def validate_levels(baseline: Mapping[int, Any], optimized: Mapping[int, Any],
                    levels: tuple[int, ...] = (1, 2, 3, 4)) -> LayeredValidation:
    """Compare supplied contract snapshots without assuming a workload shape.

    The caller names the snapshots: level 1 can be a region output, level 2 a
    fixed solver result, level 3 a policy call, and level 4 a trajectory. A
    missing snapshot is a failed check, never silently skipped.
    """
    result = LayeredValidation()
    for level in levels:
        if level not in baseline or level not in optimized:
            result.checks.append(LevelCheck(level, False, "contract snapshot missing"))
            continue
        check = compare(baseline[level], optimized[level], level=level)
        result.checks.append(LevelCheck(level, check.passed, check.detail))
    return result
