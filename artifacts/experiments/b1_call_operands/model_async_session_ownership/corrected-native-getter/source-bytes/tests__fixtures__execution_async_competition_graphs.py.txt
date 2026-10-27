"""Exact supplied captures of two request Creates and one persistent body.

Four synchronous driver activations surround three body segments. The R2
rejection has no actual BodyDrive; only its real known getter has an extra
CallActivation. No captured branch is evidence of native occupancy by itself.
"""
from dataclasses import replace

from tests.fixtures.native_coroutine_common import capture_program
from tests.fixtures.program_async_competition_graphs import async_competition_program


def async_competition_execution(*, reject_raised=False, known_association=True,
                                local_probe=False, instances=2,
                                missing_getter_call=None, missing_reject_payload=None,
                                missing_resume_transfer=None):
    program, static = async_competition_program(reject_raised=reject_raised,
        known_association=known_association, local_probe=local_probe)
    getter = static['getter']
    extras = () if getter is None else ({'label': 'r2.association', 'parent': ('driver', 1),
        'caller': static['occupancy']['association_operation'].id, 'region': getter['region'].id,
        'path': getter['path'], 'completion': getter['terminal'].id},)
    model, details = capture_program(program, static, instances=instances,
        label='async.competition', extra_calls=extras)
    examples = []
    for original in details['instances']:
        scopes = original['driver_scopes']
        operations = scopes[1][2]
        occupancy = static['occupancy']
        local = static['local_probe']
        examples.append({**original,
            'occupancy_read': operations[occupancy['predicate'].id],
            'initial_read': operations[occupancy['initial_predicate'].id],
            'association': operations[occupancy['association_operation'].id],
            'reject': operations[occupancy['reject'].id],
            'reject_terminal': operations[occupancy['selected_terminal'].id],
            'source_hold': scopes[0][2][static['first_hold']['update'].operation],
            'local_read': None if local is None else scopes[0][2][local['predicate'].id],
            'request_creations': tuple(original['caller_operations'][item['operation'].id]
                                       for item in static['requests']),
            'driver_operations': tuple(scope[2] for scope in scopes),
            'body_outcomes': tuple(row.outcome for row in original['body_drives']),
            'catch': original['caller_operations'][static['catch'].id],
            'final': original['caller_operations'][static['final'].id]})
    details = {**details, 'instances': tuple(examples)}
    if missing_getter_call is not None:
        missing = examples[missing_getter_call]['extra_call_activations']['r2.association']
        model = replace(model, call_activations=tuple(row for row in model.call_activations if row != missing))
    if missing_reject_payload is not None:
        example = examples[missing_reject_payload]
        operation, use = example['reject_terminal'], static['occupancy']['selected_terminal'].terminator.values[0]
        model = replace(model, uses=tuple(row for row in model.uses if (row.operation, row.use) != (operation, use)))
    if missing_resume_transfer is not None:
        source = examples[missing_resume_transfer]['body_drives'][0].outcome
        model = replace(model, transfers=tuple(row for row in model.transfers if row.operation != source))
    return program, model, details


__all__ = ['async_competition_execution']
