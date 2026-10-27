"""A real call/body causal contradiction with valid original CFG and ports."""
from dataclasses import replace

from scar.ir.execution.calls import CallActivation
from scar.ir.execution.coordinates import (
    BlockVisit, ControlTransfer, OperationOccurrence, UseOccurrence, ValueOccurrence,
)
from scar.ir.execution.ids import (
    BlockVisitID, CallActivationID, OperationOccurrenceID, ValueOccurrenceID,
)
from scar.ir.execution.snapshot import snapshot_for
from scar.ir.program.control import ProtocolValueKind
from scar.ir.program.drivers import RawRequestDefinition, RawRequestKind
from scar.ir.program.ids import BlockID, OperationID, ValueID
from scar.ir.program.model import (
    Behavior, CompletionResult, CompletionSignature, CompletionSuccessor, ExitKind,
    OperationResult, ProtocolValueType, Successor, Terminator, TerminatorKind,
    ValueKind, ValueType,
)
from tests.fixtures.execution_resumable_graphs import resumable_execution
from tests.fixtures.program_driver_graphs import RAW, _Builder, _use


def mixed_body_call_cycle_execution():
    """Return program/model/details; a body calls the driver entering that body.

    The only CALL activation edge is body -> driver, an acyclic call relation.
    The original driver's body-entry bridge closes a real occurrence cycle.
    No fake Return/Raise, static callee selection or extra state producer is used.
    """
    program, model, details = resumable_execution()
    instance, = details['instances']
    body = next(region for region in program.regions if region.id == program.resumable_bodies[0].region)
    driver = next(region for region in program.regions if region.id == program.driver_interfaces[0].region)
    entry = next(block for block in body.blocks if block.id == body.entry)
    operations = {row.id: row for row in program.operations}
    attach = operations[OperationID('resume.attach')]
    caller, attached = attach.results
    world, = (value.id for value in program.values if value.id == ValueID('resume.world.0'))
    domains = tuple(location.id for location in program.locations)
    states = tuple(ValueType(ValueKind.STATE, location=identity) for identity in domains)
    token = ProtocolValueType(ProtocolValueKind.DRIVE_CALLER_CONTEXT)
    b = _Builder(body.id.value, domains)
    raw = b.value('body.cycle.raw.value', OperationResult(OperationID('body.cycle.raw'), 0), RAW)
    raw_op = b.add('body.cycle.raw', results=(raw,), effects_complete=True)
    raw_op = replace(raw_op, behaviors=(Behavior.COMPUTE,))
    b.operations[-1] = raw_op
    normal_types = next(port.types for port in driver.exits if port.kind is ExitKind.NORMAL)
    raise_types = next(port.types for port in driver.exits if port.kind is ExitKind.RAISE)
    normal = b.formals('body.cycle.normal', (*normal_types, token))
    failed = b.formals('body.cycle.raise', (*raise_types, token))
    joined = b.formals('body.cycle.join', (*normal_types, token))
    inputs = tuple(_use(f'body.cycle.input.{index}', value, state=index >= 2, protocol=index == 1)
                   for index, value in enumerate((entry.arguments[0], raw, world, attached)))
    forwarded = tuple(_use(f'body.cycle.caller.{index}', caller, protocol=True) for index in range(2))
    call = b.add('body.cycle.invoke', (*inputs, *forwarded), callee=driver.id,
        invoke_arguments=tuple(use.id for use in inputs), effects_complete=True,
        completions=(CompletionSignature(ExitKind.NORMAL, normal_types),
                     CompletionSignature(ExitKind.RAISE, raise_types)),
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, BlockID('body.cycle.normal'),
                                (*(CompletionResult(index) for index in range(len(normal_types))), forwarded[0].id)),
            CompletionSuccessor(ExitKind.RAISE, BlockID('body.cycle.raise'),
                                (*(CompletionResult(index) for index in range(len(raise_types))), forwarded[1].id)),
        )))
    normal_forwards = tuple(_use(f'body.cycle.normal.join.{index}', value,
                                state=index in (1, 2), protocol=index == 3)
                            for index, value in enumerate(normal))
    normal_jump = b.add('body.cycle.normal.join', normal_forwards, effects_complete=True,
        terminator=Terminator(TerminatorKind.JUMP,
                              (Successor(BlockID('body.cycle.join'), tuple(use.id for use in normal_forwards)),)))
    forwards = tuple(_use(f'body.cycle.recover.{index}', value,
                         state=index in (1, 2), protocol=index == 3)
                     for index, value in enumerate((entry.arguments[0], *failed[1:])))
    recover = b.add('body.cycle.recover', forwards, effects_complete=True,
        terminator=Terminator(TerminatorKind.JUMP,
                              (Successor(BlockID('body.cycle.join'), tuple(use.id for use in forwards)),)))
    tail = entry.operations[2:]
    substitution = {world: joined[1], attached: joined[2], caller: joined[3]}
    changed_ops = tuple(replace(op, uses=tuple(replace(use, value=substitution.get(use.value, use.value))
                                              for use in op.uses)) if op.id in tail else op
                        for op in program.operations)
    b.block('body.cycle.normal', normal, (normal_jump,))
    b.block('body.cycle.raise', failed, (recover,))
    b.block('body.cycle.join', joined, tuple(operations[identity] for identity in tail))
    body = replace(body, blocks=tuple(replace(block,
        operations=(*entry.operations[:2], raw_op.id, call.id)) if block.id == entry.id else block
        for block in body.blocks) + tuple(b.blocks))
    program = replace(program,
        regions=tuple(body if region.id == body.id else region for region in program.regions),
        operations=(*changed_ops, *b.operations), values=(*program.values, *b.values),
        raw_driver_requests=(*program.raw_driver_requests, RawRequestDefinition(raw, RawRequestKind.NEXT, ())),
        control_scopes=tuple(replace(scope, blocks=(*scope.blocks, *(block.id for block in b.blocks)))
                             if scope.region == body.id else scope for scope in program.control_scopes))

    original_visit = instance['entries'][0]
    normal_visit = BlockVisitID('body.cycle.normal')
    new_visit = BlockVisitID('body.cycle.join')
    raw_occurrence = OperationOccurrenceID('body.cycle.raw')
    call_occurrence = OperationOccurrenceID('body.cycle.invoke')
    jump_occurrence = OperationOccurrenceID('body.cycle.normal.join')
    old_values = {(row.origin, row.value): row for row in model.values}
    attach_occurrence = next(row.id for row in model.operations
                             if row.visit == original_visit and row.operation == attach.id)
    current = {static: old_values[origin, static].id for origin, static in (
        (original_visit, entry.arguments[0]), (original_visit, world), (attach_occurrence, attached))}
    current[caller] = old_values[attach_occurrence, caller].id
    raw_value = ValueOccurrence(ValueOccurrenceID('body.cycle.raw'), raw, raw_occurrence)
    current[raw] = raw_value.id
    normal_values = tuple(ValueOccurrence(ValueOccurrenceID('body.cycle.' + value.value), value, normal_visit)
                          for value in normal)
    formal_values = tuple(ValueOccurrence(ValueOccurrenceID('body.cycle.' + value.value), value, new_visit)
                          for value in joined)
    aliases = {current[old]: new.id for old, new in zip((world, attached, caller), formal_values[1:])}
    moved = {row.id for row in model.operations if row.visit == original_visit and row.operation in tail}
    link = CallActivation(CallActivationID('body.cycle'), call_occurrence,
        instance['start'][0], instance['start'][1][0],
        instance['start'][2][OperationID('driver.outcome.exit')], details['source'])
    model = replace(model, snapshot=snapshot_for(program), denotations=(),
        visits=(*model.visits, BlockVisit(normal_visit, instance['segments'][0], BlockID('body.cycle.normal')),
                BlockVisit(new_visit, instance['segments'][0], BlockID('body.cycle.join'))),
        operations=(*(replace(row, visit=new_visit) if row.id in moved else row for row in model.operations),
            OperationOccurrence(raw_occurrence, original_visit, raw_op.id),
            OperationOccurrence(call_occurrence, original_visit, call.id),
            OperationOccurrence(jump_occurrence, normal_visit, normal_jump.id)),
        values=(*model.values, raw_value, *normal_values, *formal_values),
        uses=(*(replace(row, value=aliases.get(row.value, row.value)) if row.operation in moved else row
                for row in model.uses),
              *(UseOccurrence(call_occurrence, use.id, current[use.value]) for use in call.uses),
              *(UseOccurrence(jump_occurrence, use.id, value.id)
                for use, value in zip(normal_jump.uses, normal_values, strict=True))),
        transfers=(*model.transfers, ControlTransfer(call_occurrence, 0, normal_visit),
                   ControlTransfer(jump_occurrence, 0, new_visit)),
        call_activations=(*(row for row in model.call_activations if row.activation != link.activation), link))
    return program, model, {**details, 'cycle_call': link}


__all__ = ['mixed_body_call_cycle_execution']
