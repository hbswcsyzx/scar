"""Canonical asynchronous protocol declarations, not recovered native execution.

The receiver R, body B, scheduler S and latent request L are independent ports.
All effects/results stay on the original operations, including helper failures.
"""
from dataclasses import replace

from scar.ir.program.ids import BlockID, OperationID, ProtocolScopeID, UseID
from scar.ir.program.lifecycle import DriveOutcomeRef, SessionPost
from scar.ir.program.model import CompletionResult, ExitKind, InvokeLiteralResult, StateVersionValue
from scar.ir.program.protocols import (
    DriverSubject, OutcomeAdapter, OutcomeAdapterRule, ProtocolClause,
    ProtocolOperation, ProtocolProfile, ProtocolScope,
)
from scar.ir.program.resumption import ResumableKind, SuspensionFlavor, SuspendTerminator
from scar.ir.program.state_addresses import InvokeStateOperand
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.program_driver_graphs import driver_program
from tests.fixtures.program_no_body_graphs import _insert_association
from tests.fixtures.program_protocol_graphs import _adapt_return, _source_gap
from tests.fixtures.program_publication_graphs import with_publications
from tests.fixtures.program_session_release_graphs import _Tail


def _operation(graph, identity):
    identity = OperationID(identity) if isinstance(identity, str) else identity
    return next(row for row in graph.operations if row.id == identity)


def _association(graph):
    interface, = graph.driver_interfaces
    gate_row, = graph.final_body_gates
    gate = _operation(graph, gate_row.operation)
    region = next(row for row in graph.regions if row.id == interface.region)
    entry = next(block for block in region.blocks if block.id == region.entry)
    values = {value.id: value for value in graph.values}
    graph, normal, sources = _insert_association(graph, interface, gate, gate_row, entry, values)
    roles = {gate_row.body_argument: sources['body'], gate_row.scheduler_argument: sources['scheduler'],
             gate_row.session_argument: sources['session']}
    roles.update(zip(gate_row.delivery_arguments, sources['delivery']))
    mapping = {gate.uses[index].value: value for index, value in roles.items()}
    old_states = tuple(value for value in entry.arguments if isinstance(values[value], StateVersionValue))
    mapping.update(zip(old_states, sources['states']))
    gate = replace(gate, uses=tuple(replace(use, value=mapping.get(use.value, use.value)) for use in gate.uses))
    regions = tuple(replace(item, blocks=tuple(replace(block, operations=(gate.id,))
                    if block.id == normal else block for block in item.blocks))
                    if item.id == interface.region else item for item in graph.regions)
    blocks = next(item for item in regions if item.id == interface.region).blocks
    return replace(graph, regions=regions,
        operations=tuple(gate if row.id == gate.id else row for row in graph.operations),
        control_scopes=tuple(replace(scope, blocks=tuple(block.id for block in blocks))
            if scope.region == interface.region else scope for scope in graph.control_scopes)), sources


