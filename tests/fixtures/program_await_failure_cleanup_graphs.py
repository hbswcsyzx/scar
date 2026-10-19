"""Original await failures followed by synchronous cleanup in their caller.

The acquisition's own RAISE is immutable.  The supplied C1 records may preserve
that packet or replace the caller's current completion, including with Return.
No body drive, conversion, helper, or suspension is copied from the C1 template.
"""
from dataclasses import replace

from scar.ir.program.control import ControlScopeKind, ProtocolValueKind
from scar.ir.program.ids import (
    BlockID, ControlPortID, ControlScopeID, LocationID, OperationID, RegionID,
    UseID, ValueID,
)
from scar.ir.program.model import (
    BlockArgument, CompletionResult, ExitKind, InvokeLiteralResult, LiteralOrigin,
    OperationResult, ProtocolValue, ReferenceValue, StateVersionValue, TerminatorKind, ValueKind,
)
from scar.ir.program.protocol_connections import ProtocolOperationRef
from scar.ir.program.protocols import HostTerminal, OwnedUse
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.program_async_pipeline_graphs import _selected_path
from tests.fixtures.program_await_failure_graphs import await_failure_program
from tests.fixtures.program_await_post_cleanup_graphs import await_post_cleanup_program
from tests.fixtures.program_await_raise_cleanup_graphs import _rewrite
from tests.fixtures.program_await_wrapper_graphs import await_wrapper_program


_STAGES = (
    'lookup_raise', 'method_call_raise', 'qualification_reject',
    'wrapper_constructor_raise',
)
_MODES = ('preserve', 'replace_raise', 'replace_return', 'opaque', 'wrong_terminal')


def _completion(operation, kind):
    number, edge = next((number, edge)
        for number, edge in enumerate(operation.terminator.successors)
        if edge.kind is kind)
    signature = next(row for row in operation.completions if row.kind is kind)
    slots = tuple(slot for slot, type_ in enumerate(signature.types)
                  if type_.kind is not ValueKind.STATE)
    if len(slots) != 1:
        raise AssertionError('the original completion must have one non-state payload')
    reference = ControlEdgeReference(operation.id, number)
    return reference, InvokeLiteralResult(reference, CompletionResult(slots[0]))


def _forward_reference(program, details, operation):
    """A real forwarded value is not an own CompletionResult at this landing."""
    edge_ref, _ = _completion(operation, ExitKind.RAISE)
    edge = operation.terminator.successors[edge_ref.successor_index]
    caller = next(region for region in program.regions
                  if any(operation.id in block.operations for block in region.blocks))
    landing = next(block for block in caller.blocks if block.id == edge.block)
    forwarded_use = replace(operation.uses[0],
                            id=UseID('await.failure-cleanup.source.forward.use'))
    forwarded = ReferenceValue(ValueID('await.failure-cleanup.source.forward.value'),
                              caller.id, BlockArgument(landing.id, 0))
    successors = tuple(replace(original, arguments=(forwarded_use.id, *original.arguments))
                       if number == edge_ref.successor_index else original
                       for number, original in enumerate(operation.terminator.successors))
    operation = replace(operation, uses=(*operation.uses, forwarded_use),
                        terminator=replace(operation.terminator, successors=successors))
    caller = replace(caller, blocks=tuple(replace(block,
        arguments=(forwarded.id, *block.arguments)) if block.id == landing.id else block
        for block in caller.blocks))
    program = replace(program,
        regions=tuple(caller if region.id == caller.id else region for region in program.regions),
        operations=tuple(operation if row.id == operation.id else row for row in program.operations),
        values=tuple(replace(value, origin=replace(value.origin, index=value.origin.index + 1))
            if type(value.origin) is BlockArgument and value.origin.block == landing.id else value
            for value in program.values) + (forwarded,))
    details = {**details, 'get': operation,
        **({'constructor': operation} if details.get('constructor') is not None else {})}
    return program, details, operation, forwarded, OwnedUse(operation.id, forwarded_use.id)


