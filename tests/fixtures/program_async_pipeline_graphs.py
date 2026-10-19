"""Continuous async request fixtures over canonical ports, never native capture."""
from dataclasses import fields, is_dataclass, replace

from scar.ir.program.lifecycle import SessionPost
from scar.ir.program.model import OperationResult, TerminatorKind
from scar.ir.program.protocol_connections import AsyncSessionOutcome
from tests.fixtures.program_async_connections import async_driver_program


def await_handoff_program(*, wrong=False):
    """Keep a real AWAIT source and optionally return R instead of its export."""
    graph, details = async_driver_program(flavor='AWAIT')
    update = details['updates'][0]
    region = next(row for row in graph.regions if row.id == details['interface'].region)
    block = next(row for row in region.blocks if update.operation in row.operations)
    terminal = next(row for row in graph.operations if row.id == block.operations[-1])
    if terminal.terminator.kind is not TerminatorKind.RETURN:
        raise AssertionError('AWAIT handoff needs its actual host RETURN')
    payload = terminal.terminator.values[0]
    original = next(use for use in terminal.uses if use.id == payload)
    if wrong:
        terminal = replace(terminal, uses=tuple(
            replace(use, value=details['interface'].receiver) if use.id == payload else use
            for use in terminal.uses))
        graph = replace(graph, operations=tuple(terminal if row.id == terminal.id else row
                                                 for row in graph.operations))
    return graph, {**details, 'host_terminal': terminal, 'host_payload_use': payload,
                   'original_handoff_value': original.value, 'expected_post': SessionPost.HOLD}


def missing_session_update_program():
    """Remove post declarations, preserving the source and all real operations."""
    graph, details = await_handoff_program()
    graph = replace(graph, session_updates=(), protocol_bindings=tuple(
        row for row in graph.protocol_bindings if type(row) is not AsyncSessionOutcome))
    return graph, details


__all__ = ['await_handoff_program', 'missing_session_update_program']


def _three_cut_body():
    """Extend the original saved/current-state path with one real item cut."""
    from scar.ir.program.control import ProtocolValueKind as P
    from scar.ir.program.ids import BlockID, OperationID, ValueID
    from scar.ir.program.model import Behavior, LiteralOrigin, ReferenceValue, Terminator, UseRole
    from scar.ir.program.resumption import (ResumableKind, ResumeInput, ResumeSlot,
        ResumeSlotKind as I, ResumeSuccessor, SavedInput, SavedRole, SavedSlot,
        SuspendTerminator, SuspensionFlavor)
    from tests.fixtures.program_driver_graphs import _body_with_environment
    from tests.fixtures.program_resumption_graphs import _Body, _use, resumption_two_cuts_program

    original = resumption_two_cuts_program()
    template = _body_with_environment()
    b = _Body('resume')
    b.values = list(original.values)
    b.operations = [op for op in original.operations if op.id != OperationID('resume.second.return')]
    b.blocks = list(original.regions[0].blocks)
    b.initials = list(original.frame_context_initials)
    b.attaches = list(original.frame_context_attaches)
    b.detaches = list(original.frame_context_detaches)
    old_return = next(op for op in original.operations if op.id == OperationID('resume.second.return'))
    export = _use('pipeline.item.export', old_return.uses[0].value, UseRole.REFERENCE)
    frame = _use('pipeline.item.frame', ValueID('resume.second.detach.frame'))
    world = _use('pipeline.item.world', old_return.uses[1].value, UseRole.STATE_CONTENT)
    context = _use('pipeline.item.context', old_return.uses[2].value, UseRole.STATE_CONTENT)
    done = BlockID('pipeline.body.done')
    formals = (b.argument('pipeline.done.world', done.value, 0, b.world),
        b.argument('pipeline.done.frame', done.value, 1, P.FRAME_CONTEXT),
        b.argument('pipeline.done.sent', done.value, 2, 'reference'),
        b.argument('pipeline.done.context', done.value, 3, b.context))
    item = b.add('pipeline.item.suspend', (Behavior.CONTROL,), (export, frame, world, context),
        effects_complete=True, terminator=SuspendTerminator(SuspensionFlavor.ASYNC_YIELD,
            export.id, (SavedSlot(SavedRole.FRAME_CONTEXT, frame.id),), (world.id, context.id),
            (ResumeSuccessor((ResumeSlot(I.STATE, b.context), ResumeSlot(I.SENT_VALUE),
                              ResumeSlot(I.STATE, b.world)), done,
                             (ResumeInput(2), SavedInput(0), ResumeInput(1), ResumeInput(0))),)))
    caller, attached = b.switch('pipeline.done.attach', formals[1], formals[3], attach=True)
    _, detached = b.switch('pipeline.done.detach', caller, attached, attach=False)
    none = ReferenceValue(ValueID('pipeline.body.none'), b.region, LiteralOrigin(None), targets=())
    b.values.append(none)
    uses = (_use('pipeline.done.return.value', none.id, UseRole.REFERENCE),
            _use('pipeline.done.return.world', formals[0], UseRole.STATE_CONTENT),
            _use('pipeline.done.return.context', detached, UseRole.STATE_CONTENT))
    terminal = b.add('pipeline.done.return', (Behavior.CONTROL,), uses, effects_complete=True,
        terminator=Terminator(TerminatorKind.RETURN, exit='normal', values=tuple(use.id for use in uses)))
    b.blocks = [replace(block, operations=(*block.operations[:-1], item.id))
                if old_return.id in block.operations else block for block in b.blocks]
    b.block(done.value, formals, ('pipeline.done.attach', 'pipeline.done.detach', terminal.id.value))
    graph = b.finish(original.regions[0].entry.value, original.regions[0].exits)
    environment = template.environments[0]
    env_ids = {member.reference for member in environment.members}
    env_values = tuple(value for value in template.values if value.id in env_ids)
    body = graph.regions[0]
    body = replace(body, blocks=tuple(replace(block,
        arguments=(*block.arguments, *(member.reference for member in environment.members)))
        if block.id == body.entry else block for block in body.blocks))
    graph = replace(graph, regions=(body,), values=(*graph.values, *env_values),
        environments=template.environments, function_entries=template.function_entries,
        resumable_bodies=tuple(replace(row, kind=ResumableKind.ASYNC_GENERATOR)
                              for row in graph.resumable_bodies),
        operations=tuple(replace(op, terminator=replace(op.terminator, flavor=SuspensionFlavor.AWAIT))
            if op.id in (OperationID('resume.suspend'), OperationID('resume.second.suspend')) else op
            for op in graph.operations))
    return graph


