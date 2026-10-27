"""One Create, one B, two visits of the same acquisition operation.

The latest/earlier choice is an original CFG copy, not a timestamp or a common
B identity.  The known acquisition callee returns its input on its sole actual
NORMAL exit.  The original zero-cut body and final E/F consumer remain real.
These supplied captures grant no native, runtime or value-identity authority.
"""
from dataclasses import replace
from copy import deepcopy

import pytest

from scar.ir.execution.calls import CallActivation
from scar.ir.execution.common import EvidencePoint, MissingEvidence
from scar.ir.execution.coordinates import (
    ExecutionRun, HostThreadInstance, ProcessInstance,
)
from scar.ir.execution.ids import (
    CallActivationID, HostThreadInstanceID, ProcessInstanceID, RunID,
)
from scar.ir.execution.model import ExecutionModel
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.resumables import BodyActivationOrigin, BodyDriveExecution
from scar.ir.execution.snapshot import snapshot_for
from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.execution.validation import validate
from scar.ir.program.ids import BlockID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.lifecycle import DriveOutcomeRef
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, CompletionResult, CompletionSuccessor,
    DataValue, ExitKind, ExitPort, InvokeLiteralResult, Operation,
    OperationResult, ProgramGraph, ProtocolValue, Region, StateVersionValue, Successor,
    Terminator, TerminatorKind, Use, UseRole, ValueKind, ValueType,
)
from scar.ir.program.protocol_connections import ProtocolOperationRef, RawRequestTrigger
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.protocols import ContractResult, DriveResult, OwnedUse
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_async_pipeline_graphs import _body_path
from tests.fixtures.execution_call_graphs import _activation
from tests.fixtures.program_await_final_region_graphs import await_final_region_program
from tests.fixtures.program_await_resume_graphs import await_resume_program, with_final_adapter
from tests.fixtures.program_protocol_graphs import _scope


_BUDGET = 4_194_304
_TABLES = ('activations', 'segments', 'visits', 'operations', 'values', 'uses', 'transfers')
_FLAGS = ('source_runtime_verified', 'runtime_identity_verified',
          'value_identity_verified', 'transformation_authorized')


def _use(name, value):
    role = (UseRole.STATE_CONTENT if type(value) is StateVersionValue else
            UseRole.PROTOCOL if type(value) is ProtocolValue else
            UseRole.DATA if type(value) is DataValue else UseRole.REFERENCE)
    return Use(UseID(name), value.id, role)