def async_driver_program(*, target='start', flavor='ASYNC_YIELD', association=True,
                         session=True, post=None, helper=False, release=False,
                         attach_records=True):
    """One real association/gate/body source, with separate item/await semantics.

    ``attach_records=False`` retains the same old canonical program and lets
    tests establish that new semantic attachments do not fabricate SSA ports.
    """
    flavor = SuspensionFlavor(flavor)
    graph = driver_program(target=target, async_request=True)
    graph = replace(graph,
        resumable_bodies=tuple(replace(body, kind=ResumableKind.ASYNC_GENERATOR)
                              for body in graph.resumable_bodies),
        operations=tuple(replace(op, terminator=replace(op.terminator, flavor=flavor))
            if type(op.terminator) is SuspendTerminator else op for op in graph.operations))
    from scar.ir.program.ids import ValueID
    from scar.ir.program.model import LiteralOrigin, ReferenceValue
    body_region = graph.resumable_bodies[0].region
    none = ReferenceValue(ValueID('async.body.none'), body_region, LiteralOrigin(None), targets=())
    graph = replace(graph, values=(*graph.values, none), operations=tuple(
        replace(op, uses=tuple(replace(use, value=none.id) if i == 0 else use for i, use in enumerate(op.uses)))
        if op.id == OperationID('resume.return') else op for op in graph.operations))
    sources = None
    if association:
        graph, sources = _association(graph)
    interface, = graph.driver_interfaces
    scope = ProtocolScope(ProtocolScopeID('async.scope'), ProtocolProfile.ASYNC_GENERATOR_BODY_V1,
                          DriverSubject(interface.region), _source_gap())
    graph = replace(graph, protocol_scopes=(scope,))
    # A request iterator's completion may RAISE StopIteration(item). The actual
    # N/R constructor and packet routes are retained, not replaced by RETURN.
    if target == 'value' or (target == 'start' and flavor is SuspensionFlavor.ASYNC_YIELD):
        graph = _adapt_return(graph, scope.id)
        rule = (OutcomeAdapterRule.ASYNCGEN_YIELD_TO_REQUEST_ITEM if target == 'start'
                else OutcomeAdapterRule.ASYNCGEN_RETURN_TO_STOP_ASYNC_ITERATION)
        graph = replace(graph, protocol_operations=tuple(replace(row,
            clause=ProtocolClause.ASYNC_ITEM_ADAPTER,
            contract=replace(row.contract, rule=rule)) if type(row.contract) is OutcomeAdapter else row
            for row in graph.protocol_operations))
    graph = with_publications(graph)
    commit, = graph.body_outcome_commits
    if session:
        post = SessionPost(post) if post is not None else (
            SessionPost.HOLD if target == 'start' and flavor is SuspensionFlavor.AWAIT else SessionPost.COMPLETE)
        tail = _Tail(graph, commit.operation)
        if helper:
            tail.invoke('async.session.helper', post)
        else:
            tail.metadata(post, 'async.session.metadata')
        if release:
            tail.release(0)
        graph = tail.finish()
    details = {'scope': scope.id, 'drive': graph.body_drives[0].operation,
        'gate': graph.final_body_gates[0].operation, 'interface': interface,
        'source': commit.outcome.source, 'outcome': commit.outcome, 'sources': sources,
        'association': graph.request_association_reads[0] if association else None,
        'updates': graph.session_updates, 'rows': graph.protocol_operations}
    if attach_records:
        from scar.ir.program.protocol_connections import AsyncSessionOutcome, RequestAssociation
        if association:
            read = graph.request_association_reads[0]
            operation = _operation(graph, read.operation)
            body = InvokeLiteralResult(ControlEdgeReference(operation.id, 0), CompletionResult(read.body_result.index))
            latent = InvokeLiteralResult(ControlEdgeReference(operation.id, 0), CompletionResult(read.latent_result.index))
            sites = tuple(InvokeStateOperand(operation.id, use.id) for use in operation.uses
                          if use.id in operation.invoke_arguments
                          and isinstance(next(value for value in graph.values if value.id == use.value), StateVersionValue))
            row = ProtocolOperation(scope.id, ProtocolClause.ASYNC_REQUEST_ASSOCIATE, operation.id, 0,
                                    RequestAssociation(read.request, body, latent, sites), _source_gap())
            graph = replace(graph, protocol_operations=(*graph.protocol_operations, row))
            details['association_row'] = row
        bindings = tuple(AsyncSessionOutcome(scope.id, update.operation, commit.outcome)
                         for update in graph.session_updates)
        graph = replace(graph, protocol_bindings=bindings)
        details['bindings'] = bindings
    return graph, details


__all__ = ['async_driver_program']


def _caught_body(graph):
    """A real packet handler writes context, then jumps to Detach/RETURN."""
    from scar.ir.program.control import ProtocolValueKind as P
    from scar.ir.program.ids import ValueID
    from scar.ir.program.model import (AccessMode, Behavior, Block, BlockArgument, Footprint,
        FootprintKind, Operation, OperationResult, ProtocolValue, ReferenceValue, StateAccess,
        StateVersionValue, Successor, Terminator, TerminatorKind, Use, UseRole)
    values = {value.id: value for value in graph.values}
    detach = _operation(graph, 'resume.packet.detach')
    terminal = _operation(graph, 'resume.raise')
    block = next(block for region in graph.regions for block in region.blocks if detach.id in block.operations)
    region = next(region for region in graph.regions if block in region.blocks)
    context_input = next(use for use in detach.uses if isinstance(values[use.value], StateVersionValue))
    caller_input = next(use for use in detach.uses if use.id != context_input.id)
    world = next(use.value for use in terminal.uses if isinstance(values[use.value], StateVersionValue)
                 and values[use.value].location != values[context_input.value].location)
    handler_id = OperationID('cancel.handler')
    packet = Use(UseID('cancel.handler.packet'), terminal.uses[0].value, UseRole.PROTOCOL)
    before = Use(UseID('cancel.handler.context'), context_input.value, UseRole.STATE_CONTENT)
    continued = ReferenceValue(ValueID('cancel.handler.continued'), region.id, OperationResult(handler_id, 0))
    after = StateVersionValue(ValueID('cancel.handler.after'), region.id, OperationResult(handler_id, 1), values[context_input.value].location)
    handler = Operation(handler_id, 'original handled packet and current context',
        (Behavior.CONTROL, Behavior.READ, Behavior.WRITE), (packet, before), (continued.id, after.id),
        (StateAccess(after.location, before.id, AccessMode.READ_WRITE, after.id, Footprint(FootprintKind.WHOLE)),), effects_complete=True)
    destination = BlockID('resume.packet.handled')
    new_values = (
        ProtocolValue(ValueID('cancel.handler.caller'), region.id, BlockArgument(destination, 0), P.DRIVE_CALLER_CONTEXT),
        StateVersionValue(ValueID('cancel.handler.world'), region.id, BlockArgument(destination, 1), values[world].location),
        StateVersionValue(ValueID('cancel.handler.context.current'), region.id, BlockArgument(destination, 2), after.location),
        ReferenceValue(ValueID('cancel.handler.result'), region.id, BlockArgument(destination, 3)))
    forwarded = tuple(Use(UseID(f'cancel.handler.forward.{i}'), value, role) for i, (value, role) in enumerate((
        (caller_input.value, UseRole.PROTOCOL), (world, UseRole.STATE_CONTENT),
        (after.id, UseRole.STATE_CONTENT), (continued.id, UseRole.REFERENCE))))
    jump = Operation(OperationID('cancel.handler.jump'), 'original handler continuation', (Behavior.CONTROL,), forwarded,
        terminator=Terminator(TerminatorKind.JUMP, (Successor(destination, tuple(use.id for use in forwarded)),)))
    detach = replace(detach, uses=tuple(replace(use, value=new_values[0].id if use.id == caller_input.id else new_values[2].id)
                                       for use in detach.uses))
    terminal = replace(terminal, uses=tuple(replace(use, value=new_values[3].id, role=UseRole.REFERENCE) if i == 0
        else replace(use, value=new_values[1].id) if use.value == world else use for i, use in enumerate(terminal.uses)),
        terminator=replace(terminal.terminator, kind=TerminatorKind.RETURN, exit='normal'))
    blocks = tuple(replace(item, operations=(item.operations[0], handler.id, jump.id)) if item.id == block.id else item
                   for item in region.blocks) + (Block(destination, tuple(value.id for value in new_values), (detach.id, terminal.id)),)
    graph = replace(graph, regions=tuple(replace(item, blocks=blocks,
            exits=tuple(exit_ for exit_ in item.exits if exit_.kind is not ExitKind.RAISE))
            if item.id == region.id else item for item in graph.regions),
        values=(*graph.values, continued, after, *new_values),
        operations=tuple(detach if op.id == detach.id else terminal if op.id == terminal.id else op for op in graph.operations) + (handler, jump),
        control_scopes=tuple(replace(scope, blocks=(*scope.blocks, destination)) if scope.region == region.id else scope for scope in graph.control_scopes))
    return graph, packet, ControlEdgeReference(jump.id, 0)


