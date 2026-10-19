"""Selected original await completions and finite missing-capture variants.

The same canonical program supports the constructor's and extractor's own N/R
paths. These captures are supplied declarations, not recovered native traces.
"""
from dataclasses import replace

from scar.ir.program.lifecycle import DriveOutcomeRef
from scar.ir.program.model import ExitKind, TerminatorKind
from scar.ir.program.protocols import DriveResult, OutcomeAdapter, OutcomeAdapterRule
from tests.fixtures.execution_await_resume_graphs import await_resume_execution
from tests.fixtures.execution_call_graphs import _activation
from tests.fixtures.program_async_pipeline_graphs import _selected_path


def _replace_activation(model, identity, rows):
    segments = {row.id for row in model.segments if row.activation == identity}
    visits = {row.id for row in model.visits if row.segment in segments}
    operations = {row.id for row in model.operations if row.visit in visits}
    return replace(model,
        activations=tuple(row for row in model.activations if row.id != identity) + tuple(rows['activations']),
        segments=tuple(row for row in model.segments if row.id not in segments) + tuple(rows['segments']),
        visits=tuple(row for row in model.visits if row.id not in visits) + tuple(rows['visits']),
        operations=tuple(row for row in model.operations if row.id not in operations) + tuple(rows['operations']),
        values=tuple(row for row in model.values if row.origin != identity
                     and row.origin not in visits and row.origin not in operations) + tuple(rows['values']),
        uses=tuple(row for row in model.uses if row.operation not in operations) + tuple(rows['uses']),
        transfers=tuple(row for row in model.transfers
                        if row.operation not in operations and row.target not in visits) + tuple(rows['transfers']))


def _choices(program, region, path):
    blocks = {block.id: block for block in region.blocks}
    return {blocks[block].operations[-1]: selected for block, selected in path if selected is not None}


def _rebuild(program, model, identity, region, path, point):
    old_segment, = tuple(row for row in model.segments if row.activation == identity)
    rows, actual, visits, operations = _activation(program, region.id, path,
                                                   identity.value, point, old_segment.host_thread)
    if actual != identity:
        raise AssertionError('replacement must keep this exact original activation identity')
    return _replace_activation(model, identity, rows), visits, operations


def _omit_suffix(program, model, occurrence_id):
    occurrence = next(row for row in model.operations if row.id == occurrence_id)
    visit = next(row for row in model.visits if row.id == occurrence.visit)
    segment_visits = tuple(row for row in model.visits if row.segment == visit.segment)
    position = next(index for index, row in enumerate(segment_visits) if row.id == visit.id)
    block = next(block for region in program.regions for block in region.blocks if block.id == visit.block)
    operation_position = block.operations.index(occurrence.operation)
    omitted_visits = {row.id for row in segment_visits[position + 1:]}
    omitted_operations = {row.id for row in model.operations if row.visit in omitted_visits
        or row.visit == visit.id and block.operations.index(row.operation) >= operation_position}
    omitted_values = {row.id for row in model.values
                      if row.origin in omitted_visits or row.origin in omitted_operations}
    return replace(model,
        visits=tuple(row for row in model.visits if row.id not in omitted_visits),
        operations=tuple(row for row in model.operations if row.id not in omitted_operations),
        values=tuple(row for row in model.values if row.id not in omitted_values),
        uses=tuple(row for row in model.uses if row.operation not in omitted_operations),
        transfers=tuple(row for row in model.transfers
                        if row.operation not in omitted_operations and row.target not in omitted_visits))


