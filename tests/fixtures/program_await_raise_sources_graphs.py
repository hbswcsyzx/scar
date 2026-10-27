"""Independent general/W sources whose actual B outcome is a whole BodyRaise.

The zero path has no cut. The two-cut path preserves B's real C1 replacement,
including its reachable Return alternative and that alternative's converter.
No extractor child supplies the selected exception.
"""
from dataclasses import replace

from scar.ir.program.control import ExceptionPacketDefinition, PendingDispatchTerminator
from scar.ir.program.ids import OperationID, UseID, ValueID
from scar.ir.program.lifecycle import DriveOutcomeRef
from scar.ir.program.model import (
    Behavior, BlockArgument, CompletionResult, ExitKind, ExitPort,
    InvokeLiteralResult, LiteralOrigin, Operation, OperationResult, ProtocolValue,
    ReferenceValue, Terminator, TerminatorKind, Use,
)
from scar.ir.program.protocol_connections import ProtocolOperationRef, ProtocolResultConsumers
from scar.ir.program.protocols import (
    DriveResult, DriverSubject, HostTerminal, OutcomeAdapter, OutcomeAdapterRule,
    OwnedUse, ProtocolClause, ProtocolProfile,
)
from scar.ir.program.resumption import ResumableKind, SuspendTerminator, SuspensionFlavor
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.program_async_pipeline_graphs import _selected_path
from tests.fixtures.program_await_cleanup_final_graphs import (
    _BODY_TABLES, _PART_TABLES, _body as _cleanup_body, _rewrite, _stage,
)
from tests.fixtures.program_await_general_final_graphs import await_general_final_program
from tests.fixtures.program_await_raise_cleanup_graphs import add_driver_raise_cleanup
from tests.fixtures.program_await_resume_graphs import _body as _resume_body
from tests.fixtures.program_await_wrapper_final_graphs import await_wrapper_final_program
from tests.fixtures.program_driver_graphs import PACKET, _use
from tests.fixtures.program_packet_continuation_graphs import _explicit_transfers


def _raising_body(program, details, zero_cut, kind):
    if not zero_cut:
        body, capture_map = _cleanup_body(program, details, raised=True)
        body = replace(body,
            resumable_bodies=tuple(replace(row, kind=kind) for row in body.resumable_bodies),
            operations=tuple(replace(operation, terminator=replace(operation.terminator,
                flavor=SuspensionFlavor.AWAIT)) if kind is ResumableKind.COROUTINE
                and type(operation.terminator) is SuspendTerminator else operation
                for operation in body.operations))
        body, _ = _explicit_transfers(body)
        return body, capture_map, (OperationID('finally.suspend'),
            OperationID('finally.second.suspend')), OperationID('finally.raise-exit.op')
    body = _resume_body(zero_cut=True, kind=kind)
    region, = body.regions
    entry = next(block for block in region.blocks if block.id == region.entry)
    original = next(operation for operation in body.operations
                    if operation.terminator is not None
                    and operation.terminator.kind is TerminatorKind.RETURN)
    traceback = ReferenceValue(ValueID('await.raise.zero.traceback'), region.id,
                               LiteralOrigin(None), targets=())
    pack_id = OperationID('await.raise.zero.pack')
    packet = ProtocolValue(ValueID('await.raise.zero.packet'), region.id,
                           OperationResult(pack_id, 0), PACKET.protocol)
    packet_inputs = (_use('await.raise.zero.exception', entry.arguments[0]),
                     _use('await.raise.zero.traceback.use', traceback.id))
    pack = Operation(pack_id, 'construct the actual zero-cut body exception packet',
        (Behavior.CONTROL,), packet_inputs, (packet.id,), effects_complete=True)
    payload = _use('await.raise.zero.payload', packet.id, protocol=True)
    terminal = replace(original, id=OperationID('await.raise.zero.raise'),
        label='raise before any suspension', uses=(payload, *original.uses[1:]),
        terminator=Terminator(TerminatorKind.RAISE, exit='failure',
            values=(payload.id, *original.terminator.values[1:])))
    detach = body.frame_context_detaches[0].operation
    ordered = tuple(identity for identity in entry.operations if identity != original.id)
    operations = tuple(operation for operation in body.operations if operation.id != original.id)
    region = replace(region, parent=details['caller'].id, exits=(ExitPort('failure', ExitKind.RAISE,
        (PACKET, *region.exits[0].types[1:])),), blocks=(replace(entry,
            operations=tuple(identity for item in ordered
                for identity in ((pack.id, item) if item == detach else (item,))) + (terminal.id,)),))
    return replace(body, regions=(region,), operations=(*operations, pack, terminal),
        values=(*body.values, traceback, packet),
        exception_packets=(ExceptionPacketDefinition(packet.id,
            packet_inputs[0].id, packet_inputs[1].id),)), {}, (), terminal.id