def cancellation_program(*, handled=True, attach_records=True):
    """Task creation/cancel request, a distinct packet injection, handler/status.

    Task implementation and cancellation scheduling remain source conditions.
    Neither the cancel bool nor the packet's exception class proves delivery.
    """
    from scar.ir.program.control import ProtocolValueKind as P, ProtocolValueType
    from scar.ir.program.ids import ValueID
    from scar.ir.program.model import (AccessMode, Behavior, Block, BlockArgument, CompletionSignature,
        CompletionSuccessor, DataValue, ExitKind, Footprint, FootprintKind, Operation,
        OperationResult, ProtocolValue, ReferenceValue, StateAccess, StateVersionValue,
        Terminator, TerminatorKind, Use, UseRole, ValueKind, ValueType)
    from scar.ir.program.protocols import OperationSiteSubject, OwnedUse, ProtocolCall, ProtocolCallRule
    from scar.ir.program.state_addresses import ExistingAccess
    from tests.fixtures.program_protocol_graphs import _role, _terminal
    graph = driver_program(target='packet')
    graph = replace(graph, resumable_bodies=tuple(replace(body, kind=ResumableKind.COROUTINE) for body in graph.resumable_bodies),
        operations=tuple(replace(op, terminator=replace(op.terminator, flavor=SuspensionFlavor.AWAIT))
            if type(op.terminator) is SuspendTerminator else op for op in graph.operations))
    handler_packet, continuation = None, None
    if handled:
        graph, handler_packet, continuation = _caught_body(graph)
        # The producer is now a caught RETURN; its original driver result slot
        # must retain that exact Reference signature, not the old RAISE packet.
        projected = next(value for value in graph.values if value.id.value == 'driver.outcome.arg.0')
        projected_ref = ReferenceValue(projected.id, projected.region, projected.origin)
        old_exit = _operation(graph, 'driver.outcome.exit')
        new_exit = replace(old_exit, uses=tuple(replace(use, role=UseRole.REFERENCE) if i == 0 else use
                                               for i, use in enumerate(old_exit.uses)),
                           terminator=replace(old_exit.terminator, kind=TerminatorKind.RETURN, exit='normal'))
        graph = replace(graph, values=tuple(projected_ref if value.id == projected.id else value for value in graph.values),
                        operations=tuple(new_exit if op.id == old_exit.id else op for op in graph.operations))
    graph = with_publications(graph)
    interface, = graph.driver_interfaces
    region = next(item for item in graph.regions if item.id == interface.region)
    entry = next(block for block in region.blocks if block.id == region.entry)
    values = {value.id: value for value in graph.values}
    operations = {op.id: op for op in graph.operations}
    original = entry.arguments
    states = tuple(value for value in original if isinstance(values[value], StateVersionValue))
    roles = tuple(value for value in original if value not in states)
    state_types = tuple(ValueType(ValueKind.STATE, location=values[value].location) for value in states)
    reference = ValueType(ValueKind.REFERENCE)
    packet_type = ProtocolValueType(P.EXCEPTION_PACKET)
    boolean = ValueType(ValueKind.DATA, data_type='builtins.bool')
    added_values, added_ops, added_blocks = [], [], []

    def formal(name, block, index, type_):
        origin = BlockArgument(block, index)
        if type_ == reference:
            value = ReferenceValue(ValueID(name), region.id, origin)
        elif isinstance(type_, ValueType) and type_.kind is ValueKind.STATE:
            value = StateVersionValue(ValueID(name), region.id, origin, type_.location)
        elif type_ == boolean:
            value = DataValue(ValueID(name), region.id, origin, 'builtins.bool')
        else:
            value = ProtocolValue(ValueID(name), region.id, origin, type_.protocol)
        added_values.append(value)
        values[value.id] = value
        return value.id

    def invoke(name, role_values, current, result_type, extra_forward=()):
        identity = OperationID(name)
        arguments = tuple(Use(UseID(f'{name}.arg.{i}'), value, _role(values[value]))
                          for i, value in enumerate((*role_values, *current)))
        forwards = tuple(Use(UseID(f'{name}.forward.{i}'), value, _role(values[value]))
                         for i, value in enumerate((*roles, *extra_forward)))
        normal, raised = BlockID(name + '.normal'), BlockID(name + '.raise')
        normal_args = tuple(formal(f'{name}.normal.{i}', normal, i, type_) for i, type_ in enumerate((
            result_type, *(ValueType(ValueKind.REFERENCE) if isinstance(values[value], ReferenceValue)
                          else ProtocolValueType(values[value].protocol) for value in (*roles, *extra_forward)), *state_types)))
        failure_args = tuple(formal(f'{name}.raise.{i}', raised, i, type_) for i, type_ in enumerate((packet_type, *state_types)))
        op = Operation(identity, 'original source-relative boundary', (Behavior.CONTROL,), (*arguments, *forwards), effects_complete=False,
            invoke_arguments=tuple(use.id for use in arguments),
            completions=(CompletionSignature(ExitKind.NORMAL, (result_type, *state_types)),
                         CompletionSignature(ExitKind.RAISE, (packet_type, *state_types))),
            terminator=Terminator(TerminatorKind.INVOKE, (
                CompletionSuccessor(ExitKind.NORMAL, normal, (CompletionResult(0), *(use.id for use in forwards),
                    *(CompletionResult(i + 1) for i in range(len(states))))),
                CompletionSuccessor(ExitKind.RAISE, raised, tuple(CompletionResult(i) for i in range(len(states) + 1))))))
        raised_exit = _terminal(name + '.raise.exit', failure_args[0], failure_args[1:], values, raised=True)
        added_ops.extend((op, raised_exit))
        added_blocks.append(Block(raised, failure_args, (raised_exit.id,)))
        return op, normal, normal_args, arguments

    create, created_block, created, create_uses = invoke('cancel.task.create', (roles[0],), states, reference)
    # The original body/source and packet stay as distinct forwarded Uses.
    created_roles, created_states = created[1:1 + len(roles)], created[1 + len(roles):]
    original_roles = roles
    roles = created_roles
    cancel, cancelled_block, cancelled, cancel_uses = invoke('cancel.request', (created[0],), created_states, boolean, (created[0],))
    copied_roles = cancelled[1:1 + len(roles)]
    task = cancelled[1 + len(roles)]
    current_states = cancelled[2 + len(roles):]
    gate = operations[graph.final_body_gates[0].operation]
    mapping = dict(zip((*original_roles, *states), (*copied_roles, *current_states)))
    gate = replace(gate, uses=tuple(replace(use, value=mapping.get(use.value, use.value)) for use in gate.uses))
    operations[gate.id] = gate
    added_blocks.extend((Block(created_block, created, (cancel.id,)), Block(cancelled_block, cancelled, (gate.id,))))
    blocks = tuple(replace(block, operations=(create.id,)) if block.id == entry.id else block for block in region.blocks) + tuple(added_blocks)
    scope = ProtocolScope(ProtocolScopeID('cancel.scope'), ProtocolProfile.TASK_CANCEL_EXTERNAL_V1,
                         OperationSiteSubject(region.id, cancel.id), _source_gap())
    request_rows = tuple(ProtocolOperation(scope.id, ProtocolClause.TASK_CANCEL_REQUEST, cancel.id, slot,
        ProtocolCall(cancel_uses[0].id, (), InvokeLiteralResult(ControlEdgeReference(cancel.id, slot), CompletionResult(0)),
            tuple(InvokeStateOperand(cancel.id, use.id) for use in cancel_uses[1:]), ProtocolCallRule.TASK_CANCEL_CALL), _source_gap())
        for slot in (0, 1))
    graph = replace(graph, regions=tuple(replace(item, blocks=blocks) if item.id == region.id else item for item in graph.regions),
        values=(*graph.values, *added_values), operations=(*operations.values(), *added_ops),
        control_scopes=tuple(replace(item, blocks=tuple(block.id for block in blocks)) if item.region == region.id else item for item in graph.control_scopes),
        protocol_scopes=(scope,), protocol_operations=request_rows)
    # A separate post-outcome Task status read. Its bool is actually consumed;
    # it is not inferred from the earlier cancel() result or body exception.
    values = {value.id: value for value in graph.values}
    operations = {op.id: op for op in graph.operations}
    commit, = graph.body_outcome_commits
    region = next(item for item in graph.regions if item.id == interface.region)
    landing = next(block for block in region.blocks if commit.operation in block.operations)
    terminal = operations[landing.operations[-1]]
    state_values = tuple(use.value for use in terminal.uses if isinstance(values[use.value], StateVersionValue))
    status_id = OperationID('cancel.status')
    task_use = Use(UseID('cancel.status.task'), task, UseRole.REFERENCE)
    state_uses = tuple(Use(UseID(f'cancel.status.state.{i}'), value, UseRole.STATE_CONTENT) for i, value in enumerate(state_values))
    status_value = DataValue(ValueID('cancel.status.bool'), region.id, OperationResult(status_id, 0), 'builtins.bool')
    status = Operation(status_id, 'original conditional Task status read', (Behavior.CONTROL, Behavior.READ), (task_use, *state_uses), (status_value.id,),
        tuple(StateAccess(values[use.value].location, use.id, AccessMode.READ, footprint=Footprint(FootprintKind.WHOLE)) for use in state_uses), effects_complete=True)
    observed_use = Use(UseID('cancel.status.observed'), status_value.id, UseRole.DATA)
    observed = Operation(OperationID('cancel.status.consume'), 'actual bool consumer', (Behavior.COMPUTE,), (observed_use,), effects_complete=True)
    blocks = tuple(replace(block, operations=(*block.operations[:-1], status.id, observed.id, block.operations[-1])) if block.id == landing.id else block for block in region.blocks)
    graph = replace(graph, regions=tuple(replace(item, blocks=blocks) if item.id == region.id else item for item in graph.regions),
                    operations=(*graph.operations, status, observed), values=(*graph.values, status_value))
    details = {'scope': scope.id, 'create': create.id, 'cancel': cancel.id, 'task': task,
        'body_use': create_uses[0], 'create_result': InvokeLiteralResult(ControlEdgeReference(create.id, 0), CompletionResult(0)),
        'drive': graph.body_drives[0], 'status': status, 'status_consumer': observed_use,
        'handler_packet': handler_packet, 'continuation': continuation, 'rows': request_rows,
        'packet_source': BlockArgument(entry.id, entry.arguments.index(original_roles[2]))}
    if attach_records:
        from scar.ir.program.protocol_connections import (CancelDelivery, CancelDeliveryRef, CancelHandling,
            TaskCreatedTarget, TaskStatusRead, TaskStatusRule)
        from scar.ir.program.protocols import OwnedUse
        from tests.fixtures.program_driver_graphs import driver_rule
        target = TaskCreatedTarget(details['create_result'], OwnedUse(create.id, create_uses[0].id), driver_rule().implementation)
        delivery = CancelDelivery(scope.id, target, details['packet_source'], OwnedUse(details['drive'].operation, details['drive'].resume_inputs[0].source))
        reference = CancelDeliveryRef(delivery.scope, delivery.expected_target, delivery.packet_source, delivery.consumer)
        bindings = [delivery]
        if handled:
            bindings.append(CancelHandling(reference, OwnedUse(OperationID('cancel.handler'), handler_packet.id),
                                          (ExistingAccess(OperationID('cancel.handler'), 0),), continuation))
        bindings.append(TaskStatusRead(scope.id, OwnedUse(status.id, task_use.id), OperationResult(status.id, 0),
                        tuple(ExistingAccess(status.id, i) for i in range(len(state_uses))), TaskStatusRule.IS_CANCELLED,
                        OwnedUse(observed.id, observed_use.id)))
        graph = replace(graph, protocol_bindings=tuple(bindings))
        details['bindings'] = tuple(bindings)
    return graph, details


