"""Request admission over real READ/bool/BRANCH/gate ports.

These supplied graphs do not select native phase, dynamic identity, or a
successful runtime gate outcome. Historical predicates remain ordinary values.
"""
from dataclasses import replace

from scar.ir.program.ids import BlockID, OperationID, UseID, ValueID
from scar.ir.program.model import (AccessMode, Behavior, Block, BlockArgument,
    CompletionResult, CompletionSignature, CompletionSuccessor, DataValue,
    ExitKind, Footprint, FootprintKind, LiteralOrigin, Operation, OperationResult,
    ReferenceValue, StateAccess, StateVersionValue, Terminator, TerminatorKind,
    Use, UseRole, value_type)
from tests.fixtures.program_async_connections import request_creation_program, request_state_program
from tests.fixtures.program_driver_graphs import PACKET, _Builder


def _operation(graph, identity):
    return next(op for op in graph.operations if op.id == identity)


def _callback(graph, details):
    """A real unknown helper changes state before the gate; both exits remain."""
    gate = _operation(graph, details['gate'])
    region = next(region for region in graph.regions if region.id == details['interface'].region)
    block = next(block for block in region.blocks if gate.id in block.operations)
    values = {value.id: value for value in graph.values}
    states = tuple(value for value in block.arguments if isinstance(values[value], StateVersionValue))
    roles = tuple(value for value in block.arguments if value not in states)
    builder = _Builder(region.id.value, tuple(values[value].location for value in states))
    own = tuple(Use(UseID(f'request.callback.state.{i}'), value, UseRole.STATE_CONTENT)
                for i, value in enumerate(states))
    forwarded = tuple(Use(UseID(f'request.callback.forward.{i}'), value,
        UseRole.REFERENCE if isinstance(values[value], ReferenceValue) else UseRole.PROTOCOL)
        for i, value in enumerate(roles))
    state_types = tuple(value_type(values[value]) for value in states)
    normal = builder.formals('request.callback.normal',
        (*(value_type(values[value]) for value in roles), *state_types))
    raised = builder.formals('request.callback.raise', (PACKET, *state_types))
    helper = builder.add('request.callback', (*own, *forwarded), effects_complete=False,
        invoke_arguments=tuple(use.id for use in own),
        completions=(CompletionSignature(ExitKind.NORMAL, state_types),
                     CompletionSignature(ExitKind.RAISE, (PACKET, *state_types))),
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, BlockID('request.callback.normal'),
                (*(use.id for use in forwarded), *(CompletionResult(i) for i in range(len(states))))),
            CompletionSuccessor(ExitKind.RAISE, BlockID('request.callback.raise'),
                tuple(CompletionResult(i) for i in range(len(states) + 1))))))
    mapping = dict(zip((*roles, *states), normal))
    changed = replace(gate, uses=tuple(replace(use, value=mapping.get(use.value, use.value)) for use in gate.uses))
    builder.block('request.callback.normal', normal, (changed,))
    builder.block('request.callback.raise', raised,
        (builder.terminal('request.callback.raise.exit', raised, fail=True),))
    blocks = tuple(replace(item, operations=(helper.id,)) if item.id == block.id else item
                   for item in region.blocks) + tuple(builder.blocks)
    graph = replace(graph, values=(*graph.values, *builder.values),
        operations=tuple(changed if op.id == changed.id else op for op in graph.operations) + tuple(builder.operations),
        regions=tuple(replace(item, blocks=blocks) if item.id == region.id else item for item in graph.regions),
        control_scopes=tuple(replace(scope, blocks=tuple(block.id for block in blocks))
            if scope.region == region.id else scope for scope in graph.control_scopes))
    return graph, helper


