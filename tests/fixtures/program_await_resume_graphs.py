"""Supplied zero/two-cut await paths over one original generator coroutine.

The nonzero path first directly drives B, acquires its self iterator, then
resumes the same B twice. The final iterator call really raises its constructed
StopIteration packet; an original caller extraction INVOKE has its own N/R.
This fixture does not recover Python source or certify native applicability.
"""
from dataclasses import replace

from scar.ir.program.control import ControlScope, ControlScopeKind
from scar.ir.program.drivers import CreationCapture, NormalResultPort, RawRequestDefinition, RawRequestKind, ResumableCreate
from scar.ir.program.environments import EnvironmentRole
from scar.ir.program.ids import BlockID, ControlScopeID, OperationID, ProtocolScopeID
from scar.ir.program.model import (AccessMode, Behavior, BlockArgument, CompletionResult,
    CompletionSignature, CompletionSuccessor, ExitKind, InvokeLiteralResult, Operation, OperationResult,
    ReferenceValue, StateAccess, StateVersionValue, Terminator, TerminatorKind,
    UseRole, ValueKind, ValueType)
from scar.ir.program.protocol_await_records import AwaitAcquisition, AwaitBodyLink
from scar.ir.program.protocol_connections import (InitialAdvance, ProtocolCallInputCase,
    ProtocolCallInputs, ProtocolOperationRef, ProtocolResultConsumers, RawOperandSource, RawRequestTrigger)
from scar.ir.program.protocols import (ContractResult, DriverSubject, HostTerminal,
    OperationSiteSubject, OutcomeAdapter, OwnedUse, ProtocolCall, ProtocolCallRule,
    ProtocolClause, ProtocolOperation, ProtocolProfile, ProtocolScope, RequestProcessing,
    RequestProcessingRule)
from scar.ir.program.resumption import ResumableKind
from scar.ir.program.state_addresses import InvokeStateOperand
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.program_async_pipeline_graphs import _selected_path
from tests.fixtures.program_control_graphs import _source
from tests.fixtures.program_driver_graphs import PACKET, RAW, REFERENCE, _Builder, _body_with_environment, _use, driver_program, driver_rule
from tests.fixtures.program_generator_close_retry_graphs import _driver_part
from tests.fixtures.program_protocol_graphs import _adapt_return, _insert_processing, _source_gap
from tests.fixtures.program_publication_graphs import with_publications
from tests.fixtures.program_resumption_graphs import resumption_two_cuts_program


def _body(*, zero_cut, kind):
    template = _body_with_environment()
    if zero_cut:
        region = template.regions[0]
        entry = next(block for block in region.blocks if block.id == region.entry)
        kept = {OperationID('resume.initial'), OperationID('resume.attach'), OperationID('resume.detach')}
        detach = next(op for op in template.operations if op.id == OperationID('resume.detach'))
        uses = (_use('await.zero.return.value', entry.arguments[0]),
                _use('await.zero.return.world', entry.arguments[1], state=True),
                _use('await.zero.return.context', detach.results[1], state=True))
        terminal = Operation(OperationID('await.zero.return'), 'return before any suspension',
            (Behavior.CONTROL,), uses, effects_complete=True,
            terminator=Terminator(TerminatorKind.RETURN, exit='normal', values=tuple(use.id for use in uses)))
        operations = (*[op for op in template.operations if op.id in kept], terminal)
        region = replace(region,
            blocks=(replace(entry, operations=tuple(op.id for op in operations)),),
            exits=tuple(port for port in region.exits if port.kind is ExitKind.NORMAL))
        values = tuple(value for value in template.values
            if type(value.origin) is BlockArgument and value.origin.block == entry.id
            or type(value.origin) is OperationResult and value.origin.operation in kept)
        graph = replace(template, regions=(region,), operations=operations, values=values,
            control_scopes=tuple(replace(scope, blocks=(entry.id,)) for scope in template.control_scopes),
            frame_context_attaches=tuple(row for row in template.frame_context_attaches if row.operation in kept),
            frame_context_detaches=tuple(row for row in template.frame_context_detaches if row.operation in kept))
    else:
        graph = resumption_two_cuts_program()
        region = graph.regions[0]
        environment = template.environments[0]
        identities = {member.reference for member in environment.members}
        references = tuple(value for value in template.values if value.id in identities)
        region = replace(region, blocks=tuple(replace(block,
            arguments=(*block.arguments, *(value.id for value in references)))
            if block.id == region.entry else block for block in region.blocks))
        graph = replace(graph, regions=(region,), values=(*graph.values, *references),
                        environments=template.environments, function_entries=template.function_entries)
    return replace(graph, resumable_bodies=tuple(replace(row, kind=kind) for row in graph.resumable_bodies))