__all__.append('cancellation_program')


def cancellation_waiter_program(*, role='CURRENT_AWAITED'):
    """An actual Task read names a Future; missing forwarding is not identity."""
    from scar.ir.program.ids import ValueID
    from scar.ir.program.model import (AccessMode, Behavior, Footprint, FootprintKind,
        Operation, OperationResult, ReferenceValue, StateAccess, StateVersionValue, Use, UseRole)
    from scar.ir.program.protocol_connections import (CancelDelivery, CancelDeliveryRef, CancelHandling,
        TaskTargetRead, TaskTargetRole)
    from scar.ir.program.protocols import OwnedUse
    from scar.ir.program.state_addresses import ExistingAccess
    from tests.fixtures.program_driver_graphs import driver_rule
    graph, details = cancellation_program()
    values = {value.id: value for value in graph.values}
    gate = _operation(graph, graph.final_body_gates[0].operation)
    region = next(region for region in graph.regions if any(gate.id in block.operations for block in region.blocks))
    block = next(block for block in region.blocks if gate.id in block.operations)
    task = Use(UseID('cancel.waiter.task'), details['task'], UseRole.REFERENCE)
    states = tuple(Use(UseID(f'cancel.waiter.state.{i}'), use.value, UseRole.STATE_CONTENT)
        for i, use in enumerate(gate.uses) if use.id in gate.invoke_arguments and isinstance(values[use.value], StateVersionValue))
    identity = OperationID('cancel.waiter.read')
    result = ReferenceValue(ValueID('cancel.waiter.result'), region.id, OperationResult(identity, 0))
    operation = Operation(identity, 'original conditional Task waiter read', (Behavior.CONTROL, Behavior.READ),
        (task, *states), (result.id,), tuple(StateAccess(values[use.value].location, use.id, AccessMode.READ,
            footprint=Footprint(FootprintKind.WHOLE)) for use in states), effects_complete=True)
    target = TaskTargetRead(OwnedUse(operation.id, task.id), result.origin,
        tuple(ExistingAccess(operation.id, i) for i in range(len(states))), TaskTargetRole(role), driver_rule().implementation)
    delivery = next(row for row in graph.protocol_bindings if type(row) is CancelDelivery)
    replacement = replace(delivery, expected_target=target)
    bindings = tuple(replacement if row is delivery else replace(row, delivery=CancelDeliveryRef(
        replacement.scope, replacement.expected_target, replacement.packet_source, replacement.consumer))
        if type(row) is CancelHandling else row for row in graph.protocol_bindings)
    graph = replace(graph, operations=(*graph.operations, operation), values=(*graph.values, result),
        regions=tuple(replace(item, blocks=tuple(replace(known, operations=(operation.id, *known.operations))
            if known.id == block.id else known for known in item.blocks)) if item.id == region.id else item for item in graph.regions),
        protocol_bindings=bindings)
    return graph, {**details, 'target_read': operation, 'target_result': result}


