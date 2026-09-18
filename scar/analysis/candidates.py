"""Top-level generic candidate detector."""
from __future__ import annotations

from scar.ir import ExecutionGraph, Opportunity
from .memory import allocation_candidates
from .materialization import materialization_candidates
from .repetition import repeated_regions
from .synchronization import synchronization_candidates
from .loops import loop_invariant_candidates


def detect(graph: ExecutionGraph) -> list[Opportunity]:
    return (repeated_regions(graph) + materialization_candidates(graph) +
            allocation_candidates(graph) + synchronization_candidates(graph) +
            loop_invariant_candidates(graph))
