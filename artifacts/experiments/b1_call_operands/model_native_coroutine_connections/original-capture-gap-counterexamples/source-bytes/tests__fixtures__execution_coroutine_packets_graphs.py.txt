"""Supplied native coroutine THROW/CLOSE paths over two real AWAIT cuts.

The third normalizer has independent NORMAL and RAISE ports. Only NORMAL
enters the second cut's private packet landing; RAISE never drives the body.
"""
from dataclasses import fields, is_dataclass, replace

from scar.ir.program.control import ControlScope, ControlScopeKind, ExceptionPacketDefinition
from scar.ir.program.drivers import (
    CreationCapture, NormalResultPort, RawRequestDefinition, RawRequestKind, ResumableCreate,
)
from scar.ir.program.environments import EnvironmentRole
from scar.ir.program.ids import BlockID, ControlScopeID, OperationID, ProtocolScopeID, UseID, ValueID
from scar.ir.program.lifecycle import DriveOutcomeRef
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, CompletionResult, CompletionSignature, CompletionSuccessor,
    ExitKind, LiteralOrigin, Operation, OperationResult, ReferenceValue,
    Terminator, TerminatorKind, Use, UseRole, ValueKind, ValueType,
)
from scar.ir.program.protocol_connections import ProtocolOperationRef, ProtocolResultConsumers, ResumeSourceBinding
from scar.ir.program.protocols import (
    BodyStatePredicateRule, ContractResult, DriverSubject, DriveResult, HostTerminal,
    OutcomeAdapter, OutcomeAdapterRule, OwnedUse, ProtocolClause, ProtocolOperation,
    ProtocolProfile, ProtocolScope, RequestOperandBinding, RequestProcessing, RequestProcessingRule,
)
from scar.ir.program.resumption import ResumableKind
from tests.fixtures.native_coroutine_common import capture_program, migrate_native
from tests.fixtures.program_async_pipeline_graphs import _selected_path
from tests.fixtures.program_await_resume_graphs import _body, _stage
from tests.fixtures.program_control_graphs import _source
from tests.fixtures.program_driver_graphs import PACKET, RAW, REFERENCE, _Builder, _use, driver_program, driver_rule
from tests.fixtures.program_generator_admission_graphs import _guard
from tests.fixtures.program_generator_close_retry_graphs import _driver_part
from tests.fixtures.program_protocol_graphs import _insert_processing, _source_gap
from tests.fixtures.program_publication_graphs import with_publications


_TABLES = ('driver_interfaces', 'final_body_gates', 'body_drives', 'driver_lifecycles',
           'body_outcome_commits', 'terminal_frame_releases', 'protocol_scopes',
           'protocol_operations', 'literal_evaluations', 'exception_packets')


def _op(program, identity):
    return next(row for row in program.operations if row.id == identity)


def _rename(value, maps):
    if type(value) in maps:
        return maps[type(value)].get(value, value)
    if type(value) is tuple:
        return tuple(_rename(item, maps) for item in value)
    if type(value) is dict:
        return {_rename(key, maps): _rename(item, maps) for key, item in value.items()}
    if is_dataclass(value):
        return replace(value, **{field.name: _rename(getattr(value, field.name), maps)
                                 for field in fields(value)})
    return value


