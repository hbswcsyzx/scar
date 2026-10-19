"""Supplied first-ASEND control on one genuinely created async body.

R state, B phase and SEND operand remain independent original inputs.  The
fixture supplies declarations; it does not recover source or native identity.
"""
from dataclasses import replace

from scar.ir.program.control import ControlScope, ControlScopeKind
from scar.ir.program.drivers import (
    AsyncRequestCreate, CreationCapture, NormalResultPort, RawRequestDefinition,
    RawRequestKind, ResumableCreate,
)
from scar.ir.program.environments import EnvironmentRole
from scar.ir.program.ids import BlockID, ControlScopeID, OperationID, ProtocolScopeID, ValueID
from scar.ir.program.lifecycle import LifecyclePostBinding, SessionPost, SessionUpdate
from scar.ir.program.model import (
    AccessMode, Behavior, BlockArgument, CompletionResult, CompletionSignature,
    CompletionSuccessor, ExitKind, Footprint, FootprintKind, InvokeLiteralResult,
    LiteralOrigin, Operation, OperationResult, ReferenceValue, StateAccess,
    StateLocation, StateVersionValue, Terminator, TerminatorKind, ValueKind, ValueType,
)
from scar.ir.program.protocol_connections import (
    AsyncSessionOutcome, RequestAssociation, RequestStateCondition, RequestStateRule,
)
from scar.ir.program.protocols import (
    AdmissionPredicate, BodyStatePredicateRule, DriverSubject, OutcomeAdapter,
    OutcomeAdapterRule, ProtocolClause, ProtocolOperation, ProtocolProfile,
    ProtocolScope, RequestOperandBinding, RequestProcessing, RequestProcessingRule,
)
from scar.ir.program.state_addresses import InvokeStateOperand
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.program_async_competition_graphs import _TABLES
from tests.fixtures.program_async_connections import _association
from tests.fixtures.program_async_pipeline_graphs import (
    _driver_component, _pipeline_stage, _selected_path, _three_cut_body,
)
from tests.fixtures.program_control_graphs import _source
from tests.fixtures.program_driver_graphs import (
    PACKET, RAW, REFERENCE, _Builder, _use, driver_program, driver_rule,
)
from tests.fixtures.program_generator_admission_graphs import _guard
from tests.fixtures.program_protocol_graphs import _adapt_return, _source_gap
from tests.fixtures.program_publication_graphs import with_publications
from tests.fixtures.program_session_release_graphs import _Tail


def _op(graph, identity):
    return next(row for row in graph.operations if row.id == identity)


def _last_stage(body):
    """A new initial R resumes the existing, session-free ASYNC_YIELD cut."""
    selected = replace(body, operations=tuple(sorted(body.operations,
        key=lambda operation: operation.id != OperationID('pipeline.item.suspend'))))
    graph, association = _association(driver_program(target='value', async_request=True,
        extra_domain=True, body_graph=selected))
    interface, = graph.driver_interfaces
    scope = ProtocolScope(ProtocolScopeID('async.scope'), ProtocolProfile.ASYNC_GENERATOR_BODY_V1,
                          DriverSubject(interface.region), _source_gap())
    graph = _adapt_return(replace(graph, protocol_scopes=(scope,)), scope.id)
    graph = replace(graph, protocol_operations=tuple(replace(row,
        clause=ProtocolClause.ASYNC_ITEM_ADAPTER,
        contract=replace(row.contract, rule=OutcomeAdapterRule.ASYNCGEN_RETURN_TO_STOP_ASYNC_ITERATION))
        if type(row.contract) is OutcomeAdapter else row for row in graph.protocol_operations))
    graph = with_publications(graph)
    commit, = graph.body_outcome_commits
    tail = _Tail(graph, commit.operation)
    tail.metadata(SessionPost.COMPLETE, 'async.session.metadata')
    graph = tail.finish()
    read, = graph.request_association_reads
    operation = _op(graph, read.operation)
    association_row = ProtocolOperation(scope.id, ProtocolClause.ASYNC_REQUEST_ASSOCIATE, operation.id, 0,
        RequestAssociation(read.request,
            InvokeLiteralResult(ControlEdgeReference(operation.id, 0), CompletionResult(read.body_result.index)),
            InvokeLiteralResult(ControlEdgeReference(operation.id, 0), CompletionResult(read.latent_result.index)),
            tuple(InvokeStateOperand(operation.id, use.id) for use in operation.uses
                  if use.id in operation.invoke_arguments and
                  type(next(value for value in graph.values if value.id == use.value)) is StateVersionValue)),
        _source_gap())
    graph = replace(graph, protocol_operations=(*graph.protocol_operations, association_row),
        protocol_bindings=tuple(AsyncSessionOutcome(scope.id, update.operation, commit.outcome)
                                for update in graph.session_updates))
    graph, request = _guard(graph, block_id=BlockID('driver.no_body.test'),
        owner=association['session'], raw=association['scheduler'], label='pipeline.request.step',
        rule=BodyStatePredicateRule.IS_CREATED, admit_true=True)
    rows = []
    for row in graph.protocol_operations:
        if type(row.contract) is AdmissionPredicate and row.operation == request['predicate']:
            subject = row.contract.subject
            row = replace(row, clause=ProtocolClause.ASYNC_REQUEST_SOURCE,
                contract=replace(row.contract, subject=RequestStateCondition(subject.instance_use,
                    subject.state_sites, RequestStateRule.IS_INITIAL_STEP)))
        elif type(row.contract) is RequestProcessing and row.operation == request['helper']:
            operation = _op(graph, row.operation)
            row = replace(row, clause=ProtocolClause.ASYNC_REQUEST_DELIVERY,
                contract=replace(row.contract, raw_use=operation.invoke_arguments[0],
                                 rule=RequestProcessingRule.CHECK_ASYNC_REQUEST))
        rows.append(row)
    return replace(graph, protocol_operations=tuple(rows)), request


