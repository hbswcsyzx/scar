"""Strong local records for event generations and queue-order endpoints."""
from dataclasses import FrozenInstanceError, replace

import pytest

from scar.ir.execution.common import EvidencePoint, MissingEvidence, Unresolved
from scar.ir.execution.coordinates import (
    AccessRef, OperationOccurrenceID, ProgramSnapshot, UseRef, ValueOccurrenceID,
)
from scar.ir.execution.ids import (
    EventRecordID, QueueOrderProfileID, QueuePrefixID, QueueWaitID,
    ResourceAccessID, ResourceInstanceID, RunID, WorkTicketID,
    ProcessInstanceID,
)
from scar.ir.execution.model import ExecutionModel, TABLE_TYPES
from scar.ir.execution.order import (
    EventRecord, EventSignal, OrderPoint, PrefixEnd, QueueOrderProfile,
    QueueWait, RecordedPrefix, WorkEnd, WorkStart,
)
from scar.ir.execution.work import (
    ActualCompletionState, InvokeBoundaryStateEffect, QueueStart,
)
from scar.ir.program.ids import UseID
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference


def _artifact(uri="memory://order"):
    return ProviderArtifact(uri, "a" * 64, 0, "order-test-v1")


def _fact(locator="/fact"):
    return ProviderFactReference(_artifact(), locator)


def _point():
    return EvidencePoint(RunID("run"), ProcessInstanceID("process"), _fact("/point"))


def _gap(reason="not observed"):
    return Unresolved(reason, _point())


def _rows():
    queue = ResourceInstanceID("queue")
    event = ResourceInstanceID("event")
    ticket = WorkTicketID("consumer")
    prefix = QueuePrefixID("prefix")
    operation = OperationOccurrenceID("op")
    profile = QueueOrderProfile(
        QueueOrderProfileID("profile"), queue, prefix, _fact("/queue-order"), _fact("/profile-source"))
    start = QueueStart(_fact("/queue-start"))
    captured = RecordedPrefix(queue, start)
    generation = AccessRef(operation, 0)
    record = EventRecord(
        EventRecordID("event-record.1"), event, ResourceAccessID("record-access"),
        WorkTicketID("marker"), captured, generation, _point(), _fact("/event-protocol"),
        _fact("/record-source"))
    wait = QueueWait(
        QueueWaitID("wait"), ticket, record.id, ResourceAccessID("wait-access"),
        UseRef(operation, UseID("event-use")), _point(), _fact("/wait-protocol"),
        _fact("/wait-source"))
    return profile, record, wait, queue, prefix, ticket, operation


def test_order_records_use_distinct_exact_ids_and_preserve_generations():
    profile, record, wait, queue, prefix, ticket, operation = _rows()
    assert QueueOrderProfileID("x").wire == "exec_queue_order_profile:x"
    assert EventRecordID("x").wire == "exec_event_record:x"
    assert QueueWaitID("x").wire == "exec_queue_wait:x"
    assert len({QueueOrderProfileID("x").wire, EventRecordID("x").wire,
                QueueWaitID("x").wire}) == 3

    # A rerecord is a new record identity. A wait stores the selected record
    # ID and does not float to whichever generation is latest.
    record2 = replace(record, id=EventRecordID("event-record.2"),
                      captured=RecordedPrefix(queue, prefix))
    assert record2.id != record.id
    assert wait.record == record.id
    assert record2.captured.prefix == prefix
    assert profile.through == prefix

    normal_state = InvokeBoundaryStateEffect(
        operation,
        UseRef(operation, UseID("world-in")),
        ActualCompletionState(0, 0, ValueOccurrenceID("world-after")),
    )
    assert replace(record, id=EventRecordID("event-record.invoke"), generation=normal_state).generation is normal_state


def test_order_point_kinds_keep_work_start_end_prefix_end_and_signal_separate():
    _, record, _, _, prefix, ticket, _ = _rows()
    points: tuple[OrderPoint, ...] = (
        WorkStart(ticket), WorkEnd(ticket), PrefixEnd(prefix), EventSignal(record.id))
    assert tuple(type(point) for point in points) == (WorkStart, WorkEnd, PrefixEnd, EventSignal)
    assert points[0] != points[1]
    assert points[1] != points[2]
    assert points[2] != points[3]


@pytest.mark.parametrize("factory", [
    lambda: QueueOrderProfile(EventRecordID("wrong"), ResourceInstanceID("q"),
                              QueuePrefixID("p"), _fact(), _fact()),
    lambda: RecordedPrefix(ResourceInstanceID("q"), ResourceAccessID("not-prefix")),
    lambda: EventRecord(EventRecordID("r"), ResourceInstanceID("e"), WorkTicketID("not-access"),
                        _gap(), RecordedPrefix(ResourceInstanceID("q"), QueuePrefixID("p")),
                        _gap(), _point(), _fact(), _fact()),
    lambda: EventRecord(EventRecordID("r"), ResourceInstanceID("e"), _gap(), _gap(),
                        RecordedPrefix(ResourceInstanceID("q"), QueuePrefixID("p")),
                        QueuePrefixID("not-generation"), _point(), _fact(), _fact()),
    lambda: QueueWait(EventRecordID("not-wait"), WorkTicketID("t"), _gap(), _gap(), _gap(),
                      _point(), _fact(), _fact()),
    lambda: QueueWait(QueueWaitID("w"), WorkTicketID("t"), _gap(), _gap(),
                      AccessRef(OperationOccurrenceID("op"), 0),
                      _point(), _fact(), _fact()),
    lambda: WorkStart(EventRecordID("not-ticket")),
    lambda: WorkEnd(QueueWaitID("not-ticket")),
    lambda: PrefixEnd(WorkTicketID("not-prefix")),
    lambda: EventSignal(QueuePrefixID("not-record")),
])
def test_order_records_reject_cross_namespace_ids_and_wrong_variants(factory):
    with pytest.raises((TypeError, ValueError)):
        factory()


def test_nested_records_revalidate_and_rows_are_frozen_slotted_and_registered():
    profile, record, wait, _, _, _, _ = _rows()
    assert not hasattr(record, "__dict__")
    with pytest.raises(FrozenInstanceError):
        record.id = EventRecordID("changed")

    snapshot = ProgramSnapshot(_artifact("memory://snapshot"), 14)
    model = ExecutionModel(
        snapshot,
        queue_order_profiles=(profile,),
        event_records=(record,),
        queue_waits=(wait,),
    )
    assert TABLE_TYPES["queue_order_profiles"] is QueueOrderProfile
    assert TABLE_TYPES["event_records"] is EventRecord
    assert TABLE_TYPES["queue_waits"] is QueueWait
    assert model.event_records == (record,)

    # Frozen outer records must still revalidate nested frozen records if a
    # caller bypasses immutability with object.__setattr__.
    poisoned = _fact("/poisoned")
    object.__setattr__(poisoned, "locator", "")
    with pytest.raises((TypeError, ValueError)):
        replace(record, protocol=poisoned)

    poisoned_prefix = RecordedPrefix(ResourceInstanceID("queue"), QueuePrefixID("prefix"))
    object.__setattr__(poisoned_prefix, "queue", "queue")
    with pytest.raises((TypeError, ValueError)):
        replace(record, captured=poisoned_prefix)
