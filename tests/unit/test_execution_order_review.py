"""Independent boundary checks for external queue scope in R2.2."""
from dataclasses import replace

import pytest

from scar.ir.execution.common import MissingEvidence
from scar.ir.execution.coordinates import (
    EvidencePoint, HostThreadInstance, InitialEntry, ProcessInstance,
)
from scar.ir.execution.ids import (
    ExternalRealmID, ProcessInstanceID, QueueOrderProfileID, ResourceInstanceID,
    RunID, HostThreadInstanceID, WorkTicketID,
)
from scar.ir.execution.order import QueueOrderProfile, WorkEnd, WorkStart
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.resources import ExternalRealm
from scar.ir.execution.validation import _analyze, validate
from scar.ir.program.providers import ProviderFactReference
from tests.fixtures.execution_work_graphs import ordinary_work_execution


def _external_queue_two_scopes(*, second_scope):
    program, model, _ = ordinary_work_execution(queued=True, two_tickets=True, activations=2)
    source = MissingEvidence("external queue identity is declared; sharing protocol is unverified")
    namespace = ProviderFactReference(model.snapshot.artifact, "review-external-queue-namespace")
    for label in ("queue", "executor"):
        identity = ResourceInstanceID("work." + label)
        resource = next(row for row in model.resources if row.id == identity)
        model = replace(model, resources=tuple(
            replace(row, realm=ExternalRealm(ExternalRealmID("review." + label), namespace))
            if row.id == identity else row for row in model.resources))

    run1 = model.runs[0]
    process1 = model.processes[0]
    thread1 = model.threads[0]
    if second_scope == "same-run-two-processes":
        run2 = run1
        process2_id = ProcessInstanceID("review.process.2")
    else:
        run2 = type(run1)(RunID("review.run.2"), run1.source)
        process2_id = ProcessInstanceID("review.process.2")
    process2 = ProcessInstance(process2_id, run2.id, 202, source)
    thread2 = HostThreadInstance(HostThreadInstanceID("review.thread.2"), process2_id, 2020, source)
    point2 = EvidencePoint(run2.id, process2_id, source)
    second_activation = next(row for row in model.activations if row.id.value == "activation.1")
    second_segment = next(row for row in model.segments if row.activation == second_activation.id)
    model = replace(model,
        runs=model.runs if run2.id == run1.id else (*model.runs, run2),
        processes=(*model.processes, process2),
        threads=(*model.threads, thread2),
        activations=tuple(replace(row, process=process2_id, entry=point2)
                          if row.id == second_activation.id else row for row in model.activations),
        segments=tuple(replace(row, host_thread=thread2.id, ingress=InitialEntry(point2))
                       if row.id == second_segment.id else row for row in model.segments),
        resources=tuple(replace(row, realm=type(row.realm)(process2_id))
                         if row.id == ResourceInstanceID("activation.1.ofd") else row
                         for row in model.resources))
    protocol = model.submissions[0].protocol
    profile = QueueOrderProfile(QueueOrderProfileID("review.queue"),
        ResourceInstanceID("work.queue"), model.queue_prefixes[-1].id, protocol, source)
    model = replace(model, queue_order_profiles=(profile,))
    return program, model


def _has_cross_scope_profile_edge(ctx):
    return any(step.rule == "profile-fifo"
        and step.source == WorkEnd(WorkTicketID("work.1"))
        and step.target == WorkStart(WorkTicketID("work.2"))
        for step in ctx.order_steps)


def test_external_queue_does_not_merge_same_run_different_process_scopes():
    program, model = _external_queue_two_scopes(second_scope="same-run-two-processes")
    report = validate(model, program)
    assert not report.issues
    assert any("scope_unresolved" in row.code for row in report.gaps)
    result = ExecutionIndex(model, program).work_order(WorkTicketID("work.1"), WorkTicketID("work.2"))
    assert result["status"] == "UNRESOLVED"
    assert result["runtime_order_verified"] is False


def test_external_queue_prefix_cannot_connect_work_across_known_runs():
    program, model = _external_queue_two_scopes(second_scope="two-known-runs")
    report, ctx = _analyze(model, program)
    assert any("run_scope" in row.code for row in report.issues)
    assert not _has_cross_scope_profile_edge(ctx)
