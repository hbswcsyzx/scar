"""One supplied await pipeline whose persistent body performs real C1 cleanup.

Return preservation and Raise replacement use the original pending/cut records.
Only the actual Return path has completion/extraction semantics. No source or
native execution is inferred by these hand-authored graphs.
"""
from dataclasses import fields, is_dataclass, replace

from scar.ir.program.control import PendingDispatchTerminator
from scar.ir.program.drivers import BodyResume
from scar.ir.program.ids import LocationID, OperationID, ProtocolScopeID, RegionID, UseID
from scar.ir.program.lifecycle import DriveOutcomeRef
from scar.ir.program.model import (
    Behavior, BlockArgument, ExitKind, Operation, OperationResult, ProtocolValue, ReferenceValue,
    StateVersionValue, Terminator, TerminatorKind, Use, UseRole,
)
from scar.ir.program.protocols import (
    DriverSubject, DriveResult, HostTerminal, OutcomeAdapter, OwnedUse,
    ProtocolClause, ProtocolOperation, ProtocolProfile, ProtocolScope,
    RequestProcessing, RequestProcessingRule,
)
from scar.ir.program.protocol_connections import ProtocolOperationRef, ProtocolResultConsumers
from scar.ir.program.resumption import ResumableKind, SuspendTerminator
from tests.fixtures.program_async_pipeline_graphs import _selected_path
from tests.fixtures.program_await_final_region_graphs import await_final_region_program
from tests.fixtures.program_driver_graphs import driver_program
from tests.fixtures.program_generator_close_retry_graphs import _driver_part
from tests.fixtures.program_pending_cleanup_graphs import (
    normal_pending_two_cuts_program, pending_cleanup_two_cuts_program,
)
from tests.fixtures.program_protocol_graphs import _adapt_return, _insert_processing, _source_gap
from tests.fixtures.program_publication_graphs import with_publications
from tests.fixtures.program_resumption_graphs import resumption_cleanup_invoke_program


_PART_TABLES = (
    'driver_interfaces', 'final_body_gates', 'body_drives', 'driver_lifecycles',
    'body_outcome_commits', 'terminal_frame_releases', 'protocol_scopes',
    'protocol_operations', 'literal_evaluations', 'exception_packets',
)
_BODY_TABLES = (
    'control_ports', 'pending_completions', 'handled_context_domains',
    'cleanup_interfaces', 'cleanup_enters', 'cleanup_resumes', 'cleanup_replacements',
    'handled_context_reads', 'resumable_bodies', 'frame_context_initials',
    'frame_context_attaches', 'frame_context_detaches',
)


def _rewrite(value, maps):
    if type(value) in maps:
        return maps[type(value)].get(value, value)
    if type(value) is tuple:
        return tuple(_rewrite(item, maps) for item in value)
    if is_dataclass(value):
        return replace(value, **{field.name: _rewrite(getattr(value, field.name), maps)
                                 for field in fields(value)})
    return value


def _body(program, old, raised):
    if raised:
        # The close fixture's first resume is DELEGATE_PACKET. This pipeline
        # really sends a Reference, so retain the original generic cleanup
        # INVOKE/SENT_VALUE path and reuse only the added second-cut records.
        base = resumption_cleanup_invoke_program()
        template, second = pending_cleanup_two_cuts_program()
        additions = {second['second_suspend'], second['second_detach'],
                     second['second_replace_jump'], OperationID('finally.second.attach')}
        new_blocks = tuple(block for block in template.regions[0].blocks
                           if any(identity in additions for identity in block.operations))
        original_values = {value.id for value in base.values}
        raw = replace(base,
            regions=(replace(base.regions[0], blocks=(*base.regions[0].blocks, *new_blocks)),),
            operations=tuple(next(op for op in template.operations if op.id == old_op.id)
                if old_op.id == OperationID('finally.failed.jump') else old_op for old_op in base.operations)
                + tuple(op for op in template.operations if op.id in additions),
            values=(*base.values, *(value for value in template.values if value.id not in original_values
                and (type(value.origin) is BlockArgument and value.origin.block in {block.id for block in new_blocks}
                     or type(value.origin) is OperationResult and value.origin.operation in additions))),
            control_scopes=tuple(replace(scope, blocks=(*scope.blocks, *(block.id for block in new_blocks)))
                if scope.kind.value == 'CLEANUP' else scope for scope in base.control_scopes),
            frame_context_attaches=(*base.frame_context_attaches,
                *(row for row in template.frame_context_attaches if row.operation in additions)),
            frame_context_detaches=(*base.frame_context_detaches,
                *(row for row in template.frame_context_detaches if row.operation in additions)))
    else:
        raw = normal_pending_two_cuts_program()[0]
    old_body = old['body']
    domain_map = dict(zip((location.id for location in raw.locations),
                         (location.id for location in program.locations)))
    body = _rewrite(raw, {RegionID: {raw.root: old_body.id}, LocationID: domain_map})
    region = body.regions[0]
    entry = next(block for block in region.blocks if block.id == region.entry)
    originals = {value.id: value for value in program.values}
    old_entry = next(block for block in old_body.blocks if block.id == old_body.entry)
    old_refs = tuple(identity for identity in old_entry.arguments
                     if type(originals[identity]) is ReferenceValue)
    environment_ids = {member.reference for env in program.environments for member in env.members}
    references = tuple(replace(originals[identity],
        origin=BlockArgument(entry.id, len(entry.arguments) + number))
        for number, identity in enumerate(old_refs) if identity in environment_ids)
    # The first body reference is its actual argument; the remaining original
    # references are its environment, appended in the original capture order.
    references = tuple(replace(value, origin=BlockArgument(entry.id, len(entry.arguments) + number))
                       for number, value in enumerate(references))
    region = replace(region, parent=old['caller'].id, blocks=tuple(
        replace(block, arguments=(*block.arguments, *(value.id for value in references)))
        if block.id == entry.id else block for block in region.blocks))
    body = replace(body, regions=(region,), values=(*body.values, *references),
        resumable_bodies=tuple(replace(record, kind=ResumableKind.GENERATOR_COROUTINE)
                               for record in body.resumable_bodies))
    replacements = {old_refs[0]: entry.arguments[0]}
    return body, replacements


