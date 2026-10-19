"""A real BodyRaise enters synchronous D cleanup without a converter.

The C1 subgraph reuses the already supplied synchronous cleanup template. Only
that subgraph is alpha-renamed and grafted: none of its body, acquisition,
conversion, caller, or extraction operations enter the returned program.
"""
from dataclasses import fields, is_dataclass, replace

from scar.ir.program.control import ControlScopeKind
from scar.ir.program.ids import BlockID, ControlPortID, ControlScopeID, LocationID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, CompletionResult, CompletionSignature,
    CompletionSuccessor, ExitKind, ExitPort, InvokeLiteralResult, LiteralOrigin,
    Operation, OperationResult, ProtocolValue, ReferenceValue, StateVersionValue,
    Terminator, TerminatorKind, Use, UseRole, ValueKind, ValueType,
)
from scar.ir.program.protocol_await_records import AwaitBodyLink
from scar.ir.program.protocol_connections import ProtocolOperationRef, ProtocolResultConsumers
from scar.ir.program.protocols import DriveResult, HostTerminal, OwnedUse, ProtocolCall
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.program_async_pipeline_graphs import _selected_path
from tests.fixtures.program_await_cleanup_final_graphs import await_cleanup_final_program
from tests.fixtures.program_await_post_cleanup_graphs import await_post_cleanup_program


_MODES = ('preserve', 'replace_raise', 'replace_return', 'opaque', 'wrong_terminal')


def _rewrite(value, maps):
    if type(value) in maps:
        return maps[type(value)].get(value, value)
    if type(value) is tuple:
        return tuple(_rewrite(item, maps) for item in value)
    if is_dataclass(value):
        return replace(value, **{member.name: _rewrite(getattr(value, member.name), maps)
                                 for member in fields(value)})
    return value


