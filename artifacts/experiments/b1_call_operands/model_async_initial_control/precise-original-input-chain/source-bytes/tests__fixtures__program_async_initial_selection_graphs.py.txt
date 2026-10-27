"""Initial ASEND scheduler override on an existing external suspended body.

This fixture isolates input selection. It neither establishes Created nor
uses native identity as a copy relation. The joint Created control is separate.
"""
from dataclasses import replace

from scar.ir.program.ids import BlockID, OperationID, UseID, ValueID
from scar.ir.program.model import (
    AccessMode, Behavior, Footprint, FootprintKind, LiteralOrigin, Operation,
    OperationResult, ReferenceValue, StateAccess, StateVersionValue, Use, UseRole,
)
from tests.fixtures.program_async_connections import request_creation_program


def initial_scheduler_selection_program(*, deliver_scheduler=False, scheduler_value=77,
                                        scheduler_unknown=False):
    graph, details = request_creation_program(kind='SEND', send_none=True,
                                              initial_step=True, scheduler_kind='SEND')
    values = {value.id: value for value in graph.values}
    operations = {operation.id: operation for operation in graph.operations}
    latent = details['latent_definition']
    scheduler = details['scheduler_definition']
    latent_pack = operations[values[latent.value].origin.operation]
    latent_operand, = latent_pack.uses
    assert type(values[latent_operand.value].origin) is LiteralOrigin
    assert values[latent_operand.value].origin.value is None
    scheduler_pack = operations[values[scheduler.value].origin.operation]
    replacement = (values[scheduler_pack.uses[0].value] if scheduler_unknown else
        ReferenceValue(ValueID('initial.selection.scheduler.value'), graph.root,
                       LiteralOrigin(scheduler_value), targets=()))
    changed_scheduler = replace(scheduler_pack, uses=tuple(
        replace(use, value=replacement.id) if use.id == scheduler.operands[0] else use
        for use in scheduler_pack.uses))
    caller = operations[details['caller']]
    deliveries = tuple(use for use in caller.uses
                       if use.id in caller.invoke_arguments and use.value == latent_operand.value)
    assert len(deliveries) == 1
    changed_caller = replace(caller, uses=tuple(
        replace(use, value=replacement.id) if deliver_scheduler and use.id == deliveries[0].id
        else use for use in caller.uses))
    graph = replace(graph, values=graph.values if scheduler_unknown else (*graph.values, replacement), operations=tuple(
        changed_scheduler if operation.id == changed_scheduler.id else
        changed_caller if operation.id == changed_caller.id else operation
        for operation in graph.operations))
    return graph, {**details, 'scheduler_value': replacement,
                   'latent_operand': latent_operand, 'caller_delivery': deliveries[0].id}


def created_unknown_scheduler_program():
    from scar.ir.program.drivers import RawRequestDefinition, RawRequestKind
    from tests.fixtures.program_async_initial_control_graphs import async_initial_control_program
    graph, details = async_initial_control_program(scenario='created-none')
    stage = details['drivers'][0]
    definition = stage['scheduler']
    values = {value.id: value for value in graph.values}
    pack_id = values[definition.value].origin.operation
    source_id = OperationID('initial.unknown.scheduler.source')
    value = ReferenceValue(ValueID('initial.unknown.scheduler.value'), graph.root,
                           OperationResult(source_id, 0))
    source = Operation(source_id, 'unknown host reference', (Behavior.COMPUTE,), (),
                       (value.id,), effects_complete=False)
    operand = Use(UseID('initial.unknown.scheduler.operand'), value.id, UseRole.REFERENCE)
    changed = replace(next(operation for operation in graph.operations if operation.id == pack_id),
                      uses=(operand,))
    raw = RawRequestDefinition(definition.value, RawRequestKind.SEND, (operand.id,))
    root = next(region for region in graph.regions if region.id == graph.root)
    root = replace(root, blocks=tuple(replace(block, operations=(source.id, *block.operations))
        if block.id == root.entry else block for block in root.blocks))
    graph = replace(graph, values=(*graph.values, value),
        operations=(*(changed if operation.id == changed.id else operation
                      for operation in graph.operations), source),
        raw_driver_requests=tuple(raw if item == definition else item for item in graph.raw_driver_requests),
        regions=tuple(root if region.id == root.id else region for region in graph.regions))
    return graph, details