def _pipeline_stage(body, number, *, helper=False):
    """One request iterator call, retaining its actual host boundary."""
    from scar.ir.program.drivers import RawRequestKind
    from scar.ir.program.ids import BlockID, OperationID, ProtocolScopeID
    from scar.ir.program.model import CompletionResult, ExitKind, InvokeLiteralResult, StateVersionValue
    from scar.ir.program.protocol_connections import RequestAssociation, RequestStateCondition, RequestStateRule
    from scar.ir.program.protocols import (AdmissionPredicate, BodyStatePredicateRule, DriverSubject,
        OutcomeAdapter, OutcomeAdapterRule, ProtocolClause, ProtocolOperation, ProtocolProfile,
        ProtocolScope, RequestProcessing, RequestProcessingRule)
    from scar.ir.program.state_addresses import InvokeStateOperand
    from scar.ir.program.structured import ControlEdgeReference
    from tests.fixtures.program_async_connections import _association
    from tests.fixtures.program_driver_graphs import driver_program
    from tests.fixtures.program_generator_admission_graphs import _guard
    from tests.fixtures.program_protocol_graphs import _adapt_return, _source_gap
    from tests.fixtures.program_publication_graphs import with_publications
    from tests.fixtures.program_session_release_graphs import _Tail

    target = ('resume.suspend', 'resume.suspend', 'resume.second.suspend')[number]
    selected_body = replace(body, operations=tuple(sorted(body.operations,
        key=lambda op: op.id != OperationID(target))))
    graph = driver_program(target='start' if number == 0 else 'value', async_request=True,
                           extra_domain=True, body_graph=selected_body)
    graph, association = _association(graph)
    interface, = graph.driver_interfaces
    scope = ProtocolScope(ProtocolScopeID('async.scope'), ProtocolProfile.ASYNC_GENERATOR_BODY_V1,
                          DriverSubject(interface.region), _source_gap())
    graph = replace(graph, protocol_scopes=(scope,))
    if number == 2:
        graph = _adapt_return(graph, scope.id)
        graph = replace(graph, protocol_operations=tuple(replace(row,
            clause=ProtocolClause.ASYNC_ITEM_ADAPTER,
            contract=replace(row.contract, rule=OutcomeAdapterRule.ASYNCGEN_YIELD_TO_REQUEST_ITEM))
            if type(row.contract) is OutcomeAdapter else row for row in graph.protocol_operations))
    graph = with_publications(graph)
    commit, = graph.body_outcome_commits
    tail = _Tail(graph, commit.operation)
    post = SessionPost.COMPLETE if number == 2 else SessionPost.HOLD
    if helper:
        tail.invoke('async.session.helper', post)
    else:
        tail.metadata(post, 'async.session.metadata')
    graph = tail.finish()
    read, = graph.request_association_reads
    op = next(row for row in graph.operations if row.id == read.operation)
    normal = next(index for index, edge in enumerate(op.terminator.successors) if edge.kind is ExitKind.NORMAL)
    association_row = ProtocolOperation(scope.id, ProtocolClause.ASYNC_REQUEST_ASSOCIATE, op.id, 0,
        RequestAssociation(read.request,
            InvokeLiteralResult(ControlEdgeReference(op.id, normal), CompletionResult(read.body_result.index)),
            InvokeLiteralResult(ControlEdgeReference(op.id, normal), CompletionResult(read.latent_result.index)),
            tuple(InvokeStateOperand(op.id, use.id) for use in op.uses if use.id in op.invoke_arguments
                  and isinstance(next(value for value in graph.values if value.id == use.value), StateVersionValue))),
        _source_gap())
    graph = replace(graph, protocol_operations=(*graph.protocol_operations, association_row),
        protocol_bindings=tuple(AsyncSessionOutcome(scope.id, update.operation, commit.outcome)
                                for update in graph.session_updates))
    graph, predicate = _guard(graph, block_id=BlockID('driver.no_body.test'),
        owner=association['session'], raw=association['scheduler'], label='pipeline.request.step',
        rule=BodyStatePredicateRule.IS_CREATED, request_kind=RawRequestKind.NEXT, admit_true=number == 0)
    rows = []
    for row in graph.protocol_operations:
        if type(row.contract) is AdmissionPredicate and row.operation == predicate['predicate']:
            subject = row.contract.subject
            row = replace(row, clause=ProtocolClause.ASYNC_REQUEST_SOURCE,
                contract=replace(row.contract, subject=RequestStateCondition(subject.instance_use,
                    subject.state_sites, RequestStateRule.IS_INITIAL_STEP)))
        elif type(row.contract) is RequestProcessing and row.operation == predicate['helper']:
            operation = next(op for op in graph.operations if op.id == row.operation)
            row = replace(row, clause=ProtocolClause.ASYNC_REQUEST_DELIVERY,
                contract=replace(row.contract, raw_use=operation.invoke_arguments[0],
                                 rule=RequestProcessingRule.CHECK_ASYNC_REQUEST))
        rows.append(row)
    return replace(graph, protocol_operations=tuple(rows)), predicate