def _stage(body, ordinal, *, zero_cut):
    final = zero_cut or ordinal == 2
    selected = None if ordinal == 0 else OperationID('resume.suspend' if ordinal == 1 else 'resume.second.suspend')
    chosen_body = body if selected is None else replace(body,
        operations=tuple(sorted(body.operations, key=lambda op: op.id != selected)))
    target = 'start' if ordinal == 0 else 'value'
    graph = driver_program(body_graph=chosen_body, target=target)
    interface, = graph.driver_interfaces
    scope = ProtocolScope(ProtocolScopeID('await.body.scope'),
        ProtocolProfile.GENERATOR_COROUTINE_BODY_V1, DriverSubject(interface.region), _source_gap())
    graph = replace(graph, protocol_scopes=(scope,))
    choices = {graph.final_body_gates[0].operation: 0}
    if ordinal:
        graph, processing = _insert_processing(graph, target='value')
        rows = tuple(ProtocolOperation(scope.id, ProtocolClause.REQUEST_PROCESSING,
            processing['processing'], slot,
            RequestProcessing(processing['raw_use'], (), processing[result], processing['state_sites'],
                              RequestProcessingRule.CHECK_SEND), _source_gap())
            for slot, result in ((0, 'normal_result'), (1, 'raise_result')))
        graph = replace(graph, protocol_operations=rows)
        choices[processing['processing']] = 0
    if final:
        graph = _adapt_return(graph, scope.id)
        graph = replace(graph, protocol_operations=tuple(replace(row,
            clause=ProtocolClause.DIRECT_HOST_ADAPTER) if type(row.contract) is OutcomeAdapter else row
            for row in graph.protocol_operations))
        choices[OperationID('adapter.construct')] = 0
    graph = with_publications(graph)
    drive, = graph.body_drives
    drive_op = next(op for op in graph.operations if op.id == drive.operation)
    edge_index = 0
    choices[drive.operation] = edge_index
    source = drive_op.terminator.successors[edge_index].source
    part, maps = _driver_part(graph, f'await.resume.driver.{ordinal}')
    from dataclasses import fields, is_dataclass

    def rename(value):
        if type(value) in maps:
            return maps[type(value)].get(value, value)
        if type(value) is tuple:
            return tuple(rename(item) for item in value)
        if is_dataclass(value):
            return replace(value, **{field.name: rename(getattr(value, field.name)) for field in fields(value)})
        return value

    part['choices'] = {rename(operation): successor for operation, successor in choices.items()}
    part['source'] = source
    part['drive'] = part['body_drives'][0]
    part['host'] = rename(OperationID('adapter.normal.exit' if final else 'driver.outcome.exit'))
    part['path'] = _selected_path(replace(graph, regions=(part['region'],), operations=part['operations']),
                                  part['region'], part['choices'])
    return part


