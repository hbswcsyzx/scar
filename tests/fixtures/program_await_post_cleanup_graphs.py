"""Synchronous cleanup after an await driver's real completion conversion.

The persistent body and its two cuts are unchanged.  Each actual NORMAL/RAISE
conversion leg enters its own ordinary C1 interface inside D.  No suspension,
resumable body, extra caller context, or second producer relation is added to D.
These supplied records do not establish native exception/category semantics.
"""
from dataclasses import replace

from scar.ir.program.cleanup import (
    CleanupEnter, CleanupInterface, CleanupReplace, CleanupResume,
    CleanupRouteSuccessor, CleanupRouteTerminator, HandledContextDomain,
)
from scar.ir.program.control import (
    ControlPort, ControlScope, ControlScopeKind, ExceptionPacketDefinition,
    LanguageCompletionKind, PendingCompletionDefinition, PendingDispatchTerminator,
    PendingPayload, PendingSuccessor, ProtocolValueKind,
)
from scar.ir.program.ids import BlockID, ControlPortID, ControlScopeID, OperationID, UseID, ValueID
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, CompletionResult, CompletionSignature,
    CompletionSuccessor, ExitKind, ExitPort, Footprint, FootprintKind,
    InvokeLiteralResult, LiteralOrigin, Operation, OperationResult, ProtocolValue,
    ReferenceValue, StateAccess, StateVersionValue, Successor, Terminator,
    TerminatorKind, Use, UseRole, ValueKind, ValueType,
)
from scar.ir.program.protocol_await_records import AwaitBodyLink
from scar.ir.program.protocol_connections import ProtocolOperationRef, ProtocolResultConsumers
from scar.ir.program.protocols import HostTerminal, OwnedUse, ProtocolCall
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.program_async_pipeline_graphs import _selected_path
from tests.fixtures.program_await_final_region_graphs import await_final_region_program
from tests.fixtures.program_control_graphs import _source


_MODES = ('preserve', 'replace_raise', 'replace_return', 'opaque', 'wrong_terminal')