def _driver_component(graph, prefix):
    """Reuse the original driver renaming and include its async side records."""
    from tests.fixtures.program_generator_close_retry_graphs import _driver_part
    part, maps = _driver_part(graph, prefix)

    def rename(value):
        if type(value) in maps:
            return maps[type(value)].get(value, value)
        if type(value) is tuple:
            return tuple(rename(item) for item in value)
        if type(value) is dict:
            return {rename(key): rename(item) for key, item in value.items()}
        if is_dataclass(value):
            return replace(value, **{field.name: rename(getattr(value, field.name)) for field in fields(value)})
        return value

    for name in ('request_association_reads', 'session_updates', 'protocol_bindings',
                 'protocol_call_inputs', 'protocol_result_consumers'):
        part[name] = rename(getattr(graph, name))
    part['rename'] = rename
    return part


def _selected_path(graph, region, choices):
    """Expose explicitly selected original block edges to the occurrence fixture."""
    blocks = {block.id: block for block in region.blocks}
    operations = {op.id: op for op in graph.operations}
    current, path, seen = region.entry, [], set()
    while current not in seen:
        seen.add(current)
        operation = operations[blocks[current].operations[-1]]
        if operation.terminator.kind in (TerminatorKind.RETURN, TerminatorKind.RAISE):
            path.append((current, None))
            return tuple(path)
        selected = choices[operation.id]
        path.append((current, selected))
        current = operation.terminator.successors[selected].block
    raise AssertionError('the supplied main capture path must be finite')