def _source_visit_program(iterator_origin):
    """Add a two-visit Get loop before the original single body Start.

    The previous-iterator carrier has its own BlockArgument.  At the real
    backedge it receives Get0's own result.  It crosses Get1 only as a separate
    forward, never as Get1's CompletionResult or identity-callee argument.
    """
    if iterator_origin not in ('latest', 'earlier'):
        raise ValueError('the iterator must select one of the two original results')
    base, original = await_resume_program(zero_cut=True, extra_creation=False)
    base, final_rows = with_final_adapter(base, original)
    template, implementation = await_final_region_program(zero_cut=True, depth=2)
    original_extract = original['extract']
    assert (original_extract.uses, original_extract.terminator, original_extract.completions) == (
        implementation['original_extract'].uses, implementation['original_extract'].terminator,
        implementation['original_extract'].completions)

    # Graft only the existing implementation regions and exact producer
    # receipts. The template's second Create/caller is deliberately not copied.
    stage_ids = {region.id for region in implementation['stage_regions']}
    stage_blocks = {block.id for region in implementation['stage_regions'] for block in region.blocks}
    stage_ops = {identity for region in implementation['stage_regions']
                 for block in region.blocks for identity in block.operations}
    parent_call = replace(original_extract, callee=implementation['parent_call'].callee)
    base = replace(base,
        regions=(*base.regions, *(region for region in template.regions if region.id in stage_ids)),
        operations=tuple(parent_call if operation.id == parent_call.id else operation
                         for operation in base.operations) + tuple(
                             operation for operation in template.operations if operation.id in stage_ops),
        values=(*base.values, *(value for value in template.values if value.region in stage_ids)),
        control_scopes=(*base.control_scopes, *(scope for scope in template.control_scopes
                                              if scope.region in stage_ids)),
        protocol_result_consumers=(*base.protocol_result_consumers,
                                   *implementation['conversion_receipts']))
    assert stage_blocks
    caller = original['caller']
    blocks = {block.id: block for block in caller.blocks}
    operations = {operation.id: operation for operation in base.operations}
    values = {value.id: value for value in base.values}
    get = original['get']
    normal_index, normal_edge = next((index, edge) for index, edge in
        enumerate(get.terminator.successors) if edge.kind is ExitKind.NORMAL)
    failure_index, failure_edge = next((index, edge) for index, edge in
        enumerate(get.terminator.successors) if edge.kind is ExitKind.RAISE)
    assert normal_index == 0 and failure_index == 1
    normal_signature, = tuple(signature for signature in get.completions
                              if signature.kind is ExitKind.NORMAL)
    old_landing = blocks[normal_edge.block]
    assert len(old_landing.arguments) == 4
    landed = tuple(values[identity] for identity in old_landing.arguments)
    get_block = next(block for block in caller.blocks if get.id in block.operations)
    assert get_block.operations == (get.id,)
    created_inputs = tuple(values[identity] for identity in get_block.arguments)
    assert len(created_inputs) == 3
    additions = {name: [] for name in ('values', 'operations', 'blocks')}

    def formals(identity, templates):
        rows = tuple(replace(value, id=ValueID(f'{identity.value}.argument.{slot}'),
            region=caller.id, origin=BlockArgument(identity, slot))
            for slot, value in enumerate(templates))
        additions['values'].extend(rows)
        return rows

    def add(operation):
        additions['operations'].append(operation)
        return operation

    def jump(name, target, actuals):
        uses = tuple(_use(f'{name}.argument.{slot}', value)
                     for slot, value in enumerate(actuals))
        return add(Operation(OperationID(name), 'forward the original current tuple',
            (Behavior.CONTROL,), uses, effects_complete=True,
            terminator=Terminator(TerminatorKind.JUMP,
                (Successor(target, tuple(use.id for use in uses)),))))

    entry = blocks[caller.entry]
    counter = DataValue(ValueID('await.visits.initial.counter'), caller.id,
                       BlockArgument(entry.id, len(entry.arguments)), 'builtins.int')
    additions['values'].append(counter)
    blocks[entry.id] = replace(entry, arguments=(*entry.arguments, counter.id))
    header_id, landing_id = BlockID('await.visits.header'), BlockID('await.visits.acquired')
    header = formals(header_id, (*created_inputs, created_inputs[0], counter))
    # header = owner B, current W, current C, previous own iterator, counter.
    previous = header[3]
    decision_op = OperationID('await.visits.decision')
    decision = DataValue(ValueID('await.visits.continue'), caller.id,
                         OperationResult(decision_op, 0), 'builtins.bool')
    next_counter = DataValue(ValueID('await.visits.next.counter'), caller.id,
                            OperationResult(decision_op, 1), 'builtins.int')
    additions['values'].extend((decision, next_counter))
    choose = add(Operation(decision_op, 'supplied finite loop control on this visit',
        (Behavior.COMPUTE,), (_use('await.visits.counter.read', header[4]),),
        (decision.id, next_counter.id), effects_complete=True))
    # This result tuple keeps the full logical slots and independent forwards.
    # own Reference slot zero is formal zero, previous is formal four.
    landing = formals(landing_id, (*landed, previous, decision, next_counter))
    assert len(landing) == 7
    old_actuals = tuple(next(use for use in get.uses if use.id == identity)
                        for identity in get.invoke_arguments)
    actuals = tuple(replace(use, value=value.id)
                    for use, value in zip(old_actuals, header[:3], strict=True))
    body_forward, = tuple(use for use in get.uses if use.id not in get.invoke_arguments)
    body_forward = replace(body_forward, value=header[0].id)
    previous_forward = _use('await.visits.get.forward.previous', previous)
    decision_forward = _use('await.visits.get.forward.decision', decision)
    counter_forward = _use('await.visits.get.forward.counter', next_counter)
    edge_arguments = (CompletionResult(0), body_forward.id, CompletionResult(1),
                      CompletionResult(2), previous_forward.id,
                      decision_forward.id, counter_forward.id)

    identity_region = RegionID('await.visits.identity')
    identity_entry = BlockID('await.visits.identity.entry')
    identity_inputs = tuple(replace(value, id=ValueID(f'await.visits.identity.input.{slot}'),
        region=identity_region, origin=BlockArgument(identity_entry, slot))
        for slot, value in enumerate(header[:3]))
    identity_uses = tuple(_use(f'await.visits.identity.return.{slot}', value)
                          for slot, value in enumerate(identity_inputs))
    identity_terminal = Operation(OperationID('await.visits.identity.return'),
        'known identity callee returns these exact original inputs', (Behavior.CONTROL,),
        identity_uses, effects_complete=True,
        terminator=Terminator(TerminatorKind.RETURN, exit='normal',
                              values=tuple(use.id for use in identity_uses)))
    identity_block = Block(identity_entry, tuple(value.id for value in identity_inputs),
                           (identity_terminal.id,))
    identity = Region(identity_region, 'known identity acquisition implementation',
        identity_entry, (identity_block,), (ExitPort('normal', ExitKind.NORMAL, normal_signature.types),),
        parent=caller.id)
    get = replace(get, callee=identity.id, uses=(*actuals, body_forward, previous_forward,
        decision_forward, counter_forward), completions=(normal_signature,),
        terminator=Terminator(TerminatorKind.INVOKE,
            (CompletionSuccessor(ExitKind.NORMAL, landing_id, edge_arguments),)))
    into = jump('await.visits.enter', header_id,
                (*created_inputs, created_inputs[0], counter))
    blocks[get_block.id] = replace(get_block, operations=(into.id,))
    groups = (
        (landing[1], landing[2], landing[3], landing[0], landing[6]),
        (landing[0] if iterator_origin == 'latest' else landing[4],
         landing[1], landing[2], landing[3]),
    )
    condition = _use('await.visits.retry.condition', landing[5])
    forwarded = tuple(tuple(_use(f'await.visits.retry.{arm}.{slot}', value)
        for slot, value in enumerate(group)) for arm, group in enumerate(groups))
    retry = add(Operation(OperationID('await.visits.retry'),
        'first visit saves its own result; second visit advances once',
        (Behavior.CONTROL,), (condition, *forwarded[0], *forwarded[1]), effects_complete=True,
        terminator=Terminator(TerminatorKind.BRANCH, (
            Successor(header_id, tuple(use.id for use in forwarded[0])),
            Successor(old_landing.id, tuple(use.id for use in forwarded[1]))),
            condition=condition.id)))
    additions['blocks'].extend((
        Block(header_id, tuple(value.id for value in header), (choose.id, get.id)),
        Block(landing_id, tuple(value.id for value in landing), (retry.id,))))
    dropped_operations = set(blocks[failure_edge.block].operations)
    del blocks[failure_edge.block]
    caller = replace(caller, blocks=(*blocks.values(), *additions['blocks']))
    normal_row, = tuple(row for row in original['get_rows'] if row.slot == normal_index)
    normal_row = replace(normal_row, contract=replace(normal_row.contract,
        expected=header[0].origin))
    dropped_sites = {ProtocolOperationRef(row.scope, row.clause, row.operation, row.slot)
                     for row in original['get_rows'] if row.slot == failure_index}
    first_advance = original['calls'][0]
    raw_next = OwnedUse(first_advance.id, first_advance.invoke_arguments[1])
    inputs = tuple(replace(attachment, cases=tuple(replace(case, receiver=previous.origin,
        trigger=RawRequestTrigger(raw_next))
        for case in attachment.cases))
        if iterator_origin == 'earlier' and attachment.site.operation == first_advance.id
        else attachment for attachment in base.protocol_call_inputs)
    normal_site = ProtocolOperationRef(normal_row.scope, normal_row.clause,
                                       normal_row.operation, normal_row.slot)
    # This receipt describes this Get visit's real own-result save. The later
    # advance independently consumes the previous carrier, not a current Get
    # result; its real NEXT trigger does not make that false freshness claim.
    consumers = tuple(replace(receipt,
        targets=(OwnedUse(retry.id, forwarded[0][3].id),))
        if iterator_origin == 'earlier' and receipt.site == normal_site else receipt
        for receipt in base.protocol_result_consumers if receipt.site not in dropped_sites)
    graph = replace(base,
        regions=tuple(caller if region.id == caller.id else region for region in base.regions) + (identity,),
        operations=tuple(get if operation.id == get.id else operation for operation in base.operations
                         if operation.id not in dropped_operations) + tuple(additions['operations']) + (identity_terminal,),
        values=tuple(value for value in base.values
            if not (type(value.origin) is BlockArgument and value.origin.block == failure_edge.block))
            + tuple(additions['values']) + identity_inputs,
        control_scopes=tuple(replace(scope, blocks=tuple(block.id for block in caller.blocks))
            if scope.region == caller.id else scope for scope in base.control_scopes)
            + (_scope(identity.id, identity.blocks),),
        protocol_operations=tuple(normal_row if row.operation == get.id else row
            for row in base.protocol_operations if not (row.operation == get.id and row.slot == failure_index)),
        protocol_call_inputs=inputs,
        protocol_result_consumers=consumers)
    source = ProtocolOperationRef(normal_row.scope, normal_row.clause,
                                  normal_row.operation, normal_row.slot)
    driver = original['drivers'][0]
    drive_outcome = DriveOutcomeRef(driver['drive'].operation, driver['outcome_source'])
    old_path = original['caller_path']
    index = next(number for number, (block, _edge) in enumerate(old_path) if block == get_block.id)
    path = (*old_path[:index], (get_block.id, 0),
        (header_id, 0), (landing_id, 0), (header_id, 0), (landing_id, 1),
        *old_path[index + 1:])
    return graph, {**original, 'caller': caller, 'caller_path': path,
        'get': get, 'get_rows': (normal_row,), 'source': source,
        'extract': parent_call, 'parent_call': parent_call, 'final_rows': final_rows,
        'drive_outcome': drive_outcome, 'payload': DriveResult(drive_outcome, 0),
        'advance_operation': first_advance.id,
        'stage_records': implementation['stage_records'],
        'primitive': implementation['primitive'],
        'identity_region': identity, 'identity_terminal': identity_terminal,
        'identity_inputs': identity_inputs, 'header': header, 'landing': landing,
        'previous': previous.origin, 'previous_forward': previous_forward,
        'retry': retry, 'iterator_origin': iterator_origin}