def _packet_body(kind):
    body = _body(zero_cut=False, kind=ResumableKind.COROUTINE)
    region, = body.regions
    original = next(block for block in region.blocks if block.id == BlockID('resume.packet'))
    identities = set(original.operations)
    values = tuple(row for row in body.values if
        type(row.origin) is BlockArgument and row.origin.block == original.id
        or type(row.origin) is OperationResult and row.origin.operation in identities)
    maps = {
        BlockID: {original.id: BlockID('native.second.packet')},
        OperationID: {identity: OperationID('native.second.' + identity.value) for identity in identities},
        ValueID: {row.id: ValueID('native.second.' + row.id.value) for row in values},
        UseID: {use.id: UseID('native.second.' + use.id.value)
                for row in body.operations if row.id in identities for use in row.uses},
    }
    cloned = tuple(_rename(row, maps) for row in body.operations if row.id in identities)
    cloned_values = tuple(_rename(row, maps) for row in values)
    terminal = next(row for row in cloned if row.terminator is not None)
    if kind is RawRequestKind.CLOSE:
        none = ReferenceValue(ValueID('native.close.none'), region.id, LiteralOrigin(None), targets=())
        payload = replace(terminal.uses[0], value=none.id, role=UseRole.REFERENCE)
        terminal = replace(terminal, uses=(payload, *terminal.uses[1:]),
                           terminator=replace(terminal.terminator, kind=TerminatorKind.RETURN, exit='normal'))
        cloned = tuple(terminal if row.id == terminal.id else row for row in cloned)
        cloned_values = (*cloned_values, none)
    first = _op(body, OperationID('resume.suspend'))
    second = _op(body, OperationID('resume.second.suspend'))
    case = replace(first.terminator.successors[1], block=maps[BlockID][original.id])
    second = replace(second, terminator=replace(second.terminator,
        successors=(*second.terminator.successors, case)))
    blocks = (*region.blocks, _rename(original, maps))
    body = replace(body,
        regions=(replace(region, blocks=blocks),),
        operations=(*(second if row.id == second.id else row for row in body.operations), *cloned),
        values=(*body.values, *cloned_values),
        frame_context_attaches=(*body.frame_context_attaches,
            *(_rename(row, maps) for row in body.frame_context_attaches if row.operation in identities)),
        frame_context_detaches=(*body.frame_context_detaches,
            *(_rename(row, maps) for row in body.frame_context_detaches if row.operation in identities)),
        control_scopes=tuple(replace(row, blocks=tuple(block.id for block in blocks))
                             for row in body.control_scopes))
    return body, terminal