def async_pipeline_program(*, helper_stage=None):
    """One B/R, three real calls, two await handoffs and one item completion.

    This supplies a canonical declaration. It does not recover a Python source
    pipeline or prove that the declared request/body references are native ones.
    """
    from scar.ir.program.control import ControlScope, ControlScopeKind
    from scar.ir.program.drivers import (AsyncRequestCreate, CreationCapture, NormalResultPort,
        RawRequestDefinition, RawRequestKind, ResumableCreate)
    from scar.ir.program.environments import EnvironmentRole
    from scar.ir.program.ids import BlockID, ControlScopeID, OperationID, ValueID
    from scar.ir.program.model import (CompletionResult, CompletionSignature,
        CompletionSuccessor, ExitKind, InvokeLiteralResult, ReferenceValue, StateVersionValue, Terminator,
        ValueKind, ValueType, value_type)
    from scar.ir.program.structured import ControlEdgeReference
    from tests.fixtures.program_control_graphs import _source
    from tests.fixtures.program_driver_graphs import _Builder, _use, driver_rule, PACKET, RAW, REFERENCE

    if helper_stage is not None and (type(helper_stage) is not int or helper_stage not in (0, 1, 2)):
        raise ValueError('helper_stage must be None or an exact stage ordinal')
    body = _three_cut_body()
    stages = []
    for number in range(3):
        graph, predicate = _pipeline_stage(body, number, helper=helper_stage == number)
        component = _driver_component(graph, f'pipeline.driver.{number}')
        component['predicate'] = component['rename'](predicate)
        stages.append(component)
    domains = tuple(location.id for location in graph.locations)
    state_types = tuple(ValueType(ValueKind.STATE, location=location) for location in domains)
    b = _Builder('async.pipeline', domains)
    body_region = body.regions[0]
    values = {value.id: value for value in body.values}
    body_entry = next(block for block in body_region.blocks if block.id == body_region.entry)
    captures = tuple(value for value in body_entry.arguments if isinstance(values[value], ReferenceValue))
    entry = b.formals('pipeline.entry', (*(REFERENCE for _ in range(len(captures) + 2)), *state_types))
    initial_states = entry[-len(domains):]
    body_created = b.formals('pipeline.body.created', (REFERENCE, *state_types))
    body_failed = b.formals('pipeline.body.failed', (PACKET, *state_types))
    actuals = tuple(_use(f'pipeline.body.create.input.{index}', value, state=index >= len(captures))
                    for index, value in enumerate((*entry[:len(captures)], *initial_states)))
    create = b.add('pipeline.body.create', actuals, effects_complete=True,
        invoke_arguments=tuple(use.id for use in actuals),
        completions=(CompletionSignature(ExitKind.NORMAL, (REFERENCE, *state_types)),
                     CompletionSignature(ExitKind.RAISE, (PACKET, *state_types))),
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, BlockID('pipeline.body.created'),
                tuple(CompletionResult(index) for index in range(1 + len(domains)))),
            CompletionSuccessor(ExitKind.RAISE, BlockID('pipeline.body.failed'),
                tuple(CompletionResult(index) for index in range(1 + len(domains)))))))
    capture_rows = tuple(CreationCapture(formal, use.id) for formal, use in zip(captures, actuals))
    function = next(member.reference for member in body.environments[0].members
                    if member.role is EnvironmentRole.FUNCTION_OBJECT)
    creation = ResumableCreate(create.id, body_region.id,
        next(row.source for row in capture_rows if row.formal == function), capture_rows,
        NormalResultPort(0), driver_rule())
    b.block('pipeline.entry', entry, (create,))
    b.block('pipeline.body.failed', body_failed,
            (b.terminal('pipeline.body.failed.exit', body_failed, fail=True),))
    latent = b.value('pipeline.latent', OperationResult(OperationID('pipeline.latent.pack'), 0), RAW)
    latent_pack = b.add('pipeline.latent.pack', results=(latent,), effects_complete=True)
    request_created = b.formals('pipeline.request.created', (REFERENCE, REFERENCE, *state_types))
    request_failed = b.formals('pipeline.request.failed', (PACKET, *state_types))
    request_uses = (_use('pipeline.request.body', body_created[0]),
        _use('pipeline.request.latent', latent, protocol=True),
        *(_use(f'pipeline.request.state.{index}', state, state=True)
          for index, state in enumerate(body_created[1:])))
    forward_body = _use('pipeline.request.forward.body', body_created[0])
    request_create = b.add('pipeline.request.create', (*request_uses, forward_body), effects_complete=True,
        invoke_arguments=tuple(use.id for use in request_uses),
        completions=(CompletionSignature(ExitKind.NORMAL, (REFERENCE, *state_types)),
                     CompletionSignature(ExitKind.RAISE, (PACKET, *state_types))),
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, BlockID('pipeline.request.created'),
                (CompletionResult(0), forward_body.id,
                 *(CompletionResult(index + 1) for index in range(len(domains))))),
            CompletionSuccessor(ExitKind.RAISE, BlockID('pipeline.request.failed'),
                tuple(CompletionResult(index) for index in range(1 + len(domains)))))))
    request_row = AsyncRequestCreate(request_create.id, request_uses[0].id, request_uses[1].id,
                                     NormalResultPort(0), driver_rule())
    b.block('pipeline.body.created', body_created, (latent_pack, request_create))
    b.block('pipeline.request.failed', request_failed,
            (b.terminal('pipeline.request.failed.exit', request_failed, fail=True),))
    raw_definitions = [RawRequestDefinition(latent, RawRequestKind.NEXT, ())]
    calls, driver_details = [], []
    current_request, current_body, *current_states = request_created
    current_block = 'pipeline.request.created'
    for number, component in enumerate(stages):
        region = component['region']
        interface, = component['driver_interfaces']
        gate, = component['final_body_gates']
        drive, = component['body_drives']
        commit, = component['body_outcome_commits']
        update, = component['session_updates']
        scheduler_operands = (() if number == 0 else
            (_use(f'pipeline.scheduler.{number}.operand', entry[len(captures) + number - 1]),))
        scheduler = b.value(f'pipeline.scheduler.{number}',
            OperationResult(OperationID(f'pipeline.scheduler.{number}.pack'), 0), RAW)
        pack = b.add(f'pipeline.scheduler.{number}.pack', scheduler_operands, results=(scheduler,), effects_complete=True)
        raw_definitions.append(RawRequestDefinition(scheduler,
            RawRequestKind.NEXT if number == 0 else RawRequestKind.SEND,
            tuple(use.id for use in scheduler_operands)))
        driver_values = {value.id: value for value in component['values']}
        driver_entry = next(block for block in region.blocks if block.id == region.entry)
        actual_values = []
        for formal in driver_entry.arguments:
            value = driver_values[formal]
            if formal == interface.receiver:
                actual = current_request
            elif formal == interface.scheduler_request:
                actual = scheduler
            elif isinstance(value, StateVersionValue):
                actual = current_states[domains.index(value.location)]
            elif formal == driver_entry.arguments[0]:
                actual = current_body
            else:
                actual = entry[len(captures) + number - 1]
            actual_values.append(actual)
        uses = tuple(_use(f'pipeline.call.{number}.actual.{index}', actual,
            state=isinstance(driver_values[formal], StateVersionValue),
            protocol=not isinstance(driver_values[formal], (StateVersionValue, ReferenceValue)))
            for index, (formal, actual) in enumerate(zip(driver_entry.arguments, actual_values)))
        successors = []
        forwards = []
        normal_args = None
        for exit_ in region.exits:
            name = f'pipeline.call.{number}.{exit_.kind.value.lower()}'
            if exit_.kind is ExitKind.NORMAL:
                args = b.formals(name, (REFERENCE, REFERENCE, *exit_.types))
                copied_r = _use(f'pipeline.call.{number}.forward.request', current_request)
                copied_b = _use(f'pipeline.call.{number}.forward.body', current_body)
                forwards.extend((copied_r, copied_b))
                edge_args = (copied_r.id, copied_b.id,
                             *(CompletionResult(index) for index in range(len(exit_.types))))
                normal_args = args
            else:
                args = b.formals(name, exit_.types)
                edge_args = tuple(CompletionResult(index) for index in range(len(exit_.types)))
                b.block(name, args, (b.terminal(name + '.exit', args, fail=True),))
            successors.append(CompletionSuccessor(exit_.kind, BlockID(name), edge_args))
        call = b.add(f'pipeline.call.{number}', (*uses, *forwards), callee=region.id,
            effects_complete=True, invoke_arguments=tuple(use.id for use in uses),
            completions=tuple(CompletionSignature(exit_.kind, exit_.types) for exit_ in region.exits),
            terminator=Terminator(TerminatorKind.INVOKE, tuple(successors)))
        b.block(current_block, (request_created if number == 0 else prior_normal), (pack, call))
        calls.append(call)
        rename = component['rename']
        selected = next(index for index, edge in enumerate(next(op for op in component['operations']
            if op.id == drive.operation).terminator.successors) if edge.source == commit.outcome.source)
        operation_map = {op.id: op for op in component['operations']}
        selected_host = operation_map[rename(OperationID('adapter.normal.exit')) if number == 2
                                      else rename(OperationID('driver.outcome.exit'))]
        choices = {gate.operation: 0, drive.operation: selected,
            component['request_association_reads'][0].operation: 0,
            component['predicate']['branch']: 0 if number == 0 else 1}
        if helper_stage == number:
            choices[update.operation] = 0
        if number == 2:
            choices[rename(OperationID('adapter.construct'))] = 0
        driver_details.append({'caller_call': call, 'driver_region': region, 'interface': interface,
            'drive': drive, 'gate': gate, 'outcome': commit.outcome, 'update': update,
            'publication': commit, 'host_terminal': selected_host, 'selected_successor': selected,
            'association_read': component['request_association_reads'][0],
            'predicate': component['predicate'], 'path_choices': choices,
            'entry_formals': driver_entry.arguments,
            'host_kind': selected_host.terminator.kind, 'body_target': drive.target})
        if normal_args is not None:
            prior_normal = normal_args
            current_request, current_body = normal_args[:2]
            current_states = list(normal_args[3:])
            current_block = f'pipeline.call.{number}.normal'
    caller = b.finish('pipeline.entry')
    caller = replace(caller, exits=tuple(exit_ for exit_ in caller.exits if exit_.kind is ExitKind.RAISE))
    tables = ('driver_interfaces', 'final_body_gates', 'body_drives', 'driver_lifecycles',
        'body_outcome_commits', 'terminal_frame_releases', 'protocol_scopes', 'protocol_operations',
        'literal_evaluations', 'exception_packets', 'request_association_reads', 'session_updates',
        'protocol_bindings', 'protocol_call_inputs', 'protocol_result_consumers')
    graph = replace(body, root=caller.id,
        regions=(caller, replace(body_region, parent=caller.id),
                 *(replace(component['region'], parent=caller.id) for component in stages)),
        operations=(*body.operations, *(op for component in stages for op in component['operations']), *b.operations),
        values=(*body.values, *(value for component in stages for value in component['values']), *b.values),
        locations=graph.locations,
        control_scopes=(*body.control_scopes,
            *(scope for component in stages for scope in component['control_scopes']),
            ControlScope(ControlScopeID('pipeline.caller.function'), caller.id, None,
                ControlScopeKind.FUNCTION, _source('supplied async caller'), tuple(block.id for block in caller.blocks))),
        resumable_creates=(creation,), async_request_creates=(request_row,),
        raw_driver_requests=tuple(raw_definitions),
        **{name: tuple(row for component in stages for row in component[name]) for name in tables})
    for item in driver_details:
        item['path'] = _selected_path(graph, item['driver_region'], item['path_choices'])
    operations = {op.id: op for op in graph.operations}
    return graph, {'caller': caller, 'calls': tuple(calls), 'drivers': tuple(driver_details),
        'body': {'region': body_region, 'create': creation,
            'await1': operations[OperationID('resume.suspend')],
            'await2': operations[OperationID('resume.second.suspend')],
            'async_yield': operations[OperationID('pipeline.item.suspend')]},
        'request': {'request_create': request_row, 'operation': request_create,
            'request_result': InvokeLiteralResult(ControlEdgeReference(request_create.id, 0), CompletionResult(0)),
            'latent': latent, 'association_reads': tuple(component['request_association_reads'][0] for component in stages)},
        'raws': tuple(raw_definitions), 'root_entry': entry, 'initial_states': tuple(initial_states),
        'capture_formals': captures, 'helper_stage': helper_stage}