def _source_visit_execution(*, iterator_origin='latest', missing=None):
    program, static = _source_visit_program(iterator_origin)
    source = MissingEvidence('supplied repeated acquisition visits; no runtime/native identity proof')
    run, process, thread = (RunID('await.visits'), ProcessInstanceID('await.visits'),
                            HostThreadInstanceID('await.visits'))
    point = EvidencePoint(run, process, source)
    combined = {name: [] for name in _TABLES}

    def append(rows):
        for name in _TABLES:
            combined[name].extend(rows[name])

    caller_rows, caller, visits, caller_map = _activation(program,
        static['caller'].id, static['caller_path'], 'await.visits.caller', point, thread)
    append(caller_rows)
    get_occurrences = tuple(row for row in caller_rows['operations'] if row.operation == static['get'].id)
    assert len(get_occurrences) == 2
    get_transfers = tuple(next(row for row in caller_rows['transfers'] if row.operation == occurrence.id)
                          for occurrence in get_occurrences)
    get_values = tuple(next(row for row in caller_rows['values']
        if row.origin == transfer.target and row.value == static['landing'][0].id)
        for transfer in get_transfers)
    identity_calls = []
    for number, acquisition in enumerate(get_occurrences):
        rows, activation, entries, mapping = _activation(program, static['identity_region'].id,
            ((static['identity_region'].entry, None),),
            f'await.visits.identity.{number}', point, thread)
        append(rows)
        identity_calls.append(CallActivation(CallActivationID(f'await.visits.identity.{number}'),
            acquisition.id, activation, entries[0], mapping[static['identity_terminal'].id], source))

    driver, = static['drivers']
    driver_rows, driver_activation, driver_visits, driver_map = _activation(program,
        driver['driver_region'].id, driver['path'], 'await.visits.driver', point, thread)
    append(driver_rows)
    driver_call = CallActivation(CallActivationID('await.visits.advance'),
        caller_map[driver['caller_call'].id], driver_activation, driver_visits[0],
        driver_map[driver['host_terminal'].id], source)
    body = static['body']
    body_path = _body_path(program, body, body.entry, driver['outcome_source'])
    body_rows, body_activation, body_visits, body_map = _activation(program,
        body.id, body_path, 'await.visits.body', point, thread)
    append(body_rows)
    drive = BodyDriveExecution(driver_map[driver['drive'].operation], body_activation,
        body_visits[0], body_map[driver['outcome_source']], source)
    creation = caller_map[static['primary_creation'].operation]
    origin = BodyActivationOrigin(body_activation, creation, source)

    implementation_calls, frames = [], []
    for number, definition in enumerate(static['stage_records']):
        rows, activation, entries, mapping = _activation(program, definition['region'].id,
            definition['paths'][ExitKind.NORMAL], f'await.visits.final.{number}', point, thread)
        append(rows)
        frames.append({'definition': definition, 'activation': activation,
            'entry': entries[0], 'operations': mapping,
            'completion': mapping[definition['terminals'][ExitKind.NORMAL].id]})
    for number, frame in enumerate(frames):
        caller_occurrence = (caller_map[static['extract'].id] if number == 0 else
            frames[number - 1]['operations'][frames[number - 1]['definition']['operation'].id])
        implementation_calls.append(CallActivation(CallActivationID(f'await.visits.final.{number}'),
            caller_occurrence, frame['activation'], frame['entry'], frame['completion'], source))

    captured_identity_calls = list(identity_calls)
    if missing == 'operand':
        combined['uses'] = [row for row in combined['uses'] if
            (row.operation, row.use) != (get_occurrences[1].id,
                                        static['get'].invoke_arguments[0])]
    elif missing == 'transfer':
        combined['transfers'] = [row for row in combined['transfers']
                                 if row.operation != get_occurrences[1].id]
    elif missing == 'call-association':
        captured_identity_calls.remove(identity_calls[1])
    elif missing == 'return-use':
        combined['uses'] = [row for row in combined['uses'] if
            (row.operation, row.use) != (identity_calls[1].completion,
                                        static['identity_terminal'].terminator.values[0])]
    elif missing is not None:
        raise ValueError('unknown Get1 capture omission')
    model = ExecutionModel(snapshot_for(program),
        runs=(ExecutionRun(run, source),),
        processes=(ProcessInstance(process, run, 501, source),),
        threads=(HostThreadInstance(thread, process, 502, source),),
        **{name: tuple(rows) for name, rows in combined.items()},
        call_activations=(*captured_identity_calls, driver_call, *implementation_calls),
        body_drive_executions=(drive,), body_activation_origins=(origin,))
    iterator_use, = tuple(row for row in caller_rows['uses']
        if row.operation == driver_call.caller and row.use == driver['caller_call'].invoke_arguments[0])
    return program, model, {'static': static, 'caller': caller, 'caller_visits': visits,
        'caller_operations': caller_map, 'gets': get_occurrences, 'get_values': get_values,
        'get_transfers': get_transfers, 'identity_calls': tuple(identity_calls),
        'iterator_use': iterator_use, 'advance': driver_call.caller,
        'driver_call': driver_call, 'drive': drive, 'body_activation': body_activation,
        'body_origin': origin, 'creation': creation,
        'extraction': caller_map[static['extract'].id], 'final': caller_map[static['final'].id],
        'implementation_calls': tuple(implementation_calls), 'implementation_frames': tuple(frames),
        'missing': missing}