def _packet_driver(body, kind, *, raised, wrong_packet, attach_source):
    second = OperationID('resume.second.suspend')
    prioritized = replace(body, operations=tuple(sorted(body.operations, key=lambda row: row.id != second)))
    graph = driver_program(body_graph=prioritized, target='packet')
    body_ids = {row.id for row in body.operations}
    graph = replace(graph, operations=(*body.operations, *(row for row in graph.operations if row.id not in body_ids)))
    drive, = graph.body_drives
    assert drive.target.suspend == second and drive.target.successor == 1
    interface, = graph.driver_interfaces
    region = next(row for row in graph.regions if row.id == interface.region)
    original_exits = region.exits
    graph, processing = _insert_processing(graph, target='packet')
    graph = replace(graph, regions=tuple(replace(row, exits=original_exits
        if kind is RawRequestKind.CLOSE else tuple(port for port in original_exits if port.kind is ExitKind.RAISE))
        if row.id == region.id else row for row in graph.regions))
    entry = next(block for block in region.blocks if block.id == region.entry)
    old_argument = next(row for row in graph.values if row.id == entry.arguments[2])
    helper = _op(graph, processing['processing'])
    if kind is RawRequestKind.THROW:
        argument = ReferenceValue(old_argument.id, old_argument.region, old_argument.origin)
        expanded = _use('native.normalization.argument', argument.id)
        helper = replace(helper, uses=(*helper.uses, expanded),
                         invoke_arguments=(*helper.invoke_arguments, expanded.id))
        graph = replace(graph, values=tuple(argument if row.id == argument.id else row for row in graph.values))
        operands = (RequestOperandBinding(0, expanded.id),)
    else:
        # The old packet driver boundary had an unused prepacked third formal.
        kept = tuple(value for value in entry.arguments if value != old_argument.id)
        graph = replace(graph, values=tuple(replace(row, origin=BlockArgument(entry.id, kept.index(row.id)))
            if row.id in kept else row for row in graph.values if row.id != old_argument.id),
            regions=tuple(replace(row, blocks=tuple(replace(block, arguments=kept)
                if block.id == entry.id else block for block in row.blocks))
                if row.id == region.id else row for row in graph.regions))
        operands = ()
    graph = replace(graph, operations=tuple(helper if row.id == helper.id else row for row in graph.operations))
    scope = ProtocolScope(ProtocolScopeID('native.packet.scope'), ProtocolProfile.COROUTINE_BODY_V1,
                          DriverSubject(region.id), _source_gap())
    rule = (RequestProcessingRule.NORMALIZE_THROW_CLASS if kind is RawRequestKind.THROW
            else RequestProcessingRule.NORMALIZE_GENERATOR_EXIT)
    rows = tuple(ProtocolOperation(scope.id, ProtocolClause.REQUEST_PROCESSING, helper.id, slot,
        RequestProcessing(processing['raw_use'], operands, processing[port], processing['state_sites'], rule),
        _source_gap()) for slot, port in ((0, 'normal_result'), (1, 'raise_result')))
    source = ContractResult(scope.id, ProtocolClause.REQUEST_PROCESSING, helper.id, 0, processing['normal_result'])
    binding = ProtocolOperation(scope.id, ProtocolClause.BODY_INGRESS, drive.operation, drive.resume_inputs[0].slot,
                                ResumeSourceBinding(source), _source_gap())
    graph = replace(graph, protocol_scopes=(scope,), protocol_operations=(*rows, *((binding,) if attach_source else ())))

    # This independent typed packet exists in both controls. Only its delivery
    # Use changes in the negative; both packets dominate the same final gate.
    normal = next(block for row in graph.regions for block in row.blocks if block.id == BlockID('boundary.normal'))
    none = ReferenceValue(ValueID('native.decoy.traceback'), region.id, LiteralOrigin(None), targets=())
    from scar.ir.program.model import ProtocolValue
    decoy = ProtocolValue(ValueID('native.decoy.packet'), region.id,
                          OperationResult(OperationID('native.decoy.construct'), 0), PACKET.protocol)
    decoy_uses = (_use('native.decoy.exception', normal.arguments[0]), _use('native.decoy.tb', none.id))
    constructor = Operation(OperationID('native.decoy.construct'), 'independent typed packet',
        (Behavior.CONTROL,), decoy_uses, (decoy.id,), effects_complete=True)
    gate = _op(graph, processing['consumer'])
    delivered = normal.arguments[2]
    if wrong_packet:
        gate = replace(gate, uses=tuple(replace(use, value=decoy.id) if use.value == delivered else use
                                        for use in gate.uses))
    graph = replace(graph, values=(*graph.values, none, decoy),
        operations=(*(gate if row.id == gate.id else row for row in graph.operations), constructor),
        exception_packets=(*graph.exception_packets,
            ExceptionPacketDefinition(decoy.id, *(use.id for use in decoy_uses))),
        regions=tuple(replace(row, blocks=tuple(replace(block, operations=(constructor.id, *block.operations))
            if block.id == normal.id else block for block in row.blocks))
            if row.id == region.id else row for row in graph.regions))
    graph, guard = _guard(graph, block_id=normal.id, owner=normal.arguments[0], raw=normal.arguments[1],
        label='native.suspended', rule=BodyStatePredicateRule.IS_SUSPENDED, request_kind=kind)
    drive_operation = _op(graph, drive.operation)
    outcome, = drive_operation.terminator.successors
    terminal_id = next(block.operations[-1] for row in graph.regions for block in row.blocks if block.id == outcome.block)
    terminal = _op(graph, terminal_id)
    if kind is RawRequestKind.CLOSE:
        row = ProtocolOperation(scope.id, ProtocolClause.CLOSE_ROUTE, terminal.id, 0,
            OutcomeAdapter(DriveResult(DriveOutcomeRef(drive.operation, outcome.source), 0),
                terminal.terminator.values[0], HostTerminal(terminal.id), OutcomeAdapterRule.CLOSE_RETURN_VALUE),
            _source_gap())
        graph = replace(graph, protocol_operations=(*graph.protocol_operations, row))
    graph = with_publications(graph)
    consumers = tuple(ProtocolResultConsumers(ProtocolOperationRef(scope.id, row.clause, row.operation, row.slot),
        (HostTerminal(OperationID('boundary.raise')), ) if row.slot else
        (OwnedUse(gate.id, next(use.id for use in gate.uses if use.value in (delivered, decoy.id))),)) for row in rows)
    graph = replace(graph, protocol_result_consumers=consumers)
    choices = {helper.id: int(raised), guard['branch']: 0, gate.id: 0, drive.operation: 0}
    host = OperationID('boundary.raise') if raised else terminal.id
    part, maps = _driver_part(graph, 'native.packet.driver.2')
    part.update(source=outcome.source, drive=part['body_drives'][0], host=_rename(host, maps),
        choices={_rename(key, maps): value for key, value in choices.items()},
        protocol_result_consumers=_rename(consumers, maps))
    part['path'] = _selected_path(replace(graph, regions=(part['region'],), operations=part['operations']),
                                  part['region'], part['choices'])
    metadata = _rename({'scope': scope.id, 'normalizer': helper.id, 'rows': rows,
        'normal_source': source, 'source_binding': binding, 'guard': guard,
        'normalizer_failure': OperationID('boundary.raise'), 'gate': gate.id,
        'decoy': decoy.id, 'normal_result': processing['normal_result'],
        'raise_result': processing['raise_result'], 'raw_use': processing['raw_use']}, maps)
    return part, metadata