__all__.append('async_pipeline_program')


def _await_fork_body():
    """Two real first AWAIT frontiers, preserving their separate original ports."""
    from scar.ir.program.control import ProtocolValueKind as P
    from scar.ir.program.ids import BlockID, OperationID, UseID, ValueID
    from scar.ir.program.model import (AccessMode, Behavior, BlockArgument, DataValue,
        LiteralOrigin, ReferenceValue, StateAccess, Successor, Terminator, Use, UseRole)
    from scar.ir.program.resumption import (ResumableKind, ResumeInput, ResumeSlot,
        ResumeSlotKind as I, ResumeSuccessor, SavedInput, SavedRole, SavedSlot,
        SuspendTerminator, SuspensionFlavor)
    from tests.fixtures.program_driver_graphs import _body_with_environment
    from tests.fixtures.program_resumption_graphs import _Body, _use

    template = _body_with_environment()
    region = template.regions[0]
    entry = next(block for block in region.blocks if block.id == region.entry)
    initial, attached = OperationID('resume.initial'), OperationID('resume.attach')
    b = _Body('resume')
    b.operations = [op for op in template.operations if op.id in (initial, attached)]
    b.values = [value for value in template.values if
        isinstance(value.origin, BlockArgument) and value.origin.block == entry.id
        or isinstance(value.origin, OperationResult) and value.origin.operation in (initial, attached)]
    b.initials = list(template.frame_context_initials)
    b.attaches = [row for row in template.frame_context_attaches if row.operation == attached]
    x, world = entry.arguments[:2]
    context = ValueID('resume.attach.after')
    caller = ValueID('resume.attach.caller')
    predicate_id, branch_id = OperationID('pipeline.fork.read'), OperationID('pipeline.fork.branch')
    owner = Use(UseID('pipeline.fork.owner'), x, UseRole.REFERENCE)
    state = Use(UseID('pipeline.fork.state'), world, UseRole.STATE_CONTENT)
    result = DataValue(ValueID('pipeline.fork.bool'), region.id, OperationResult(predicate_id, 0), 'builtins.bool')
    b.values.append(result)
    predicate = b.add(predicate_id.value, (Behavior.CONTROL, Behavior.READ), (owner, state), (result.id,),
        accesses=(StateAccess(b.world, state.id, AccessMode.READ),),
        effects_complete=True)
    condition = Use(UseID('pipeline.fork.condition'), result.id, UseRole.DATA)
    none = ReferenceValue(ValueID('pipeline.fork.none'), region.id, LiteralOrigin(None), targets=())
    b.values.append(none)
    branch_uses, successors, suspends = [condition], [], []
    for ordinal in range(2):
        name = f'pipeline.fork.arm.{ordinal}'
        arm = (b.argument(name + '.world', name, 0, b.world),
            b.argument(name + '.caller', name, 1, P.DRIVE_CALLER_CONTEXT),
            b.argument(name + '.context', name, 2, b.context),
            b.argument(name + '.x', name, 3, 'reference'))
        incoming = tuple(Use(UseID(f'pipeline.fork.edge.{ordinal}.{index}'), source, role)
            for index, (source, role) in enumerate(((world, UseRole.STATE_CONTENT),
                (caller, UseRole.PROTOCOL), (context, UseRole.STATE_CONTENT), (x, UseRole.REFERENCE))))
        branch_uses.extend(incoming)
        successors.append(Successor(BlockID(name), tuple(use.id for use in incoming)))
        frame, detached = b.switch(name + '.detach', arm[1], arm[2], attach=False)
        value_name, packet_name = name + '.value', name + '.packet'
        value_args = (b.argument(value_name + '.world', value_name, 0, b.world),
            b.argument(value_name + '.x', value_name, 1, 'reference'),
            b.argument(value_name + '.frame', value_name, 2, P.FRAME_CONTEXT),
            b.argument(value_name + '.sent', value_name, 3, 'reference'),
            b.argument(value_name + '.context', value_name, 4, b.context))
        packet_args = (b.argument(packet_name + '.context', packet_name, 0, b.context),
            b.argument(packet_name + '.frame', packet_name, 1, P.FRAME_CONTEXT),
            b.argument(packet_name + '.payload', packet_name, 2, P.EXCEPTION_PACKET),
            b.argument(packet_name + '.world', packet_name, 3, b.world),
            b.argument(packet_name + '.x', packet_name, 4, 'reference'))
        exported = _use(name + '.export', arm[3], UseRole.REFERENCE)
        saved_frame, saved_x = _use(name + '.frame', frame), _use(name + '.saved.x', arm[3], UseRole.REFERENCE)
        handoff = (_use(name + '.handoff.world', arm[0], UseRole.STATE_CONTENT),
                   _use(name + '.handoff.context', detached, UseRole.STATE_CONTENT))
        suspend = b.add(name + '.suspend', (Behavior.CONTROL,),
            (exported, saved_frame, saved_x, *handoff), effects_complete=True,
            terminator=SuspendTerminator(SuspensionFlavor.AWAIT, exported.id,
                (SavedSlot(SavedRole.FRAME_CONTEXT, saved_frame.id), SavedSlot(SavedRole.VALUE, saved_x.id)),
                tuple(use.id for use in handoff), (
                    ResumeSuccessor((ResumeSlot(I.STATE, b.context), ResumeSlot(I.SENT_VALUE),
                        ResumeSlot(I.STATE, b.world)), BlockID(value_name),
                        (ResumeInput(2), SavedInput(1), SavedInput(0), ResumeInput(1), ResumeInput(0))),
                    ResumeSuccessor((ResumeSlot(I.THROWN_PACKET), ResumeSlot(I.STATE, b.world),
                        ResumeSlot(I.STATE, b.context)), BlockID(packet_name),
                        (ResumeInput(2), SavedInput(0), ResumeInput(0), ResumeInput(1), SavedInput(1))))))
        suspends.append(suspend)
        b.block(name, arm, (name + '.detach', suspend.id.value))
        token, attached_context = b.switch(value_name + '.attach', value_args[2], value_args[4], attach=True)
        _, final_context = b.switch(value_name + '.detach', token, attached_context, attach=False)
        ret_uses = (_use(value_name + '.return.value', none.id, UseRole.REFERENCE),
            _use(value_name + '.return.world', value_args[0], UseRole.STATE_CONTENT),
            _use(value_name + '.return.context', final_context, UseRole.STATE_CONTENT))
        ret = b.add(value_name + '.return', (Behavior.CONTROL,), ret_uses, effects_complete=True,
            terminator=Terminator(TerminatorKind.RETURN, exit='normal', values=tuple(use.id for use in ret_uses)))
        b.block(value_name, value_args, (value_name + '.attach', value_name + '.detach', ret.id.value))
        token, attached_context = b.switch(packet_name + '.attach', packet_args[1], packet_args[0], attach=True)
        _, final_context = b.switch(packet_name + '.detach', token, attached_context, attach=False)
        raise_uses = (_use(packet_name + '.raise.packet', packet_args[2]),
            _use(packet_name + '.raise.world', packet_args[3], UseRole.STATE_CONTENT),
            _use(packet_name + '.raise.context', final_context, UseRole.STATE_CONTENT))
        raised = b.add(packet_name + '.raise', (Behavior.CONTROL,), raise_uses, effects_complete=True,
            terminator=Terminator(TerminatorKind.RAISE, exit='failure', values=tuple(use.id for use in raise_uses)))
        b.block(packet_name, packet_args, (packet_name + '.attach', packet_name + '.detach', raised.id.value))
    branch = b.add(branch_id.value, (Behavior.CONTROL,), tuple(branch_uses), effects_complete=True,
        terminator=Terminator(TerminatorKind.BRANCH, tuple(successors), condition=condition.id))
    b.block(entry.id.value, entry.arguments, (initial.value, attached.value, predicate.id.value, branch.id.value))
    graph = b.finish(entry.id.value, region.exits)
    return replace(graph, environments=template.environments, function_entries=template.function_entries,
        resumable_bodies=tuple(replace(row, kind=ResumableKind.ASYNC_GENERATOR) for row in graph.resumable_bodies)), tuple(suspends)