def _stage_details(program, details, stage):
    """Keep a rejecting control edge separate from its real packet producer."""
    if stage == 'wrapper_constructor_raise':
        return {
            'helper_region': None, 'helper_path': (), 'helper_terminal': None,
            'helper_stage_packet_use': None, 'helper_state_uses': (),
            'stage_operation': details['constructor'], 'stage_source': None,
            'stage_edge': None, 'stage_prefix': (), 'reject_edge': None,
            'packet_definition': None, 'packet_constructor': None,
            'packet_exception_use': None, 'packet_traceback_use': None,
        }
    helper = details['helper']
    terminal = details['failure_terminal']
    terminal_use = OwnedUse(terminal.id, terminal.terminator.values[0])
    values = {value.id: value for value in program.values}
    operations = {operation.id: operation for operation in program.operations}
    owned = next(use for use in terminal.uses if use.id == terminal_use.use)
    packet = values[owned.value]
    if type(packet) is not ProtocolValue or packet.protocol is not ProtocolValueKind.EXCEPTION_PACKET:
        raise AssertionError('the original helper failure must emit its whole packet')
    choices, prefix = {}, []
    lookup, call = details['helper_lookup'], details['helper_call']
    reject, definition, constructor, exception_use, traceback_use = None, None, None, None, None
    if stage == 'lookup_raise':
        operation = lookup
        edge, source = _completion(operation, ExitKind.RAISE)
        choices[operation.id] = edge.successor_index
    else:
        lookup_normal, _ = _completion(lookup, ExitKind.NORMAL)
        choices[lookup.id] = lookup_normal.successor_index
        prefix.append(lookup_normal)
        if stage == 'method_call_raise':
            operation = call
            edge, source = _completion(operation, ExitKind.RAISE)
            choices[operation.id] = edge.successor_index
        else:
            call_normal, _ = _completion(call, ExitKind.NORMAL)
            choices[call.id] = call_normal.successor_index
            prefix.append(call_normal)
            operation = details['qualification_branch']
            qualification = details['qualification_row'].contract
            reject = ControlEdgeReference(operation.id, 1 if qualification.accepts_true else 0)
            edge = reject
            choices[operation.id] = reject.successor_index
            # The original terminal's packet has a canonical construction,
            # independent of the later caller cleanup or replacement value.
            source = packet.origin
            if type(source) is not OperationResult:
                raise AssertionError('this rejection arm supplies an original packet constructor')
            definition = next(row for row in program.exception_packets if row.value == packet.id)
            constructor = operations[source.operation]
            exception_use = OwnedUse(constructor.id, definition.exception)
            traceback_use = OwnedUse(constructor.id, definition.traceback)
    return {
        'helper_region': helper,
        'helper_path': _selected_path(program, helper, choices),
        'helper_terminal': terminal,
        'helper_stage_packet_use': terminal_use,
        'helper_state_uses': tuple(OwnedUse(terminal.id, identity)
                                  for identity in terminal.terminator.values[1:]),
        'stage_operation': operation, 'stage_source': source, 'stage_edge': edge,
        'stage_prefix': tuple(prefix), 'reject_edge': reject,
        'packet_definition': definition, 'packet_constructor': constructor,
        'packet_exception_use': exception_use, 'packet_traceback_use': traceback_use,
    }


