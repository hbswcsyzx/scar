"""Conditional queue/event order over original pending work, never readiness."""
from dataclasses import replace

import pytest

from scar.ir.execution.common import EvidencePoint, Unresolved
from scar.ir.execution.coordinates import AccessRef, ExecutionRun, OccurrencePhase, OccurrencePoint, ProcessInstance, UseRef
from scar.ir.execution.ids import (
    EventRecordID, ProcessInstanceID, QueuePrefixID, ResourceAccessID,
    ResourceInstanceID, RunID, WorkTicketID,
)
from scar.ir.execution.order import EventSignal, PrefixEnd, WorkEnd, WorkStart
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.validation import require_valid, validate
from scar.ir.program.ids import UseID
from scar.ir.program.model import AccessMode, Behavior
from scar.ir.program.validation import require_valid as require_program_valid
from tests.fixtures.execution_order_graphs import event_order_execution


def _valid(**options):
    program, model = event_order_execution(**options)
    require_program_valid(program)
    report = require_valid(model, program)
    assert report.gaps and not report.source_runtime_verified and not report.transformation_authorized
    return program, model, ExecutionIndex(model, program)


def _conditional(result):
    assert result["status"] == "CONDITIONAL"
    assert result["path"]
    assert result["gaps"]
    for key in ("source_runtime_verified", "runtime_order_verified", "transformation_authorized"):
        assert result[key] is False
    assert not {"ready", "free", "host_ready", "persistent"}.intersection(result)


def _unresolved(result):
    assert result["status"] == "UNRESOLVED"
    assert not result["path"]
    assert result["runtime_order_verified"] is False


def test_real_order_state_accesses_read_the_exact_first_record_generation_while_all_work_is_pending():
    program, model, _ = _valid()
    assert [row.id.value for row in model.submissions] == ["p1", "r1", "w", "c", "p2", "r2"]
    assert not model.outcomes and not model.quiescences
    first, second = model.event_records
    assert first.id != second.id and first.event == second.event
    wait, = model.queue_waits
    selected = next(row for row in model.uses if row.operation == wait.selection.operation and row.use == wait.selection.use)
    producer = next(row for row in model.values if row.id == selected.value)
    assert producer.origin == first.generation.operation
    assert wait.record == first.id
    op = next(row for row in program.operations if row.id.value == "order.w")
    assert Behavior.ORDER in op.behaviors
    assert op.accesses[0].mode is AccessMode.READ and op.accesses[0].after is None
    assert op.accesses[1].mode is AccessMode.READ_WRITE
    assert all(not access.full_overwrite for access in op.accesses)


def test_cross_queue_wait_connects_producer_end_to_consumer_start_without_any_host_completed_outcome():
    _, model, index = _valid()
    result = index.work_order(WorkTicketID("p1"), WorkTicketID("c"))
    _conditional(result)
    assert result["path"][0].source == WorkEnd(WorkTicketID("p1"))
    assert result["path"][-1].target == WorkStart(WorkTicketID("c"))
    assert not model.outcomes
    assert index.work(WorkTicketID("p1"))["outcomes"] == ()


def test_same_queue_fifo_profile_orders_start_without_event_wait_or_host_sync():
    _, model, index = _valid(same_queue=True, with_wait=False)
    assert not model.queue_waits and not model.outcomes
    _conditional(index.work_order(WorkTicketID("p1"), WorkTicketID("c")))


def test_host_submission_order_does_not_order_two_queues_without_the_actual_wait_association():
    _, _, index = _valid(with_wait=False)
    _unresolved(index.work_order(WorkTicketID("p1"), WorkTicketID("c")))


def test_re_record_does_not_retarget_old_wait_or_cover_new_producer_work():
    _, model, index = _valid()
    assert model.queue_waits[0].record == EventRecordID("r1")
    assert model.event_records[1].id == EventRecordID("r2")
    _conditional(index.order_path(WorkEnd(WorkTicketID("p1")), EventSignal(EventRecordID("r1"))))
    _unresolved(index.order_path(WorkEnd(WorkTicketID("p2")), EventSignal(EventRecordID("r1"))))
    _unresolved(index.work_order(WorkTicketID("p2"), WorkTicketID("c")))


def test_event_wait_can_constrain_wait_end_without_constraining_wait_start():
    _, _, index = _valid()
    _conditional(index.order_path(WorkEnd(WorkTicketID("p1")), WorkEnd(WorkTicketID("w"))))
    _unresolved(index.order_path(WorkEnd(WorkTicketID("p1")), WorkStart(WorkTicketID("w"))))


def test_missing_fifo_profile_does_not_erase_event_capture_but_cannot_order_same_queue_start():
    program, model, _ = _valid(same_queue=True, with_wait=False)
    model = replace(model, queue_order_profiles=())
    require_valid(model, program)
    index = ExecutionIndex(model, program)
    _conditional(index.order_path(WorkEnd(WorkTicketID("p1")), EventSignal(EventRecordID("r1"))))
    _unresolved(index.work_order(WorkTicketID("p1"), WorkTicketID("c")))


def test_explicit_event_capture_does_not_need_source_queue_fifo_profile():
    program, model, _ = _valid()
    model = replace(model, queue_order_profiles=tuple(row for row in model.queue_order_profiles if row.id.value != "qa"))
    require_valid(model, program)
    _conditional(ExecutionIndex(model, program).work_order(WorkTicketID("p1"), WorkTicketID("c")))


