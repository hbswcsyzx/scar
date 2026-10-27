"""Known failed/non-Create origins versus missing successful-handle evidence."""
from dataclasses import replace

from scar.ir.program.ids import BlockID, OperationID
from tests.fixtures.execution_call_graphs import _model
from tests.fixtures.execution_resumable_graphs import resumable_execution


def body_creation_execution(*, mode='failed'):
    """Return a supplied graph; only ``failed`` and ``plain`` are invalid O.

    The failed variant rebuilds the actual factory path and typed RAISE
    landing/terminal. It never changes an edge index over a NORMAL landing.
    """
    if mode not in ('failed', 'plain', 'missing_transfer', 'missing_handle'):
        raise ValueError('unknown finite creation evidence variant')
    program, model, details = resumable_execution()
    item, = details['instances']
    if mode == 'failed':
        fresh, scopes, _ = _model(program, ((program.root,
            ((BlockID('factory.entry'), 1), (BlockID('factory.failed'), None)), 'instance.0.factory'),))
        activation = item['factory'][0]
        old_segments = {row.id for row in model.segments if row.activation == activation}
        old_visits = {row.id for row in model.visits if row.segment in old_segments}
        old_operations = {row.id for row in model.operations if row.visit in old_visits}
        old_values = {row.id for row in model.values if row.origin in old_visits | old_operations | {activation}}
        model = replace(model,
            activations=tuple(row for row in model.activations if row.id != activation) + fresh.activations,
            segments=tuple(row for row in model.segments if row.id not in old_segments) + fresh.segments,
            visits=tuple(row for row in model.visits if row.id not in old_visits) + fresh.visits,
            operations=tuple(row for row in model.operations if row.id not in old_operations) + fresh.operations,
            values=tuple(row for row in model.values if row.id not in old_values) + fresh.values,
            uses=tuple(row for row in model.uses if row.operation not in old_operations) + fresh.uses,
            transfers=tuple(row for row in model.transfers if row.operation not in old_operations) + fresh.transfers,
            call_activations=tuple(row for row in model.call_activations if row.caller not in old_operations))
        keep = {row.id for row in model.values}
        model = replace(model, denotations=tuple(row for row in model.denotations if row.value in keep))
        details = {**details, 'failed_visit': scopes[0][1][1],
                   'failed_terminal': scopes[0][2][OperationID('factory.failed.raise')]}
    elif mode == 'plain':
        plain = item['factory'][2][OperationID('factory.raw.pack')]
        model = replace(model, body_activation_origins=tuple(replace(row, creation=plain)
            if row.activation == item['activation'] else row for row in model.body_activation_origins))
    elif mode == 'missing_transfer':
        model = replace(model, transfers=tuple(row for row in model.transfers if row.operation != item['creation']))
    else:
        handle = next(row for row in model.values if row.origin == item['factory'][1][1]
                      and row.value.value == 'factory.created.arg.0')
        model = replace(model, values=tuple(row for row in model.values if row.id != handle.id),
            uses=tuple(replace(row, value=details['gap']) if row.value == handle.id else row for row in model.uses),
            denotations=tuple(row for row in model.denotations if row.value != handle.id))
        details = {**details, 'missing_handle': handle}
    return program, model, {**details, 'mode': mode}


__all__ = ['body_creation_execution']