def shared_async_update_program(*, wrong_body_arm=None, omit_binding=None):
    """Two selected AWAIT sources meet one current-state HOLD post/host return."""
    from scar.ir.program.ids import BlockID, OperationID
    from scar.ir.program.lifecycle import LifecyclePostBinding, SessionUpdate
    from scar.ir.program.model import (AccessMode, Behavior, Block, Footprint, FootprintKind,
        Operation, StateAccess, StateVersionValue, Successor, Terminator, UseRole, value_type)
    from scar.ir.program.protocols import DriverSubject, ProtocolProfile, ProtocolScope
    from scar.ir.program.ids import ProtocolScopeID
    from scar.ir.program.structured import ControlEdgeReference
    from tests.fixtures.program_async_connections import _association
    from tests.fixtures.program_driver_graphs import _Builder, _use, driver_program, REFERENCE
    from tests.fixtures.program_protocol_graphs import _source_gap
    from tests.fixtures.program_publication_graphs import with_publications

    body, sources = _await_fork_body()
    graph, _ = _association(driver_program(body_graph=body, async_request=True, extra_domain=True))
    graph = with_publications(graph)
    interface, = graph.driver_interfaces
    scope = ProtocolScope(ProtocolScopeID('pipeline.shared.scope'), ProtocolProfile.ASYNC_GENERATOR_BODY_V1,
                          DriverSubject(interface.region), _source_gap())
    region = next(row for row in graph.regions if row.id == interface.region)
    values = {value.id: value for value in graph.values}
    operations = {op.id: op for op in graph.operations}
    blocks = {block.id: block for block in region.blocks}
    domains = tuple(location.id for location in graph.locations)
    b = _Builder(region.id.value, domains)
    state_types = tuple(value_type(values[value]) for value in blocks[region.entry].arguments
                        if isinstance(values[value], StateVersionValue))
    args = b.formals('pipeline.shared.merge', (REFERENCE, REFERENCE, REFERENCE, *state_types))
    request, owner, payload = args[:3]
    current = dict(zip(domains, args[3:]))
    incoming = []
    for ordinal, commit in enumerate(graph.body_outcome_commits):
        block = next(row for row in blocks.values() if commit.operation in row.operations)
        marker = operations[commit.operation]
        old_exit = operations.pop(block.operations[-1])
        body_value = next(use.value for use in marker.uses if use.id == commit.instance)
        states = {values[value].location: value for value in block.arguments
                  if isinstance(values[value], StateVersionValue)}
        for result in marker.results:
            states[values[result].location] = result
        actual_values = (interface.receiver, interface.receiver if wrong_body_arm == ordinal else body_value,
                         next(use.value for use in old_exit.uses if use.id == old_exit.terminator.values[0]),
                         *(states[location] for location in domains))
        actuals = tuple(_use(f'pipeline.shared.incoming.{ordinal}.{index}', value, state=index >= 3)
                        for index, value in enumerate(actual_values))
        jump = b.add(f'pipeline.shared.incoming.{ordinal}', actuals, effects_complete=True,
            terminator=Terminator(TerminatorKind.JUMP, (Successor(BlockID('pipeline.shared.merge'),
                tuple(use.id for use in actuals)),)))
        blocks[block.id] = replace(block, operations=(*block.operations[:-1], jump.id))
        incoming.append(ControlEdgeReference(jump.id, 0))
    operation = OperationID('pipeline.shared.post')
    role_uses = (_use('pipeline.shared.post.request', request), _use('pipeline.shared.post.body', owner))
    uses, results, accesses = list(role_uses), [], []
    for ordinal, location in enumerate(interface.lifecycle):
        before = _use(f'pipeline.shared.post.before.{ordinal}', current[location], state=True)
        after = b.value(f'pipeline.shared.post.after.{ordinal}', OperationResult(operation, len(results)),
                        state_types[domains.index(location)])
        uses.append(before)
        results.append(after)
        accesses.append(StateAccess(location, before.id, AccessMode.READ_WRITE, after, Footprint(FootprintKind.WHOLE)))
        current[location] = after
    post = Operation(operation, 'one shared current session post', (Behavior.CONTROL, Behavior.READ, Behavior.WRITE),
                     tuple(uses), tuple(results), tuple(accesses), effects_complete=True)
    b.operations.append(post)
    update = SessionUpdate(post.id, role_uses[0].id, role_uses[1].id,
                           LifecyclePostBinding.AFTER_OPERATION, SessionPost.HOLD)
    host = b.terminal('pipeline.shared.host', (payload, *(current[location] for location in domains)))
    b.block('pipeline.shared.merge', args, (post, host))
    region = replace(region, blocks=(*blocks.values(), *b.blocks))
    bindings = tuple(AsyncSessionOutcome(scope.id, update.operation, commit.outcome)
                     for ordinal, commit in enumerate(graph.body_outcome_commits) if omit_binding != ordinal)
    graph = replace(graph, regions=tuple(region if row.id == region.id else row for row in graph.regions),
        operations=(*operations.values(), *b.operations), values=(*graph.values, *b.values),
        protocol_scopes=(scope,), protocol_bindings=bindings, session_updates=(update,),
        control_scopes=tuple(replace(row, blocks=tuple(block.id for block in region.blocks))
            if row.region == region.id else row for row in graph.control_scopes))
    drive, = graph.body_drives
    drive_op = next(op for op in graph.operations if op.id == drive.operation)
    return graph, {'scope': scope, 'drive': drive, 'sources': sources,
        'outcomes': tuple(commit.outcome for commit in graph.body_outcome_commits),
        'selected_drive_edges': tuple(ControlEdgeReference(drive.operation, index)
                                      for index in range(len(drive_op.terminator.successors))),
        'incoming_edges': tuple(incoming), 'update': update, 'host_terminal': host,
        'merge': next(block for block in region.blocks if block.id == BlockID('pipeline.shared.merge')),
        'wrong_body_arm': wrong_body_arm, 'omit_binding': omit_binding}


__all__.append('shared_async_update_program')