def test_missing_destination_fifo_profile_cannot_turn_wait_end_order_into_consumer_start():
    program, model, _ = _valid()
    model = replace(model, queue_order_profiles=tuple(row for row in model.queue_order_profiles if row.id.value != "qb"))
    require_valid(model, program)
    index = ExecutionIndex(model, program)
    _conditional(index.order_path(WorkEnd(WorkTicketID("p1")), WorkEnd(WorkTicketID("w"))))
    _conditional(index.order_path(WorkEnd(WorkTicketID("p1")), PrefixEnd(QueuePrefixID("c"))))
    _unresolved(index.work_order(WorkTicketID("p1"), WorkTicketID("c")))


def test_missing_generation_has_an_exact_gap_and_does_not_guess_wait_selection():
    program, model, _ = _valid()
    unknown = Unresolved("record generation was not captured", model.activations[0].entry)
    first, second = model.event_records
    model = replace(model, event_records=(replace(first, generation=unknown), second))
    report = require_valid(model, program)
    assert any("generation" in row.code and "r1" in row.path for row in report.gaps)
    _unresolved(ExecutionIndex(model, program).work_order(WorkTicketID("p1"), WorkTicketID("c")))


def test_queue_order_does_not_create_a_host_read_completion_ready_or_free_fact():
    program, model, index = _valid()
    assert any(row.id.value == "order.host_read" for row in program.operations)
    result = index.work_order(WorkTicketID("p1"), WorkTicketID("c"))
    _conditional(result)
    assert not model.outcomes and not model.quiescences
    assert index.work(WorkTicketID("w"))["host_completion"] is None


@pytest.mark.parametrize("which", (
    "record-event", "record-access", "marker-missing", "marker-other", "captured-queue", "captured-future",
    "generation-location", "wait-access", "wait-ticket-missing", "wait-ticket-other", "wait-r2-selection",
    "selection-location", "selection-reference", "profile-queue", "profile-cutoff-missing",
))
def test_known_event_wait_profile_and_original_port_mismatches_are_issues(which):
    program, model, _ = _valid()
    first, second = model.event_records
    wait, = model.queue_waits
    if which == "record-event":
        changed = replace(model, event_records=(replace(first, event=ResourceInstanceID("order.executor")), second))
    elif which == "record-access":
        changed = replace(model, event_records=(replace(first, event_access=ResourceAccessID("order.r1.qa")), second))
    elif which == "marker-missing":
        changed = replace(model, event_records=(replace(first, marker=WorkTicketID("absent-marker")), second))
    elif which == "marker-other":
        changed = replace(model, event_records=(replace(first, marker=WorkTicketID("p1")), second))
    elif which == "captured-queue":
        changed = replace(model, event_records=(replace(first,
            captured=replace(first.captured, queue=ResourceInstanceID("order.qb"))), second))
    elif which == "captured-future":
        changed = replace(model, event_records=(replace(first,
            captured=replace(first.captured, prefix=QueuePrefixID("r2"))), second))
    elif which == "generation-location":
        changed = replace(model, event_records=(replace(first, generation=replace(first.generation, index=1)), second))
    elif which == "wait-access":
        changed = replace(model, queue_waits=(replace(wait, event_access=ResourceAccessID("order.w.qb")),))
    elif which == "wait-ticket-missing":
        changed = replace(model, queue_waits=(replace(wait, ticket=WorkTicketID("absent-wait")),))
    elif which == "wait-ticket-other":
        changed = replace(model, queue_waits=(replace(wait, ticket=WorkTicketID("c")),))
    elif which == "wait-r2-selection":
        changed = replace(model, queue_waits=(replace(wait, record=second.id),))
    elif which in ("selection-location", "selection-reference"):
        selected = "order.w.qb" if which == "selection-location" else "order.w.event.reference"
        changed = replace(model, queue_waits=(replace(wait,
            selection=UseRef(wait.selection.operation, UseID(selected))),))
    elif which == "profile-queue":
        a, b = model.queue_order_profiles
        changed = replace(model, queue_order_profiles=(replace(a, queue=b.queue), b))
    else:
        a, b = model.queue_order_profiles
        changed = replace(model, queue_order_profiles=(replace(a, through=QueuePrefixID("absent-cutoff")), b))
    assert validate(changed, program).issues, which


def test_event_record_observation_cannot_cross_a_known_run():
    program, model, _ = _valid()
    source = model.runs[0].source
    run = ExecutionRun(RunID("other-run"), source)
    process = ProcessInstance(ProcessInstanceID("other-process"), run.id, None, source)
    point = EvidencePoint(run.id, process.id, source)
    first, second = model.event_records
    changed = replace(model, runs=(*model.runs, run), processes=(*model.processes, process),
        event_records=(replace(first, observed_at=point), second))
    assert validate(changed, program).issues


def test_combined_event_fifo_and_work_dependency_cycle_is_not_a_proof():
    program, model, _ = _valid()
    first, *rest = model.submissions
    # Individually the dependency graph and both prefix chains are acyclic.
    # C.end -> P1.start closes a cycle only through event r1 / W / QB FIFO.
    changed = replace(model, submissions=(replace(first, dependencies=(WorkTicketID("c"),)), *rest))
    old_layer = replace(changed, queue_order_profiles=(), event_records=(), queue_waits=())
    require_valid(old_layer, program)
    assert any("cycle" in row.code for row in validate(changed, program).issues)