__all__.append('cancellation_waiter_program')


def request_state_program(*, rule='IS_INITIAL_STEP', target='start', initial_step=True):
    """Read R's actual state and branch on that very boolean evaluation."""
    from scar.ir.program.drivers import RawRequestKind
    from scar.ir.program.protocols import AdmissionPredicate, BodyStatePredicateRule, RequestProcessing, RequestProcessingRule
    from scar.ir.program.protocol_connections import RequestStateCondition, RequestStateRule
    from tests.fixtures.program_generator_admission_graphs import _guard
    graph, details = async_driver_program(target=target)
    graph, guard = _guard(graph, block_id=BlockID('driver.no_body.test'),
        owner=details['sources']['session'], raw=details['sources']['scheduler'],
        label='async.request.state', rule=BodyStatePredicateRule.IS_CREATED,
        request_kind=RawRequestKind.NEXT, admit_true=rule == 'IS_INITIAL_STEP' and initial_step)
    rows = []
    predicate = None
    for row in graph.protocol_operations:
        if type(row.contract) is AdmissionPredicate and row.operation == guard['predicate']:
            subject = row.contract.subject
            row = replace(row, clause=ProtocolClause.ASYNC_REQUEST_SOURCE,
                contract=replace(row.contract, subject=RequestStateCondition(subject.instance_use, subject.state_sites, RequestStateRule(rule))))
            predicate = row
        elif type(row.contract) is RequestProcessing and row.operation == guard['helper']:
            helper = _operation(graph, row.operation)
            row = replace(row, clause=ProtocolClause.ASYNC_REQUEST_DELIVERY,
                contract=replace(row.contract, raw_use=helper.invoke_arguments[0], rule=RequestProcessingRule.CHECK_ASYNC_REQUEST))
        rows.append(row)
    graph = replace(graph, protocol_operations=tuple(rows))
    return graph, {**details, **guard, 'predicate_row': predicate}


