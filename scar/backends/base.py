"""Backend protocol and explicit no-op fallback."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(slots=True)
class BackendResult:
    value: Any
    applied: bool
    reason: str


class Backend:
    name = "noop"

    def applicable(self, candidate) -> tuple[bool, str]:
        return False, "no-op backend"

    def transform(self, fn: Callable, candidate=None) -> Callable:
        return fn

