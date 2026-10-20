"""Exact finished-frame/new-request captures; no additional body segment."""
from dataclasses import replace

from tests.fixtures.native_coroutine_common import capture_program
from tests.fixtures.program_async_finished_requests_graphs import async_finished_requests_program


def async_finished_requests_execution(*, terminal='return', request='throw',
                                      constructor_raised=False, retry=False,
                                      instances=2, missing_call=None,
                                      missing_constructor_state=None):
    program, static = async_finished_requests_program(terminal=terminal, request=request,
        constructor_raised=constructor_raised, retry=retry)
    finished = static['finished_request']
    extra = []
    if terminal == 'raise':
        intrinsic = static['intrinsic']
        extra.append({'label': 'terminal.intrinsic', 'parent': ('body', 1),
            'caller': intrinsic['call'].id, 'region': intrinsic['region'].id,
            'path': intrinsic['path'], 'completion': intrinsic['completion'].id})
    for ordinal, (call, path, host) in enumerate(zip(finished['caller_calls'], finished['paths'],
                                                   finished['selected_hosts'], strict=True)):
        extra.append({'label': f'finished.request.{ordinal}', 'parent': 'caller',
            'caller': call.id, 'region': finished['region'].id, 'path': path,
            'completion': host.id})
    model, details = capture_program(program, static, instances=instances,
        label='async.finished.request', body_paths=static.get('body_paths'), extra_calls=tuple(extra))
    examples = []
    for example in details['instances']:
        attempts = []
        for ordinal, call in enumerate(finished['caller_calls']):
            label = f'finished.request.{ordinal}'
            activation, visits, operations = example['extra_scopes'][label]
            attempts.append({'activation': activation, 'visits': visits, 'operations': operations,
                'call': example['extra_call_activations'][label],
                'caller': example['caller_operations'][call.id],
                'request_predicate': operations[finished['request_predicate'].id],
                'body_predicate': operations.get(finished['predicate'].id),
                'association': operations.get(finished['association'].id),
                'complete': operations.get(finished['complete'].id),
                'constructor': operations[(finished['reuse_constructor'] if ordinal else finished['constructor']).id],
                'host': operations[finished['selected_hosts'][ordinal].id]})
        examples.append({**example, 'finished_requests': tuple(attempts),
            'new_request_creation': example['caller_operations'][finished['request_operation'].id],
            'final': example['caller_operations'][finished['caller_terminal'].id]})
    for selected in (missing_call, missing_constructor_state):
        if selected is not None and (type(selected) is not int or not 0 <= selected < instances):
            raise ValueError('missing capture selects one exact instance')
    if missing_call is not None:
        association = examples[missing_call]['finished_requests'][0]['call']
        model = replace(model, call_activations=tuple(row for row in model.call_activations
                                                     if row.id != association.id))
    if missing_constructor_state is not None:
        example = examples[missing_constructor_state]['finished_requests'][0]
        constructor = finished['constructor']
        # Original constructor inputs are (R, *all current state domains).
        use = constructor.invoke_arguments[1]
        model = replace(model, uses=tuple(row for row in model.uses
            if (row.operation, row.use) != (example['constructor'], use)))
    return program, model, {**details, 'instances': tuple(examples)}


__all__ = ['async_finished_requests_execution']