def await_outcome_execution(*, zero_cut=False, instances=1, constructor_raised=False,
                           extractor_raised=False, attach_final_adapter=True,
                           missing_use=None, missing_suffix=None,
                           omit_extractor_raise_adapter=False):
    """Return ``(program, model, details)`` without rewriting a canonical port.

    Missing variants identify a root invocation by ordinal. Other invocations
    retain the same static extractor, making cross-instance borrowing visible.
    """
    for value in (constructor_raised, extractor_raised, omit_extractor_raise_adapter):
        if type(value) is not bool:
            raise TypeError('selected completion switches must be exact bools')
    for index in (missing_use, missing_suffix):
        if index is not None and (type(index) is not int or index < 0 or index >= instances):
            raise ValueError('missing capture must select an exact existing instance ordinal')
    program, model, details = await_resume_execution(zero_cut=zero_cut, instances=instances,
        attach_final_adapter=attach_final_adapter)
    static = details['static']
    last = static['drivers'][-1]
    outcome = DriveOutcomeRef(last['drive'].operation, last['outcome_source'])
    payload = DriveResult(outcome, 0)
    producer_ids = tuple(dict.fromkeys(row.operation for row in program.protocol_operations
        if type(row.contract) is OutcomeAdapter and row.contract.input == payload
        and row.contract.rule in (OutcomeAdapterRule.GENERATOR_RETURN_TO_STOP_ITERATION,
                                  OutcomeAdapterRule.COROUTINE_RETURN_TO_STOP_ITERATION)))
    if len(producer_ids) != 1:
        raise AssertionError('the exact final BodyReturn has one original conversion operation')
    operations = {row.id: row for row in program.operations}
    blocks = {block.id: block for region in program.regions for block in region.blocks}
    conversion = operations[producer_ids[0]]
    extraction = static['extract']
    omitted_final_rows = ()
    if omit_extractor_raise_adapter:
        from scar.ir.execution.snapshot import snapshot_for
        from scar.ir.program.protocol_connections import ProtocolOperationRef

        omitted_final_rows = tuple(row for row in program.protocol_operations
            if type(row.contract) is OutcomeAdapter and row.operation == extraction.id
            and row.contract.rule is OutcomeAdapterRule.AWAIT_STOPITER_TO_EXPRESSION
            and extraction.terminator.successors[row.slot].kind is ExitKind.RAISE)
        if not omitted_final_rows:
            raise ValueError('omitting the final RAISE adapter requires that original adapter')
        sites = tuple(ProtocolOperationRef(row.scope, row.clause, row.operation, row.slot)
                      for row in omitted_final_rows)
        program = replace(program,
            protocol_operations=tuple(row for row in program.protocol_operations if row not in omitted_final_rows),
            protocol_result_consumers=tuple(row for row in program.protocol_result_consumers if row.site not in sites))
        model = replace(model, snapshot=snapshot_for(program))
    examples = []
    for example in details['instances']:
        example = dict(example)
        driver_scopes = list(example['driver_scopes'])
        calls = list(example['call_activations'])
        if constructor_raised:
            identity, _, _ = driver_scopes[-1]
            choices = _choices(program, last['driver_region'], last['path'])
            selected = next(index for index, edge in enumerate(conversion.terminator.successors)
                            if edge.kind is ExitKind.RAISE)
            choices[conversion.id] = selected
            path = _selected_path(program, last['driver_region'], choices)
            model, visits, mapping = _rebuild(program, model, identity, last['driver_region'], path,
                                             details['point'])
            terminal = operations[blocks[path[-1][0]].operations[-1]]
            if terminal.terminator.kind is not TerminatorKind.RAISE:
                raise AssertionError('constructor failure must keep the real selected host RAISE')
            old = calls[-1]
            current = replace(old, completion=mapping[terminal.id])
            model = replace(model, call_activations=tuple(current if row == old else row
                                                         for row in model.call_activations))
            calls[-1] = current
            driver_scopes[-1] = (identity, visits, mapping)
        if extractor_raised:
            choices = _choices(program, static['caller'], static['caller_path'])
            selected = next(index for index, edge in enumerate(extraction.terminator.successors)
                            if edge.kind is ExitKind.RAISE)
            choices[extraction.id] = selected
            path = _selected_path(program, static['caller'], choices)
            model, visits, mapping = _rebuild(program, model, example['caller_activation'],
                                             static['caller'], path, details['point'])
            example.update(caller_visits=visits, caller_operations=mapping,
                           extraction=mapping[extraction.id],
                           final=mapping[blocks[path[-1][0]].operations[-1]])
        example['driver_scopes'] = tuple(driver_scopes)
        example['call_activations'] = tuple(calls)
        example['advance'] = calls[-1].caller
        example['conversion'] = driver_scopes[-1][2][conversion.id]
        example['driver_terminal'] = calls[-1].completion
        example['body_outcome'] = example['body_drives'][-1].outcome
        examples.append(example)

    missing_binding = None
    if missing_use is not None:
        example = examples[missing_use]
        missing_binding, = tuple(row for row in model.uses if row.operation == example['extraction']
                                  and row.use == static['extract_input'].use)
        model = replace(model, uses=tuple(row for row in model.uses if row != missing_binding))
    if missing_suffix is not None:
        model = _omit_suffix(program, model, examples[missing_suffix]['extraction'])
    return program, model, {**details, 'instances': tuple(examples), 'drive_outcome': outcome,
        'conversion': conversion, 'constructor_raised': constructor_raised,
        'extractor_raised': extractor_raised, 'missing_use': missing_use,
        'missing_suffix': missing_suffix, 'missing_binding': missing_binding,
        'omitted_final_rows': omitted_final_rows}


__all__ = ['await_outcome_execution']