def _query(program, model, details):
    require_valid(program)
    validity = validate(model, program)
    assert validity.valid, validity.issues
    report = ExecutionIndex(model, program).await_body_links(
        details['static']['acquisition_scope'], budget=_BUDGET)
    assert not report['budget']['truncated'], report['budget']
    for flag in _FLAGS:
        assert report[flag] is False
    return report


def _active(report, details):
    jobs = tuple(job for job in report['jobs'] if job['source'] == details['static']['source']
                 and job['advance_operation'] == details['static']['advance_operation'])
    assert jobs
    assert report['inventory']['source_count'] == 1
    assert all(job['source_occurrence_count'] == 2 for job in jobs)
    selected = tuple((job, occurrence) for job in jobs for occurrence in job['occurrences']
        if occurrence['advance'].id == details['advance']
        and occurrence['advance_selected'] is True and occurrence['case_selected'] is True)
    assert len(selected) == 1
    job, occurrence = selected[0]
    assert {row['occurrence'].id for row in occurrence['source_candidates']} == {
        row.id for row in details['gets']}
    return job, occurrence


def _final_implementation(report, details):
    rows = tuple(row for row in report['outcomes']
        if row['definition']['drive_outcome'] == details['static']['drive_outcome']
        and row['definition']['advance_operation'] == details['static']['advance_operation'])
    occurrences = tuple(occurrence for row in rows for occurrence in row['occurrences']
        if occurrence['advance'].id == details['advance']
        and occurrence['drive'].id == details['drive'].drive)
    assert len(occurrences) == 1
    consumer, = tuple(row for row in occurrences[0]['consumers']
        if row['definition']['actual'] == details['static']['extract_input']
        and row['definition']['requires_final_extraction'] is True)
    return consumer, consumer['implementation']


