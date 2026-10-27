"""Layered exactness checks for backend experiments."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class Validation:
    level: int
    passed: bool
    detail: str


def compare(a: Any, b: Any, level: int = 1, atol: float = 0.0, rtol: float = 0.0) -> Validation:
    try:
        import torch
        if isinstance(a, torch.Tensor) and isinstance(b, torch.Tensor):
            ok = torch.equal(a, b) if atol == rtol == 0 else bool(torch.allclose(a, b, atol=atol, rtol=rtol))
        elif isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
            ok = len(a) == len(b) and all(compare(x, y, level, atol, rtol).passed for x, y in zip(a, b))
        elif isinstance(a, dict) and isinstance(b, dict):
            ok = a.keys() == b.keys() and all(compare(a[k], b[k], level, atol, rtol).passed for k in a)
        else:
            ok = a == b
    except Exception as exc:
        return Validation(level, False, f"comparison failed: {exc}")
    return Validation(level, bool(ok), "exact output/effect match" if ok else "mismatch")

