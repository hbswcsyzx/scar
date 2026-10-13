"""Query a particular execution result use, not a logical value's origin.

A singleton can be returned by many operations.  Its shared ValueVersion or
Materialization cannot identify which result a particular consumer used.  This
query follows explicit EEG observation edges only.  It does not certify edge
truth, close unobserved consumers, or authorize a transformation.
"""
from dataclasses import dataclass
from enum import Enum

from scar.ir.v2 import (
    EvidenceClaim, EvidenceKind, EvidenceNodeKind, EvidenceRelation,
    IRBundle, OperationInstanceID,
)


class OccurrenceOriginStatus(str, Enum):
    LOCATED_IN_EVIDENCE = "LOCATED_IN_EVIDENCE"
    AMBIGUOUS = "AMBIGUOUS"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class ExecutionResultUse:
    consumer: OperationInstanceID
    observation: str
    scope: str
    status: OccurrenceOriginStatus
    producers: tuple[OperationInstanceID, ...]
    read_edges: tuple[str, ...]
    producer_edges: tuple[str, ...]
    evidence: tuple[EvidenceClaim, ...]
    gaps: tuple[str, ...]


def query_execution_result_use(
    bundle: IRBundle, consumer: OperationInstanceID, observation: str, *, scope: str,
) -> ExecutionResultUse:
    """Locate the recorded producer of one explicit consumer/observation use.

    A unique recorded edge is only a lookup result.  A caller needing a factual
    claim must separately validate the collector's source and event witnesses.
    Never fall back to other observations sharing the same value or object.
    """
    bundle.assert_valid()
    if not isinstance(consumer, OperationInstanceID) or not scope:
        raise ValueError("query requires a typed consumer and explicit scope")
    graph = bundle.evidence
    if consumer not in graph.instances or observation not in graph.observations:
        raise ValueError("query endpoints are absent from execution evidence")
    reads, produces = [], []
    for edge in graph.edges.values():
        if (edge.target.kind is not EvidenceNodeKind.VALUE_OBSERVATION
                or edge.target.reference != observation):
            continue
        if (edge.relation is EvidenceRelation.OBSERVED_READ
                and edge.source.reference == consumer):
            reads.append(edge)
        elif edge.relation is EvidenceRelation.PRODUCES:
            produces.append(edge)
    reads.sort(key=lambda item: item.edge_id)
    produces.sort(key=lambda item: item.edge_id)
    producers = tuple(sorted({edge.source.reference for edge in produces},
                             key=lambda item: item.wire))
    claims = tuple(edge.evidence for edge in (*reads, *produces))
    gaps = []
    if not reads:
        gaps.append("no explicit consumer read of this result observation")
    if not produces:
        gaps.append("no producer edge for this particular result observation")
    if any(claim.scope != scope or not claim.references or claim.kind not in (
            EvidenceKind.OBSERVED, EvidenceKind.INFERRED) for claim in claims):
        gaps.append("use/producer evidence lacks the requested scope or runtime references")
    owner = graph.observations[observation].operation
    if owner is None or any(producer != owner for producer in producers):
        gaps.append("result observation ownership does not identify its recorded producer")
    if len(producers) > 1 or len(reads) > 1 or len(produces) > 1:
        status = OccurrenceOriginStatus.AMBIGUOUS
        gaps.append("multiple recorded read/producer edges require disambiguation")
    elif gaps:
        status = OccurrenceOriginStatus.UNRESOLVED
    else:
        status = OccurrenceOriginStatus.LOCATED_IN_EVIDENCE
    return ExecutionResultUse(
        consumer, observation, scope, status, producers,
        tuple(edge.edge_id for edge in reads),
        tuple(edge.edge_id for edge in produces), claims, tuple(gaps),
    )