@pytest.mark.parametrize('iterator_origin', ('latest', 'earlier'), ids=('latest', 'earlier'))
def test_same_static_get_visits_select_the_actual_own_result_not_latest_or_common_b(iterator_origin):
    program, model, details = _source_visit_execution(iterator_origin=iterator_origin)
    static = details['static']
    assert len(program.resumable_creates) == 1
    assert len(model.body_activation_origins) == len(model.body_drive_executions) == 1
    assert details['body_origin'].creation == details['creation']
    assert len({row.visit for row in details['gets']}) == 2
    assert {row.operation for row in details['gets']} == {static['get'].id}
    assert tuple(row.caller for row in details['identity_calls']) == tuple(row.id for row in details['gets'])
    assert len({row.activation for row in details['identity_calls']}) == 2
    assert len(static['get'].completions) == 1
    assert static['get'].completions[0].kind is ExitKind.NORMAL
    assert tuple(edge.kind for edge in static['get'].terminator.successors) == (ExitKind.NORMAL,)
    assert details['get_values'][0].id != details['get_values'][1].id
    assert static['get'].terminator.successors[0].arguments[0] == CompletionResult(0)
    assert static['get'].terminator.successors[0].arguments[4] == static['previous_forward'].id
    assert static['previous_forward'].id not in static['get'].invoke_arguments
    assert type(static['previous']) is BlockArgument
    expected_number = 1 if iterator_origin == 'latest' else 0
    if iterator_origin == 'earlier':
        first_inputs = tuple(row for row in program.protocol_call_inputs
                             if row.site.operation == static['advance_operation'])
        assert first_inputs
        assert all(case.receiver == static['previous'] for row in first_inputs for case in row.cases)
        # The actual backedge saves the first own result, not the stable B seed.
        saved, = tuple(use for use in static['retry'].uses
                       if use.id == static['retry'].terminator.successors[0].arguments[3])
        assert saved.value == static['landing'][0].id
    # Current W/C always come from Get1's full logical state slots, even when
    # the iterator is the earlier returned Reference.
    proceed = static['retry'].terminator.successors[1]
    assert tuple(next(use.value for use in static['retry'].uses if use.id == identity)
                 for identity in proceed.arguments[-2:]) == tuple(value.id for value in static['landing'][2:4])
    assert tuple(static['get'].terminator.successors[0].arguments[slot]
                 for slot in (2, 3)) == (CompletionResult(1), CompletionResult(2))

    report = _query(program, model, details)
    _job, occurrence = _active(report, details)
    assert tuple(row['occurrence'].id for row in occurrence['matched_sources']) == (
        details['gets'][expected_number].id,)
    assert occurrence['bindings']
    assert all(binding['original_copy'] is True for binding in occurrence['bindings'])
    assert occurrence['bindings'][0]['source_value'].id == details['get_values'][expected_number].id
    route, = occurrence['routes']
    assert tuple(row['association'] for row in route['call_chain']) == (details['driver_call'],)
    assert route['drive']['activation'].id == details['body_activation']
    assert route['drive']['association'] == details['drive']
    consumer, implementation = _final_implementation(report, details)
    assert consumer['selected'] is True
    assert len(implementation['frames']) == 2
    assert tuple(frame['call']['association'].id for frame in implementation['frames']) == tuple(
        call.id for call in details['implementation_calls'])
    assert tuple(frame['completion'].id for frame in implementation['frames']) == tuple(
        frame['completion'] for frame in details['implementation_frames'])
    paths = tuple(path for stage in implementation['stages'] for leg in stage['legs']
                  for result in leg['results'] for path in result['paths']
                  if path['status'] == 'DECLARED')
    assert paths
    assert all(all(hop['binding']['match'] is True for hop in path['hops']) for path in paths)
    for flag in _FLAGS:
        assert implementation[flag] is False


