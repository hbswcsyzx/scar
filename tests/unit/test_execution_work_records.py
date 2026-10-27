"""Local record contracts for work, outcome and retention declarations.

Cross-record matching to invoke successors, current state, queues and resources
belongs to execution graph validation rather than these constructors.
"""
from dataclasses import FrozenInstanceError, fields, replace

import pytest

from scar.ir.execution.common import EvidencePoint, MissingEvidence, Unresolved
from scar.ir.execution.coordinates import (
    AccessRef, OccurrencePhase, OccurrencePoint, OperationOccurrenceID, UseRef,
    ValueOccurrenceID,
)
from scar.ir.execution.ids import (
    HandleBindingID, HostThreadInstanceID, ProcessInstanceID, QueuePrefixID,
    ResourceAccessID, RunID,
    WorkOutcomeID, WorkQuiescenceID, WorkRetentionID, WorkTicketID,
)
from scar.ir.execution.resources import (
    AllocationTarget, InstanceTarget, ReleaseAuthority, ResourceInstanceID, Sharing,
)
from scar.ir.execution.work import (
    ActualCompletionState, BorrowRelease, DirectExecution, ExternalWorkSource,
    HandleTarget, InvokeBoundaryStateEffect, MaterializationRef, QueuePrefix,
    QueueStart, Queued, ResourceOutcome, WorkOutcomeKind, WorkQuiescence,
    WorkRetention, WorkSubmission, WithinOperation,
)
from scar.ir.program.ids import UseID
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.record_codec import decode, encode
from scar.ir.v2.common import Completeness
from scar.ir.v2.ids import MaterializationID, StorageAllocationID


def _artifact(uri="memory://work"):
    return ProviderArtifact(uri, "a" * 64, 0, "work-test-v1")


def _fact(locator="/fact"):
    return ProviderFactReference(_artifact(), locator)


def _point():
    return EvidencePoint(RunID("run"), ProcessInstanceID("process"), _fact("/event"))


def _gap(reason="not captured"):
    return Unresolved(reason, _point())


def _submission(**changes):
    args = dict(
        id=WorkTicketID("ticket"),
        origin=WithinOperation(OperationOccurrenceID("submit"), _fact("/submit")),
        executor=ResourceAccessID("executor-access"),
        scheduling=DirectExecution(HostThreadInstanceID("host-thread"), _fact("/direct")),
        dependencies=(),
        dependencies_coverage=Completeness.COMPLETE,
        effects=(AccessRef(OperationOccurrenceID("submit"), 0),),
        effects_coverage=Completeness.PARTIAL,
        materializations=(MaterializationRef(_artifact("memory://values"),
                                             MaterializationID("mat")),),
        materializations_coverage=Completeness.PARTIAL,
        retention=(WorkRetentionID("retention"),),
        protocol=_fact("/protocol/submit"),
        source=_fact("/source"),
    )
    args.update(changes)
    return WorkSubmission(**args)


def test_submission_keeps_ticket_origin_queue_and_core_effect_endpoints_typed():
    operation = OperationOccurrenceID("invoke")
    effect = InvokeBoundaryStateEffect(
        operation, UseRef(operation, UseID("world-in")),
        ActualCompletionState(1, 2, ValueOccurrenceID("world-after-raise")),
    )
    prefix = QueuePrefixID("prefix")
    queue = QueuePrefix(
        prefix, ResourceInstanceID("queue-instance"),
        QueueStart(_fact("/queue-start")), WorkTicketID("ticket"),
        OccurrencePoint(operation, OccurrencePhase.AFTER), _fact("/queue-protocol"),
        _fact("/queue-prefix"),
    )
    row = _submission(
        origin=ExternalWorkSource(_point(), _fact("/external-submit")),
        scheduling=Queued(ResourceAccessID("queue-access"), prefix),
        effects=(effect,),
        materializations=(), materializations_coverage=Completeness.UNKNOWN,
        retention=_gap("retention coverage missing"),
    )

    assert row.id == queue.work
    assert row.scheduling.prefix == queue.id
    assert effect.state_input.use == UseID("world-in")
    assert effect.post.formal == ValueOccurrenceID("world-after-raise")
    assert isinstance(row.origin, ExternalWorkSource)


def test_terminal_failure_keeps_partial_effects_and_quiescence_independent():
    effect = AccessRef(OperationOccurrenceID("write"), 1)
    outcome = ResourceOutcome(
        WorkOutcomeID("failed-observation"), WorkTicketID("ticket"),
        WorkOutcomeKind.FAILED, OccurrencePoint(OperationOccurrenceID("wait"), OccurrencePhase.AFTER),
        ValueOccurrenceID("error-result"), (effect,), Completeness.PARTIAL,
        _gap("device quiescence was not observed"), _fact("/failed"),
    )
    cancelled = replace(outcome, id=WorkOutcomeID("cancelled-observation"),
                        kind=WorkOutcomeKind.CANCELLED)

    assert outcome.effect_frontier == (effect,)
    assert outcome.quiescence.reason == "device quiescence was not observed"
    assert cancelled.effect_frontier == outcome.effect_frontier
    assert cancelled.kind is WorkOutcomeKind.CANCELLED