def _typed_part(part, source_kind):
    profile = (ProtocolProfile.COROUTINE_BODY_V1 if source_kind == 'wrapper'
               else ProtocolProfile.GENERATOR_BODY_V1)
    clause = (ProtocolClause.AWAIT_COMPLETION_ADAPTER if source_kind == 'wrapper'
              else ProtocolClause.HOST_ADAPTER)
    rows = []
    for row in part['protocol_operations']:
        if type(row.contract) is OutcomeAdapter:
            contract = row.contract
            if source_kind == 'wrapper' and contract.rule is OutcomeAdapterRule.GENERATOR_RETURN_TO_STOP_ITERATION:
                contract = replace(contract, rule=OutcomeAdapterRule.COROUTINE_RETURN_TO_STOP_ITERATION)
            row = replace(row, clause=clause, contract=contract)
        rows.append(row)
    return {**part, 'protocol_scopes': tuple(replace(scope, profile=profile)
        if type(scope.subject) is DriverSubject else scope for scope in part['protocol_scopes']),
        'protocol_operations': tuple(rows)}


def await_raise_source_program(source_kind='general', zero_cut=True, cleanup_mode=None):
    """Return one connected source -> B Raise -> D -> original parent graph."""
    if type(source_kind) is not str or source_kind not in ('general', 'wrapper'):
        raise ValueError('source_kind must be general or wrapper')
    if type(zero_cut) is not bool:
        raise TypeError('zero_cut must be exact bool')
    if cleanup_mode not in (None, 'preserve', 'replace_raise'):
        raise ValueError('cleanup_mode must be None, preserve or replace_raise')
    factory = await_wrapper_final_program if source_kind == 'wrapper' else await_general_final_program
    program, old = factory(zero_cut=zero_cut, depth=1)
    kind = ResumableKind.COROUTINE if source_kind == 'wrapper' else ResumableKind.GENERATOR
    body, capture_map, cuts, terminal_id = _raising_body(program, old, zero_cut, kind)
    sources = (*cuts, terminal_id)
    parts = tuple(_typed_part(_stage(body, ordinal, source,
        None if ordinal == 0 else cuts[ordinal - 1]), source_kind)
        for ordinal, source in enumerate(sources))
    replaced_regions = {old['body'].id, *(item['driver_region'].id for item in old['drivers'])}
    replaced_operations = {identity for region in program.regions if region.id in replaced_regions
                           for block in region.blocks for identity in block.operations}
    replaced_values = {value.id for value in program.values if value.region in replaced_regions}
    replaced_scopes = {scope.id for scope in program.protocol_scopes
        if type(scope.subject) is DriverSubject and scope.subject.interface_region in replaced_regions}
    retained = {
        'protocol_scopes': tuple(scope for scope in program.protocol_scopes if scope.id not in replaced_scopes),
        'protocol_operations': tuple(row for row in program.protocol_operations if row.scope not in replaced_scopes),
        'exception_packets': tuple(row for row in program.exception_packets if row.value not in replaced_values),
        'literal_evaluations': tuple(row for row in program.literal_evaluations
            if getattr(row.site, 'operation', getattr(getattr(row.site, 'edge', None), 'operation', None))
                not in replaced_operations),
    }
    updates = {name: (*retained.get(name, ()), *getattr(body, name),
        *(row for part in parts for row in part[name])) for name in _PART_TABLES}
    updates.update({name: getattr(body, name) for name in _BODY_TABLES})
    graph = replace(program,
        regions=tuple(region for region in program.regions if region.id not in replaced_regions)
            + body.regions + tuple(replace(part['region'], parent=(old['drivers'][number]['wrapper']['region'].id
                if source_kind == 'wrapper' else old['caller'].id)) for number, part in enumerate(parts)),
        operations=tuple(operation for operation in program.operations if operation.id not in replaced_operations)
            + body.operations + tuple(operation for part in parts for operation in part['operations']),
        values=tuple(value for value in program.values if value.region not in replaced_regions)
            + body.values + tuple(value for part in parts for value in part['values']),
        control_scopes=tuple(scope for scope in program.control_scopes if scope.region not in replaced_regions)
            + body.control_scopes + tuple(scope for part in parts for scope in part['control_scopes']),
        protocol_call_inputs=(*program.protocol_call_inputs, *body.protocol_call_inputs),
        protocol_result_consumers=tuple(row for row in program.protocol_result_consumers
            if row.site.scope not in replaced_scopes) + body.protocol_result_consumers,
        protocol_bindings=(*program.protocol_bindings, *body.protocol_bindings), **updates)
    if capture_map:
        graph = _rewrite(graph, {type(next(iter(capture_map))): capture_map})
    operations = {operation.id: operation for operation in graph.operations}
    values = {value.id: value for value in graph.values}
    blocks = {block.id: block for region in graph.regions for block in region.blocks}
    receipts = []
    for row in graph.protocol_operations:
        if type(row.contract) is not OutcomeAdapter or type(row.contract.input) is not DriveResult:
            continue
        edge = operations[row.operation].terminator.successors[row.contract.output.edge.successor_index]
        if edge.kind is ExitKind.RAISE:
            targets = (HostTerminal(blocks[edge.block].operations[-1]),)
        else:
            formal = next(formal for argument, formal in zip(edge.arguments, blocks[edge.block].arguments)
                          if argument == row.contract.output.result)
            targets = tuple(OwnedUse(values[packet.value].origin.operation, packet.exception)
                for packet in graph.exception_packets
                if next(use for use in operations[values[packet.value].origin.operation].uses
                    if use.id == packet.exception).value == formal)
        receipts.append(ProtocolResultConsumers(ProtocolOperationRef(row.scope,
            row.clause, row.operation, row.slot), targets))
    graph = replace(graph, protocol_result_consumers=(*graph.protocol_result_consumers, *receipts))
    caller = next(region for region in graph.regions if region.id == old['caller'].id)
    extract = old['extract']
    removed_regions = {region.id for region in old['stage_regions']}
    removed_blocks = {edge.block for edge in extract.terminator.successors}
    removed_operations = {extract.id,
        *(identity for block in caller.blocks if block.id in removed_blocks for identity in block.operations),
        *(identity for region in graph.regions if region.id in removed_regions
          for block in region.blocks for identity in block.operations)}
    actuals = {use.id: use for use in extract.uses}
    uses = tuple(Use(UseID(f'await.raise.source.consumer.{slot}'), actuals[identity].value,
        actuals[identity].role) for slot, identity in enumerate(extract.invoke_arguments))
    host = Operation(OperationID('await.raise.source.consumer'), 'consume the current propagated exception',
        (Behavior.CONTROL,), uses, effects_complete=True,
        terminator=Terminator(TerminatorKind.RAISE, exit='failure', values=tuple(use.id for use in uses)))
    caller = replace(caller, exits=tuple(port for port in caller.exits if port.kind is ExitKind.RAISE),
        blocks=tuple(replace(block, operations=(host.id,)) if extract.id in block.operations else block
                     for block in caller.blocks if block.id not in removed_blocks))
    removed_values = {value.id for value in graph.values if value.region in removed_regions
        or type(value.origin) is BlockArgument and value.origin.block in removed_blocks}
    removed_sites = {row.site for row in graph.protocol_result_consumers if row.site.operation in removed_operations}
    graph = replace(graph,
        regions=tuple(caller if region.id == caller.id else region for region in graph.regions
                      if region.id not in removed_regions),
        operations=tuple(operation for operation in graph.operations if operation.id not in removed_operations) + (host,),
        values=tuple(value for value in graph.values if value.id not in removed_values),
        control_scopes=tuple(replace(scope, blocks=tuple(block for block in scope.blocks if block not in removed_blocks))
            if scope.region == caller.id else scope for scope in graph.control_scopes if scope.region not in removed_regions),
        protocol_operations=tuple(row for row in graph.protocol_operations if row.operation not in removed_operations),
        protocol_result_consumers=tuple(replace(row, targets=(HostTerminal(host.id),))
            if row.site.operation == old['drivers'][-1]['caller_call'].id else row
            for row in graph.protocol_result_consumers if row.site not in removed_sites))
    operations = {operation.id: operation for operation in graph.operations}
    regions = {region.id: region for region in graph.regions}
    drivers = tuple({**item, 'driver_region': regions[part['region'].id], 'drive': part['drive'],
        'outcome_source': source, 'path': part['path'], 'host_terminal': operations[part['host'].id]}
        for item, part, source in zip(old['drivers'], parts, sources, strict=True))
    choices = {next(block for block in old['caller'].blocks if block.id == block_id).operations[-1]: number
               for block_id, number in old['caller_path'] if number is not None}
    choices.pop(extract.id, None)
    body_terminal = operations[terminal_id]
    outcome = DriveOutcomeRef(drivers[-1]['drive'].operation, terminal_id)
    parent = drivers[-1]['caller_call']
    edge_number = drivers[-1]['selected_call_edge']
    primary = next(row for row in graph.resumable_creates if row.operation == old['primary_creation'].operation)
    details = {**old, 'source_kind': source_kind, 'zero_cut': zero_cut, 'cleanup_mode': cleanup_mode,
        'caller': caller, 'caller_path': _selected_path(graph, caller, choices),
        'caller_choices': choices, 'body': regions[old['body'].id], 'body_kind': kind,
        'body_definition': graph.resumable_bodies[0], 'drivers': drivers,
        'capture_formals': tuple(capture_map.get(formal, formal) for formal in old['capture_formals']),
        'primary_creation': primary, 'cuts': cuts, 'body_raised': True,
        'body_terminal': body_terminal, 'body_packet_use': OwnedUse(body_terminal.id, body_terminal.terminator.values[0]),
        'drive_outcome': outcome, 'payload': DriveResult(outcome, 0), 'root_source': DriveResult(outcome, 0),
        'parent_call': parent, 'advance_operation': parent.id,
        'driver_operation': operations[drivers[-1]['drive'].operation], 'driver_region': drivers[-1]['driver_region'],
        'driver_packet_use': OwnedUse(drivers[-1]['host_terminal'].id, drivers[-1]['host_terminal'].terminator.values[0]),
        'advance_packet_result': InvokeLiteralResult(ControlEdgeReference(parent.id, edge_number), CompletionResult(0)),
        'extract': None, 'extract_input': HostTerminal(host.id), 'final': host,
        'host_packet_use': OwnedUse(host.id, uses[0].id), 'packet_use': OwnedUse(host.id, uses[0].id),
        'state_uses': tuple(OwnedUse(host.id, use.id) for use in uses[1:]),
        'conversion': None, 'conversion_rows': (), 'conversion_sites': (), 'conversion_receipts': (),
        'final_rows': (), 'final_sites': (), 'stage_records': (), 'stage_regions': (), 'stage_operations': (),
        'primitive': None, 'raise_cleanup': None, 'scope': old['acquisition_scope'],
        'pending_definitions': body.pending_completions, 'cleanup_body': body,
        'pending_projection': next((operation for operation in body.operations
            if type(operation.terminator) is PendingDispatchTerminator), None)}
    if source_kind == 'general':
        details['helper_create'] = primary
    if cleanup_mode is not None:
        graph, details = add_driver_raise_cleanup(graph, details, mode=cleanup_mode)
        last = details['drivers'][-1]
        details.update(driver_region=last['driver_region'],
            driver_packet_use=details['raise_cleanup']['payload_uses'][0])
    return graph, details


__all__ = ['await_raise_source_program']