@pytest.mark.parametrize('missing', ('operand', 'transfer'), ids=('operand-use', 'selected-transfer'))
def test_missing_get1_input_or_selected_transfer_keeps_both_sources_without_borrowing_get0(missing):
    program, model, details = _source_visit_execution(iterator_origin='latest', missing=missing)
    if missing == 'operand':
        assert not any(row.operation == details['gets'][1].id
            and row.use == details['static']['get'].invoke_arguments[0] for row in model.uses)
    else:
        assert not any(row.operation == details['gets'][1].id for row in model.transfers)
    report = _query(program, model, details)
    _job, occurrence = _active(report, details)
    assert occurrence['status'] == 'PARTIAL'
    assert occurrence['gaps']
    assert all(row['occurrence'].id == details['gets'][1].id
               for row in occurrence['matched_sources'])
    # Capture omission cannot erase the independently inventoried completion
    # consumer, actual advance, original body outcome or final implementation.
    consumer, implementation = _final_implementation(report, details)
    assert consumer['operation'] is not None
    assert consumer['operation'].id == details['extraction']
    assert implementation['frames']
    assert len(implementation['frames']) == 2
    assert report['status'] == 'PARTIAL'


@pytest.mark.parametrize('missing', ('call-association', 'return-use'),
                         ids=('call-association', 'callee-return-use'))
def test_missing_get1_call_support_keeps_its_own_candidate_without_borrowing_get0(missing):
    program, model, details = _source_visit_execution(iterator_origin='latest', missing=missing)
    get0, get1 = details['identity_calls']
    assert get0 in model.call_activations
    if missing == 'call-association':
        assert get1 not in model.call_activations
        assert any(row.id == get1.completion for row in model.operations)
    else:
        assert get1 in model.call_activations
        payload_use = details['static']['identity_terminal'].terminator.values[0]
        assert not any((row.operation, row.use) == (get1.completion, payload_use)
                       for row in model.uses)
        assert any((row.operation, row.use) == (get0.completion, payload_use)
                   for row in model.uses)
    report = _query(program, model, details)
    _job, occurrence = _active(report, details)
    candidate, = tuple(row for row in occurrence['source_candidates']
                       if row['occurrence'].id == details['gets'][1].id)
    assert candidate['value'].id == details['get_values'][1].id
    assert all(row['occurrence'].id == details['gets'][1].id
               for row in occurrence['matched_sources'])
    assert occurrence['status'] == 'PARTIAL'
    assert occurrence['gaps']
    consumer, implementation = _final_implementation(report, details)
    assert consumer['operation'].id == details['extraction']
    assert len(implementation['frames']) == 2
    assert report['status'] == 'PARTIAL'


