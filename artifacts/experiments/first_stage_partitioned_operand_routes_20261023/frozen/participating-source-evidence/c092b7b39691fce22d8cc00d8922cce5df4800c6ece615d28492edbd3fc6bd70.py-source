"""Typed work, outcome, queue-prefix, and retention records.

These records connect work to existing execution occurrences, state accesses,
resource bindings, and value-graph materializations.  They do not establish
physical execution, outcome truth, visibility, or release authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.v2.common import Completeness
from scar.ir.v2.ids import MaterializationID
from .common import FactSource, Unresolved
from .coordinates import (
    AccessRef, EvidencePoint, ExecutionPoint, OccurrencePoint, OperationOccurrenceID,
    UseRef, ValueOccurrenceID,
)
from .ids import (
    HandleBindingID, HostThreadInstanceID, QueuePrefixID, ResourceAccessID,
    ResourceInstanceID, WorkOutcomeID, WorkQuiescenceID, WorkRetentionID,
    WorkTicketID,
)
from .resources import (
    AllocationTarget, ReleaseAuthority, ResourceTarget, Sharing, _exact, _id,
    _index, _point, _record, _source, _variant,
)


@dataclass(frozen=True, slots=True)
class MaterializationRef:
    artifact: ProviderArtifact
    materialization: MaterializationID

    def __post_init__(self):
        _record(self.artifact, ProviderArtifact, "materialization artifact")
        _id(self.materialization, MaterializationID, "materialization ID")


@dataclass(frozen=True, slots=True)
class WithinOperation:
    operation: OperationOccurrenceID
    source: FactSource

    def __post_init__(self):
        _id(self.operation, OperationOccurrenceID, "submission operation occurrence")
        _source(self.source, "submission source")


@dataclass(frozen=True, slots=True)
class ExternalWorkSource:
    point: EvidencePoint
    source: FactSource

    def __post_init__(self):
        _record(self.point, EvidencePoint, "external work point")
        _source(self.source, "external work source")


SubmissionOrigin: TypeAlias = WithinOperation | ExternalWorkSource


@dataclass(frozen=True, slots=True)
class ActualCompletionState:
    successor_index: int
    result_index: int
    formal: ValueOccurrenceID

    def __post_init__(self):
        _index(self.successor_index, "completion successor index")
        _index(self.result_index, "completion result index")
        _id(self.formal, ValueOccurrenceID, "completion state formal occurrence")


@dataclass(frozen=True, slots=True)
class InvokeBoundaryStateEffect:
    invocation: OperationOccurrenceID
    state_input: UseRef
    post: ActualCompletionState | Unresolved

    def __post_init__(self):
        _id(self.invocation, OperationOccurrenceID, "state-effect invocation")
        _record(self.state_input, UseRef, "invoke state input")
        _variant(self.post, (ActualCompletionState, Unresolved), "invoke state post")


CanonicalEffectOccurrence: TypeAlias = AccessRef | InvokeBoundaryStateEffect


@dataclass(frozen=True, slots=True)
class QueueStart:
    source: FactSource

    def __post_init__(self):
        _source(self.source, "queue start source")


QueuePrefixPrevious: TypeAlias = QueuePrefixID | QueueStart | Unresolved


@dataclass(frozen=True, slots=True)
class QueuePrefix:
    id: QueuePrefixID
    queue: ResourceInstanceID
    previous: QueuePrefixPrevious
    work: WorkTicketID | None
    observed_at: ExecutionPoint
    protocol: ProviderFactReference
    source: FactSource

    def __post_init__(self):
        _id(self.id, QueuePrefixID, "queue-prefix ID")
        _id(self.queue, ResourceInstanceID, "queue instance")
        _variant(self.previous, (QueuePrefixID, QueueStart, Unresolved), "previous queue prefix")
        if type(self.previous) is QueuePrefixID and self.previous == self.id:
            raise ValueError("a queue prefix cannot be its own predecessor")
        if self.work is not None:
            _id(self.work, WorkTicketID, "queue-prefix work ticket")
        if self.work is None and type(self.previous) is not QueueStart:
            raise ValueError("an empty queue prefix must begin at QueueStart")
        _point(self.observed_at, "queue-prefix observation point")
        _record(self.protocol, ProviderFactReference, "queue protocol")
        _source(self.source, "queue-prefix source")


@dataclass(frozen=True, slots=True)
class Queued:
    queue_access: ResourceAccessID
    prefix: QueuePrefixID

    def __post_init__(self):
        _id(self.queue_access, ResourceAccessID, "queued work queue access")
        _id(self.prefix, QueuePrefixID, "queued work prefix")


@dataclass(frozen=True, slots=True)
class DirectExecution:
    thread: HostThreadInstanceID | Unresolved
    source: FactSource

    def __post_init__(self):
        _variant(self.thread, (HostThreadInstanceID, Unresolved), "direct execution thread")
        _source(self.source, "direct execution source")


Scheduling: TypeAlias = Queued | DirectExecution | Unresolved


@dataclass(frozen=True, slots=True)
class WorkSubmission:
    id: WorkTicketID
    origin: SubmissionOrigin
    executor: ResourceAccessID | Unresolved
    scheduling: Scheduling
    dependencies: tuple[WorkTicketID, ...]
    dependencies_coverage: Completeness
    effects: tuple[CanonicalEffectOccurrence, ...]
    effects_coverage: Completeness
    materializations: tuple[MaterializationRef, ...]
    materializations_coverage: Completeness
    retention: tuple[WorkRetentionID, ...] | Unresolved
    protocol: ProviderFactReference
    source: FactSource

    def __post_init__(self):
        _id(self.id, WorkTicketID, "work ticket ID")
        _variant(self.origin, (WithinOperation, ExternalWorkSource), "work submission origin")
        _variant(self.executor, (ResourceAccessID, Unresolved), "work executor")
        _variant(self.scheduling, (Queued, DirectExecution, Unresolved), "work scheduling")
        _exact(self.dependencies, tuple, "work dependencies")
        for item in self.dependencies:
            _id(item, WorkTicketID, "work dependency ticket")
        if len(self.dependencies) != len(set(self.dependencies)):
            raise ValueError("work dependencies must be unique")
        if self.id in self.dependencies:
            raise ValueError("work cannot depend on its own ticket")
        _exact(self.dependencies_coverage, Completeness, "dependency coverage")
        _exact(self.effects, tuple, "work effects")
        for item in self.effects:
            _variant(item, (AccessRef, InvokeBoundaryStateEffect), "canonical work effect")
        if len(self.effects) != len(set(self.effects)):
            raise ValueError("work effects must be unique")
        _exact(self.effects_coverage, Completeness, "effect coverage")
        _exact(self.materializations, tuple, "work materializations")
        for item in self.materializations:
            _record(item, MaterializationRef, "work materialization")
        if len(self.materializations) != len(set(self.materializations)):
            raise ValueError("work materializations must be unique")
        _exact(self.materializations_coverage, Completeness, "materialization coverage")
        if type(self.retention) is tuple:
            for item in self.retention:
                _id(item, WorkRetentionID, "work-retention ID")
            if len(self.retention) != len(set(self.retention)):
                raise ValueError("work retention references must be unique")
        elif type(self.retention) is Unresolved:
            _record(self.retention, Unresolved, "work retention gap")
        else:
            raise TypeError("work retention must be a tuple of IDs or Unresolved")
        _record(self.protocol, ProviderFactReference, "work protocol")
        _source(self.source, "work-submission source")


class WorkOutcomeKind(str, Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class WorkQuiescence:
    id: WorkQuiescenceID
    ticket: WorkTicketID
    observed_at: ExecutionPoint
    source: FactSource

    def __post_init__(self):
        _id(self.id, WorkQuiescenceID, "work-quiescence ID")
        _id(self.ticket, WorkTicketID, "quiescent work ticket")
        _point(self.observed_at, "work-quiescence point")
        _source(self.source, "work-quiescence source")


ProtocolResult: TypeAlias = ValueOccurrenceID | ProviderFactReference | Unresolved


@dataclass(frozen=True, slots=True)
class ResourceOutcome:
    id: WorkOutcomeID
    ticket: WorkTicketID
    kind: WorkOutcomeKind
    observed_at: ExecutionPoint
    protocol_result: ProtocolResult
    effect_frontier: tuple[CanonicalEffectOccurrence, ...]
    frontier_coverage: Completeness
    quiescence: WorkQuiescenceID | Unresolved
    source: FactSource

    def __post_init__(self):
        _id(self.id, WorkOutcomeID, "work-outcome ID")
        _id(self.ticket, WorkTicketID, "outcome work ticket")
        _exact(self.kind, WorkOutcomeKind, "work outcome kind")
        _point(self.observed_at, "work-outcome point")
        _variant(self.protocol_result, (ValueOccurrenceID, ProviderFactReference, Unresolved),
                 "work protocol result")
        _exact(self.effect_frontier, tuple, "work effect frontier")
        for item in self.effect_frontier:
            _variant(item, (AccessRef, InvokeBoundaryStateEffect), "frontier effect")
        if len(self.effect_frontier) != len(set(self.effect_frontier)):
            raise ValueError("work effect frontier must be unique")
        _exact(self.frontier_coverage, Completeness, "effect-frontier coverage")
        _variant(self.quiescence, (WorkQuiescenceID, Unresolved), "work quiescence")
        _source(self.source, "work-outcome source")


@dataclass(frozen=True, slots=True)
class HandleTarget:
    binding: HandleBindingID

    def __post_init__(self):
        _id(self.binding, HandleBindingID, "retained handle binding")


RetentionTarget: TypeAlias = ResourceTarget | HandleTarget | MaterializationRef
RetentionBasis: TypeAlias = UseRef | AccessRef | ResourceAccessID | MaterializationRef | Unresolved
WorkStart: TypeAlias = WithinOperation | OccurrencePoint | EvidencePoint


@dataclass(frozen=True, slots=True)
class BorrowRelease:
    point: ExecutionPoint
    quiescence: WorkQuiescenceID | Unresolved
    source: FactSource

    def __post_init__(self):
        _point(self.point, "borrow-release point")
        _variant(self.quiescence, (WorkQuiescenceID, Unresolved), "borrow-release quiescence")
        _source(self.source, "borrow-release source")


@dataclass(frozen=True, slots=True)
class WorkRetention:
    id: WorkRetentionID
    ticket: WorkTicketID
    target: RetentionTarget
    basis: RetentionBasis
    start: WorkStart
    support: tuple[ValueOccurrenceID, ...]
    authority: ReleaseAuthority
    sharing: Sharing
    release: BorrowRelease | Unresolved
    source: FactSource

    def __post_init__(self):
        _id(self.id, WorkRetentionID, "work-retention ID")
        _id(self.ticket, WorkTicketID, "retained work ticket")
        _variant(self.target, (AllocationTarget, HandleTarget, MaterializationRef,
                               *(_resource_target_types())), "retention target")
        _variant(self.basis, (UseRef, AccessRef, ResourceAccessID, MaterializationRef, Unresolved),
                 "retention basis")
        _variant(self.start, (WithinOperation, OccurrencePoint, EvidencePoint), "retention start")
        _exact(self.support, tuple, "retention state support")
        for item in self.support:
            _id(item, ValueOccurrenceID, "retention support occurrence")
        if len(self.support) != len(set(self.support)):
            raise ValueError("retention state support must be unique")
        _exact(self.authority, ReleaseAuthority, "retention release authority")
        _exact(self.sharing, Sharing, "retention sharing")
        _variant(self.release, (BorrowRelease, Unresolved), "retention release")
        _source(self.source, "work-retention source")


def _resource_target_types():
    # ResourceTarget is a PEP 604 union and cannot be passed to the strict
    # variant helper.  Keep the accepted runtime classes explicit.
    from .resources import InstanceTarget, ProcessTarget, ThreadTarget
    return (InstanceTarget, ProcessTarget, ThreadTarget)


__all__ = [
    "MaterializationRef", "WithinOperation", "ExternalWorkSource", "SubmissionOrigin",
    "ActualCompletionState", "InvokeBoundaryStateEffect", "CanonicalEffectOccurrence",
    "QueueStart", "QueuePrefixPrevious", "QueuePrefix", "Queued", "DirectExecution",
    "Scheduling", "WorkSubmission", "WorkOutcomeKind", "WorkQuiescence",
    "ProtocolResult", "ResourceOutcome", "HandleTarget", "RetentionTarget",
    "RetentionBasis", "WorkStart", "BorrowRelease", "WorkRetention",
]