def add_driver_raise_cleanup(program, details, mode='preserve'):
    """Graft C1 onto this exact last driver's original BodyRaise landing.

    General and wrapper programs can compose preserve/replace_raise without
    changing a single caller signature or wrapper edge. Return is supported for
    an original direct parent only, and adds its genuine NORMAL exit/consumer.
    Other outcomes, source scopes, body slots and current-state records survive.
    """
    if type(mode) is not str or mode not in _MODES:
        raise ValueError('unknown BodyRaise cleanup mode')
    outcome = details['drive_outcome']
    values = {value.id: value for value in program.values}
    operations = {operation.id: operation for operation in program.operations}
    driver = next(region for region in program.regions
                  if region.id == details['drivers'][-1]['driver_region'].id)
    drive = next(row for row in program.body_drives if row.operation == outcome.drive)
    if drive.operation not in {identity for block in driver.blocks for identity in block.operations}:
        raise AssertionError('the supplied last driver must own the original DriveOutcomeRef')
    body_terminal = operations[outcome.source]
    if body_terminal.terminator.kind is not TerminatorKind.RAISE:
        raise AssertionError('the source must be a true body RAISE, not an adapter failure')
    drive_operation = operations[drive.operation]
    edge_number, edge = next((number, edge) for number, edge in enumerate(drive_operation.terminator.successors)
                             if edge.source == body_terminal.id)
    blocks = {block.id: block for block in driver.blocks}
    landing = blocks[edge.block]
    old_terminal = operations[landing.operations[-1]]
    if old_terminal.terminator.kind is not TerminatorKind.RAISE:
        raise AssertionError('the original body exception must have its genuine direct Raise terminal')
    old_uses = {use.id: use for use in old_terminal.uses}
    payload = values[old_uses[old_terminal.terminator.values[0]].value]
    states = tuple(values[old_uses[identity].value] for identity in old_terminal.terminator.values[1:])
    if type(payload) is not ProtocolValue or any(type(state) is not StateVersionValue for state in states):
        raise AssertionError('the original terminal retains the whole packet and its state tuple')
    function = next(scope for scope in program.control_scopes
        if scope.region == driver.id and scope.kind is ControlScopeKind.FUNCTION)
    parent = operations[details['drivers'][-1]['caller_call'].id]
    direct_parent = parent.callee == driver.id and any(parent.id in block.operations
                                                     for block in details['caller'].blocks)
    if mode == 'replace_return' and not direct_parent:
        raise ValueError('Return needs a real direct caller; no wrapper NORMAL edge is fabricated')

    template, template_details = await_post_cleanup_program(mode=mode)
    source = next(leg for leg in template_details['post_cleanup']['legs'] if leg['kind'] is ExitKind.NORMAL)
    template_driver = template_details['post_cleanup']['driver_region']
    template_values = {value.id: value for value in template.values}
    template_operations = {operation.id: operation for operation in template.operations}
    template_blocks = {block.id: block for block in template_driver.blocks}
    primary_operation = template_values[source['pending'].value].origin.operation
    template_terminal = source['terminals'][0]
    template_cleanup = next(scope for scope in template.control_scopes if scope.id == source['interface'].scope)
    copied_blocks = {block for block in template_cleanup.blocks}
    copied_blocks.update(block.id for block in template_driver.blocks
        if any(item.id in block.operations for item in (source['dispatch'], source['routes'][-1])))
    copied_blocks.add(source['handler'].id)
    operation_ids = {identity for block in copied_blocks for identity in template_blocks[block].operations}
    operation_ids.update((primary_operation, source['routes'][0].id))
    copied_operations = tuple(operation for operation in template.operations if operation.id in operation_ids)
    used_values = {use.value for operation in copied_operations for use in operation.uses}
    copied_values = tuple(value for value in template.values
        if type(value.origin) is OperationResult and value.origin.operation in operation_ids
        or type(value.origin) is BlockArgument and value.origin.block in copied_blocks
        or type(value.origin) is LiteralOrigin and value.id in used_values)
    prefix = 'await.raise-cleanup.'
    maps = {
        RegionID: {template_driver.id: driver.id},
        BlockID: {identity: BlockID(prefix + identity.value) for identity in copied_blocks},
        OperationID: {identity: OperationID(prefix + identity.value) for identity in operation_ids},
        ValueID: {value.id: ValueID(prefix + value.id.value) for value in copied_values},
        UseID: {use.id: UseID(prefix + use.id.value) for operation in copied_operations for use in operation.uses},
        ControlScopeID: {source['interface'].scope: ControlScopeID(prefix + 'cleanup.scope'),
            source['interface'].protected: ControlScopeID(prefix + 'protected.scope')},
        ControlPortID: {port.id: ControlPortID(prefix + port.id.value)
                       for port in (source['port'], source['outgoing_port'])},
        LocationID: {},
    }
    template_function = next(scope for scope in template.control_scopes
        if scope.region == template_driver.id and scope.kind is ControlScopeKind.FUNCTION)
    maps[ControlScopeID][template_function.id] = function.id
    maps[BlockID][source['entry'].id] = landing.id
    maps[OperationID][template_terminal.id] = old_terminal.id
    maps[ValueID][source['packet_value'].id] = payload.id
    for template_use, actual_use in zip(template_terminal.uses, old_terminal.uses, strict=True):
        maps[UseID][template_use.id] = actual_use.id
    # Entry-route state operands, rather than the post-cleanup template
    # terminal operands, identify the template's current incoming states.
    template_entry_states = tuple(template_values[use.value]
        for use in source['routes'][0].uses if type(template_values[use.value]) is StateVersionValue)
    if len(template_entry_states) != len(states):
        raise AssertionError('cleanup template and target must carry the same full state arity')
    for old, actual in zip(template_entry_states, states, strict=True):
        maps[ValueID][old.id] = actual.id
        maps[LocationID][old.location] = actual.location
    rewrite = lambda item: _rewrite(item, maps)
    added_operations = tuple(rewrite(operation) for operation in copied_operations)
    added_values = tuple(rewrite(value) for value in copied_values)
    added_blocks = tuple(rewrite(block) for block in template_driver.blocks if block.id in copied_blocks)
    into, primary_pack = rewrite(source['routes'][0]), rewrite(template_operations[primary_operation])
    landed = replace(landing, operations=(*landing.operations[:-1], primary_pack.id, into.id))
    selected_cleanup_scopes = {source['interface'].scope, source['interface'].protected}
    added_scopes = tuple(rewrite(scope) for scope in template.control_scopes if scope.id in selected_cleanup_scopes)
    root_blocks = tuple(block.id for block in added_blocks if block.id not in
                        {block for scope in added_scopes for block in scope.blocks})
    driver = replace(driver, blocks=tuple(landed if block.id == landing.id else block for block in driver.blocks)
                     + added_blocks)
    if mode == 'replace_return':
        if any(port.kind is ExitKind.NORMAL for port in driver.exits):
            raise ValueError('this direct Return fixture needs an originally Raise-only D')
        types = (ValueType(ValueKind.REFERENCE), *(ValueType(ValueKind.STATE, location=state.location) for state in states))
        driver = replace(driver, exits=(*driver.exits, ExitPort('normal', ExitKind.NORMAL, types)))
    selected_pending = {source['pending'].value}
    if source['replacement_pending'] is not None:
        selected_pending.add(source['replacement_pending'].value)
    added_tables = {}
    for name in ('handled_context_domains', 'cleanup_interfaces', 'cleanup_enters', 'cleanup_resumes',
                 'cleanup_replacements', 'pending_completions', 'exception_packets', 'control_ports'):
        rows = getattr(template, name)
        if name == 'handled_context_domains':
            selected_rows = tuple(row for row in rows if row.region == template_driver.id)
        elif name == 'cleanup_interfaces':
            selected_rows = tuple(row for row in rows if row.scope == source['interface'].scope)
        elif name in ('cleanup_enters', 'cleanup_resumes', 'cleanup_replacements'):
            selected_rows = tuple(row for row in rows if row.operation in operation_ids)
        elif name == 'pending_completions':
            selected_rows = tuple(row for row in rows if row.value in selected_pending)
        elif name == 'exception_packets':
            selected_rows = tuple(row for row in rows if row.value in {value.id for value in copied_values})
        else:
            selected_rows = tuple(row for row in rows if row.id in (source['port'].id, source['outgoing_port'].id))
        added_tables[name] = (*getattr(program, name), *rewrite(selected_rows))
    result = replace(program,
        regions=tuple(driver if region.id == driver.id else region for region in program.regions),
        operations=tuple(operation for operation in program.operations if operation.id != old_terminal.id) + added_operations,
        values=(*program.values, *added_values),
        control_scopes=tuple(replace(scope,
            blocks=tuple(block for block in scope.blocks if block != landing.id) + root_blocks)
            if scope.id == function.id else scope for scope in program.control_scopes) + added_scopes,
        **added_tables)

    caller = next(region for region in result.regions if region.id == details['caller'].id)
    normal_consumer = None
    if mode == 'replace_return':
        target = BlockID(prefix + 'caller.normal')
        outputs = (ReferenceValue(ValueID(prefix + 'caller.normal.value'), caller.id, BlockArgument(target, 0)),
            *(StateVersionValue(ValueID(prefix + f'caller.normal.state.{number}'), caller.id,
                BlockArgument(target, number + 1), state.location) for number, state in enumerate(states)))
        operands = tuple(Use(UseID(prefix + f'caller.normal.use.{number}'), value.id,
            UseRole.REFERENCE if number == 0 else UseRole.STATE_CONTENT) for number, value in enumerate(outputs))
        normal_consumer = Operation(OperationID(prefix + 'caller.normal.return'), 'actual replacement Return consumer',
            (Behavior.CONTROL,), operands, effects_complete=True,
            terminator=Terminator(TerminatorKind.RETURN, exit='normal', values=tuple(use.id for use in operands)))
        number = len(parent.terminator.successors)
        parent = replace(parent, completions=(*parent.completions, CompletionSignature(ExitKind.NORMAL, types)),
            terminator=replace(parent.terminator, successors=(*parent.terminator.successors,
                CompletionSuccessor(ExitKind.NORMAL, target, tuple(CompletionResult(slot) for slot in range(len(types)))))))
        caller = replace(caller, blocks=(*caller.blocks, Block(target, tuple(value.id for value in outputs), (normal_consumer.id,))),
            exits=(*caller.exits, ExitPort('normal', ExitKind.NORMAL, types)))
        new_rows, new_inputs, new_links, new_receipts = [], [], [], []
        for row in result.protocol_operations:
            if row.operation != parent.id or type(row.contract) is not ProtocolCall:
                continue
            old_ref = ProtocolOperationRef(row.scope, row.clause, row.operation, row.slot)
            added = replace(row, slot=number, contract=replace(row.contract,
                result=InvokeLiteralResult(ControlEdgeReference(parent.id, number), CompletionResult(0))))
            new_ref = ProtocolOperationRef(added.scope, added.clause, added.operation, added.slot)
            new_rows.append(added)
            new_inputs.extend(replace(item, site=new_ref) for item in result.protocol_call_inputs if item.site == old_ref)
            new_links.extend(replace(item, advance=new_ref) for item in result.protocol_bindings
                             if type(item) is AwaitBodyLink and item.advance == old_ref)
            new_receipts.append(ProtocolResultConsumers(new_ref, (HostTerminal(normal_consumer.id),)))
        result = replace(result, regions=tuple(caller if region.id == caller.id else region for region in result.regions),
            operations=tuple(parent if operation.id == parent.id else operation for operation in result.operations) + (normal_consumer,),
            values=(*result.values, *outputs),
            control_scopes=tuple(replace(scope, blocks=(*scope.blocks, target))
                if scope.region == caller.id and scope.kind is ControlScopeKind.FUNCTION else scope for scope in result.control_scopes),
            protocol_operations=(*result.protocol_operations, *new_rows),
            protocol_call_inputs=(*result.protocol_call_inputs, *new_inputs),
            protocol_bindings=(*result.protocol_bindings, *new_links),
            protocol_result_consumers=(*result.protocol_result_consumers, *new_receipts))

    old_driver_blocks = {block.id: block for block in next(region for region in program.regions if region.id == driver.id).blocks}
    choices = {old_driver_blocks[block].operations[-1]: number
               for block, number in details['drivers'][-1]['path'] if number is not None}
    choices.update((operation.id, 0) for operation in added_operations
                   if operation.terminator is not None and operation.terminator.successors)
    driver_path = _selected_path(result, driver, choices)
    all_operations = {operation.id: operation for operation in result.operations}
    terminal = all_operations[old_terminal.id]
    current_source = rewrite(source['replacement_source']) if source['replacement_source'] is not None else DriveResult(outcome, 0)
    original_caller_blocks = {block.id: block for block in details['caller'].blocks}
    caller_choices = {original_caller_blocks[block].operations[-1]: number
                      for block, number in details['caller_path'] if number is not None}
    if mode == 'replace_return':
        caller_choices[parent.id] = len(parent.terminator.successors) - 1
    caller_path = _selected_path(result, caller, caller_choices)
    consumer_block = next(block for block in caller.blocks if block.id == caller_path[-1][0])
    consumer_operation = all_operations.get(consumer_block.operations[-1], normal_consumer)
    if consumer_operation is None:
        raise AssertionError('the selected caller path must retain its actual final consumer')
    final_driver = {**details['drivers'][-1], 'driver_region': driver, 'path': driver_path,
        'host_terminal': terminal, 'caller_call': parent}
    if direct_parent:
        final_driver.update(selected_call_edge=caller_choices[parent.id],
                            selected_landing=parent.terminator.successors[caller_choices[parent.id]].block)
    metadata = {key: rewrite(source[key]) for key in (
        'interface', 'pending', 'pending_payload_use', 'actions', 'action_operations', 'routes',
        'dispatch', 'port', 'outgoing_port', 'replacement_source', 'replacement_result', 'replacement_pending', 'opaque')}
    selected_choices = tuple(ControlEdgeReference(next(block for block in driver.blocks if block.id == identity).operations[-1], number)
                             for identity, number in driver_path if number is not None)
    metadata.update(mode=mode, driver_region=driver, drive=drive,
        drive_edge=ControlEdgeReference(drive.operation, edge_number), root_source=DriveResult(outcome, 0),
        packet_source=DriveResult(outcome, 0), body_terminal=body_terminal, entry=landed,
        cleanup_entry=next(block for block in driver.blocks if block.id == metadata['interface'].entry),
        current_source=current_source, terminals=(terminal,),
        payload_uses=(OwnedUse(terminal.id, terminal.terminator.values[0]),),
        state_uses=tuple(OwnedUse(terminal.id, use) for use in terminal.terminator.values[1:]),
        choices=selected_choices, caller_normal_terminal=normal_consumer,
        consumer=HostTerminal(consumer_operation.id), consumer_operation=consumer_operation,
        consumer_payload_use=OwnedUse(consumer_operation.id, consumer_operation.terminator.values[0]),
        consumer_state_uses=tuple(OwnedUse(consumer_operation.id, identity)
                                 for identity in consumer_operation.terminator.values[1:]),
        original_driver_region=next(region for region in program.regions if region.id == driver.id),
        original_host_terminal=old_terminal, parent_calls=tuple(operation for operation in result.operations if operation.callee == driver.id))
    return result, {**details, 'caller': caller, 'caller_path': caller_path,
        'drivers': (*details['drivers'][:-1], final_driver),
        'calls': tuple(parent if call.id == parent.id else call for call in details.get('calls', ())),
        **({'final': normal_consumer, 'extract_input': HostTerminal(normal_consumer.id),
            'packet_use': metadata['consumer_payload_use'], 'state_uses': metadata['consumer_state_uses'],
            'call_rows': (*details.get('call_rows', ()), *new_rows),
            'links': (*details.get('links', ()), *new_links)} if normal_consumer is not None else {}),
        'raise_cleanup': metadata}


def await_raise_cleanup_program(mode='preserve'):
    program, details = await_cleanup_final_program(body_raised=True)
    return add_driver_raise_cleanup(program, details, mode=mode)


__all__ = ['add_driver_raise_cleanup', 'await_raise_cleanup_program']