__all__.append('request_state_program')


def request_creation_program(*, kind='SEND', send_none=False, with_predicate=True,
                             initial_step=True, scheduler_kind='NEXT', normalize=False):
    """An actual caller packs L/S, creates R, then calls its exact driver.

    No operation creates a second body; B is an external bound continuation.
    A successful request creation is distinct from starting or resuming B.
    """
    from scar.ir.program.control import ControlScope, ControlScopeKind, ProtocolValueKind as P
    from scar.ir.program.drivers import AsyncRequestCreate, NormalResultPort, RawRequestDefinition, RawRequestKind
    from scar.ir.program.ids import ControlScopeID, RegionID, ValueID
    from scar.ir.program.model import (Behavior, CompletionSignature, CompletionSuccessor,
        Operation, OperationResult, ReferenceValue, Region, StateVersionValue,
        Terminator, TerminatorKind, Use, UseRole, ValueKind, ValueType)
    from tests.fixtures.program_control_graphs import _source
    from tests.fixtures.program_driver_graphs import _Builder, _use, driver_rule, PACKET, RAW, REFERENCE
    kind = RawRequestKind(kind)
    target = 'value' if kind in (RawRequestKind.NEXT, RawRequestKind.SEND) else 'packet'
    graph, details = (request_state_program(target=target, initial_step=initial_step) if with_predicate else async_driver_program(target=target))
    if normalize:
        graph, normalized = _latent_normalization(graph, details, kind)
        details.update(normalized)
    interface, = graph.driver_interfaces
    driver = next(region for region in graph.regions if region.id == interface.region)
    driver_entry = next(block for block in driver.blocks if block.id == driver.entry)
    values = {value.id: value for value in graph.values}
    domains = tuple(location.id for location in graph.locations)
    state_types = tuple(ValueType(ValueKind.STATE, location=location) for location in domains)
    b = _Builder('async.caller', domains)
    entry_types = (REFERENCE, REFERENCE, *((PACKET,) if target == 'packet' else ()), *state_types)
    entry = b.formals('async.caller.entry', entry_types)
    state_values = entry[-len(domains):]
    from scar.ir.program.model import LiteralOrigin
    none = ReferenceValue(ValueID('async.caller.none'), b.region, LiteralOrigin(None), targets=())
    b.values.append(none)
    operand = none.id if send_none or kind is RawRequestKind.NEXT else entry[1]
    latent_uses = () if kind in (RawRequestKind.NEXT, RawRequestKind.CLOSE) else (_use('async.caller.latent.operand', operand),)
    latent = b.value('async.caller.latent', OperationResult(OperationID('async.caller.latent.pack'), 0), RAW)
    scheduler = b.value('async.caller.scheduler', OperationResult(OperationID('async.caller.scheduler.pack'), 0), RAW)
    latent_op = b.add('async.caller.latent.pack', latent_uses, results=(latent,), effects_complete=True)
    scheduler_kind = RawRequestKind(scheduler_kind)
    scheduler_uses = (() if scheduler_kind in (RawRequestKind.NEXT, RawRequestKind.CLOSE) else
                      (_use('async.caller.scheduler.operand', entry[1]),))
    scheduler_op = b.add('async.caller.scheduler.pack', scheduler_uses, results=(scheduler,), effects_complete=True)
    create_uses = (_use('async.caller.create.body', entry[0]), _use('async.caller.create.latent', latent, protocol=True),
                   *(_use(f'async.caller.create.state.{i}', value, state=True) for i, value in enumerate(state_values)))
    created = b.formals('async.caller.created', (REFERENCE, *state_types))
    failed = b.formals('async.caller.failed', (PACKET, *state_types))
    create = b.add('async.caller.create', create_uses, effects_complete=False,
        invoke_arguments=tuple(use.id for use in create_uses),
        completions=(CompletionSignature(ExitKind.NORMAL, (REFERENCE, *state_types)), CompletionSignature(ExitKind.RAISE, (PACKET, *state_types))),
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, BlockID('async.caller.created'), tuple(CompletionResult(i) for i in range(1 + len(domains)))),
            CompletionSuccessor(ExitKind.RAISE, BlockID('async.caller.failed'), tuple(CompletionResult(i) for i in range(1 + len(domains)))))))
    actuals = []
    for number, formal in enumerate(driver_entry.arguments):
        value = values[formal]
        if formal == interface.receiver:
            actual = created[0]
        elif formal == interface.scheduler_request:
            actual = scheduler
        elif isinstance(value, StateVersionValue):
            actual = created[1 + domains.index(value.location)]
        elif number == 0:
            actual = entry[0]
        elif isinstance(value, ReferenceValue):
            actual = operand if initial_step else (none.id if scheduler_kind is RawRequestKind.NEXT else entry[1])
        else:
            actual = entry[2]
        actuals.append(_use(f'async.caller.invoke.arg.{number}', actual,
            state=isinstance(value, StateVersionValue), protocol=not isinstance(value, (ReferenceValue, StateVersionValue))))
    successors, signatures = [], []
    for port in driver.exits:
        name = 'async.caller.driver.' + port.kind.value
        formals = b.formals(name, port.types)
        terminal = b.terminal(name + '.exit', formals, fail=port.kind is ExitKind.RAISE)
        b.block(name, formals, (terminal,))
        signatures.append(CompletionSignature(port.kind, port.types))
        successors.append(CompletionSuccessor(port.kind, BlockID(name), tuple(CompletionResult(i) for i in range(len(formals)))))
    invoke = b.add('async.caller.invoke', tuple(actuals), effects_complete=False, callee=driver.id,
        invoke_arguments=tuple(use.id for use in actuals), completions=tuple(signatures),
        terminator=Terminator(TerminatorKind.INVOKE, tuple(successors)))
    b.block('async.caller.entry', entry, (latent_op, scheduler_op, create))
    b.block('async.caller.created', created, (invoke,))
    b.block('async.caller.failed', failed, (b.terminal('async.caller.failed.exit', failed, fail=True),))
    root = b.finish('async.caller.entry')
    # The caller has only actual exits. The async request iterator adapter can
    # make its successful item path a host RAISE rather than NORMAL.
    exit_kinds = {port.kind for port in driver.exits} | {ExitKind.RAISE}
    root = replace(root, exits=tuple(port for port in root.exits if port.kind in exit_kinds))
    graph = replace(graph, root=root.id,
        regions=(root, *(replace(region, parent=root.id) if region.id == driver.id else region for region in graph.regions)),
        operations=(*graph.operations, *b.operations), values=(*graph.values, *b.values),
        control_scopes=(*graph.control_scopes, ControlScope(ControlScopeID('async.caller.function'), root.id, None,
            ControlScopeKind.FUNCTION, _source('async caller'), tuple(block.id for block in root.blocks))),
        raw_driver_requests=(*graph.raw_driver_requests, RawRequestDefinition(latent, kind, tuple(use.id for use in latent_uses)),
                          RawRequestDefinition(scheduler, scheduler_kind, tuple(use.id for use in scheduler_uses))),
        async_request_creates=(*graph.async_request_creates, AsyncRequestCreate(create.id, create_uses[0].id,
            create_uses[1].id, NormalResultPort(0), driver_rule())))
    return graph, {**details, 'request_create': create.id, 'latent_definition': graph.raw_driver_requests[-2],
                    'scheduler_definition': graph.raw_driver_requests[-1], 'caller': invoke.id}


