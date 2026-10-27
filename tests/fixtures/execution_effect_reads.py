"""Shared-effect fixtures; all rows are declarations, not runtime proof."""
from dataclasses import replace

from scar.ir.execution.common import MissingEvidence, Unresolved
from scar.ir.execution.content import (
    ContentRead, HostConsumer, ResourceConsumer, ProtocolInterval, WholeWorkRead,
)
from scar.ir.execution.coordinates import (
    OccurrencePhase, OccurrencePoint, UseRef,
)
from scar.ir.execution.ids import ContentReadID, WorkTicketID
from scar.ir.execution.snapshot import snapshot_for
from scar.ir.execution.work import (
    ActualCompletionState, InvokeBoundaryStateEffect, WorkOutcomeKind,
)
from scar.ir.program.ids import BlockID, OperationID, UseID, ValueID
from scar.ir.program.model import BlockArgument, CompletionResult, Use, UseRole
from scar.ir.program.providers import ProviderFactReference
from scar.ir.v2.common import Completeness
from tests.fixtures.execution_paths import declared_path
from tests.fixtures.execution_work_graphs import _with_compute_resources, _work_rows
from tests.fixtures.program_resumption_invoke_graphs import partial_state_invoke_program


def invoke_state_content_read(*, consumer="host", raised=False, other_ticket_coverage=None):
    """Build a host/resource content read whose original effect is an INVOKE.

    ``other_ticket_coverage`` adds a second same-operation ticket that omits
    the effect, exposing any accidental use of the global effect union.
    """
    if consumer not in ("host", "work"):
        raise ValueError("consumer must be 'host' or 'work'")
    if other_ticket_coverage not in (None, Completeness.PARTIAL, Completeness.UNKNOWN,
                                     Completeness.COMPLETE):
        raise ValueError("unsupported second-ticket effect coverage")
    if consumer == "host" and other_ticket_coverage is not None:
        raise ValueError("a host consumer has no second work ticket")

    program = partial_state_invoke_program()
    invoke_id = OperationID("invoke.call")
    content_use = Use(UseID("invoke.call.content"), ValueID("invoke.x"), UseRole.REFERENCE)
    invoke = next(row for row in program.operations if row.id == invoke_id)
    invoke = replace(invoke, uses=(*invoke.uses, content_use),
                     invoke_arguments=(*invoke.invoke_arguments, content_use.id))
    program = replace(program, operations=tuple(
        invoke if row.id == invoke_id else row for row in program.operations))

    edge = 1 if raised else 0
    landing = "invoke.failure" if raised else "invoke.normal"
    model = declared_path(program, ((BlockID("invoke.entry"), edge), (BlockID(landing), None)))
    operation = next(row for row in program.operations if row.id == invoke_id)
    occurrence = next(row for row in model.operations if row.operation == invoke_id)
    successor = operation.terminator.successors[edge]
    formal = next((value for value in program.values
                   if type(value.origin) is BlockArgument
                   and value.origin.block == successor.block
                   and successor.arguments[value.origin.index] == CompletionResult(0)))
    formal_occurrence = next(row.id for row in model.values if row.value == formal.id)
    state_input = UseID("invoke.call.world")
    effect = InvokeBoundaryStateEffect(
        occurrence.id, UseRef(occurrence.id, state_input),
        ActualCompletionState(edge, 0, formal_occurrence))
    input_value = next(row.value for row in model.uses
                       if row.operation == occurrence.id and row.use == state_input)
    subject = UseRef(occurrence.id, content_use.id)
    source = MissingEvidence("hand-authored invoke read fixture; no source/runtime authority")
    protocol = ProviderFactReference(snapshot_for(program).artifact, "effect-read-interval")
    point = OccurrencePoint(occurrence.id, OccurrencePhase.BEFORE)
    interval = ProtocolInterval(point, point, protocol, source)

    work_catalogs = {}
    ticket = None
    second_ticket = None
    if consumer == "work":
        program, model = _with_compute_resources(program, model, (invoke_id,))
        occurrence = next(row for row in model.operations if row.operation == invoke_id)
        model, work_catalogs = _work_rows(
            program, model, (occurrence,), (effect,), queued=False,
            kind=WorkOutcomeKind.FAILED if raised else WorkOutcomeKind.COMPLETED,
            quiescent=True, retained="resource")
        ticket = model.submissions[0].id
        if other_ticket_coverage is not None:
            second_ticket = WorkTicketID("effect-read.other-ticket")
            second = replace(model.submissions[0], id=second_ticket, effects=(),
                             effects_coverage=other_ticket_coverage, retention=())
            model = replace(model, submissions=(*model.submissions, second))
        read_consumer = ResourceConsumer(
            subject, WholeWorkRead(ticket if second_ticket is None else second_ticket),
            Unresolved("native input slot is not captured", model.activations[0].entry))
    else:
        read_consumer = HostConsumer(subject, interval)

    # Work-resource setup refreshes the program fingerprint. The dynamic
    # occurrence and state input remain the same canonical endpoints.
    point = OccurrencePoint(occurrence.id, OccurrencePhase.BEFORE)
    protocol = ProviderFactReference(model.snapshot.artifact, "effect-read-interval")
    if consumer == "host":
        interval = ProtocolInterval(point, point, protocol, source)
        read_consumer = HostConsumer(subject, interval)
    content_read = ContentRead(
        ContentReadID("effect-read.content"), read_consumer,
        Unresolved("content placement is not established", model.activations[0].entry), effect, point,
        (input_value,), Unresolved("source port is not captured", model.activations[0].entry), source)
    model = replace(model, content_reads=(content_read,))
    return program, model, work_catalogs, {
        "effect": effect,
        "occurrence": occurrence.id,
        "subject": subject,
        "input_value": input_value,
        "read": content_read.id,
        "ticket": ticket,
        "second_ticket": second_ticket,
        "formal": formal_occurrence,
    }


__all__ = ["invoke_state_content_read"]
