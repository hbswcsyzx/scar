"""This actual BodyRaise and this synchronous D cleanup share original ports.

The existing capture supplies B's two C1 cuts, actual Raise, acquisition and
caller. Changed D/caller regions are recaptured from their full new paths; all
affected CallActivation/BodyDriveExecution endpoints are updated explicitly.
"""
from dataclasses import replace

from scar.ir.execution.common import Unresolved
from scar.ir.execution.snapshot import snapshot_for
from scar.ir.program.drivers import BodyDriveResult
from scar.ir.program.model import OperationResult
from tests.fixtures.execution_await_cleanup_final_graphs import await_cleanup_final_execution
from tests.fixtures.execution_await_outcome_graphs import _omit_suffix, _rebuild
from tests.fixtures.program_await_raise_cleanup_graphs import add_driver_raise_cleanup


def await_raise_cleanup_execution(mode='preserve', instances=2, missing_payload_use=None,
                                   missing_dispatch=None, missing_driver_call=None):
    """Return supplied occurrences, with missing evidence local to one instance.

    The pending fields name D's new active token, not B's distinct pending token
    from the two-cut capture. The original body evidence is retained under
    ``body_pending_*``. No D resumption or fictitious converter is introduced.
    """
    if type(instances) is not int or instances < 1:
        raise ValueError('instances must be a positive exact integer')
    for ordinal in (missing_payload_use, missing_dispatch, missing_driver_call):
        if ordinal is not None and (type(ordinal) is not int or not 0 <= ordinal < instances):
            raise ValueError('missing evidence selects an exact captured instance')
    original, model, base = await_cleanup_final_execution(body_raised=True, instances=instances)
    program, static = add_driver_raise_cleanup(original, base['static'], mode=mode)
    model = replace(model, snapshot=snapshot_for(program))
    cleanup = static['raise_cleanup']
    selected_definition = cleanup['replacement_pending'] or cleanup['pending']
    values = {value.id: value for value in program.values}
    constructor = values[selected_definition.value].origin
    primary_constructor = values[cleanup['pending'].value].origin
    if type(constructor) is not OperationResult or type(primary_constructor) is not OperationResult:
        raise AssertionError('each selected token must retain its own canonical constructor')
    driver = cleanup['driver_region']
    terminal, = cleanup['terminals']
    examples = []

    for instance, original_example in enumerate(base['instances']):
        example = dict(original_example)
        caller_operations = example['caller_operations']
        if mode == 'replace_return':
            old_caller_operations = caller_operations
            model, visits, caller_operations = _rebuild(program, model,
                example['caller_activation'], static['caller'], static['caller_path'], base['point'])
            by_occurrence = {occurrence: site for site, occurrence in old_caller_operations.items()}
            call_updates = {}
            for association in model.call_activations:
                site = by_occurrence.get(association.caller)
                if site is not None:
                    if site not in caller_operations:
                        raise AssertionError('the supplied new caller path cannot retain an unexecuted child association')
                    call_updates[association.id] = replace(association, caller=caller_operations[site])
            model = replace(model,
                call_activations=tuple(call_updates.get(row.id, row) for row in model.call_activations),
                body_activation_origins=tuple(replace(row,
                    creation=caller_operations[static['primary_creation'].operation])
                    if row.activation == example['body_activation'] else row
                    for row in model.body_activation_origins))
            example.update(caller_visits=visits, caller_operations=caller_operations,
                creation=caller_operations[static['primary_creation'].operation],
                body_origin=next(row for row in model.body_activation_origins
                                 if row.activation == example['body_activation']))

        driver_scopes = list(example['driver_scopes'])
        activation, _, old_driver_operations = driver_scopes[-1]
        model, visits, driver_operations = _rebuild(program, model, activation,
            driver, static['drivers'][-1]['path'], base['point'])
        driver_scopes[-1] = activation, visits, driver_operations
        old_drive = example['body_drives'][-1]
        current_drive = replace(old_drive, drive=driver_operations[cleanup['drive'].operation])
        model = replace(model, body_drive_executions=tuple(current_drive if row.drive == old_drive.drive else row
                                                         for row in model.body_drive_executions))
        old_association = example['call_activations'][-1]
        association = next(row for row in model.call_activations if row.id == old_association.id)
        association = replace(association, caller=caller_operations[static['drivers'][-1]['caller_call'].id],
            entry=visits[0], completion=driver_operations[terminal.id])
        model = replace(model, call_activations=tuple(association if row.id == association.id else row
                                                    for row in model.call_activations))
        instance_calls = tuple(next(row for row in model.call_activations if row.id == old.id)
                               for old in example['call_activations'])
        instance_drives = (*example['body_drives'][:-1], current_drive)
        root_call = next(row for row in model.operations if row.id == association.caller)
        if root_call.operation != static['advance_operation']:
            raise AssertionError('the self capture must retain its precise original advance site')
        final_block = next(block for block in static['caller'].blocks
                           if block.id == static['caller_path'][-1][0])
        final_definition = next(operation for operation in program.operations
                                if operation.id == final_block.operations[-1])
        transfer, = tuple(row for row in model.transfers
                          if row.operation == driver_operations[cleanup['drive'].operation])
        drive_definition = next(operation for operation in program.operations
                                if operation.id == cleanup['drive'].operation)
        edge = drive_definition.terminator.successors[transfer.successor_index]
        if edge.source != static['drive_outcome'].source:
            raise AssertionError('this Drive must select the actual BodyRaise source')
        landing = next(block for block in driver.blocks if block.id == edge.block)
        formal, = tuple(formal for argument, formal in zip(edge.arguments, landing.arguments)
                         if type(argument) is BodyDriveResult and argument.index == 0)
        root_value, = tuple(value for value in model.values
                            if value.origin == transfer.target and value.value == formal)
        examples.append({**example, 'driver_scopes': tuple(driver_scopes),
            'call_activations': instance_calls, 'body_drives': instance_drives,
            'advance': association.caller, 'body_outcome': current_drive.outcome,
            'driver_activation': activation, 'driver_operations': driver_operations,
            'driver_visits': visits, 'driver_terminal': association.completion,
            'driver_call': association, 'driver_root_value': root_value,
            'body_pending_constructor': example['pending_constructor'],
            'body_pending_definition': example['pending_definition'],
            'body_pending_payload_use': example['pending_payload_use'],
            'body_dispatch': example['dispatch'],
            'pending_definition': selected_definition,
            'pending_constructor': driver_operations[constructor.operation],
            'pending_payload_use': selected_definition.payload,
            'primary_pending_constructor': driver_operations[primary_constructor.operation],
            'primary_pending_definition': cleanup['pending'],
            'dispatch': driver_operations[cleanup['dispatch'].id],
            'cleanup_actions': tuple(driver_operations[operation.id] for operation in cleanup['action_operations']),
            'final': caller_operations[final_definition.id], 'final_definition': final_definition,
            'extraction': None})

    if missing_payload_use is not None:
        example = examples[missing_payload_use]
        model = replace(model, uses=tuple(row for row in model.uses
            if (row.operation, row.use) != (example['pending_constructor'], example['pending_payload_use'])))
    if missing_dispatch is not None:
        example = examples[missing_dispatch]
        model = _omit_suffix(program, model, example['dispatch'])
        call = example['driver_call']
        model = replace(model, call_activations=tuple(replace(row,
            completion=Unresolved('this instance D dispatch and completion were not captured', base['point']))
            if row.id == call.id else row for row in model.call_activations))
    if missing_driver_call is not None:
        selected = examples[missing_driver_call]['driver_call'].id
        model = replace(model, call_activations=tuple(row for row in model.call_activations if row.id != selected))
    return program, model, {**base, 'static': static, 'instances': tuple(examples),
        'mode': mode, 'drive_outcome': static['drive_outcome'], 'missing_payload_use': missing_payload_use,
        'missing_dispatch': missing_dispatch, 'missing_driver_call': missing_driver_call}


__all__ = ['await_raise_cleanup_execution']