__all__.append('request_creation_program')


def _latent_normalization(graph, details, kind):
    """One genuine N/R helper consumes L before the private final gate."""
    from scar.ir.program.drivers import RawRequestKind
    from scar.ir.program.model import (CompletionSignature, CompletionSuccessor, Block, OperationResult,
        StateVersionValue, Terminator, TerminatorKind, Use, value_type)
    from scar.ir.program.protocols import RequestProcessing, RequestProcessingRule
    from tests.fixtures.program_driver_graphs import _Builder, _use, PACKET
    from tests.fixtures.program_protocol_graphs import _role
    kind = RawRequestKind(kind)
    if kind not in (RawRequestKind.THROW, RawRequestKind.CLOSE):
        raise ValueError('only actual THROW/CLOSE normalization belongs here')
    gate = _operation(graph, details['gate'])
    region = next(region for region in graph.regions if region.id == details['interface'].region)
    block = next(block for block in region.blocks if gate.id in block.operations)
    values = {value.id: value for value in graph.values}
    states = tuple(value for value in block.arguments if isinstance(values[value], StateVersionValue))
    roles = tuple(value for value in block.arguments if value not in states)
    domains = tuple(values[value].location for value in states)
    state_types = tuple(value_type(values[value]) for value in states)
    b = _Builder(region.id.value, domains)
    # _insert_association / _guard keep the original order B,L,S,R,delivery.
    raw = _use('async.normalize.latent', block.arguments[1], protocol=True)
    state_uses = tuple(_use(f'async.normalize.state.{i}', value, state=True) for i, value in enumerate(states))
    forwards = tuple(Use(UseID(f'async.normalize.forward.{i}'), value, _role(values[value]))
                     for i, value in enumerate(roles))
    normal = b.formals('async.normalize.normal', (PACKET, *(value_type(values[value]) for value in roles), *state_types))
    raised = b.formals('async.normalize.raise', (PACKET, *state_types))
    helper = b.add('async.normalize', (raw, *state_uses, *forwards), effects_complete=False,
        invoke_arguments=(raw.id, *(use.id for use in state_uses)),
        completions=(CompletionSignature(ExitKind.NORMAL, (PACKET, *state_types)),
                     CompletionSignature(ExitKind.RAISE, (PACKET, *state_types))),
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, BlockID('async.normalize.normal'),
                (CompletionResult(0), *(use.id for use in forwards), *(CompletionResult(i + 1) for i in range(len(states))))),
            CompletionSuccessor(ExitKind.RAISE, BlockID('async.normalize.raise'),
                tuple(CompletionResult(i) for i in range(len(states) + 1))))))
    substitution = dict(zip(roles, normal[1:1 + len(roles)]))
    substitution.update(zip(states, normal[1 + len(roles):]))
    gate_row, = graph.final_body_gates
    payload_value = next(use.value for use in gate.uses if use.id == gate.invoke_arguments[gate_row.delivery_arguments[0]])
    substitution[payload_value] = normal[0]
    changed = replace(gate, uses=tuple(replace(use, value=substitution.get(use.value, use.value)) for use in gate.uses))
    b.block('async.normalize.normal', normal, (changed,))
    b.block('async.normalize.raise', raised, (b.terminal('async.normalize.raise.exit', raised, fail=True),))
    blocks = tuple(replace(item, operations=(helper.id,)) if item.id == block.id else item for item in region.blocks) + tuple(b.blocks)
    rule = (RequestProcessingRule.NORMALIZE_GENERATOR_EXIT if kind is RawRequestKind.CLOSE else
            RequestProcessingRule.NORMALIZE_ASYNC_THROW)
    sites = tuple(InvokeStateOperand(helper.id, use.id) for use in state_uses)
    rows = tuple(ProtocolOperation(details['scope'], ProtocolClause.ASYNC_REQUEST_DELIVERY, helper.id, i,
        RequestProcessing(raw.id, (), InvokeLiteralResult(ControlEdgeReference(helper.id, i), CompletionResult(0)), sites, rule),
        _source_gap()) for i in range(2))
    graph = replace(graph, regions=tuple(replace(item, blocks=blocks) if item.id == region.id else item for item in graph.regions),
        operations=tuple(changed if op.id == gate.id else op for op in graph.operations) + tuple(b.operations),
        values=(*graph.values, *b.values), protocol_operations=(*graph.protocol_operations, *rows),
        control_scopes=tuple(replace(scope, blocks=tuple(block.id for block in blocks)) if scope.region == region.id else scope
                             for scope in graph.control_scopes))
    return graph, {'normalization': helper.id, 'normalization_rows': rows, 'normalization_raw': raw}