def await_post_cleanup_program(mode='preserve', depth=1):
    """Return a complete original caller/B/D/E graph plus per-conversion C1.

    ``preserve`` restores the original pending Raise on both constructor legs.
    The two replacement modes construct a new payload *after Enter* and perform
    an actual CleanupReplace.  A replacement Return has a genuine D NORMAL exit
    and a genuine caller NORMAL landing; it is not a StopIteration extraction.
    ``opaque`` inserts unknown work in the actual post-dispatch handler landing.
    ``wrong_terminal`` keeps the selected pending packet but raises an independent
    locally constructed packet at that landing.  Neither mutation violates an
    exact pending exit shim: the original Raise port is a real block port.
    """
    if type(mode) is not str or mode not in _MODES:
        raise ValueError('unknown synchronous post-conversion cleanup mode')
    if type(depth) is not int or depth not in (1, 2):
        raise ValueError('the extraction implementation has one or two regions')
    graph, original = await_final_region_program(zero_cut=False, depth=depth)
    values = {value.id: value for value in graph.values}
    operations = {operation.id: operation for operation in graph.operations}
    driver = next(region for region in graph.regions
                  if region.id == original['drivers'][-1]['driver_region'].id)
    blocks = {block.id: block for block in driver.blocks}
    conversion = original['conversion']
    function = next(scope for scope in graph.control_scopes
        if scope.region == driver.id and scope.kind is ControlScopeKind.FUNCTION)
    entry = blocks[driver.entry]
    domains = tuple(values[identity].location for identity in entry.arguments
                    if type(values[identity]) is StateVersionValue)
    if len(domains) != 2:
        raise AssertionError('this original driver carries its world and handled-context domains')

    additions = {name: [] for name in (
        'values', 'operations', 'blocks', 'control_scopes', 'control_ports',
        'pending_completions', 'exception_packets', 'cleanup_interfaces',
        'cleanup_enters', 'cleanup_resumes', 'cleanup_replacements')}
    protected_blocks, root_blocks, legs = [], [], []
    terminal_updates, receipt_updates = {}, {}
    prefix_choices = tuple(ControlEdgeReference(blocks[block].operations[-1], number)
        for block, number in original['drivers'][-1]['path']
        if number is not None and blocks[block].operations[-1] != conversion.id)

    def value(name, origin, template):
        result = replace(template, id=ValueID(name), region=driver.id, origin=origin)
        additions['values'].append(result)
        values[result.id] = result
        return result

    def protocol(name, origin, kind):
        result = ProtocolValue(ValueID(name), driver.id, origin, kind)
        additions['values'].append(result)
        values[result.id] = result
        return result

    def reference(name, origin):
        result = ReferenceValue(ValueID(name), driver.id, origin,
                                targets=() if type(origin) is LiteralOrigin else None)
        additions['values'].append(result)
        values[result.id] = result
        return result

    def use(name, actual):
        actual = actual.id if hasattr(actual, 'id') else actual
        role = (UseRole.STATE_CONTENT if type(values[actual]) is StateVersionValue else
                UseRole.PROTOCOL if type(values[actual]) is ProtocolValue else UseRole.REFERENCE)
        return Use(UseID(name), actual, role)

    def operation(name, uses=(), **kwargs):
        result = Operation(OperationID(name), name, (Behavior.CONTROL,), tuple(uses), **kwargs)
        additions['operations'].append(result)
        operations[result.id] = result
        return result

    def pending(name, payload, port):
        identity = OperationID(name)
        result = protocol(name + '.value', OperationResult(identity, 0),
                          ProtocolValueKind.PENDING_COMPLETION)
        operand = use(name + '.payload', payload)
        producer = operation(name, (operand,), results=(result.id,), effects_complete=True)
        definition = PendingCompletionDefinition(result.id, port.id, operand.id)
        additions['pending_completions'].append(definition)
        return producer, result, definition, OwnedUse(producer.id, operand.id)

    def new_packet(name):
        exception_id = OperationID(name + '.exception')
        exception = reference(name + '.exception.value', OperationResult(exception_id, 0))
        new_exception = operation(exception_id.value, results=(exception.id,), effects_complete=True)
        traceback = reference(name + '.traceback', LiteralOrigin(None))
        pack_id = OperationID(name + '.pack')
        packet = protocol(name + '.packet', OperationResult(pack_id, 0),
                          ProtocolValueKind.EXCEPTION_PACKET)
        operands = (use(name + '.exception.use', exception), use(name + '.traceback.use', traceback))
        pack = operation(pack_id.value, operands, results=(packet.id,), effects_complete=True)
        additions['exception_packets'].append(ExceptionPacketDefinition(
            packet.id, operands[0].id, operands[1].id))
        return (new_exception, pack), packet

    def formals(name, templates):
        block = BlockID(name)
        return tuple(value(name + f'.argument.{number}', BlockArgument(block, number), template)
                     for number, template in enumerate(templates))

    def jump(name, destination, actuals):
        operands = tuple(use(name + f'.argument.{number}', actual)
                         for number, actual in enumerate(actuals))
        return operation(name, operands, effects_complete=True,
            terminator=Terminator(TerminatorKind.JUMP,
                (Successor(destination, tuple(operand.id for operand in operands)),)))

    def route(name, destination, token, actuals, port):
        selector = use(name + '.selector', token)
        operands = tuple(use(name + f'.argument.{number}', actual)
                         for number, actual in enumerate(actuals))
        return operation(name, (selector, *operands), effects_complete=True,
            terminator=CleanupRouteTerminator(selector.id,
                (CleanupRouteSuccessor(port.id, destination,
                                       tuple(operand.id for operand in operands)),)))

    def state_action(name, protocols, states, *, saved=False):
        identity = OperationID(name)
        saved_value = (protocol(name + '.saved-context', OperationResult(identity, 0),
            ProtocolValueKind.SAVED_HANDLED_CONTEXT) if saved else None)
        post = tuple(value(name + f'.state.{number}',
            OperationResult(identity, number + int(saved)), state)
            for number, state in enumerate(states))
        state_uses = tuple(use(name + f'.before.{number}', state)
                           for number, state in enumerate(states))
        result = Operation(identity, name, (Behavior.CONTROL, Behavior.READ, Behavior.WRITE),
            (*protocols, *state_uses),
            (*((saved_value.id,) if saved else ()), *(state.id for state in post)),
            tuple(StateAccess(state.location, operand.id, AccessMode.READ_WRITE, after.id,
                              Footprint(FootprintKind.WHOLE))
                  for state, operand, after in zip(states, state_uses, post)), effects_complete=False)
        additions['operations'].append(result)
        operations[result.id] = result
        return result, post, saved_value

    replacement = mode in ('replace_raise', 'replace_return')
    for number, edge in enumerate(conversion.terminator.successors):
        landing = blocks[edge.block]
        terminal = operations[landing.operations[-1]]
        terminal_by_use = {operand.id: operand for operand in terminal.uses}
        payload_id = terminal_by_use[terminal.terminator.values[0]].value
        packet_value = values[payload_id]
        if type(packet_value) is not ProtocolValue or packet_value.protocol is not ProtocolValueKind.EXCEPTION_PACKET:
            raise AssertionError('each original constructor leg must supply its actual whole packet')
        states = tuple(values[terminal_by_use[identity].value]
                       for identity in terminal.terminator.values[1:])
        if tuple(state.location for state in states) != domains:
            raise AssertionError('the original constructor terminal keeps both current state slots')
        label = 'normal' if edge.kind is ExitKind.NORMAL else 'raise'
        name = 'await.post-cleanup.' + label
        own = InvokeLiteralResult(ControlEdgeReference(conversion.id, number), CompletionResult(0))
        packet_source = packet_value.origin if edge.kind is ExitKind.NORMAL else own
        cleanup_id = ControlScopeID(name + '.cleanup.scope')
        protected_id = ControlScopeID(name + '.protected.scope')
        cleanup_entry_id = BlockID(name + '.entry')
        route_block_id, dispatch_block_id = BlockID(name + '.post-pop-route'), BlockID(name + '.dispatch')
        handler_id = BlockID(name + '.handler')
        incoming_port = ControlPort(ControlPortID(name + '.incoming-raise'), function.id,
            LanguageCompletionKind.RAISE, exit=terminal.terminator.exit) if replacement else ControlPort(
            ControlPortID(name + '.incoming-raise'), function.id,
            LanguageCompletionKind.RAISE, block=handler_id)
        outgoing_port = incoming_port
        if replacement:
            outgoing_port = (ControlPort(ControlPortID(name + '.replacement-return'), function.id,
                LanguageCompletionKind.RETURN, exit='normal') if mode == 'replace_return' else
                ControlPort(ControlPortID(name + '.replacement-raise'), function.id,
                    LanguageCompletionKind.RAISE, block=handler_id))
        additions['control_ports'].extend((incoming_port, *((outgoing_port,) if replacement else ())))

        pack, token, definition, pending_payload = pending(name + '.pending', packet_value, incoming_port)
        pending_templates = (token, *states)
        cleanup_arguments = formals(cleanup_entry_id.value, pending_templates)
        into = route(name + '.enter-route', cleanup_entry_id, token, (token, *states), incoming_port)
        blocks[landing.id] = replace(landing, operations=(*landing.operations[:-1], pack.id, into.id))
        protected_blocks.append(landing.id)
        pending_use = use(name + '.enter.pending', cleanup_arguments[0])
        enter, enter_post, saved = state_action(name + '.enter', (pending_use,), cleanup_arguments[1:], saved=True)
        enter_record = CleanupEnter(enter.id, cleanup_id, pending_use.id, saved.id)
        additions['cleanup_enters'].append(enter_record)
        interface = CleanupInterface(cleanup_id, protected_id, cleanup_entry_id, cleanup_arguments[0].id)
        additions['cleanup_interfaces'].append(interface)
        action_records, action_operations = [enter_record], [enter]
        cleanup_blocks, cleanup_operations = [cleanup_entry_id], [enter.id]
        local_routes = [into]
        replacement_source, replacement_result, replacement_definition = None, None, None

        if replacement:
            if mode == 'replace_raise':
                producers, replacement_payload = new_packet(name + '.replacement')
                cleanup_operations.extend(item.id for item in producers)
                replacement_result = replacement_payload.origin
            else:
                producer_id = OperationID(name + '.replacement.reference')
                replacement_payload = reference(name + '.replacement.reference.value', OperationResult(producer_id, 0))
                producer = operation(producer_id.value, results=(replacement_payload.id,), effects_complete=True)
                cleanup_operations.append(producer.id)
                replacement_result = replacement_payload.origin
            replacement_pack, replacement_token, replacement_definition, replacement_source = pending(
                name + '.replacement.pending', replacement_payload, outgoing_port)
            cleanup_operations.append(replacement_pack.id)
            replace_id = BlockID(name + '.replace')
            replacement_arguments = formals(replace_id.value,
                (cleanup_arguments[0], replacement_token, saved, *enter_post))
            to_replace = route(name + '.replace-route', replace_id, replacement_token,
                (cleanup_arguments[0], replacement_token, saved, *enter_post), outgoing_port)
            cleanup_operations.append(to_replace.id)
            local_routes.append(to_replace)
            additions['blocks'].append(Block(cleanup_entry_id,
                tuple(actual.id for actual in cleanup_arguments), tuple(cleanup_operations)))
            operands = tuple(use(name + f'.replace.protocol.{ordinal}', actual)
                             for ordinal, actual in enumerate(replacement_arguments[:3]))
            action, after, _ = state_action(name + '.replace', operands, replacement_arguments[3:])
            selected_token = replacement_arguments[1]
            handoff = jump(name + '.replace-to-route', route_block_id, (selected_token, *after))
            action_record = CleanupReplace(action.id, cleanup_id, operands[0].id, operands[1].id,
                                           operands[2].id, ControlEdgeReference(handoff.id, 0))
            additions['cleanup_replacements'].append(action_record)
            additions['blocks'].append(Block(replace_id, tuple(actual.id for actual in replacement_arguments),
                                            (action.id, handoff.id)))
            cleanup_blocks.append(replace_id)
        else:
            operands = (use(name + '.resume.pending', cleanup_arguments[0]),
                        use(name + '.resume.context', saved))
            action, after, _ = state_action(name + '.resume', operands, enter_post)
            selected_token = cleanup_arguments[0]
            handoff = jump(name + '.resume-to-route', route_block_id, (selected_token, *after))
            action_record = CleanupResume(action.id, cleanup_id, operands[0].id,
                                           operands[1].id, ControlEdgeReference(handoff.id, 0))
            additions['cleanup_resumes'].append(action_record)
            additions['blocks'].append(Block(cleanup_entry_id,
                tuple(actual.id for actual in cleanup_arguments), (enter.id, action.id, handoff.id)))
        action_records.append(action_record)
        action_operations.append(action)

        route_arguments = formals(route_block_id.value, (selected_token, *after))
        dispatch_arguments = formals(dispatch_block_id.value, route_arguments)
        post_route = route(name + '.route', dispatch_block_id, route_arguments[0],
                           route_arguments, outgoing_port)
        local_routes.append(post_route)
        additions['blocks'].append(Block(route_block_id, tuple(actual.id for actual in route_arguments), (post_route.id,)))
        output_template = replacement_payload if replacement else packet_value
        handler_arguments = formals(handler_id.value, (output_template, *after))
        selector = use(name + '.dispatch.selector', dispatch_arguments[0])
        state_forwards = tuple(use(name + f'.dispatch.state.{ordinal}', state)
                               for ordinal, state in enumerate(dispatch_arguments[1:]))
        dispatch = operation(name + '.dispatch', (selector, *state_forwards), effects_complete=True,
            terminator=PendingDispatchTerminator(selector.id,
                (PendingSuccessor(outgoing_port.id, handler_id,
                    (PendingPayload(), *(operand.id for operand in state_forwards))),)))
        additions['blocks'].append(Block(dispatch_block_id, tuple(actual.id for actual in dispatch_arguments), (dispatch.id,)))
        terminal_payload, handler_operations, opaque = handler_arguments[0], [], None
        if mode == 'opaque':
            opaque = operation(name + '.handler.opaque', effects_complete=False)
            handler_operations.append(opaque.id)
        elif mode == 'wrong_terminal':
            wrong_operations, terminal_payload = new_packet(name + '.handler.unrelated')
            handler_operations.extend(item.id for item in wrong_operations)
        terminal_values = (terminal_payload, *handler_arguments[1:])
        terminal = replace(terminal,
            uses=tuple(use(identity.value, actual)
                       for identity, actual in zip(terminal.terminator.values, terminal_values)),
            effects_complete=True,
            terminator=replace(terminal.terminator,
                kind=TerminatorKind.RETURN if mode == 'replace_return' else TerminatorKind.RAISE,
                exit='normal' if mode == 'replace_return' else terminal.terminator.exit))
        terminal_updates[terminal.id] = terminal
        handler_operations.append(terminal.id)
        additions['blocks'].append(Block(handler_id, tuple(actual.id for actual in handler_arguments), tuple(handler_operations)))
        root_blocks.extend((route_block_id, dispatch_block_id, handler_id))
        additions['control_scopes'].extend((
            ControlScope(protected_id, driver.id, function.id, ControlScopeKind.BLOCK,
                         _source(name + '.protected'), (landing.id,)),
            ControlScope(cleanup_id, driver.id, function.id, ControlScopeKind.CLEANUP,
                         _source(name + '.cleanup'), tuple(cleanup_blocks)),
        ))
        choices = (*prefix_choices, ControlEdgeReference(conversion.id, number),
                   *(ControlEdgeReference(item.id, 0) for item in local_routes),
                   ControlEdgeReference(handoff.id, 0), ControlEdgeReference(dispatch.id, 0))
        payload_uses = (OwnedUse(terminal.id, terminal.terminator.values[0]),)
        leg = {'kind': edge.kind, 'edge': ControlEdgeReference(conversion.id, number),
            'own_result': own, 'packet_source': packet_source, 'packet_value': packet_value,
            'entry': blocks[landing.id], 'interface': interface, 'pending': definition,
            'pending_payload_use': pending_payload, 'actions': tuple(action_records),
            'action_operations': tuple(action_operations), 'routes': tuple(local_routes),
            'dispatch': dispatch, 'port': incoming_port, 'outgoing_port': outgoing_port,
            'replacement_source': replacement_source, 'replacement_definition': replacement_definition,
            'replacement_result': replacement_result, 'replacement_pending': replacement_definition,
            'terminals': (terminal,), 'payload_uses': payload_uses,
            'state_uses': tuple(OwnedUse(terminal.id, identity) for identity in terminal.terminator.values[1:]),
            'choices': choices, 'opaque': opaque, 'handler': additions['blocks'][-1]}
        legs.append(leg)
        if edge.kind is ExitKind.RAISE:
            for row in original['conversion_rows']:
                if row.contract.output == own:
                    receipt_updates[ProtocolOperationRef(row.scope, row.clause, row.operation, row.slot)] = pending_payload

    updated_driver = replace(driver, blocks=tuple(blocks[block.id] for block in driver.blocks) + tuple(additions['blocks']))
    if mode == 'replace_return':
        updated_driver = replace(updated_driver, exits=(*driver.exits,
            ExitPort('normal', ExitKind.NORMAL, (ValueType(ValueKind.REFERENCE),
                *(ValueType(ValueKind.STATE, location=location) for location in domains)))))
    graph = replace(graph,
        regions=tuple(updated_driver if region.id == driver.id else region for region in graph.regions),
        operations=tuple(terminal_updates.get(item.id, item) for item in graph.operations) + tuple(additions['operations']),
        values=(*graph.values, *additions['values']),
        control_scopes=tuple(replace(scope,
            blocks=tuple(block for block in scope.blocks if block not in protected_blocks) + tuple(root_blocks))
            if scope.id == function.id else scope for scope in graph.control_scopes) + tuple(additions['control_scopes']),
        handled_context_domains=(*graph.handled_context_domains, HandledContextDomain(driver.id, domains[-1])),
        protocol_result_consumers=tuple(replace(receipt, targets=(receipt_updates[receipt.site],))
            if receipt.site in receipt_updates else receipt for receipt in graph.protocol_result_consumers),
        **{name: (*getattr(graph, name), *additions[name]) for name in (
            'control_ports', 'pending_completions', 'exception_packets', 'cleanup_interfaces',
            'cleanup_enters', 'cleanup_resumes', 'cleanup_replacements')})

    caller, advance = original['caller'], original['drivers'][-1]['caller_call']
    new_normal_terminal = None
    if mode == 'replace_return':
        name = 'await.post-cleanup.caller.normal'
        target = BlockID(name)
        signature = next(port for port in updated_driver.exits if port.kind is ExitKind.NORMAL)
        caller_values = (ReferenceValue(ValueID(name + '.payload'), caller.id, BlockArgument(target, 0)),
            *(StateVersionValue(ValueID(name + f'.state.{number}'), caller.id,
                BlockArgument(target, number + 1), location) for number, location in enumerate(domains)))
        operands = tuple(Use(UseID(name + f'.return.{number}'), actual.id,
            UseRole.REFERENCE if number == 0 else UseRole.STATE_CONTENT)
            for number, actual in enumerate(caller_values))
        new_normal_terminal = Operation(OperationID(name + '.return'), 'actual replacement Return consumer',
            (Behavior.CONTROL,), operands, effects_complete=True,
            terminator=Terminator(TerminatorKind.RETURN, exit='normal', values=tuple(operand.id for operand in operands)))
        number = len(advance.terminator.successors)
        updated_advance = replace(advance,
            completions=(*advance.completions, CompletionSignature(ExitKind.NORMAL, signature.types)),
            terminator=replace(advance.terminator, successors=(*advance.terminator.successors,
                CompletionSuccessor(ExitKind.NORMAL, target,
                    tuple(CompletionResult(slot) for slot in range(len(signature.types)))))))
        caller = replace(caller, blocks=(*caller.blocks, Block(target,
            tuple(actual.id for actual in caller_values), (new_normal_terminal.id,))))
        new_rows, new_inputs, new_links, new_receipts = [], [], [], []
        for row in graph.protocol_operations:
            if row.operation != advance.id or type(row.contract) is not ProtocolCall:
                continue
            site = ProtocolOperationRef(row.scope, row.clause, row.operation, row.slot)
            added = replace(row, slot=number, contract=replace(row.contract,
                result=InvokeLiteralResult(ControlEdgeReference(advance.id, number), CompletionResult(0))))
            added_site = ProtocolOperationRef(added.scope, added.clause, added.operation, added.slot)
            new_rows.append(added)
            new_inputs.extend(replace(receipt, site=added_site) for receipt in graph.protocol_call_inputs if receipt.site == site)
            new_links.extend(replace(link, advance=added_site) for link in graph.protocol_bindings
                             if type(link) is AwaitBodyLink and link.advance == site)
            new_receipts.append(ProtocolResultConsumers(added_site, (HostTerminal(new_normal_terminal.id),)))
        graph = replace(graph,
            regions=tuple(caller if region.id == caller.id else region for region in graph.regions),
            operations=tuple(updated_advance if item.id == advance.id else item for item in graph.operations)
                + (new_normal_terminal,), values=(*graph.values, *caller_values),
            control_scopes=tuple(replace(scope, blocks=(*scope.blocks, target))
                if scope.region == caller.id and scope.kind is ControlScopeKind.FUNCTION else scope
                for scope in graph.control_scopes),
            protocol_operations=(*graph.protocol_operations, *new_rows),
            protocol_call_inputs=(*graph.protocol_call_inputs, *new_inputs),
            protocol_bindings=(*graph.protocol_bindings, *new_links),
            protocol_result_consumers=(*graph.protocol_result_consumers, *new_receipts))
        advance = updated_advance

    selected_leg = next(leg for leg in legs if leg['kind'] is ExitKind.NORMAL)
    driver_choices = {edge.operation: edge.successor_index for edge in selected_leg['choices']}
    driver_path = _selected_path(graph, updated_driver, driver_choices)
    caller_blocks = {block.id: block for block in original['caller'].blocks}
    caller_choices = {caller_blocks[block].operations[-1]: number
        for block, number in original['caller_path'] if number is not None}
    if mode == 'replace_return':
        caller_choices[advance.id] = len(advance.terminator.successors) - 1
    caller_path = _selected_path(graph, caller, caller_choices)
    updated_last = {**original['drivers'][-1], 'driver_region': updated_driver,
        'caller_call': advance, 'path': driver_path, 'host_terminal': selected_leg['terminals'][0],
        'selected_call_edge': caller_choices[advance.id],
        'selected_landing': advance.terminator.successors[caller_choices[advance.id]].block}
    post_cleanup = {'mode': mode, 'driver_region': updated_driver, 'legs': tuple(legs),
        **{key: selected_leg[key] for key in ('packet_source', 'entry', 'actions', 'dispatch',
             'terminals', 'payload_uses', 'choices')},
        'packet_sources': tuple(leg['packet_source'] for leg in legs),
        'all_terminals': tuple(terminal for leg in legs for terminal in leg['terminals']),
        'caller_normal_terminal': new_normal_terminal,
        'original_driver_region': driver, 'original_host_terminal': original['drivers'][-1]['host_terminal']}
    return graph, {**original, 'caller': caller, 'caller_path': caller_path,
        'drivers': (*original['drivers'][:-1], updated_last),
        'calls': (*original['calls'][:-1], advance), 'post_cleanup': post_cleanup}


__all__ = ['await_post_cleanup_program']