def test_quiescence_and_borrow_release_have_separate_exact_records():
    ticket = WorkTicketID("ticket")
    point = OccurrencePoint(OperationOccurrenceID("drain"), OccurrencePhase.AFTER)
    quiescence = WorkQuiescence(WorkQuiescenceID("quiet"), ticket, point, _fact("/quiet"))
    retention = WorkRetention(
        WorkRetentionID("retention"), ticket,
        HandleTarget(HandleBindingID("handle")),
        AccessRef(OperationOccurrenceID("submit"), 0),
        WithinOperation(OperationOccurrenceID("submit"), _fact("/retained")),
        (ValueOccurrenceID("world"),), ReleaseAuthority.BORROWED, Sharing.SHARED,
        BorrowRelease(point, quiescence.id, _fact("/released")), _fact("/retention"),
    )

    assert retention.ticket == quiescence.ticket
    assert retention.release.quiescence == quiescence.id
    allocation_retention = replace(
        retention, id=WorkRetentionID("allocation-retention"),
        target=AllocationTarget(_artifact("memory://values"), StorageAllocationID("allocation")),
        basis=MaterializationRef(_artifact("memory://values"), MaterializationID("mat")),
        release=_gap("release evidence missing"),
    )
    assert isinstance(allocation_retention.target, AllocationTarget)


def test_prefix_start_and_append_are_distinct_from_submission_table_order():
    start = QueueStart(_fact("/queue-start"))
    first = QueuePrefix(
        QueuePrefixID("q0"), ResourceInstanceID("queue-instance"), start, None,
        _point(), _fact("/queue-protocol"), _fact("/q0"),
    )
    second = QueuePrefix(
        QueuePrefixID("q1"), ResourceInstanceID("queue-instance"), first.id,
        WorkTicketID("ticket"),
        _point(), _fact("/queue-protocol"), _fact("/q1"),
    )
    assert second.previous == first.id
    assert decode(QueuePrefix, encode(second)) == second


def test_records_are_frozen_slotted_and_revalidate_nested_values():
    row = _submission()
    assert not hasattr(row, "__dict__")
    assert not ({"verified", "proven", "ready", "complete"} &
                {field.name for field in fields(row)})
    with pytest.raises(FrozenInstanceError):
        row.id = WorkTicketID("mutated")
    assert decode(WorkSubmission, encode(row)) == row

    artifact = _artifact("memory://corrupted")
    materialization = MaterializationRef(artifact, MaterializationID("mat"))
    object.__setattr__(artifact, "uri", "")
    with pytest.raises((TypeError, ValueError)):
        replace(row, materializations=(materialization,))


@pytest.mark.parametrize("factory", [
    lambda: ActualCompletionState(True, 0, ValueOccurrenceID("formal")),
    lambda: ActualCompletionState(0, False, ValueOccurrenceID("formal")),
    lambda: QueuePrefix(QueuePrefixID("empty"), ResourceAccessID("q"),
                        QueuePrefixID("prior"), None, _point(), _fact(), _fact()),
    lambda: QueuePrefix(QueuePrefixID("prefix"), ResourceAccessID("not-an-instance"),
                        QueueStart(_fact("/start")), None, _point(), _fact(), _fact()),
    lambda: _submission(dependencies=(WorkTicketID("ticket"),)),
    lambda: _submission(dependencies=(WorkTicketID("dep"), WorkTicketID("dep"))),
    lambda: _submission(effects=[]),
    lambda: _submission(effects=(AccessRef(OperationOccurrenceID("o"), True),)),
    lambda: _submission(dependencies_coverage="COMPLETE"),
    lambda: ResourceOutcome(
        WorkOutcomeID("o"), WorkTicketID("t"), "FAILED", _point(),
        _gap(), (), Completeness.UNKNOWN, _gap(), _fact()),
    lambda: WorkRetention(
        WorkRetentionID("r"), WorkTicketID("t"),
        InstanceTarget(ResourceInstanceID("instance")),
        UseRef(OperationOccurrenceID("op"), UseID("use")),
        _point(), (ValueOccurrenceID("s"), ValueOccurrenceID("s")),
        ReleaseAuthority.BORROWED, Sharing.SHARED, _gap(), _fact()),
])
def test_work_records_reject_wrong_variants_duplicate_coordinates_and_bool_indices(factory):
    with pytest.raises((TypeError, ValueError)):
        factory()


def test_exact_nested_types_reject_subclasses_and_wrong_resource_targets():
    class ChildTicket(WorkTicketID):
        pass

    class ChildPoint(OccurrencePoint):
        pass

    with pytest.raises(TypeError):
        _submission(id=ChildTicket("child"))
    with pytest.raises(TypeError):
        ResourceOutcome(
            WorkOutcomeID("o"), WorkTicketID("t"), WorkOutcomeKind.FAILED,
            ChildPoint(OperationOccurrenceID("op"), OccurrencePhase.AFTER),
            _gap(), (), Completeness.UNKNOWN, _gap(), _fact())