def _initial_guards(graph, request, *, start):
    """Read associated B, then check the exact L operand only for Created."""
    interface, = graph.driver_interfaces
    region = next(row for row in graph.regions if row.id == interface.region)
    entry = next(block for block in region.blocks if block.id == region.entry)
    operand = ReferenceValue(ValueID('initial.effective.operand'), region.id,
                             BlockArgument(entry.id, len(entry.arguments)))
    graph = replace(graph, values=(*graph.values, operand), regions=tuple(replace(row,
        blocks=tuple(replace(block, arguments=(*block.arguments, operand.id))
                     if block.id == entry.id else block for block in row.blocks))
        if row.id == region.id else row for row in graph.regions))
    region = next(row for row in graph.regions if row.id == interface.region)
    first = next(block for block in region.blocks if block.id == request['admitted'])
    # The association's normal tuple is B,L,S,R followed by all current states.
    body, latent = first.arguments[:2]
    graph, phase = _guard(graph, block_id=first.id, owner=body, raw=latent,
        label='initial.body.created', rule=BodyStatePredicateRule.IS_CREATED,
        admit_true=start)
    none = None
    if start:
        region = next(row for row in graph.regions if row.id == interface.region)
        block = next(block for block in region.blocks if block.id == phase['admitted'])
        graph, none = _guard(graph, block_id=block.id, owner=block.arguments[0],
            raw=block.arguments[1], label='initial.operand.none', input_value=operand.id,
            request_kind=RawRequestKind.SEND)
    rows = []
    processing = []
    for row in graph.protocol_operations:
        if type(row.contract) is AdmissionPredicate and row.operation in (
                phase['predicate'], None if none is None else none['predicate']):
            row = replace(row, clause=ProtocolClause.ASYNC_REQUEST_SOURCE)
        elif type(row.contract) is RequestProcessing and row.operation == phase['helper']:
            operation = _op(graph, row.operation)
            row = replace(row, clause=ProtocolClause.ASYNC_REQUEST_DELIVERY,
                contract=replace(row.contract, raw_use=operation.invoke_arguments[0],
                                 rule=RequestProcessingRule.CHECK_ASYNC_REQUEST))
        elif none is not None and type(row.contract) is RequestProcessing and row.operation == none['helper']:
            operation = _op(graph, row.operation)
            expanded = _use('initial.check.operand', operand.id)
            if not any(use.id == expanded.id for use in operation.uses):
                operation = replace(operation, uses=(*operation.uses, expanded),
                    invoke_arguments=(*operation.invoke_arguments, expanded.id))
                graph = replace(graph, operations=tuple(operation if old.id == operation.id else old
                                                        for old in graph.operations))
            row = replace(row, clause=ProtocolClause.ASYNC_REQUEST_DELIVERY,
                contract=replace(row.contract, operand_bindings=(RequestOperandBinding(0, expanded.id),),
                                 rule=RequestProcessingRule.CHECK_INITIAL_ASEND))
            processing.append(row)
        rows.append(row)
    graph = replace(graph, protocol_operations=tuple(rows))
    return graph, {'request': request, 'phase': phase, 'none': none,
                   'operand': operand, 'processing': tuple(processing)}