def await_resume_program(*, zero_cut=False, kind=ResumableKind.GENERATOR_COROUTINE,
                         extra_creation=True):
    """Return ``(program, details)`` for exact Create/acquire/drive/extract ports.

    Nonzero: direct NEXT -> cut1; acquire B -> SEND -> cut2; SEND -> Return.
    Zero: acquire B -> first NEXT -> Return. Neither path invents a suspension.
    """
    if type(zero_cut) is not bool or type(extra_creation) is not bool:
        raise TypeError('fixture switches require exact bools')
    if kind is not ResumableKind.GENERATOR_COROUTINE:
        raise ValueError('this direct-plus-await fixture models generator-coroutine B')
    body = _body(zero_cut=zero_cut, kind=kind)
    stages = tuple(_stage(body, index, zero_cut=zero_cut) for index in range(1 if zero_cut else 3))
    domains = tuple(location.id for location in body.locations)
    states = tuple(ValueType(ValueKind.STATE, location=location) for location in domains)
    builder = _Builder('await.resume.caller', domains)
    body_region = body.regions[0]
    body_values = {value.id: value for value in body.values}
    body_entry = next(block for block in body_region.blocks if block.id == body_region.entry)
    capture_formals = tuple(value for value in body_entry.arguments if isinstance(body_values[value], ReferenceValue))
    entry_name = 'await.resume.entry'
    entry = builder.formals(entry_name, (*(REFERENCE for _ in range(len(capture_formals) + 1)), *states))
    captures, sent = entry[:len(capture_formals)], entry[len(capture_formals)]
    initial_states = entry[-len(states):]
    function = next(member.reference for member in body.environments[0].members
                    if member.role is EnvironmentRole.FUNCTION_OBJECT)
    creations, create_operations = [], []
    created = None
    current_block, current_args, current_states = entry_name, entry, initial_states
    for ordinal in range(2 if extra_creation else 1):
        name = f'await.resume.create.{ordinal}'
        normal_name, failure_name = name + '.normal', name + '.failure'
        keep_body = ordinal > 0
        normal = builder.formals(normal_name, (*((REFERENCE,) if keep_body else ()), REFERENCE, *states))
        failure = builder.formals(failure_name, (PACKET, *states))
        actuals = tuple(_use(f'{name}.arg.{index}', value, state=index >= len(captures))
                        for index, value in enumerate((*captures, *current_states)))
        forwards = () if not keep_body else (_use(name + '.forward.body', created),)
        operation = builder.add(name, (*actuals, *forwards), effects_complete=True,
            invoke_arguments=tuple(use.id for use in actuals),
            completions=(CompletionSignature(ExitKind.NORMAL, (REFERENCE, *states)),
                         CompletionSignature(ExitKind.RAISE, (PACKET, *states))),
            terminator=Terminator(TerminatorKind.INVOKE, (
                CompletionSuccessor(ExitKind.NORMAL, BlockID(normal_name),
                    (*(use.id for use in forwards), *(CompletionResult(index) for index in range(1 + len(states))))),
                CompletionSuccessor(ExitKind.RAISE, BlockID(failure_name),
                    tuple(CompletionResult(index) for index in range(1 + len(states)))))))
        capture_rows = tuple(CreationCapture(formal, use.id) for formal, use in zip(capture_formals, actuals))
        creations.append(ResumableCreate(operation.id, body_region.id,
            next(row.source for row in capture_rows if row.formal == function), capture_rows,
            NormalResultPort(0), driver_rule()))
        create_operations.append(operation)
        builder.block(current_block, current_args, (operation,))
        builder.block(failure_name, failure, (builder.terminal(failure_name + '.exit', failure, fail=True),))
        current_block, current_args = normal_name, normal
        created = normal[0]
        current_states = normal[2 if keep_body else 1:]
    main_body = created
    decoy = current_args[1] if extra_creation else None
    iterator = None
    acquisition_scope = ProtocolScopeID('await.resume.acquisition')
    get = None
    get_rows, call_rows, input_rows, consumer_rows, links, scopes = [], [], [], [], [], []
    raw_definitions, calls, driver_details, handoffs = [], [], [], []
    final_call_landing = None

    def acquire(block_name, args, body_value, decoy_value, current):
        normal_name, failure_name = 'await.resume.acquired', 'await.resume.acquire.failure'
        retained = (body_value, *((decoy_value,) if decoy_value is not None else ()))
        normal = builder.formals(normal_name, (REFERENCE, *(REFERENCE for _ in retained), *states))
        failure = builder.formals(failure_name, (PACKET, *states))
        actuals = (_use('await.resume.acquire.body', body_value),
                   *(_use(f'await.resume.acquire.state.{index}', state, state=True) for index, state in enumerate(current)))
        forwards = tuple(_use(f'await.resume.acquire.forward.{index}', value) for index, value in enumerate(retained))
        operation = builder.add('await.resume.acquire', (*actuals, *forwards), effects_complete=False,
            invoke_arguments=tuple(use.id for use in actuals),
            completions=(CompletionSignature(ExitKind.NORMAL, (REFERENCE, *states)),
                         CompletionSignature(ExitKind.RAISE, (PACKET, *states))),
            terminator=Terminator(TerminatorKind.INVOKE, (
                CompletionSuccessor(ExitKind.NORMAL, BlockID(normal_name),
                    (CompletionResult(0), *(use.id for use in forwards),
                     *(CompletionResult(index + 1) for index in range(len(states))))),
                CompletionSuccessor(ExitKind.RAISE, BlockID(failure_name),
                    tuple(CompletionResult(index) for index in range(1 + len(states)))))))
        failure_exit = builder.terminal(failure_name + '.exit', failure, fail=True)
        builder.block(block_name, args, (operation,))
        builder.block(failure_name, failure, (failure_exit,))
        expected = next(value.origin for value in builder.values if value.id == body_value)
        rows = tuple(ProtocolOperation(acquisition_scope, ProtocolClause.AWAIT_ACQUISITION,
            operation.id, slot, AwaitAcquisition(actuals[0].id, expected,
                InvokeLiteralResult(ControlEdgeReference(operation.id, slot), CompletionResult(0)),
                tuple(InvokeStateOperand(operation.id, use.id) for use in actuals[1:]), _source_gap()),
            _source_gap()) for slot in range(2))
        get_rows.extend(rows)
        consumer_rows.append(ProtocolResultConsumers(ProtocolOperationRef(acquisition_scope,
            ProtocolClause.AWAIT_ACQUISITION, operation.id, 1), (HostTerminal(failure_exit.id),)))
        scopes.append(ProtocolScope(acquisition_scope, ProtocolProfile.AWAIT_ACQUISITION_V1,
                                    OperationSiteSubject(builder.region, operation.id), _source_gap()))
        return operation, normal_name, normal, normal[0], normal[1], (normal[2] if decoy_value is not None else None), normal[1 + len(retained):]

    for ordinal, component in enumerate(stages):
        if zero_cut or ordinal == 1:
            get, current_block, current_args, iterator, main_body, decoy, current_states = acquire(
                current_block, current_args, main_body, decoy, current_states)
        receiver = main_body if iterator is None else iterator
        name = f'await.resume.call.{ordinal}'
        raw_operands = () if ordinal == 0 else (_use(name + '.raw.operand', sent),)
        raw = builder.value(name + '.raw.value', OperationResult(OperationID(name + '.raw'), 0), RAW)
        pack = builder.add(name + '.raw', raw_operands, results=(raw,), effects_complete=True)
        raw_definitions.append(RawRequestDefinition(raw, RawRequestKind.NEXT if ordinal == 0 else RawRequestKind.SEND,
                                                    tuple(use.id for use in raw_operands)))
        actual_values = (receiver, raw, *((sent,) if ordinal else ()), *current_states)
        actuals = tuple(_use(f'{name}.input.{index}', value,
            state=index >= len(actual_values) - len(states), protocol=index == 1)
            for index, value in enumerate(actual_values))
        forwarded_values = (main_body, *((decoy,) if decoy is not None else ()),
                            *((iterator,) if iterator is not None else ()))
        forwards, edges, normal_data = [], [], None
        selected_kind = ExitKind.RAISE if zero_cut or ordinal == 2 else ExitKind.NORMAL
        selected_landing = None
        for exit_ in component['region'].exits:
            landing_name = name + '.' + exit_.kind.value.lower()
            keep = exit_.kind is ExitKind.NORMAL
            args = builder.formals(landing_name, (*(REFERENCE for _ in forwarded_values), *exit_.types)
                                   if keep else exit_.types)
            copied = tuple(_use(f'{name}.forward.{index}', value) for index, value in enumerate(forwarded_values)) if keep else ()
            forwards.extend(copied)
            edges.append(CompletionSuccessor(exit_.kind, BlockID(landing_name),
                (*(use.id for use in copied), *(CompletionResult(index) for index in range(len(exit_.types))))))
            if keep:
                normal_data = landing_name, args
            elif exit_.kind is selected_kind:
                final_call_landing = landing_name, args
            else:
                builder.block(landing_name, args,
                              (builder.terminal(landing_name + '.exit', args, fail=True),))
            if exit_.kind is selected_kind:
                selected_landing = landing_name, args
        call = builder.add(name, (*actuals, *forwards), effects_complete=True,
            callee=component['region'].id, invoke_arguments=tuple(use.id for use in actuals),
            completions=tuple(CompletionSignature(exit_.kind, exit_.types) for exit_ in component['region'].exits),
            terminator=Terminator(TerminatorKind.INVOKE, tuple(edges)))
        builder.block(current_block, current_args, (pack, call))
        calls.append(call)
        driver_details.append({'caller_call': call, 'driver_region': component['region'],
            'drive': component['drive'], 'outcome_source': component['source'],
            'path': component['path'], 'host_terminal': next(op for op in component['operations'] if op.id == component['host']),
            'selected_call_edge': next(index for index, edge in enumerate(edges) if edge.kind is selected_kind),
            'selected_landing': BlockID(selected_landing[0]), 'direct': iterator is None})
        if iterator is not None:
            scope_id = ProtocolScopeID(name + '.scope')
            scopes.append(ProtocolScope(scope_id, ProtocolProfile.DELEGATION_SITE_V1,
                                        OperationSiteSubject(builder.region, call.id), _source_gap()))
            acquired = ContractResult(acquisition_scope, ProtocolClause.AWAIT_ACQUISITION,
                                      get.id, 0, get_rows[0].contract.result)
            for slot in range(len(edges)):
                row = ProtocolOperation(scope_id, ProtocolClause.DELEGATE_ADVANCE, call.id, slot,
                    ProtocolCall(actuals[0].id, () if ordinal == 0 else (actuals[2].id,),
                        InvokeLiteralResult(ControlEdgeReference(call.id, slot), CompletionResult(0)),
                        tuple(InvokeStateOperand(call.id, use.id) for use in actuals if
                              any(value.id == use.value and isinstance(value, StateVersionValue) for value in builder.values)),
                        ProtocolCallRule.DELEGATE_NEXT if ordinal == 0 else ProtocolCallRule.DELEGATE_SEND), _source_gap())
                call_rows.append(row)
                raw_use = OwnedUse(call.id, actuals[1].id)
                input_rows.append(ProtocolCallInputs(ProtocolOperationRef(scope_id, row.clause, call.id, slot),
                    (ProtocolCallInputCase(None, acquired,
                        () if ordinal == 0 else (RawOperandSource(raw_use, 0),),
                        InitialAdvance(acquired) if ordinal == 0 else RawRequestTrigger(raw_use)),)))
                links.append(AwaitBodyLink(ProtocolOperationRef(acquisition_scope, ProtocolClause.AWAIT_ACQUISITION, get.id, 0),
                    ProtocolOperationRef(scope_id, row.clause, call.id, slot), component['drive'].operation, None, None))
        if normal_data is not None:
            current_block, current_args = normal_data
            count = len(forwarded_values)
            main_body = current_args[0]
            decoy = current_args[1] if extra_creation else None
            iterator = current_args[count - 1] if iterator is not None else None
            payload = current_args[count]
            current_states = current_args[count + 1:]
            # A real caller READ observes this intermediate handoff, separately
            # from the final extractor result. The following acquisition/call
            # remains in the same block after this read.
            before = _use(f'{name}.handoff.world', current_states[0], state=True)
            value_use = _use(f'{name}.handoff.value', payload)
            handoff = Operation(OperationID(name + '.handoff'), 'observe this intermediate export',
                (Behavior.CONTROL, Behavior.READ), (value_use, before),
                accesses=(StateAccess(domains[0], before.id, AccessMode.READ),), effects_complete=True)
            builder.operations.append(handoff)
            handoffs.append(handoff)
            # block() is emitted next iteration; retain this existing prefix.
            # The final assembly inserts it before that block's real terminator.

    if final_call_landing is None:
        raise AssertionError('final native iterator step must have a real RAISE landing')
    landing_name, incoming = final_call_landing
    extract_args = (_use('await.resume.extract.packet', incoming[0], protocol=True),
                    *(_use(f'await.resume.extract.state.{index}', state, state=True) for index, state in enumerate(incoming[1:])))
    normal = builder.formals('await.resume.final', (REFERENCE, *states))
    failure = builder.formals('await.resume.extract.failure', (PACKET, *states))
    extract = builder.add('await.resume.extract', extract_args, effects_complete=False,
        invoke_arguments=tuple(use.id for use in extract_args),
        completions=(CompletionSignature(ExitKind.NORMAL, (REFERENCE, *states)),
                     CompletionSignature(ExitKind.RAISE, (PACKET, *states))),
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, BlockID('await.resume.final'),
                tuple(CompletionResult(index) for index in range(len(normal)))),
            CompletionSuccessor(ExitKind.RAISE, BlockID('await.resume.extract.failure'),
                tuple(CompletionResult(index) for index in range(len(failure)))))))
    builder.block(landing_name, incoming, (extract,))
    final = builder.terminal('await.resume.final.return', normal)
    extraction_failure = builder.terminal('await.resume.extract.failure.raise', failure, fail=True)
    builder.block('await.resume.final', normal, (final,))
    builder.block('await.resume.extract.failure', failure, (extraction_failure,))
    # Bind each previously recorded handoff to the successor normal block.
    for ordinal, handoff in enumerate(handoffs):
        block_id = BlockID(f'await.resume.call.{ordinal}.normal')
        builder.blocks = [replace(block, operations=(handoff.id, *block.operations))
                          if block.id == block_id else block for block in builder.blocks]
    if get is not None:
        consumer_rows.append(ProtocolResultConsumers(ProtocolOperationRef(acquisition_scope,
            ProtocolClause.AWAIT_ACQUISITION, get.id, 0), tuple(OwnedUse(row.operation, row.contract.receiver_use)
                for row in call_rows if row.slot == 0)))
    for row in call_rows:
        if row.operation == calls[-1].id and row.slot == driver_details[-1]['selected_call_edge']:
            consumer_rows.append(ProtocolResultConsumers(ProtocolOperationRef(row.scope, row.clause, row.operation, row.slot),
                                                         (OwnedUse(extract.id, extract_args[0].id),)))
    caller = builder.finish(entry_name)
    tables = ('driver_interfaces', 'final_body_gates', 'body_drives', 'driver_lifecycles',
        'body_outcome_commits', 'terminal_frame_releases', 'protocol_scopes', 'protocol_operations',
        'literal_evaluations', 'exception_packets')
    graph = replace(body, root=caller.id,
        regions=(caller, replace(body_region, parent=caller.id),
                 *(replace(component['region'], parent=caller.id) for component in stages)),
        operations=(*body.operations, *(op for component in stages for op in component['operations']), *builder.operations),
        values=(*body.values, *(value for component in stages for value in component['values']), *builder.values),
        control_scopes=(*body.control_scopes, *(scope for component in stages for scope in component['control_scopes']),
            ControlScope(ControlScopeID('await.resume.caller.function'), caller.id, None, ControlScopeKind.FUNCTION,
                         _source('supplied direct/await driver caller'), tuple(block.id for block in caller.blocks))),
        resumable_creates=tuple(creations), raw_driver_requests=tuple(raw_definitions),
        protocol_call_inputs=tuple(input_rows), protocol_result_consumers=tuple(consumer_rows), protocol_bindings=tuple(links),
        **{name: tuple(row for component in stages for row in component[name]) +
           (tuple(scopes) if name == 'protocol_scopes' else tuple((*get_rows, *call_rows)) if name == 'protocol_operations' else ())
           for name in tables})
    caller_choices = {operation.id: 0 for operation in create_operations}
    caller_choices[get.id] = 0
    caller_choices.update((item['caller_call'].id, item['selected_call_edge']) for item in driver_details)
    caller_choices[extract.id] = 0
    return graph, {'caller': caller, 'caller_path': _selected_path(graph, caller, caller_choices),
        'body': body_region, 'body_kind': kind, 'creations': tuple(creations),
        'create_operations': tuple(create_operations), 'primary_creation': creations[0],
        'decoy_creation': creations[1] if extra_creation else None,
        'drivers': tuple(driver_details), 'calls': tuple(calls), 'get': get,
        'get_rows': tuple(get_rows), 'call_rows': tuple(call_rows), 'links': tuple(links),
        'acquisition_scope': acquisition_scope, 'handoffs': tuple(handoffs),
        'extract': extract, 'extract_input': OwnedUse(extract.id, extract_args[0].id),
        'final': final, 'final_value': normal[0], 'zero_cut': zero_cut,
        'capture_formals': capture_formals, 'sent_value': sent}


