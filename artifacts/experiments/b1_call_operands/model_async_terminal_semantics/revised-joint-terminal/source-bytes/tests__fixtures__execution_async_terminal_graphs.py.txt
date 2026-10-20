"""Exact captures of the supplied body-local async termination intrinsic."""
from dataclasses import replace

from scar.ir.program.model import StateVersionValue
from scar.ir.program.state_addresses import ExistingAccess, ReferenceOwner
from tests.fixtures.native_coroutine_common import capture_program
from tests.fixtures.program_async_terminal_graphs import async_terminal_program


def _state_use(program, operation):
    values = {row.id: row for row in program.values}
    return next(use for use in operation.uses if use.id in operation.invoke_arguments
                and type(values[use.value]) is StateVersionValue)


def async_terminal_execution(*, route='stop-iteration', instances=2,
                             missing_intrinsic_call=None, missing_constructor_input=None,
                             missing_chaining_owner=None, missing_driver_input=None):
    program, static = async_terminal_program(route=route)
    intrinsic = static['intrinsic']
    terminal = intrinsic['completion']
    model, details = capture_program(program, static, instances=instances,
        label='async.terminal', body_paths=static['body_paths'], extra_calls=({
            'label': 'terminal.intrinsic', 'parent': ('body', 1),
            'caller': intrinsic['call'].id, 'region': intrinsic['region'].id,
            'path': intrinsic['path'], 'completion': terminal.id},))
    examples = []
    for example in details['instances']:
        scope = example['extra_scopes']['terminal.intrinsic']
        operations = scope[2]
        examples.append({**example, 'terminal': {
            'activation': scope[0], 'visits': scope[1], 'operations': operations,
            'association': example['extra_call_activations']['terminal.intrinsic'],
            'body_call': example['body_scopes'][1][2][intrinsic['call'].id],
            'matchers': tuple((row, operations[row.operation], operations[row.branch])
                              for row in intrinsic['matchers'] if row.operation in operations),
            'constructor': operations.get(intrinsic['constructor'].id),
            'chaining': tuple(operations[row.id] for row in intrinsic['chaining'] if row.id in operations),
            'completion': operations[terminal.id], 'body_raise': example['body_drives'][1].outcome,
            'host': example['driver_scopes'][1][2][static['drivers'][1]['host_terminal'].id]}})
    details = {**details, 'instances': tuple(examples)}
    for ordinal in (missing_intrinsic_call, missing_constructor_input,
                    missing_chaining_owner, missing_driver_input):
        if ordinal is not None and (type(ordinal) is not int or not 0 <= ordinal < instances):
            raise ValueError('missing capture must select an exact instance ordinal')
    if missing_intrinsic_call is not None:
        association = examples[missing_intrinsic_call]['terminal']['association']
        model = replace(model, call_activations=tuple(row for row in model.call_activations
                                                     if row.id != association.id))
    if missing_constructor_input is not None:
        occurrence = examples[missing_constructor_input]['terminal']['constructor']
        if occurrence is None:
            raise ValueError('the selected route has no actual constructor')
        use = _state_use(program, intrinsic['constructor'])
        model = replace(model, uses=tuple(row for row in model.uses
            if (row.operation, row.use) != (occurrence, use.id)))
    if missing_chaining_owner is not None:
        example = examples[missing_chaining_owner]
        operation = next((row for row in intrinsic['chaining']
                          if row.id in example['terminal']['operations']), None)
        if operation is None:
            raise ValueError('the selected route has no actual chaining write')
        owner = next(effect.owner.use for row in program.state_address_refinements
            if type(row.site) is ExistingAccess and row.site.operation == operation.id
            for effect in row.effects if type(effect.owner) is ReferenceOwner)
        occurrence = example['terminal']['operations'][operation.id]
        model = replace(model, uses=tuple(row for row in model.uses
            if (row.operation, row.use) != (occurrence, owner)))
    if missing_driver_input is not None:
        driver = static['drivers'][1]
        use = _state_use(program, driver['caller_call'])
        occurrence = examples[missing_driver_input]['caller_operations'][driver['caller_call'].id]
        model = replace(model, uses=tuple(row for row in model.uses
            if (row.operation, row.use) != (occurrence, use.id)))
    return program, model, details