@pytest.mark.parametrize('iterator_origin', ('latest', 'earlier'), ids=('latest', 'earlier'))
def test_repeated_source_inventory_survives_shared_budget_and_detached_requery(iterator_origin):
    program, model, details = _source_visit_execution(iterator_origin=iterator_origin)
    require_valid(program)
    validity = validate(model, program)
    assert validity.valid, validity.issues
    index = ExecutionIndex(model, program)
    scope = details['static']['acquisition_scope']
    complete = index.await_body_links(scope, budget=_BUDGET)
    assert complete['budget']['truncated'] is False
    _job, occurrence = _active(complete, details)
    expected = details['gets'][1 if iterator_origin == 'latest' else 0].id
    assert tuple(row['occurrence'].id for row in occurrence['matched_sources']) == (expected,)
    consumer, implementation = _final_implementation(complete, details)
    assert consumer['operation'].id == details['extraction']
    assert len(implementation['frames']) == 2
    full_cost = complete['budget']['used']
    assert full_cost > 2
    job_keys = {(row['source'], row['advance']) for row in complete['jobs']}
    original_anchors = deepcopy(complete['inventory']['original_anchors'])
    # The middle limit is derived from this actual complete query, without
    # increasing the public budget or inventing a fixed implementation cost.
    for limit in (1, full_cost // 2):
        limited = index.await_body_links(scope, budget=limit)
        assert limited['budget']['used'] <= limit
        assert limited['budget']['truncated'] is True
        assert limited['status'] == 'PARTIAL'
        assert limited['cursor'] is not None
        assert limited['inventory']['source_count'] == 1
        # Unpaid declared templates can repeat a source/advance with a still
        # unchecked guard/choice. They must retain the original anchors and
        # cannot remove any known source/advance or its occurrence denominator.
        assert limited['inventory']['original_anchors'] == original_anchors
        assert {(row['source'], row['advance']) for row in limited['jobs']} == job_keys
        assert all(row['source_occurrence_count'] == 2 for row in limited['jobs'])
        assert all(row['checked_source_occurrence_count'] + row['pending_source_occurrence_count'] == 2
                   for row in limited['jobs'])
        for flag in _FLAGS:
            assert limited[flag] is False

    # Detached reports must not overwrite the next fresh public projection.
    occurrence['matched_sources'] = ()
    complete['inventory']['source_count'] = -1
    complete['jobs'][0]['source_occurrence_count'] = -1
    implementation['frames'][0]['status'] = 'caller-mutated report'
    again = index.await_body_links(scope, budget=_BUDGET)
    _job, selected = _active(again, details)
    assert tuple(row['occurrence'].id for row in selected['matched_sources']) == (expected,)
    _consumer, current = _final_implementation(again, details)
    assert current['frames'][0]['status'] != 'caller-mutated report'
    assert len(current['frames']) == 2
    for flag in _FLAGS:
        assert again[flag] is False


def test_declared_previous_carrier_retains_history_without_changing_current_copy_receipts():
    program, static = _source_visit_program('earlier')
    require_valid(program)
    row, = static['get_rows']
    expected = ContractResult(row.scope, row.clause, row.operation, row.slot, row.contract.result)
    advance = static['calls'][0]
    actual = OwnedUse(advance.id, advance.invoke_arguments[0])
    carrier = static['previous']
    context = ConnectionContext(program, index=ProgramIndex(program), budget=ValidityBudget(_BUDGET))
    current = deepcopy(context.bind(expected, actual))
    carrier_copy = deepcopy(context.bind(carrier, actual))
    origins_before = deepcopy(context.origins(actual))
    assert current['match'] is False
    assert carrier_copy['match'] is True
    assert origins_before['source_inventory_complete'] is True
    assert origins_before['cursor'] is None
    assert origins_before['recipes']

    historical = context.carried_source(expected, carrier, actual)
    assert historical['match'] is None
    assert historical['current_binding'] == current
    assert historical['carrier_binding'] == carrier_copy
    assert 'carried_source_evaluation_unselected' in historical['gaps']
    assert historical['historical_origins'] == origins_before
    # Preserve every recipe and its original local freshness receipt. Some
    # recipe anchors are fresh even though the current Get->advance is False.
    assert tuple(recipe.get('freshness') for recipe in historical['historical_origins']['recipes']) == tuple(
        recipe.get('freshness') for recipe in origins_before['recipes'])
    matching = historical['matching_historical_recipes']
    assert matching
    formal_ids = set(context.port(carrier).values)
    for recipe in matching:
        assert recipe in origins_before['recipes']
        assert recipe['kind'] == 'INVOKE_COMPLETION'
        assert recipe['origin'] == row.contract.result
        assert any(step.get('kind') == 'CFG_COPY'
            and getattr(step.get('formal'), 'id', step.get('formal')) in formal_ids
            for step in recipe['path'])
    assert context.bind(expected, actual) == current
    assert context.origins(actual) == origins_before
    assert historical['source_runtime_verified'] is False
    assert historical['runtime_identity_verified'] is False
    assert historical['transformation_authorized'] is False
    assert not context.budget.truncated


def test_history_port_budget_exhaustion_preserves_cached_current_false_as_nested_receipt():
    program, static = _source_visit_program('earlier')
    require_valid(program)
    row, = static['get_rows']
    expected = ContractResult(row.scope, row.clause, row.operation, row.slot, row.contract.result)
    advance = static['calls'][0]
    actual = OwnedUse(advance.id, advance.invoke_arguments[0])
    budget = ValidityBudget(_BUDGET)
    context = ConnectionContext(program, index=ProgramIndex(program), budget=budget)
    current = deepcopy(context.bind(expected, actual))
    assert current['match'] is False
    assert not budget.truncated
    budget.limit = budget.used + 1

    historical = context.carried_source(expected, static['previous'], actual)
    assert budget.truncated is True
    assert budget.used == budget.limit
    assert historical['match'] is None
    assert historical['cursor'] is not None
    assert historical['current_binding'] == current
    assert historical['current_binding']['match'] is False
    assert 'carried_source_origin_inventory_unresolved' in historical['gaps']
    assert historical['source_runtime_verified'] is False
    assert historical['runtime_identity_verified'] is False
    assert historical['transformation_authorized'] is False


def test_owned_input_is_not_a_supported_historical_own_result_source(monkeypatch):
    program, static = _source_visit_program('earlier')
    require_valid(program)
    get, advance = static['get'], static['calls'][0]
    # The current Get's operand is an original pre-operation Use. It is not
    # an own-result source, even though the identity callee returns that input.
    unsupported = OwnedUse(get.id, get.invoke_arguments[0])
    actual = OwnedUse(advance.id, advance.invoke_arguments[0])
    context = ConnectionContext(program, index=ProgramIndex(program), budget=ValidityBudget(_BUDGET))
    current = deepcopy(context.bind(unsupported, actual))
    assert current['match'] is False

    def no_historical_search(*_args, **_kwargs):
        raise AssertionError('unsupported OwnedUse source must not enter historical recipe search')

    monkeypatch.setattr(context, 'origins', no_historical_search)
    historical = context.carried_source(unsupported, static['previous'], actual)
    assert historical == current
    assert historical['match'] is False
    assert 'historical_origins' not in historical
    assert 'matching_historical_recipes' not in historical
    assert not context.budget.truncated
    assert historical['source_runtime_verified'] is False
    assert historical['runtime_identity_verified'] is False
    assert historical['transformation_authorized'] is False


@pytest.mark.parametrize('compatible', (True, False), ids=('compatible', 'conflicting'))
def test_cyclic_entry_guard_does_not_erase_an_earlier_acyclic_incoming_conflict(compatible):
    owner = RegionID('source.guard.owner')
    entry, left, right, merge, header, body, exit_ = tuple(
        BlockID('source.guard.' + name)
        for name in ('entry', 'left', 'right', 'merge', 'header', 'body', 'exit'))
    entry_choice = DataValue(ValueID('source.guard.entry.choice'), owner,
                             BlockArgument(entry, 0), 'builtins.bool')
    loop_choice = DataValue(ValueID('source.guard.loop.choice'), owner,
                            BlockArgument(entry, 1), 'builtins.bool')
    source_id = OperationID('source.guard.produce')
    produced = DataValue(ValueID('source.guard.result'), owner,
                         OperationResult(source_id, 0), 'builtins.int')
    entry_use = _use('source.guard.entry.condition', entry_choice)
    split = Operation(OperationID('source.guard.split'), 'choose one original acyclic arm',
        (Behavior.CONTROL,), (entry_use,), effects_complete=True,
        terminator=Terminator(TerminatorKind.BRANCH,
            (Successor(left, ()), Successor(right, ())), condition=entry_use.id))

    def jump(name, destination):
        return Operation(OperationID('source.guard.' + name), 'original CFG copy/control edge',
            (Behavior.CONTROL,), effects_complete=True,
            terminator=Terminator(TerminatorKind.JUMP, (Successor(destination, ()),)))

    left_jump, right_jump = jump('left.merge', merge), jump('right.merge', merge)
    enter_loop, backedge = jump('enter.loop', header), jump('backedge', header)
    source = Operation(source_id, 'one original source reevaluated at the loop header',
        (Behavior.COMPUTE,), results=(produced.id,), effects_complete=True)
    loop_use = _use('source.guard.loop.condition', loop_choice)
    retry = Operation(OperationID('source.guard.retry'), 'choose loop or current return',
        (Behavior.CONTROL,), (loop_use,), effects_complete=True,
        terminator=Terminator(TerminatorKind.BRANCH,
            (Successor(body, ()), Successor(exit_, ())), condition=loop_use.id))
    payload = _use('source.guard.return.value', produced)
    terminal = Operation(OperationID('source.guard.return'), 'consume this header result',
        (Behavior.CONTROL,), (payload,), effects_complete=True,
        terminator=Terminator(TerminatorKind.RETURN, exit='normal', values=(payload.id,)))
    blocks = (
        Block(entry, (entry_choice.id, loop_choice.id), (split.id,)),
        Block(left, (), (left_jump.id,)), Block(right, (), (right_jump.id,)),
        Block(merge, (), (enter_loop.id,)), Block(header, (), (source.id, retry.id)),
        Block(body, (), (backedge.id,)), Block(exit_, (), (terminal.id,)),
    )
    region = Region(owner, 'independent incoming choices followed by a real copy loop',
        entry, blocks, (ExitPort('normal', ExitKind.NORMAL,
                                 (ValueType(ValueKind.DATA, 'builtins.int'),)),))
    program = ProgramGraph(owner, (region,),
        (split, left_jump, right_jump, enter_loop, source, retry, backedge, terminal),
        (entry_choice, loop_choice, produced), control_scopes=(_scope(owner, blocks),))
    require_valid(program)
    context = ConnectionContext(program, index=ProgramIndex(program), budget=ValidityBudget(_BUDGET))
    expected, actual = produced.origin, OwnedUse(terminal.id, payload.id)
    assert context.bind(expected, actual)['match'] is True
    guards = (ControlEdgeReference(split.id, 0),
        ControlEdgeReference(left_jump.id if compatible else right_jump.id, 0),
        ControlEdgeReference(backedge.id, 0))
    report = context.bind(expected, actual, guard=guards)
    if compatible:
        assert report['match'] is None
        assert 'selected_loop_entry_requires_occurrence_context' in report['gaps']
    else:
        assert report['match'] is False
        assert 'selected_loop_entry_requires_occurrence_context' not in report['gaps']
    assert not context.budget.truncated
    assert report['source_runtime_verified'] is False
    assert report['runtime_identity_verified'] is False
    assert report['transformation_authorized'] is False