def changed_association_state_program():
    from tests.fixtures.program_async_initial_control_graphs import async_initial_control_program
    graph, details = async_initial_control_program(scenario='created-none')
    stage = details['drivers'][0]
    identity = stage['initial_controls']['phase']['predicate']
    predicate = next(operation for operation in graph.operations if operation.id == identity)
    access = predicate.accesses[0]
    original = next(use.value for use in predicate.uses if use.id == access.before)
    region = next(region for region in graph.regions
                  if any(identity in block.operations for block in region.blocks))
    block = next(block for block in region.blocks if identity in block.operations)
    write_id = OperationID('initial.association.state.write')
    after = StateVersionValue(ValueID('initial.association.state.after'), region.id,
                              OperationResult(write_id, 0), access.location)
    before = Use(UseID('initial.association.state.before'), original, UseRole.STATE_CONTENT)
    write = Operation(write_id, 'real state change before frame predicate',
        (Behavior.READ, Behavior.WRITE), (before,), (after.id,),
        (StateAccess(access.location, before.id, AccessMode.READ_WRITE, after.id,
                     Footprint(FootprintKind.WHOLE)),), effects_complete=True)
    position = block.operations.index(identity)
    changed_ids = set(block.operations[position:])
    graph = replace(graph, values=(*graph.values, after),
        operations=(*(replace(operation, uses=tuple(replace(use, value=after.id)
            if use.value == original else use for use in operation.uses))
            if operation.id in changed_ids else operation for operation in graph.operations), write),
        regions=tuple(replace(item, blocks=tuple(replace(candidate,
            operations=(*candidate.operations[:position], write.id, *candidate.operations[position:]))
            if candidate.id == block.id else candidate for candidate in item.blocks))
            if item.id == region.id else item for item in graph.regions))
    return graph, details


def mixed_scheduler_recipe_program():
    """One original driver sees a known pack and a real opaque own RAW result."""
    from scar.ir.program.model import (
        CompletionResult, CompletionSignature, CompletionSuccessor, ExitKind,
        Terminator, TerminatorKind, ValueKind, ValueType,
    )
    from tests.fixtures.program_driver_graphs import PACKET, RAW, _Builder, _use
    from tests.fixtures.program_request_admission_graphs import request_two_callers_program
    graph, details = request_two_callers_program()
    first, second = details['callers']
    interface, = graph.driver_interfaces
    region = next(row for row in graph.regions if row.id == interface.region)
    entry = next(row for row in region.blocks if row.id == region.entry)
    scheduler_use = second.invoke_arguments[entry.arguments.index(interface.scheduler_request)]
    values = {value.id: value for value in graph.values}
    states = tuple(use for use in second.uses if type(values[use.value]) is StateVersionValue)
    domains = tuple(values[use.value].location for use in states)
    types = tuple(ValueType(ValueKind.STATE, location=location) for location in domains)
    root = next(row for row in graph.regions if row.id == graph.root)
    landing = next(block for block in root.blocks if second.id in block.operations)
    builder = _Builder(root.id.value, domains)
    normal_name, raise_name = 'initial.mixed.raw.normal', 'initial.mixed.raw.raise'
    normal = builder.formals(normal_name, (RAW, *types))
    raised = builder.formals(raise_name, (PACKET, *types))
    inputs = tuple(_use(f'initial.mixed.raw.state.{number}', use.value, state=True)
                   for number, use in enumerate(states))
    opaque = builder.add('initial.mixed.raw.call', inputs, effects_complete=False,
        invoke_arguments=tuple(use.id for use in inputs),
        completions=(CompletionSignature(ExitKind.NORMAL, (RAW, *types)),
                     CompletionSignature(ExitKind.RAISE, (PACKET, *types))),
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, BlockID(normal_name),
                tuple(CompletionResult(index) for index in range(len(normal)))),
            CompletionSuccessor(ExitKind.RAISE,
                BlockID(raise_name),
                tuple(CompletionResult(index) for index in range(len(raised)))))))
    current = dict(zip(domains, normal[1:]))
    second = replace(second, uses=tuple(replace(use, value=normal[0]) if use.id == scheduler_use
        else replace(use, value=current[values[use.value].location])
        if type(values[use.value]) is StateVersionValue else use for use in second.uses))
    failure = builder.terminal('initial.mixed.raw.failure', raised, fail=True)
    builder.block(normal_name, normal, (second,))
    builder.block(raise_name, raised, (failure,))
    blocks = (*tuple(replace(block, operations=tuple(opaque.id if identity == second.id else identity
        for identity in block.operations)) if block.id == landing.id else block
        for block in root.blocks), *builder.blocks)
    graph = replace(graph, values=(*graph.values, *builder.values),
        operations=(*tuple(second if operation.id == second.id else operation
                           for operation in graph.operations), *builder.operations),
        regions=tuple(replace(row, blocks=blocks) if row.id == root.id else row for row in graph.regions),
        control_scopes=tuple(replace(scope, blocks=tuple(block.id for block in blocks))
            if scope.region == root.id else scope for scope in graph.control_scopes))
    return graph, {**details, 'opaque_scheduler': opaque, 'callers': (first, second)}