def _stage(body, ordinal, source, previous):
    # Driver construction uses only the body's canonical records; its internal
    # delegation scope is retained once in the final graph, not once per driver.
    core = replace(body, protocol_scopes=(), protocol_operations=(),
        protocol_call_inputs=(), protocol_result_consumers=(), protocol_bindings=())
    if previous is not None:
        core = replace(core, operations=tuple(sorted(core.operations, key=lambda op: op.id != previous)))
    graph = driver_program(body_graph=core, target='start' if previous is None else 'value')
    scope = ProtocolScope(ProtocolScopeID('await.body.scope'),
        ProtocolProfile.GENERATOR_COROUTINE_BODY_V1,
        DriverSubject(graph.driver_interfaces[0].region), _source_gap())
    graph = replace(graph, protocol_scopes=(scope,))
    choices = {graph.final_body_gates[0].operation: 0}
    if previous is not None:
        graph, processor = _insert_processing(graph, target='value')
        rows = tuple(ProtocolOperation(scope.id, ProtocolClause.REQUEST_PROCESSING,
            processor['processing'], slot, RequestProcessing(processor['raw_use'], (),
                processor[port], processor['state_sites'], RequestProcessingRule.CHECK_SEND), _source_gap())
            for slot, port in ((0, 'normal_result'), (1, 'raise_result')))
        graph = replace(graph, protocol_operations=rows)
        choices[processor['processing']] = 0
    drive = graph.body_drives[0]
    operation = next(op for op in graph.operations if op.id == drive.operation)
    original_edges = operation.terminator.successors
    source_operations = {op.id: op for op in graph.operations}
    for edge in original_edges:
        if source_operations[edge.source].terminator.kind is not TerminatorKind.RETURN:
            continue
        narrowed = replace(operation, terminator=replace(operation.terminator, successors=(edge,)))
        graph = replace(graph, operations=tuple(narrowed if op.id == operation.id else op
                                                for op in graph.operations))
        graph = _adapt_return(graph, scope.id)
        graph = replace(graph, operations=tuple(operation if op.id == operation.id else op
                                                for op in graph.operations))
    has_handoff = any(source_operations[edge.source].terminator.kind is TerminatorKind.SUSPEND
                      for edge in original_edges)
    driver = next(region for region in graph.regions if region.id == graph.driver_interfaces[0].region)
    if has_handoff:
        # The base builder's genuine normal exit is supplied by Suspend, while
        # Return conversion and actual Raise both leave through RAISE.
        base_region = next(region for region in driver_program(body_graph=core,
            target='start' if previous is None else 'value').regions if region.id == driver.id)
        driver = replace(driver, exits=base_region.exits)
    else:
        driver = replace(driver, exits=tuple(port for port in driver.exits if port.kind is ExitKind.RAISE))
    graph = replace(graph, regions=tuple(driver if region.id == driver.id else region
        for region in graph.regions), protocol_operations=tuple(replace(row,
            clause=ProtocolClause.DIRECT_HOST_ADAPTER) if type(row.contract) is OutcomeAdapter else row
            for row in graph.protocol_operations))
    if source_operations[source].terminator.kind is TerminatorKind.RETURN:
        choices[OperationID('adapter.construct')] = 0
    choices[drive.operation] = next(number for number, edge in enumerate(original_edges) if edge.source == source)
    graph = with_publications(graph)
    part, maps = _driver_part(graph, f'await.resume.driver.{ordinal}')
    part['choices'] = {_rewrite(key, maps): number for key, number in choices.items()}
    part['drive'] = part['body_drives'][0]
    part['source'] = source
    shell = replace(graph, regions=(part['region'],), operations=part['operations'])
    part['path'] = _selected_path(shell, part['region'], part['choices'])
    terminal = part['path'][-1][0]
    block = next(block for block in part['region'].blocks if block.id == terminal)
    part['host'] = next(op for op in part['operations'] if op.id == block.operations[-1])
    return part