def _complete_rejected_request(graph, guard):
    """Close R before its error boundary, without a body outcome or F."""
    interface, = graph.driver_interfaces
    region = next(row for row in graph.regions if row.id == interface.region)
    block = next(row for row in region.blocks if row.id == guard['rejected'])
    values = {row.id: row for row in graph.values}
    current = {values[identity].location: identity for identity in block.arguments
               if type(values[identity]) is StateVersionValue}
    identity = OperationID('initial.rejected.complete')
    receiver = _use('initial.rejected.request', interface.receiver)
    body = _use('initial.rejected.body', block.arguments[0])
    uses, accesses, results, substitution = [receiver, body], [], [], {}
    for ordinal, location in enumerate(interface.lifecycle):
        before = _use(f'initial.rejected.before.{ordinal}', current[location], state=True)
        uses.append(before)
        if ordinal == 0:
            after = StateVersionValue(ValueID(f'initial.rejected.after.{ordinal}'), region.id,
                                      OperationResult(identity, len(results)), location)
            results.append(after)
            substitution[before.value] = after.id
            accesses.append(StateAccess(location, before.id, AccessMode.READ_WRITE, after.id,
                                        Footprint(FootprintKind.WHOLE)))
        else:
            accesses.append(StateAccess(location, before.id, AccessMode.READ,
                                        footprint=Footprint(FootprintKind.WHOLE)))
    operation = Operation(identity, 'complete this failed initial request',
        (Behavior.CONTROL, Behavior.READ, Behavior.WRITE), tuple(uses),
        tuple(value.id for value in results), tuple(accesses), effects_complete=True)
    helper = _op(graph, guard['helper'])
    helper = replace(helper, uses=tuple(replace(use, value=substitution.get(use.value, use.value))
                                       for use in helper.uses))
    update = SessionUpdate(identity, receiver.id, body.id, LifecyclePostBinding.AFTER_OPERATION,
                           SessionPost.COMPLETE)
    graph = replace(graph, values=(*graph.values, *results),
        operations=(*(helper if old.id == helper.id else old for old in graph.operations), operation),
        regions=tuple(replace(row, blocks=tuple(replace(candidate,
            operations=(operation.id, *candidate.operations)) if candidate.id == block.id else candidate
            for candidate in row.blocks)) if row.id == region.id else row for row in graph.regions),
        session_updates=(*graph.session_updates, update))
    return graph, update


def _component(body, number, *, reject=False, reject_raised=False, last=False):
    graph, request = _last_stage(body) if last else _pipeline_stage(body, number)
    controls, complete = None, None
    if number == 0 or last:
        graph, controls = _initial_guards(graph, request, start=not last)
    if reject:
        graph, complete = _complete_rejected_request(graph, controls['none'])
    part = _driver_component(graph, f'initial.driver.{number}' + ('.reject' if reject else ''))
    rename = part['rename']
    interface, = part['driver_interfaces']
    gate, = part['final_body_gates']
    drive, = part['body_drives']
    publication, = part['body_outcome_commits']
    request = rename(request)
    controls = None if controls is None else rename(controls)
    complete = None if complete is None else rename(complete)
    operations = {row.id: row for row in part['operations']}
    drive_operation = operations[drive.operation]
    selected = next(index for index, edge in enumerate(drive_operation.terminator.successors)
                    if edge.source == publication.outcome.source)
    choices = {row.id: 0 for row in part['operations'] if row.terminator is not None
               and row.terminator.successors}
    choices[request['branch']] = 0 if number == 0 or last else 1
    choices[drive.operation] = selected
    if controls is not None:
        choices[controls['phase']['branch']] = 1 if last else 0
        if controls['none'] is not None:
            choices[controls['none']['branch']] = 1 if reject else 0
    if reject:
        choices[controls['none']['helper']] = int(reject_raised)
        terminal = operations[controls['none']['terminals'][int(reject_raised)]]
    else:
        terminal = operations[rename(OperationID('adapter.normal.exit')) if number == 2 or last
                              else rename(OperationID('driver.outcome.exit'))]
    update = next(row for row in part['session_updates'] if row != complete)
    details = {'driver_region': part['region'], 'interface': interface, 'gate': gate,
        'drive': drive, 'publication': publication, 'outcome': publication.outcome,
        'outcome_source': publication.outcome.source, 'update': update,
        'association_read': part['request_association_reads'][0], 'predicate': request,
        'initial_controls': controls, 'reject_complete': complete, 'host_terminal': terminal,
        'path_choices': choices, 'reject': reject, 'entry_formals': next(
            row.arguments for row in part['region'].blocks if row.id == part['region'].entry)}
    return part, details


