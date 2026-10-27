"""Execute two callable paths under a caller-defined validation scope."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .layers import LayeredValidation, validate_levels


@dataclass(slots=True)
class ValidationRun:
    baseline_snapshots: Mapping[int, Any]
    optimized_snapshots: Mapping[int, Any]
    validation: LayeredValidation
    baseline_s: float
    optimized_s: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "validation": self.validation.as_dict(),
            "baseline_s": self.baseline_s,
            "optimized_s": self.optimized_s,
        }


def validate_callables(
    baseline: Callable,
    optimized: Callable,
    snapshot_builder: Callable[[Callable], Mapping[int, Any]],
    *,
    reset: Callable[[], None] | None = None,
    levels: tuple[int, ...] = (1, 2, 3, 4),
) -> ValidationRun:
    """Run and compare arbitrary baseline/optimized contract scopes.

    ``snapshot_builder`` owns the workload semantics: it executes one callable
    and returns snapshots for levels 1–4 (or another requested subset). A
    caller may provide ``reset`` to restore inputs, module state and RNG before
    each path. SCAR does not assume that resetting Python globals or external
    environment state is possible; omitting the reset is allowed but leaves
    that contract responsibility visible to the caller.
    """
    if reset is not None:
        reset()
    started = time.perf_counter()
    baseline_snapshots = snapshot_builder(baseline)
    baseline_s = time.perf_counter() - started
    if reset is not None:
        reset()
    started = time.perf_counter()
    optimized_snapshots = snapshot_builder(optimized)
    optimized_s = time.perf_counter() - started
    validation = validate_levels(baseline_snapshots, optimized_snapshots, levels)
    return ValidationRun(baseline_snapshots, optimized_snapshots, validation,
                         baseline_s, optimized_s)


__all__ = ["ValidationRun", "validate_callables"]