def await_cleanup_final_program(body_raised=False, depth=1):
    if type(body_raised) is not bool:
        raise TypeError('body_raised requires exact bool')
    program, original = await_final_region_program(zero_cut=False, depth=depth)
    body, capture_map = _body(program, original, body_raised)
    region = body.regions[0]
    cuts = (OperationID('finally.suspend'), OperationID(
        'finally.second.suspend' if body_raised else 'finally.second-normal.suspend'))
    terminal = OperationID('finally.raise-exit.op' if body_raised else 'finally.return')
    selected_sources = (*cuts, terminal)
    parts = tuple(_stage(body, number, source, None if number == 0 else cuts[number - 1])
                  for number, source in enumerate(selected_sources))
    old_regions = {original['body'].id, *(item['driver_region'].id for item in original['drivers'])}
    old_ops = {identity for region_ in program.regions if region_.id in old_regions
               for block in region_.blocks for identity in block.operations}
    old_scope_ids = {scope.id for scope in program.protocol_scopes
        if type(scope.subject) is DriverSubject and scope.subject.interface_region in old_regions}
    updates = {name: tuple(row for row in getattr(program, name)
        if (row.scope not in old_scope_ids if name == 'protocol_operations' else
            row.id not in old_scope_ids if name == 'protocol_scopes' else
            row.value not in {value.id for value in program.values if value.region in old_regions}
            if name == 'exception_packets' else True))
        for name in ('protocol_scopes', 'protocol_operations', 'exception_packets', 'literal_evaluations')}
    # Driver literals all refer to replaced operations; remove their old receipts.
    updates['literal_evaluations'] = tuple(row for row in program.literal_evaluations
        if getattr(row.site, 'operation', getattr(getattr(row.site, 'edge', None), 'operation', None)) not in old_ops)
    for name in _PART_TABLES:
        retained = updates.get(name, ())
        updates[name] = (*retained, *getattr(body, name), *(row for part in parts for row in part[name]))
    for name in _BODY_TABLES:
        updates[name] = getattr(body, name)
    graph = replace(program,
        regions=tuple(item for item in program.regions if item.id not in old_regions)
            + (region, *(replace(part['region'], parent=original['caller'].id) for part in parts)),
        operations=tuple(op for op in program.operations if op.id not in old_ops)
            + body.operations + tuple(op for part in parts for op in part['operations']),
        values=tuple(value for value in program.values if value.region not in old_regions)
            + body.values + tuple(value for part in parts for value in part['values']),
        control_scopes=tuple(scope for scope in program.control_scopes if scope.region not in old_regions)
            + body.control_scopes + tuple(scope for part in parts for scope in part['control_scopes']),
        protocol_call_inputs=(*program.protocol_call_inputs, *body.protocol_call_inputs),
        protocol_result_consumers=tuple(receipt for receipt in program.protocol_result_consumers
            if receipt.site.scope not in old_scope_ids) + body.protocol_result_consumers,
        protocol_bindings=(*program.protocol_bindings, *body.protocol_bindings), **updates)
    graph = _rewrite(graph, {type(next(iter(capture_map))): capture_map})
    blocks = {block.id: block for item in graph.regions for block in item.blocks}
    ops = {op.id: op for op in graph.operations}
    values = {value.id: value for value in graph.values}
    receipts = []
    for row in graph.protocol_operations:
        if type(row.contract) is not OutcomeAdapter or type(row.contract.input) is not DriveResult:
            continue
        operation = ops[row.operation]
        edge = operation.terminator.successors[row.contract.output.edge.successor_index]
        if edge.kind is ExitKind.RAISE:
            targets = (HostTerminal(blocks[edge.block].operations[-1]),)
        else:
            formal = next(formal for argument, formal in zip(edge.arguments, blocks[edge.block].arguments)
                          if argument == row.contract.output.result)
            targets = tuple(OwnedUse(values[packet.value].origin.operation, packet.exception)
                for packet in graph.exception_packets
                if next(use for use in ops[values[packet.value].origin.operation].uses
                        if use.id == packet.exception).value == formal)
        receipts.append(ProtocolResultConsumers(ProtocolOperationRef(row.scope, row.clause,
            row.operation, row.slot), targets))
    graph = replace(graph, protocol_result_consumers=(*graph.protocol_result_consumers, *receipts))
    caller = next(item for item in graph.regions if item.id == original['caller'].id)
    drivers = tuple({**old, 'driver_region': part['region'], 'drive': part['drive'],
        'outcome_source': source, 'path': part['path'], 'host_terminal': part['host']}
        for old, part, source in zip(original['drivers'], parts, selected_sources))
    details = {**original, 'body': region, 'drivers': drivers,
        'capture_formals': tuple(capture_map.get(value, value) for value in original['capture_formals']),
        'body_raised': body_raised, 'cuts': cuts, 'body_terminal': ops[terminal],
        'pending_definitions': body.pending_completions, 'cleanup_body': body}
    if body_raised:
        removed_regions = {item.id for item in original['stage_regions']}
        extract = original['extract']
        removed_blocks = {edge.block for edge in extract.terminator.successors}
        removed = {extract.id, *(identity for block in caller.blocks if block.id in removed_blocks
                                  for identity in block.operations),
                   *(identity for item in graph.regions if item.id in removed_regions
                       for block in item.blocks for identity in block.operations)}
        uses = tuple(Use(UseID(f'await.cleanup.propagate.{number}'), use.value, use.role)
                     for number, use in enumerate(extract.uses)
                     if use.id in extract.invoke_arguments)
        host = Operation(OperationID('await.cleanup.propagate'), 'propagate this actual body exception',
            (Behavior.CONTROL,), uses, effects_complete=True,
            terminator=Terminator(TerminatorKind.RAISE, exit='failure', values=tuple(use.id for use in uses)))
        caller = replace(caller, exits=tuple(port for port in caller.exits if port.kind is ExitKind.RAISE),
            blocks=tuple(replace(block, operations=(host.id,)) if extract.id in block.operations else block
                         for block in caller.blocks if block.id not in removed_blocks))
        removed_values = {value.id for value in graph.values if value.region in removed_regions
                          or type(value.origin) is BlockArgument and value.origin.block in removed_blocks}
        sites = {receipt.site for receipt in graph.protocol_result_consumers if receipt.site.operation in removed}
        graph = replace(graph,
            regions=tuple(caller if item.id == caller.id else item for item in graph.regions
                          if item.id not in removed_regions),
            operations=tuple(op for op in graph.operations if op.id not in removed) + (host,),
            values=tuple(value for value in graph.values if value.id not in removed_values),
            control_scopes=tuple(replace(scope, blocks=tuple(block for block in scope.blocks if block not in removed_blocks))
                if scope.region == caller.id else scope for scope in graph.control_scopes if scope.region not in removed_regions),
            protocol_operations=tuple(row for row in graph.protocol_operations if row.operation not in removed),
            protocol_result_consumers=tuple(replace(receipt, targets=(HostTerminal(host.id),))
                if receipt.site.operation == original['drivers'][-1]['caller_call'].id else receipt
                for receipt in graph.protocol_result_consumers if receipt.site not in sites))
        details.update(extract=None, extract_input=HostTerminal(host.id),
                       packet_use=OwnedUse(host.id, uses[0].id),
                       state_uses=tuple(OwnedUse(host.id, use.id) for use in uses[1:]), final=host,
                       final_rows=(), stage_records=(), stage_regions=(), stage_operations=(), primitive=None)
    caller = next(item for item in graph.regions if item.id == caller.id)
    choices = {op.id: 0 for op in original['create_operations']}
    choices[original['get'].id] = 0
    choices.update((item['caller_call'].id, item['selected_call_edge']) for item in drivers)
    if not body_raised:
        choices[original['extract'].id] = 0
    source_operation = ops[terminal]
    outcome = DriveOutcomeRef(drivers[-1]['drive'].operation, terminal)
    conversion = tuple(row for row in graph.protocol_operations if type(row.contract) is OutcomeAdapter
        and type(row.contract.input) is DriveResult and row.contract.input.outcome == outcome)
    return graph, {**details, 'caller': caller, 'caller_path': _selected_path(graph, caller, choices),
        'drive_outcome': outcome, 'payload': DriveResult(outcome, 0),
        'conversion_rows': conversion, 'conversion': None if not conversion else ops.get(conversion[0].operation),
        'advance_operation': drivers[-1]['caller_call'].id, 'body_terminal': source_operation,
        'pending_projection': next(op for op in body.operations
                                   if type(op.terminator) is PendingDispatchTerminator)}


__all__ = ['await_cleanup_final_program']