def async_initial_control_program(*, scenario='created-none', reject_raised=False):
    """One Create B; selected requests are separate real AsyncRequestCreate rows."""
    if scenario not in ('created-none', 'created-reject', 'suspended-new'):
        raise ValueError('unknown initial-control scenario')
    if type(reject_raised) is not bool or reject_raised and scenario != 'created-reject':
        raise ValueError('reject_raised applies only to the created-reject scenario')
    body = _three_cut_body()
    stages = []
    if scenario == 'created-reject':
        stages.append(_component(body, 0, reject=True, reject_raised=reject_raised))
    stages.extend(_component(body, number) for number in range(3))
    if scenario == 'suspended-new':
        stages.append(_component(body, 3, last=True))
    domains = tuple(row.location for row in stages[0][0]['values']
                    if type(row) is StateVersionValue and type(row.origin) is BlockArgument
                    and row.origin.block == stages[0][0]['region'].entry)
    state_types = tuple(ValueType(ValueKind.STATE, location=location) for location in domains)
    b = _Builder('async.initial.caller', domains)
    body_region = body.regions[0]
    body_values = {value.id: value for value in body.values}
    body_entry = next(block for block in body_region.blocks if block.id == body_region.entry)
    captures = tuple(value for value in body_entry.arguments if type(body_values[value]) is ReferenceValue)
    entry = b.formals('initial.entry', (*(REFERENCE for _ in range(len(captures) + 2)), *state_types))
    none = ReferenceValue(ValueID('initial.literal.none'), b.region, LiteralOrigin(None), targets=())
    nonnone = ReferenceValue(ValueID('initial.literal.non_none'), b.region, LiteralOrigin(61), targets=())
    b.values.extend((none, nonnone))
    created = b.formals('initial.body.created', (REFERENCE, *state_types))
    failed = b.formals('initial.body.failed', (PACKET, *state_types))
    actuals = tuple(_use(f'initial.create.input.{ordinal}', value, state=ordinal >= len(captures))
                    for ordinal, value in enumerate((*entry[:len(captures)], *entry[-len(domains):])))
    create = b.add('initial.body.create', actuals, effects_complete=True,
        invoke_arguments=tuple(use.id for use in actuals),
        completions=(CompletionSignature(ExitKind.NORMAL, (REFERENCE, *state_types)),
                     CompletionSignature(ExitKind.RAISE, (PACKET, *state_types))),
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, BlockID('initial.body.created'),
                tuple(CompletionResult(index) for index in range(1 + len(domains)))),
            CompletionSuccessor(ExitKind.RAISE, BlockID('initial.body.failed'),
                tuple(CompletionResult(index) for index in range(1 + len(domains)))))))
    capture_rows = tuple(CreationCapture(formal, use.id) for formal, use in zip(captures, actuals))
    function = next(member.reference for member in body.environments[0].members
                    if member.role is EnvironmentRole.FUNCTION_OBJECT)
    creation = ResumableCreate(create.id, body_region.id,
        next(row.source for row in capture_rows if row.formal == function), capture_rows,
        NormalResultPort(0), driver_rule())
    b.block('initial.entry', entry, (create,))
    b.block('initial.body.failed', failed, (b.terminal('initial.body.failed.exit', failed, fail=True),))
    current_block, current_formals = 'initial.body.created', created
    current_body, current_states = created[0], created[1:]
    current_request, current_operand = None, None
    request_rows, requests, raw_definitions, calls, selected_choices = [], [], [], [], {create.id: 0}
    parts, drivers = [], []
    request_number = 0
    for ordinal, (part, item) in enumerate(stages):
        new_request = ordinal == 0 or scenario == 'created-reject' and ordinal == 1 or item['outcome_source'] == OperationID('pipeline.done.return')
        operations_before = []
        if new_request:
            current_operand = nonnone if item['reject'] or ordinal > 0 and scenario == 'suspended-new' else none
            prefix = f'initial.request.{request_number}'
            latent_operand = _use(prefix + '.operand', current_operand.id)
            latent = b.value(prefix + '.latent', OperationResult(OperationID(prefix + '.pack'), 0), RAW)
            pack = b.add(prefix + '.pack', (latent_operand,), results=(latent,), effects_complete=True)
            definition = RawRequestDefinition(latent, RawRequestKind.SEND, (latent_operand.id,))
            raw_definitions.append(definition)
            normal = b.formals(prefix + '.normal', (REFERENCE, REFERENCE, *state_types))
            error = b.formals(prefix + '.raise', (PACKET, *state_types))
            inputs = (_use(prefix + '.body', current_body), _use(prefix + '.raw', latent, protocol=True),
                *(_use(prefix + f'.state.{index}', state, state=True) for index, state in enumerate(current_states)))
            forwarded = _use(prefix + '.forward.body', current_body)
            operation = b.add(prefix + '.create', (*inputs, forwarded), effects_complete=True,
                invoke_arguments=tuple(use.id for use in inputs),
                completions=(CompletionSignature(ExitKind.NORMAL, (REFERENCE, *state_types)),
                             CompletionSignature(ExitKind.RAISE, (PACKET, *state_types))),
                terminator=Terminator(TerminatorKind.INVOKE, (
                    CompletionSuccessor(ExitKind.NORMAL, BlockID(prefix + '.normal'),
                        (CompletionResult(0), forwarded.id, *(CompletionResult(i + 1) for i in range(len(domains))))),
                    CompletionSuccessor(ExitKind.RAISE, BlockID(prefix + '.raise'),
                        tuple(CompletionResult(i) for i in range(1 + len(domains)))))))
            row = AsyncRequestCreate(operation.id, inputs[0].id, inputs[1].id,
                                     NormalResultPort(0), driver_rule())
            request_rows.append(row)
            requests.append({'create': row, 'operation': operation, 'latent': definition,
                'operand': current_operand, 'result': InvokeLiteralResult(
                    ControlEdgeReference(operation.id, 0), CompletionResult(0))})
            b.block(current_block, current_formals, (*operations_before, pack, operation))
            b.block(prefix + '.raise', error, (b.terminal(prefix + '.raise.exit', error, fail=True),))
            selected_choices[operation.id] = 0
            current_block, current_formals = prefix + '.normal', normal
            current_request, current_body, *current_states = normal
            request_number += 1
        prefix = f'initial.call.{ordinal}'
        resumed = not item['reject'] and item['initial_controls'] is None
        scheduler_inputs = (_use(prefix + '.sent', entry[len(captures) + (1 if item['outcome_source'] == OperationID('pipeline.item.suspend') else 0)]),) if resumed else ()
        scheduler = b.value(prefix + '.scheduler', OperationResult(OperationID(prefix + '.pack'), 0), RAW)
        scheduler_pack = b.add(prefix + '.pack', scheduler_inputs, results=(scheduler,), effects_complete=True)
        raw_definitions.append(RawRequestDefinition(scheduler, RawRequestKind.SEND if resumed else RawRequestKind.NEXT,
                                                   tuple(use.id for use in scheduler_inputs)))
        interface = item['interface']
        driver_values = {row.id: row for row in part['values']}
        actual_values = []
        for formal in item['entry_formals']:
            value = driver_values[formal]
            if formal == interface.receiver:
                actual = current_request
            elif formal == interface.scheduler_request:
                actual = scheduler
            elif type(value) is StateVersionValue:
                actual = current_states[domains.index(value.location)]
            elif formal == item['entry_formals'][0]:
                actual = current_body
            elif resumed:
                actual = scheduler_inputs[0].value
            else:
                actual = current_operand.id
            actual_values.append(actual)
        inputs = tuple(_use(prefix + f'.actual.{index}', actual,
            state=type(driver_values[formal]) is StateVersionValue,
            protocol=type(driver_values[formal]) not in (StateVersionValue, ReferenceValue))
            for index, (formal, actual) in enumerate(zip(item['entry_formals'], actual_values)))
        successors, forwards, landings = [], [], {}
        for exit_ in item['driver_region'].exits:
            name = prefix + '.' + exit_.kind.value.lower()
            args = b.formals(name, (REFERENCE, REFERENCE, *exit_.types))
            forward_r, forward_b = _use(name + '.request', current_request), _use(name + '.body', current_body)
            forwards.extend((forward_r, forward_b))
            successors.append(CompletionSuccessor(exit_.kind, BlockID(name),
                (forward_r.id, forward_b.id, *(CompletionResult(i) for i in range(len(exit_.types))))))
            landings[exit_.kind] = (name, args)
        call = b.add(prefix, (*inputs, *forwards), callee=item['driver_region'].id,
            effects_complete=True, invoke_arguments=tuple(use.id for use in inputs),
            completions=tuple(CompletionSignature(exit_.kind, exit_.types) for exit_ in item['driver_region'].exits),
            terminator=Terminator(TerminatorKind.INVOKE, tuple(successors)))
        b.block(current_block, current_formals, (scheduler_pack, call))
        wanted = ExitKind.RAISE if item['host_terminal'].terminator.kind is TerminatorKind.RAISE else ExitKind.NORMAL
        selected_choices[call.id] = next(index for index, edge in enumerate(successors) if edge.kind is wanted)
        for kind, (name, args) in landings.items():
            if kind is not wanted or ordinal == len(stages) - 1:
                b.block(name, args, (b.terminal(name + '.exit', args[2:], fail=kind is ExitKind.RAISE),))
        current_block, current_formals = landings[wanted]
        current_request, current_body = current_formals[:2]
        current_states = current_formals[3:]
        item = {**item, 'caller_call': call, 'request': requests[-1],
                'effective_operand': current_operand, 'scheduler': raw_definitions[-1]}
        parts.append(part)
        drivers.append(item)
        calls.append(call)
    caller = b.finish('initial.entry')
    # Preserve every declared exit which really occurs, including untaken ones.
    actual_kinds = {operation.terminator.kind for operation in b.operations
                    if operation.terminator is not None and operation.terminator.kind in
                    (TerminatorKind.RETURN, TerminatorKind.RAISE)}
    caller = replace(caller, exits=tuple(exit_ for exit_ in caller.exits if
        (TerminatorKind.RETURN if exit_.kind is ExitKind.NORMAL else TerminatorKind.RAISE) in actual_kinds))
    graph = replace(body, root=caller.id, locations=(*body.locations,
        *(StateLocation(location, 'driver-only contents') for location in domains
          if location not in {row.id for row in body.locations})),
        regions=(caller, replace(body_region, parent=caller.id),
                 *(replace(part['region'], parent=caller.id) for part in parts)),
        operations=(*body.operations, *(operation for part in parts for operation in part['operations']), *b.operations),
        values=(*body.values, *(value for part in parts for value in part['values']), *b.values),
        control_scopes=(*body.control_scopes, *(scope for part in parts for scope in part['control_scopes']),
            ControlScope(ControlScopeID('initial.caller.scope'), caller.id, None, ControlScopeKind.FUNCTION,
                          _source('supplied initial ASEND caller'), tuple(block.id for block in caller.blocks))),
        resumable_creates=(creation,), async_request_creates=tuple(request_rows),
        raw_driver_requests=tuple(raw_definitions),
        **{name: tuple(row for part in parts for row in part[name]) for name in _TABLES})
    for item in drivers:
        item['path'] = _selected_path(graph, item['driver_region'], item['path_choices'])
    predicates = tuple(row for row in graph.protocol_operations if type(row.contract) is AdmissionPredicate)
    processing = tuple(row for row in graph.protocol_operations if type(row.contract) is RequestProcessing
                       and row.contract.rule is RequestProcessingRule.CHECK_INITIAL_ASEND)
    details = {'caller': caller, 'caller_path': _selected_path(graph, caller, selected_choices),
        'body': body_region, 'primary_creation': creation, 'drivers': tuple(drivers), 'calls': tuple(calls),
        'scenario': scenario, 'reject_raised': reject_raised, 'requests': tuple(requests),
        'body_definition': {'region': body_region, 'create': creation,
            'await1': _op(graph, OperationID('resume.suspend')),
            'await2': _op(graph, OperationID('resume.second.suspend')),
            'async_yield': _op(graph, OperationID('pipeline.item.suspend'))},
        'initial_control': {'predicates': predicates, 'processing': processing,
            'request_creates': tuple(request_rows), 'latent_definitions': tuple(request['latent'] for request in requests),
            'effective_operand': requests[0]['operand'],
            'reject_driver': drivers[0] if scenario == 'created-reject' else None,
            'reject_helper': drivers[0]['initial_controls']['none']['helper'] if scenario == 'created-reject' else None,
            'reject_complete': drivers[0]['reject_complete'] if scenario == 'created-reject' else None,
            'reject_terminals': drivers[0]['initial_controls']['none']['terminals'] if scenario == 'created-reject' else ()},
        'initial_states': entry[-len(domains):], 'root_entry': entry, 'capture_formals': captures}
    return graph, details
