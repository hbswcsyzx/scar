"""The same complete predicate graph admits reject and forbids wrong accept.

These are supplied occurrence declarations, not observed native executions.
"""
from dataclasses import replace

from scar.ir.execution.snapshot import snapshot_for
from scar.ir.program.resumption import ResumableKind
from tests.fixtures.execution_await_failure_graphs import await_failure_execution
from tests.fixtures.execution_await_general_graphs import await_general_execution


def qualified_general_execution(*, accepted=False):
    """Return ``(program, model, details)`` for an exact known-bad candidate."""
    if type(accepted) is not bool:
        raise TypeError('accepted must be an exact bool')
    if not accepted:
        program, model, details = await_failure_execution('qualification_reject')
    else:
        # Reuse the unchanged successful original capture. Only its declared
        # body family and the corresponding program snapshot change; its
        # actual branch/Uses/ports remain the exact acceptance counterexample.
        program, model, details = await_general_execution()
        program = replace(program, resumable_bodies=tuple(
            replace(body, kind=ResumableKind.GENERATOR_COROUTINE)
            for body in program.resumable_bodies))
        model = replace(model, snapshot=snapshot_for(program))
        details = {**details, 'body': next(body for body in program.resumable_bodies
                                        if body.region == details['body'].region)}
    return program, model, {**details, 'acceptance_selected': accepted,
        'qualification_occurrence': details['helper_operations'][details['qualification'].id]}


def accepted_without_later_drive_execution():
    """Keep the actual bad acceptance but omit all later advance/body capture.

    The caller's GET NORMAL transfer and landing formal occurrences remain.
    That landing is an uncaptured suffix before its first advance operation;
    the helper's predicate, accepting transfer and real RETURN remain captured.
    """
    program, model, details = qualified_general_execution(accepted=True)
    advance = details['factory_operations'][details['call'].id]
    operation = next(row for row in model.operations if row.id == advance)
    visits = {row.id: row for row in model.visits}
    segment = visits[operation.visit].segment
    ordered = tuple(row for row in model.visits if row.segment == segment)
    position = next(index for index, row in enumerate(ordered) if row.id == operation.visit)
    block = next(block for region in program.regions for block in region.blocks
                 if block.id == visits[operation.visit].block)
    operation_position = block.operations.index(operation.operation)
    omitted_activations = {details['driver_activation'], details['body_activation']}
    omitted_segments = {row.id for row in model.segments if row.activation in omitted_activations}
    omitted_visits = {row.id for row in model.visits if row.segment in omitted_segments}
    omitted_visits.update(row.id for row in ordered[position + 1:])
    omitted_operations = {row.id for row in model.operations
        if row.visit in omitted_visits or row.visit == operation.visit
        and block.operations.index(row.operation) >= operation_position}
    omitted_values = {row.id for row in model.values
        if row.origin in omitted_activations or row.origin in omitted_visits
        or row.origin in omitted_operations}
    model = replace(model,
        activations=tuple(row for row in model.activations if row.id not in omitted_activations),
        segments=tuple(row for row in model.segments if row.id not in omitted_segments),
        visits=tuple(row for row in model.visits if row.id not in omitted_visits),
        operations=tuple(row for row in model.operations if row.id not in omitted_operations),
        values=tuple(row for row in model.values if row.id not in omitted_values),
        uses=tuple(row for row in model.uses if row.operation not in omitted_operations),
        transfers=tuple(row for row in model.transfers
            if row.operation not in omitted_operations and row.target not in omitted_visits),
        call_activations=(details['acquisition_call'],),
        body_drive_executions=(), body_activation_origins=())
    return program, model, {**details, 'omitted_advance': advance}


__all__ = ['qualified_general_execution', 'accepted_without_later_drive_execution']
