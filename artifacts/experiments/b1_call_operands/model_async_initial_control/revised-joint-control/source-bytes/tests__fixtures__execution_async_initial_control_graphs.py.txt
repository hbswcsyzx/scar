"""Actual per-instance ports over the supplied initial-ASEND control graph."""
from dataclasses import replace

from tests.fixtures.native_coroutine_common import capture_program
from tests.fixtures.program_async_initial_control_graphs import async_initial_control_program


def async_initial_control_execution(*, scenario='created-none', reject_raised=False,
                                    instances=2, missing_call=None,
                                    missing_operand=None, missing_initial_transfer=None):
    program, static = async_initial_control_program(scenario=scenario, reject_raised=reject_raised)
    model, details = capture_program(program, static, instances=instances,
                                     label='async.initial.control')
    examples = []
    for example in details['instances']:
        controls = []
        for ordinal, item in enumerate(static['drivers']):
            occurrences = example['driver_scopes'][ordinal][2]
            for row in static['initial_control']['predicates']:
                if row.operation not in occurrences:
                    continue
                branch = occurrences[row.contract.branch]
                transfer, = tuple(transfer for transfer in model.transfers if transfer.operation == branch)
                controls.append({'record': row, 'occurrence': occurrences[row.operation],
                    'branch': branch, 'transfer': transfer, 'driver_ordinal': ordinal})
        examples.append({**example, 'control_predicates': tuple(controls),
            'request_creations': tuple(example['caller_operations'][request['operation'].id]
                                       for request in static['requests'])})
    details = {**details, 'instances': tuple(examples)}
    for requested in (missing_call, missing_operand, missing_initial_transfer):
        if requested is not None and (type(requested) is not int or not 0 <= requested < instances):
            raise ValueError('a missing-capture switch must select an exact instance ordinal')
    if missing_call is not None:
        association = examples[missing_call]['call_activations'][0]
        model = replace(model, call_activations=tuple(row for row in model.call_activations
                                                     if row.id != association.id))
    if missing_operand is not None:
        item = static['drivers'][0]
        formal = item['initial_controls']['operand'].id
        ordinal = item['entry_formals'].index(formal)
        use = item['caller_call'].invoke_arguments[ordinal]
        occurrence = examples[missing_operand]['caller_operations'][item['caller_call'].id]
        model = replace(model, uses=tuple(row for row in model.uses
            if (row.operation, row.use) != (occurrence, use)))
    if missing_initial_transfer is not None:
        example = examples[missing_initial_transfer]
        branch = example['driver_scopes'][0][2][static['drivers'][0]['predicate']['branch']]
        model = replace(model, transfers=tuple(row for row in model.transfers if row.operation != branch))
    return program, model, details
