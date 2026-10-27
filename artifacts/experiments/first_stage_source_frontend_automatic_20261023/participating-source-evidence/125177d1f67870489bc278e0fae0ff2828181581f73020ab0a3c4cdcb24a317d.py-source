"""Conservative liveness facts; absence of a consumer is never proof of deadness."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass

from scar.ir import ExecutionGraph, ProgramGraph


def consumer_counts(graph: ExecutionGraph) -> Counter:
    counts = Counter()
    for event in graph.events:
        for value in event.inputs:
            if value.get("logical_version"):
                counts[value["logical_version"]] += 1
    return counts


@dataclass(slots=True)
class LivenessFact:
    state_id: str
    producer_actions: list[str]
    consumer_actions: list[str]
    escape_actions: list[str]
    status: str
    evidence: str
    reason: str

    def as_dict(self) -> dict:
        return asdict(self)


def graph_liveness(graph: ProgramGraph, *, closed_world: bool = False) -> list[LivenessFact]:
    """Classify written graph states without treating missing edges as NONE.

    ``closed_world`` is an explicit contract supplied by a caller that knows
    the trace includes every consumer and escape. Ordinary child-process
    traces leave it false, so a written state with no observed consumer is
    ``UNKNOWN`` rather than removable. Alias edges also keep an otherwise
    unconsumed state unknown because another representation may escape.
    """
    producers: dict[str, set[str]] = {}
    consumers: dict[str, set[str]] = {}
    escapes: dict[str, set[str]] = {}
    aliased: set[str] = set()
    for edge in graph.edges:
        if edge.relation == "writes" and edge.target.startswith("state:"):
            producers.setdefault(edge.target, set()).add(edge.source)
        elif edge.relation == "reads" and edge.source.startswith("state:"):
            consumers.setdefault(edge.source, set()).add(edge.target)
        elif edge.relation == "escapes" and edge.target.startswith("state:"):
            escapes.setdefault(edge.target, set()).add(edge.source)
        elif edge.relation == "aliases":
            if edge.source.startswith("state:"):
                aliased.add(edge.source)
            if edge.target.startswith("state:"):
                aliased.add(edge.target)

    facts: list[LivenessFact] = []
    for state_id in sorted(producers):
        producer = sorted(producers[state_id])
        consumer = sorted(consumers.get(state_id, set()))
        escape = sorted(escapes.get(state_id, set()))
        if consumer or escape:
            status = "LIVE"
            evidence = "Observed"
            reason = "an observed read or escape keeps the logical state live"
        elif not closed_world or state_id in aliased:
            status = "UNKNOWN"
            evidence = "Inferred"
            reason = ("no consumer was observed, but trace scope or alias coverage is "
                      "incomplete; absence is not proof of dead work")
        else:
            status = "DEAD"
            evidence = "Inferred"
            reason = "closed-world contract declares all consumers and escapes observed"
        facts.append(LivenessFact(state_id, producer, consumer, escape,
                                  status, evidence, reason))
    return facts


__all__ = ["LivenessFact", "consumer_counts", "graph_liveness"]