def request_admission_program(*, rule='IS_COMPLETE', drive_on_true=False,
                              callback=False, wrong_receiver=False, wrong_bool=False):
    graph, details = request_state_program(rule=rule, target='value')
    branch = _operation(graph, details['branch'])
    # The base COMPLETE predicate rejects true and reaches the gate on false.
    if (rule == 'IS_COMPLETE' and drive_on_true):
        branch = replace(branch, terminator=replace(branch.terminator,
            successors=tuple(reversed(branch.terminator.successors))))
        graph = replace(graph, operations=tuple(branch if op.id == branch.id else op for op in graph.operations))
    if wrong_receiver:
        predicate = _operation(graph, details['predicate'])
        region = next(region for region in graph.regions if region.id == details['interface'].region)
        block = next(block for block in region.blocks if predicate.id in block.operations)
        changed = replace(predicate, uses=tuple(replace(use, value=block.arguments[0])
            if use.id == details['predicate_row'].contract.subject.request_use else use for use in predicate.uses))
        graph = replace(graph, operations=tuple(changed if op.id == changed.id else op for op in graph.operations))
    if wrong_bool:
        original = next(value for value in graph.values if value.id == branch.uses[0].value)
        boolean = DataValue(ValueID('request.unrelated.bool'), original.region, LiteralOrigin(True), 'builtins.bool')
        branch = replace(branch, uses=tuple(replace(use, value=boolean.id)
            if use.id == branch.terminator.condition else use for use in branch.uses))
        graph = replace(graph, values=(*graph.values, boolean),
            operations=tuple(branch if op.id == branch.id else op for op in graph.operations))
    if callback:
        graph, helper = _callback(graph, details)
        details = {**details, 'callback': helper}
    return graph, details


def request_two_callers_program():
    """Two real calls use one declared R source, without inferring native reuse.

    The first iterator completion is caught at its actual RAISE landing; a
    context RW primitive supplies the second call's latest context state.
    Both call occurrences remain static source recipes, not native identity.
    """
    graph, details = request_creation_program(kind='SEND')
    first = _operation(graph, details['caller'])
    root = next(region for region in graph.regions if region.id == graph.root)
    values = {value.id: value for value in graph.values}
    edge, = first.terminator.successors
    assert edge.kind is ExitKind.RAISE
    landing = next(block for block in root.blocks if block.id == edge.block)
    terminal = _operation(graph, landing.operations[-1])
    state_values = {values[value].location: value for value in landing.arguments
                    if isinstance(values[value], StateVersionValue)}
    context = graph.resumable_bodies[0].context_location
    identity = OperationID('request.first_completion.context')
    packet = Use(UseID('request.first_completion.packet'), landing.arguments[0], UseRole.PROTOCOL)
    before = Use(UseID('request.first_completion.before'), state_values[context], UseRole.STATE_CONTENT)
    after = StateVersionValue(ValueID('request.first_completion.after'), root.id, OperationResult(identity, 0), context)
    handler = Operation(identity, 'declared caught request completion context install',
        (Behavior.CONTROL, Behavior.READ, Behavior.WRITE), (packet, before), (after.id,),
        (StateAccess(context, before.id, AccessMode.READ_WRITE, after.id, Footprint(FootprintKind.WHOLE)),),
        effects_complete=True)
    state_values[context] = after.id
    arguments = tuple(replace(use, id=UseID(f'request.second.actual.{number}'),
        value=state_values[values[use.value].location] if isinstance(values[use.value], StateVersionValue) else use.value)
        for number, use in enumerate(first.uses))
    next_block = BlockID('request.second.raise')
    result_values = tuple(replace(values[value], id=ValueID(f'request.second.result.{number}'),
        origin=BlockArgument(next_block, number)) for number, value in enumerate(landing.arguments))
    second = replace(first, id=OperationID('request.second.call'), uses=arguments,
        invoke_arguments=tuple(use.id for use in arguments),
        terminator=replace(first.terminator, successors=(replace(edge, block=next_block),)))
    mapping = dict(zip(landing.arguments, (value.id for value in result_values)))
    terminal = replace(terminal, uses=tuple(replace(use, value=mapping.get(use.value, use.value)) for use in terminal.uses))
    blocks = tuple(replace(block, operations=(handler.id, second.id)) if block.id == landing.id else block
                   for block in root.blocks) + (Block(next_block, tuple(value.id for value in result_values), (terminal.id,)),)
    graph = replace(graph, values=(*graph.values, after, *result_values),
        operations=tuple(terminal if op.id == terminal.id else op for op in graph.operations) + (handler, second),
        regions=tuple(replace(region, blocks=blocks) if region.id == root.id else region for region in graph.regions),
        control_scopes=tuple(replace(scope, blocks=tuple(block.id for block in blocks))
            if scope.region == root.id else scope for scope in graph.control_scopes))
    return graph, {**details, 'callers': (first, second), 'completion_handler': handler}


__all__ = ['request_admission_program', 'request_two_callers_program']
