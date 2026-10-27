"""One query budget shared by source, geometry, ordering and interval scans.

Artifact replay has a separate explicitly reported bound. This object accounts
for derived query work only; failed charges never grant partial work for free.
"""
from __future__ import annotations


class ValidityBudget:
    def __init__(self, limit: int):
        if type(limit) is not int:
            raise TypeError("validity budget must be an exact integer")
        if limit < 1:
            raise ValueError("validity budget must be positive")
        self.limit = limit
        self.used = 0
        self.truncated = False
        self.costs: dict[str, int] = {}
        self.gaps: list[dict] = []

    @property
    def remaining(self) -> int:
        return self.limit - self.used

    def spend(self, kind: str, cost: int = 1, path: str = "") -> bool:
        if type(kind) is not str or not kind:
            raise TypeError("budget kind must be a nonempty exact string")
        if type(cost) is not int or cost < 0:
            raise ValueError("budget cost must be a nonnegative exact integer")
        if type(path) is not str:
            raise TypeError("budget path must be an exact string")
        if cost > self.remaining:
            # Saturation charges the inspected prefix. No subsequent stage may
            # restart from the original limit after a truncated traversal.
            charged = self.remaining
            self.used += charged
            self.costs[kind] = self.costs.get(kind, 0) + charged
            self.mark_truncated(path, "shared validity query budget exhausted")
            return False
        self.used += cost
        self.costs[kind] = self.costs.get(kind, 0) + cost
        return True

    def mark_truncated(self, path: str, message: str) -> None:
        if type(path) is not str or type(message) is not str:
            raise TypeError("budget gap path and message must be exact strings")
        self.truncated = True
        gap = {"code": "validity_budget_exhausted", "path": path, "message": message}
        if gap not in self.gaps:
            self.gaps.append(gap)


__all__ = ["ValidityBudget"]