def await_failure_cleanup_program(stage='qualification_reject', mode='preserve'):
    """Return a full original graph and exact failure/C1 capture metadata."""
    if type(stage) is not str or stage not in _STAGES:
        raise ValueError('unknown original await failure stage')
    if type(mode) is not str or mode not in _MODES:
        raise ValueError('unknown synchronous failure cleanup mode')
    if stage == 'wrapper_constructor_raise':
        program, details = await_wrapper_program()
        source_operation = details['constructor']
        source_rows = details['constructor_rows']
    else:
        program, details = await_failure_program(stage)
        source_operation = details['get']
        source_rows = details['get_rows']
    program, details, source_operation, forwarded, forwarded_use = _forward_reference(
        program, details, source_operation)
    internal = _stage_details(program, details, stage)
    source_edge, source_result = _completion(source_operation, ExitKind.RAISE)
    source_row = next(row for row in source_rows if row.contract.result == source_result)
    source_ref = ProtocolOperationRef(source_row.scope, source_row.clause,
                                      source_row.operation, source_row.slot)
    if stage == 'wrapper_constructor_raise':
        internal.update(stage_source=source_result, stage_edge=source_edge)
    caller = next(region for region in program.regions
        if any(source_operation.id in block.operations for block in region.blocks))
    values = {value.id: value for value in program.values}
    operations = {operation.id: operation for operation in program.operations}
    landing = next(block for block in caller.blocks
                   if block.id == source_operation.terminator.successors[source_edge.successor_index].block)
    old_terminal = operations[landing.operations[-1]]
    if old_terminal.terminator.kind is not TerminatorKind.RAISE:
        raise AssertionError('the unmodified source has its own genuine Raise landing')
    old_uses = {use.id: use for use in old_terminal.uses}
    root_packet = values[old_uses[old_terminal.terminator.values[0]].value]
    source_states = tuple(values[old_uses[identity].value]
                          for identity in old_terminal.terminator.values[1:])
    if (type(root_packet) is not ProtocolValue
            or root_packet.protocol is not ProtocolValueKind.EXCEPTION_PACKET
            or any(type(state_value) is not StateVersionValue for state_value in source_states)):
        raise AssertionError('the source Raise landing retains its packet and complete state tuple')
    function = next(scope for scope in program.control_scopes
                    if scope.region == caller.id and scope.kind is ControlScopeKind.FUNCTION)

    template, template_details = await_post_cleanup_program(mode=mode)
    graft = next(leg for leg in template_details['post_cleanup']['legs'] if leg['kind'] is ExitKind.NORMAL)
    template_region = template_details['post_cleanup']['driver_region']
    template_values = {value.id: value for value in template.values}
    template_operations = {operation.id: operation for operation in template.operations}
    template_blocks = {block.id: block for block in template_region.blocks}
    cleanup_scope = next(scope for scope in template.control_scopes if scope.id == graft['interface'].scope)
    copied_blocks = set(cleanup_scope.blocks)
    copied_blocks.update(block.id for block in template_region.blocks
        if any(item.id in block.operations for item in (graft['dispatch'], graft['routes'][-1])))
    copied_blocks.add(graft['handler'].id)
    primary_operation = template_values[graft['pending'].value].origin.operation
    operation_ids = {identity for block in copied_blocks for identity in template_blocks[block].operations}
    operation_ids.update((primary_operation, graft['routes'][0].id))
    copied_operations = tuple(operation for operation in template.operations if operation.id in operation_ids)
    used_values = {use.value for operation in copied_operations for use in operation.uses}
    copied_values = tuple(value for value in template.values
        if type(value.origin) is OperationResult and value.origin.operation in operation_ids
        or type(value.origin) is BlockArgument and value.origin.block in copied_blocks
        or type(value.origin) is LiteralOrigin and value.id in used_values)
    prefix = 'await.failure-cleanup.'
    maps = {
        RegionID: {template_region.id: caller.id},
        BlockID: {identity: BlockID(prefix + identity.value) for identity in copied_blocks},
        OperationID: {identity: OperationID(prefix + identity.value) for identity in operation_ids},
        ValueID: {value.id: ValueID(prefix + value.id.value) for value in copied_values},
        UseID: {use.id: UseID(prefix + use.id.value) for operation in copied_operations for use in operation.uses},
        ControlScopeID: {
            graft['interface'].scope: ControlScopeID(prefix + 'cleanup.scope'),
            graft['interface'].protected: ControlScopeID(prefix + 'protected.scope'),
        },
        ControlPortID: {port.id: ControlPortID(prefix + port.id.value)
                       for port in (graft['port'], graft['outgoing_port'])},
        LocationID: {},
    }
    template_function = next(scope for scope in template.control_scopes
        if scope.region == template_region.id and scope.kind is ControlScopeKind.FUNCTION)
    maps[ControlScopeID][template_function.id] = function.id
    maps[BlockID][graft['entry'].id] = landing.id
    maps[OperationID][graft['terminals'][0].id] = old_terminal.id
    maps[ValueID][graft['packet_value'].id] = root_packet.id
    for original, actual in zip(graft['terminals'][0].uses, old_terminal.uses, strict=True):
        maps[UseID][original.id] = actual.id
    entry_states = tuple(template_values[use.value] for use in graft['routes'][0].uses
                         if type(template_values[use.value]) is StateVersionValue)
    if len(entry_states) != len(source_states):
        raise AssertionError('the cleanup and original failure must carry the same state arity')
    for original, actual in zip(entry_states, source_states, strict=True):
        maps[ValueID][original.id] = actual.id
        maps[LocationID][original.location] = actual.location
    rewrite = lambda item: _rewrite(item, maps)
    added_operations = tuple(rewrite(operation) for operation in copied_operations)
    added_values = tuple(rewrite(value) for value in copied_values)
    added_blocks = tuple(rewrite(block) for block in template_region.blocks if block.id in copied_blocks)
    into = rewrite(graft['routes'][0])
    primary_pack = rewrite(template_operations[primary_operation])
    entry = replace(landing, operations=(*landing.operations[:-1], primary_pack.id, into.id))
    selected_scopes = {graft['interface'].scope, graft['interface'].protected}
    added_scopes = tuple(rewrite(scope) for scope in template.control_scopes if scope.id in selected_scopes)
    owned_blocks = {block for scope in added_scopes for block in scope.blocks}
    root_blocks = tuple(block.id for block in added_blocks if block.id not in owned_blocks)
    caller = replace(caller, blocks=tuple(entry if block.id == entry.id else block for block in caller.blocks)
                     + added_blocks)
    # The caller already has its real NORMAL exit; the get/constructor N/R
    # signature, result slots, and both original successor edges stay intact.
    terminal = next(operation for operation in added_operations if operation.id == old_terminal.id)
    pending_values = {graft['pending'].value}
    if graft['replacement_pending'] is not None:
        pending_values.add(graft['replacement_pending'].value)
    added_tables = {}
    for name in ('handled_context_domains', 'cleanup_interfaces', 'cleanup_enters', 'cleanup_resumes',
                 'cleanup_replacements', 'pending_completions', 'exception_packets', 'control_ports'):
        rows = getattr(template, name)
        if name == 'handled_context_domains':
            selected_rows = tuple(row for row in rows if row.region == template_region.id)
        elif name == 'cleanup_interfaces':
            selected_rows = tuple(row for row in rows if row.scope == graft['interface'].scope)
        elif name in ('cleanup_enters', 'cleanup_resumes', 'cleanup_replacements'):
            selected_rows = tuple(row for row in rows if row.operation in operation_ids)
        elif name == 'pending_completions':
            selected_rows = tuple(row for row in rows if row.value in pending_values)
        elif name == 'exception_packets':
            selected_rows = tuple(row for row in rows if row.value in {value.id for value in copied_values})
        else:
            selected_rows = tuple(row for row in rows if row.id in (graft['port'].id, graft['outgoing_port'].id))
        added_tables[name] = (*getattr(program, name), *rewrite(selected_rows))
    pending_payload_use = rewrite(graft['pending_payload_use'])
    result = replace(program,
        regions=tuple(caller if region.id == caller.id else region for region in program.regions),
        operations=tuple(operation for operation in program.operations if operation.id != old_terminal.id)
            + added_operations,
        values=(*program.values, *added_values),
        control_scopes=tuple(replace(scope,
            blocks=tuple(block for block in scope.blocks if block != entry.id) + root_blocks)
            if scope.id == function.id else scope for scope in program.control_scopes) + added_scopes,
        protocol_result_consumers=tuple(replace(receipt, targets=(pending_payload_use,))
            if receipt.site == source_ref else receipt for receipt in program.protocol_result_consumers),
        **added_tables)
    # All new C1 transfer blocks have one real successor. The existing Create
    # selects its original NORMAL edge; the source keeps its original RAISE.
    choices = {source_operation.id: source_edge.successor_index}
    choices.update((operation.id, 0) for operation in added_operations
                   if operation.terminator is not None and operation.terminator.successors)
    creation = operations[details['create'].operation]
    create_edge, _ = _completion(creation, ExitKind.NORMAL)
    choices[creation.id] = create_edge.successor_index
    caller_path = _selected_path(result, caller, choices)
    blocks = {block.id: block for block in caller.blocks}
    caller_choices = tuple(ControlEdgeReference(blocks[block].operations[-1], number)
                           for block, number in caller_path if number is not None)
    metadata = {key: rewrite(graft[key]) for key in (
        'interface', 'pending', 'actions', 'action_operations', 'routes', 'dispatch',
        'port', 'outgoing_port', 'replacement_source', 'replacement_result',
        'replacement_pending', 'opaque',
    )}
    current_source = metadata['replacement_source'] or source_result
    payload_use = OwnedUse(terminal.id, terminal.terminator.values[0])
    state_uses = tuple(OwnedUse(terminal.id, identity) for identity in terminal.terminator.values[1:])
    metadata.update(
        stage=stage, mode=mode, caller_region=caller, caller_path=caller_path,
        source_operation=source_operation, source_result=source_result, source_edge=source_edge,
        source_row=source_row, source_ref=source_ref,
        forwarded_reference=forwarded, forwarded_use=forwarded_use,
        root_source=source_result, root_packet=root_packet, source_states=source_states,
        source_consumer=pending_payload_use, source_consumers=(pending_payload_use,),
        pending_payload_use=pending_payload_use, current_source=current_source,
        entry=entry, cleanup_entry=next(block for block in caller.blocks if block.id == metadata['interface'].entry),
        terminals=(terminal,), payload_uses=(payload_use,), state_uses=state_uses,
        consumer=HostTerminal(terminal.id), consumer_operation=terminal,
        consumer_payload_use=payload_use, consumer_state_uses=state_uses,
        choices=caller_choices, original_terminal=old_terminal,
        **internal,
    )
    return result, {**details, 'get_failure': terminal,
        'caller': caller, 'caller_path': caller_path, 'failure_stage': stage,
        'failure_cleanup': metadata}


__all__ = ['await_failure_cleanup_program']
