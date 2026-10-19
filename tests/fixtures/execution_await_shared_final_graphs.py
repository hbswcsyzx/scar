"""Actual copy-loop visits, persistent B, and two callers of shared E/F.

Only caller copy/control visits repeat before the first Drive. Each instance
keeps its original helper Create, one B activation, exact driver calls, and
one selected extractor call into the shared implementation definitions.
"""
from dataclasses import replace

from scar.ir.execution.snapshot import snapshot_for
from scar.ir.program.model import CompletionResult, ExitKind
from tests.fixtures.execution_await_general_final_graphs import await_general_final_execution
from tests.fixtures.execution_await_outcome_graphs import _rebuild
from tests.fixtures.program_await_shared_final_graphs import (
    await_shared_final_program, shared_final_caller_path,
)


def await_shared_final_execution(zero_cut=False, depth=2, case_mode='explicit',
        instances=2, arms=(0, 1), extractor=0, child_raised=False, instance_choices=None,
        missing_helper_call=None, missing_child_call=None, missing_terminal_use=None,
        missing_incoming=None):
    """Return one graph and independent complete or locally missing captures.

    ``instance_choices`` is an exact tuple of dictionaries with optional arms,
    extractor and child_raised keys. Missing child/use coordinates are original
    (instance, parent frame) and (instance, frame, full terminal slot).
    """
    if type(instances) is not int or instances < 1:
        raise ValueError('instances must be a positive exact integer')
    for label, selected in (('missing_helper_call', missing_helper_call),
                            ('missing_incoming', missing_incoming)):
        if selected is not None and (type(selected) is not int or not 0 <= selected < instances):
            raise ValueError(label + ' must select this captured instance')
    for label, item, size in (('missing_child_call', missing_child_call, 2),
                              ('missing_terminal_use', missing_terminal_use, 3)):
        if item is not None and (type(item) is not tuple or len(item) != size
                or any(type(index) is not int or index < 0 for index in item)
                or item[0] >= instances):
            raise ValueError(label + ' must name exact captured coordinates')
    if missing_child_call is not None and missing_child_call[1] >= depth - 1:
        raise ValueError('missing_child_call must select a parent with an actual nested frame')
    if missing_terminal_use is not None and missing_terminal_use[1] >= depth:
        raise ValueError('missing_terminal_use must select an actual implementation frame')
    if instance_choices is not None and (type(instance_choices) is not tuple
            or len(instance_choices) != instances or any(type(item) is not dict
                or set(item) - {'arms', 'extractor', 'child_raised'} for item in instance_choices)):
        raise ValueError('instance_choices must give one exact dictionary per captured instance')
    choices = tuple({'arms': arms, 'extractor': extractor, 'child_raised': child_raised,
        **({} if instance_choices is None else instance_choices[number])} for number in range(instances))
    for item in choices:
        if (type(item['arms']) is not tuple or not item['arms']
                or any(type(arm) is not int or arm not in (0, 1) for arm in item['arms'])):
            raise ValueError('arms must be a nonempty exact tuple of actual branch ordinals')
        if type(item['extractor']) is not int or item['extractor'] not in (0, 1):
            raise ValueError('extractor must select one original callsite')
        if type(item['child_raised']) is not bool:
            raise TypeError('child_raised must be exact bool')
    program, static = await_shared_final_program(zero_cut=zero_cut, depth=depth, case_mode=case_mode)
    _, model, base = await_general_final_execution(zero_cut=zero_cut,
        depth=depth, instances=instances, child_raised=False)
    model = replace(model, snapshot=snapshot_for(program))
    point = base['point']
    shared = static['shared_final']
    blocks = {block.id: block for region in program.regions for block in region.blocks}
    operations = {operation.id: operation for operation in program.operations}
    examples, updates = [], {}

    def occurrence_indexes(visits):
        allowed = set(visits)
        index = {(row.visit, row.operation): row.id for row in model.operations if row.visit in allowed}
        by_site = {}
        for visit in visits:
            block = blocks[next(row.block for row in model.visits if row.id == visit)]
            for site in block.operations:
                occurrence = index[(visit, site)]
                by_site.setdefault(site, []).append(occurrence)
        by_site = {site: tuple(rows) for site, rows in by_site.items()}
        unique = {site: rows[0] for site, rows in by_site.items() if len(rows) == 1}
        return index, by_site, unique

    def exact(by_site, site):
        rows = by_site.get(site, ())
        if len(rows) != 1:
            raise AssertionError('this endpoint requires one exact occurrence, not a static-site choice')
        return rows[0]

    def own_results(occurrence, operation):
        transfer, = tuple(row for row in model.transfers if row.operation == occurrence)
        edge = operation.terminator.successors[transfer.successor_index]
        visit = next(row for row in model.visits if row.id == transfer.target)
        block = blocks[visit.block]
        signature = next(row for row in operation.completions if row.kind is edge.kind)
        values = []
        for slot in range(len(signature.types)):
            formal, = tuple(formal for argument, formal in zip(edge.arguments, block.arguments)
                if type(argument) is CompletionResult and argument.index == slot)
            value, = tuple(row for row in model.values if (row.origin, row.value) == (visit.id, formal))
            values.append(value)
        return transfer, tuple(values)

    for number, (original, selected) in enumerate(zip(base['instances'], choices, strict=True)):
        path = shared_final_caller_path(program, static, arms=selected['arms'],
            extractor=selected['extractor'], child_raised=selected['child_raised'])
        model, caller_visits, _ = _rebuild(program, model, original['caller_activation'],
            static['caller'], path, point)
        caller_index, caller_by_site, caller_unique = occurrence_indexes(caller_visits)
        acquisition = replace(original['acquisition_call'], caller=exact(caller_by_site, static['get'].id))
        updates[acquisition.id] = acquisition
        driver_calls = tuple(replace(call, caller=exact(caller_by_site, item['caller_call'].id))
            for call, item in zip(original['call_activations'], static['drivers'], strict=True))
        updates.update((call.id, call) for call in driver_calls)

        kind = ExitKind.RAISE if selected['child_raised'] else ExitKind.NORMAL
        frames = []
        for old_frame, definition in zip(original['implementation_frames'], static['stage_records'], strict=True):
            model, entered, _ = _rebuild(program, model, old_frame['activation'],
                definition['region'], definition['paths'][kind], point)
            index, by_site, unique = occurrence_indexes(entered)
            frames.append({**old_frame, 'definition': definition, 'visits': entered,
                'operations': unique, 'occurrence_index': index, 'operations_by_site': by_site,
                'entry': entered[0], 'completion': exact(by_site, definition['terminals'][kind].id),
                'terminal': definition['terminals'][kind]})
        extractor_record = shared['extractors'][selected['extractor']]
        extractor_operation = extractor_record['operation']
        extraction = exact(caller_by_site, extractor_operation.id)
        root_call = replace(original['implementation_root_call'], caller=extraction,
            activation=frames[0]['activation'], entry=frames[0]['entry'], completion=frames[0]['completion'])
        updates[root_call.id] = root_call
        nested = []
        for old_call, parent, child in zip(original['implementation_nested_calls'], frames, frames[1:]):
            call = replace(old_call,
                caller=exact(parent['operations_by_site'], parent['definition']['operation'].id),
                activation=child['activation'], entry=child['entry'], completion=child['completion'])
            nested.append(call)
            updates[call.id] = call

        caller_rows = {row.id: row for row in model.visits if row.id in set(caller_visits)}
        arm_blocks = {block.id for block in shared['arms']}
        arm_visits = tuple(visit for visit in caller_visits if caller_rows[visit].block in arm_blocks)
        merge_visits = tuple(visit for visit in caller_visits if caller_rows[visit].block == shared['merge'].id)
        loop_transfers = tuple(next(row for row in model.transfers if row.target == visit) for visit in merge_visits)
        if len(merge_visits) != len(selected['arms']):
            raise AssertionError('the actual trace must retain every supplied arm/merge visit')
        merged = tuple(tuple(next(row for row in model.values if (row.origin, row.value) == (visit, formal))
            for formal in shared['merge'].arguments) for visit in merge_visits)
        final_definition = operations[blocks[path[-1][0]].operations[-1]]
        final = exact(caller_by_site, final_definition.id)
        current_uses = tuple(next(row for row in model.uses if (row.operation, row.use) == (final, identity))
                             for identity in final_definition.terminator.values)
        extractor_transfer, extractor_values = own_results(extraction, extractor_operation)
        examples.append({**original, 'caller_visits': caller_visits, 'caller_operations': caller_unique,
            'caller_occurrence_index': caller_index, 'caller_operations_by_site': caller_by_site,
            'caller_path': path, 'acquisition_call': acquisition, 'acquisition': acquisition.caller,
            'call_activations': driver_calls, 'advance': driver_calls[-1].caller,
            'first_advance': driver_calls[0].caller,
            'decoy_creation': exact(caller_by_site, static['outer_creations'][0].operation),
            'arm_visits': arm_visits, 'merge_visits': merge_visits, 'loop_transfers': loop_transfers,
            'merge_values': merged, 'current_tuple': merged[-1], 'arms': selected['arms'],
            'selected_guard': shared['guards'][selected['arms'][-1]],
            'incoming': loop_transfers[-1], 'extractor': selected['extractor'],
            'extractor_site': extractor_operation.id, 'parent_call': extractor_operation,
            'extractor_record': extractor_record, 'extractor_transfer': extractor_transfer,
            'extractor_values': extractor_values, 'extraction': extraction,
            'implementation_frames': tuple(frames), 'implementation_root_call': root_call,
            'implementation_nested_calls': tuple(nested), 'implementation_kind': kind,
            'child_raised': selected['child_raised'], 'final': final, 'final_definition': final_definition,
            'current_consumer_uses': current_uses,
            'current_consumer_values': tuple(next(row for row in model.values if row.id == use.value)
                                             for use in current_uses)})

    model = replace(model, call_activations=tuple(updates.get(call.id, call) for call in model.call_activations))
    if missing_helper_call is not None:
        omitted = examples[missing_helper_call]['acquisition_call'].id
        model = replace(model, call_activations=tuple(call for call in model.call_activations if call.id != omitted))
    if missing_child_call is not None:
        number, parent = missing_child_call
        omitted = examples[number]['implementation_nested_calls'][parent].id
        model = replace(model, call_activations=tuple(call for call in model.call_activations if call.id != omitted))
    if missing_terminal_use is not None:
        number, frame_number, slot = missing_terminal_use
        frame = examples[number]['implementation_frames'][frame_number]
        terminal = frame['terminal']
        if slot >= len(terminal.terminator.values):
            raise ValueError('missing_terminal_use must select an original full terminal slot')
        identity = terminal.terminator.values[slot]
        model = replace(model, uses=tuple(use for use in model.uses
            if (use.operation, use.use) != (frame['completion'], identity)))
    if missing_incoming is not None:
        omitted = examples[missing_incoming]['incoming']
        model = replace(model, transfers=tuple(transfer for transfer in model.transfers if transfer != omitted))
    return program, model, {**base, 'static': static, 'instances': tuple(examples),
        'adapter_rows': static['final_rows'],
        'implementation_instances': tuple(examples), 'case_mode': case_mode,
        'instance_choices': choices, 'missing_helper_call': missing_helper_call,
        'missing_child_call': missing_child_call, 'missing_terminal_use': missing_terminal_use,
        'missing_incoming': missing_incoming}


__all__ = ['await_shared_final_execution']
