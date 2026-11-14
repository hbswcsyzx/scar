"""Optimization of the guarded CPU array-region execution-plan profile."""

from .optimizer import optimize_region
from .selection import select_measured

__all__ = ["optimize_region", "select_measured"]