__all__ = ['await_resume_program']


def with_final_adapter(graph, details):
    """The existing extraction contract on the accurate self-acquisition scope.

    This is deliberately an ordinary OutcomeAdapter, not a fake lookup scope.
    Its current profile admission is tested independently before the product
    amendment; merely constructing the core extraction does not grant meaning.
    """
    from scar.ir.program.protocols import OutcomeAdapterRule
    call = details['calls'][-1]
    slot = details['drivers'][-1]['selected_call_edge']
    advance = next(row for row in details['call_rows'] if row.operation == call.id and row.slot == slot)
    expected = ContractResult(advance.scope, advance.clause, advance.operation, advance.slot,
                              advance.contract.result)
    operation = details['extract']
    rows = tuple(ProtocolOperation(details['acquisition_scope'], ProtocolClause.AWAIT_RESULT_ADAPTER,
        operation.id, number, OutcomeAdapter(expected, details['extract_input'].use,
            InvokeLiteralResult(ControlEdgeReference(operation.id, number), CompletionResult(0)),
            OutcomeAdapterRule.AWAIT_STOPITER_TO_EXPRESSION), _source_gap())
        for number in range(len(operation.terminator.successors)))
    consumers = tuple(ProtocolResultConsumers(ProtocolOperationRef(row.scope, row.clause, row.operation, row.slot),
        (HostTerminal(details['final'].id if operation.terminator.successors[row.slot].kind is ExitKind.NORMAL
                      else OperationID('await.resume.extract.failure.raise')),)) for row in rows)
    return replace(graph, protocol_operations=(*graph.protocol_operations, *rows),
                   protocol_result_consumers=(*graph.protocol_result_consumers, *consumers)), rows


__all__.append('with_final_adapter')