def coroutine_suspended_packet_program(kind=RawRequestKind.THROW, *, normalization_raised=False,
                                      wrong_packet=False, attach_source=True):
    if kind not in (RawRequestKind.THROW, RawRequestKind.CLOSE):
        raise ValueError('only THROW and CLOSE are modeled')
    body, body_terminal = _packet_body(kind)
    first = tuple(_stage(body, ordinal, zero_cut=False) for ordinal in (0, 1))
    final, packet = _packet_driver(body, kind, raised=normalization_raised,
                                  wrong_packet=wrong_packet, attach_source=attach_source)
    stages = (*first, final)
    domains = tuple(row.id for row in body.locations)
    states = tuple(ValueType(ValueKind.STATE, location=identity) for identity in domains)
    b = _Builder('native.packet.caller', domains)
    body_region, = body.regions
    values = {row.id: row for row in body.values}
    body_entry = next(block for block in body_region.blocks if block.id == body_region.entry)
    captures = tuple(identity for identity in body_entry.arguments if type(values[identity]) is ReferenceValue)
    entry_name = 'native.packet.entry'
    entry = b.formals(entry_name, (*(REFERENCE for _ in captures), REFERENCE, *states))
    create_actuals = tuple(_use(f'native.create.input.{i}', value, state=i >= len(captures))
        for i, value in enumerate((*entry[:len(captures)], *entry[-len(states):])))
    created = b.formals('native.created', (REFERENCE, *states))
    failed = b.formals('native.create.failed', (PACKET, *states))
    creation = b.add('native.create', create_actuals, effects_complete=True,
        invoke_arguments=tuple(use.id for use in create_actuals),
        completions=(CompletionSignature(ExitKind.NORMAL, (REFERENCE, *states)),
                     CompletionSignature(ExitKind.RAISE, (PACKET, *states))),
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, BlockID('native.created'), tuple(CompletionResult(i) for i in range(len(created)))),
            CompletionSuccessor(ExitKind.RAISE, BlockID('native.create.failed'), tuple(CompletionResult(i) for i in range(len(failed)))))))
    function = next(row.reference for row in body.environments[0].members if row.role is EnvironmentRole.FUNCTION_OBJECT)
    capture_rows = tuple(CreationCapture(formal, use.id) for formal, use in zip(captures, create_actuals))
    create = ResumableCreate(creation.id, body_region.id,
        next(row.source for row in capture_rows if row.formal == function), capture_rows, NormalResultPort(0), driver_rule())
    b.block(entry_name, entry, (creation,))
    b.block('native.create.failed', failed, (b.terminal('native.create.failure', failed, fail=True),))
    block_name, current, owner, current_states = 'native.created', created, created[0], created[1:]
    raws, drivers, choices = [], [], {creation.id: 0}
    selected_terminal = None
    for ordinal, part in enumerate(stages):
        name = f'native.call.{ordinal}'
        request_kind = (RawRequestKind.NEXT if ordinal == 0 else RawRequestKind.SEND if ordinal == 1 else kind)
        operand = () if request_kind in (RawRequestKind.NEXT, RawRequestKind.CLOSE) else (_use(name + '.operand', entry[len(captures)]),)
        raw = b.value(name + '.raw', OperationResult(OperationID(name + '.pack'), 0), RAW)
        pack = b.add(name + '.pack', operand, results=(raw,), effects_complete=True)
        raws.append(RawRequestDefinition(raw, request_kind, tuple(use.id for use in operand)))
        actual_values = (owner, raw, *((entry[len(captures)],) if operand else ()), *current_states)
        actual = tuple(_use(f'{name}.input.{i}', value, protocol=i == 1,
                           state=i >= len(actual_values) - len(states)) for i, value in enumerate(actual_values))
        edges, forwards, selected = [], [], None
        selected_kind = (ExitKind.NORMAL if ordinal < 2 or kind is RawRequestKind.CLOSE and not normalization_raised
                         else ExitKind.RAISE)
        for port in part['region'].exits:
            landing_name = name + '.' + port.kind.value.lower()
            keep = ordinal < 2 and port.kind is ExitKind.NORMAL
            landing = b.formals(landing_name, (*((REFERENCE,) if keep else ()), *port.types))
            forwarded = (_use(name + '.owner.forward', owner),) if keep else ()
            forwards.extend(forwarded)
            edges.append(CompletionSuccessor(port.kind, BlockID(landing_name),
                (*(use.id for use in forwarded), *(CompletionResult(i) for i in range(len(port.types))))))
            if keep:
                selected = landing_name, landing
            else:
                terminal = b.terminal(landing_name + '.exit', landing, fail=port.kind is ExitKind.RAISE)
                b.block(landing_name, landing, (terminal,))
                if ordinal == 2 and port.kind is selected_kind:
                    selected_terminal = terminal
        call = b.add(name, (*actual, *forwards), callee=part['region'].id, effects_complete=True,
            invoke_arguments=tuple(use.id for use in actual),
            completions=tuple(CompletionSignature(port.kind, port.types) for port in part['region'].exits),
            terminator=Terminator(TerminatorKind.INVOKE, tuple(edges)))
        b.block(block_name, current, (pack, call))
        choices[call.id] = next(i for i, edge in enumerate(edges) if edge.kind is selected_kind)
        drivers.append({'caller_call': call, 'driver_region': part['region'], 'path': part['path'],
            'host_terminal': next(row for row in part['operations'] if row.id == part['host']),
            'drive': part['drive'], 'outcome_source': part['source']})
        if selected is not None:
            block_name, current = selected
            owner, current_states = current[0], current[2:]
    caller = b.finish(entry_name)
    if kind is RawRequestKind.THROW:
        caller = replace(caller, exits=tuple(port for port in caller.exits if port.kind is ExitKind.RAISE))
    graph = replace(body, root=caller.id,
        regions=(caller, replace(body_region, parent=caller.id),
            *(replace(part['region'], parent=caller.id) for part in stages)),
        operations=(*body.operations, *(row for part in stages for row in part['operations']), *b.operations),
        values=(*body.values, *(row for part in stages for row in part['values']), *b.values),
        control_scopes=(*body.control_scopes, *(row for part in stages for row in part['control_scopes']),
            ControlScope(ControlScopeID('native.packet.caller.function'), caller.id, None, ControlScopeKind.FUNCTION,
                         _source('supplied native packet caller'), tuple(block.id for block in caller.blocks))),
        resumable_creates=(create,), raw_driver_requests=tuple(raws),
        protocol_result_consumers=final['protocol_result_consumers'],
        **{name: tuple(row for part in stages for row in part[name]) for name in _TABLES})
    details = {'caller': caller, 'caller_path': _selected_path(graph, caller, choices),
        'body': body_region, 'primary_creation': create, 'drivers': tuple(drivers),
        'packet': packet, 'kind': kind, 'normalization_raised': normalization_raised,
        'body_terminal': body_terminal, 'caller_terminal': selected_terminal,
        'second_suspend': OperationID('resume.second.suspend')}
    return migrate_native(graph, details)


def coroutine_suspended_packet_execution(kind=RawRequestKind.THROW, *, normalization_raised=False, instances=2):
    program, details = coroutine_suspended_packet_program(kind, normalization_raised=normalization_raised)
    model, captured = capture_program(program, details, instances=instances, label='native.packet.' + kind.value.lower())
    return program, model, captured
