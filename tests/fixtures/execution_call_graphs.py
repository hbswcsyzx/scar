"""Declared synchronous call paths, not recovered source/runtime execution.

Each child has its own entry/formal/result occurrences. CallActivation connects
the original ports; no UseOccurrence borrows a value from another activation.
"""
from dataclasses import replace

from scar.ir.execution.calls import CallActivation
from scar.ir.execution.common import EvidencePoint, MissingEvidence
from scar.ir.execution.coordinates import (
    BlockVisit, ControlTransfer, ExecutionRun, ExecutionSegment, HostThreadInstance,
    InitialEntry, OperationOccurrence, ProcessInstance, RegionActivation,
    UseOccurrence, ValueOccurrence,
)
from scar.ir.execution.ids import (
    BlockVisitID, CallActivationID, ExecutionSegmentID, HostThreadInstanceID,
    OperationOccurrenceID, ProcessInstanceID, RegionActivationID, RunID, ValueOccurrenceID,
)
from scar.ir.execution.model import ExecutionModel
from scar.ir.execution.snapshot import snapshot_for
from scar.ir.program.ids import BlockID, LocationID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, CompletionResult, CompletionSignature,
    CompletionSuccessor, DataValue, ExitKind, ExitPort, LiteralOrigin, Operation,
    OperationResult, ProgramGraph, ReferenceValue, Region, StateAccess, StateLocation,
    StateVersionValue, Successor, Terminator, TerminatorKind, Use, UseRole, ValueKind,
    ValueType,
)
from tests.fixtures.program_graphs import shared_body_calls_program


def _activation(program, region, path, label, point, thread):
    """Build one finite declared path without re-rooting the canonical program."""
    blocks = {row.id: row for owner in program.regions for row in owner.blocks}
    operations = {row.id: row for row in program.operations}
    identity = RegionActivationID(label)
    segment = ExecutionSegmentID(label)
    rows = {name: [] for name in ('visits', 'operations', 'values', 'uses', 'transfers')}
    environment, operation_ids, visit_ids = {}, {}, []
    for value in program.values:
        if value.region == region and isinstance(value.origin, LiteralOrigin):
            occurrence = ValueOccurrence(ValueOccurrenceID(label + '.literal.' + value.id.value),
                                         value.id, identity)
            rows['values'].append(occurrence)
            environment[value.id] = occurrence.id
    previous = None
    for number, (block_id, selected) in enumerate(path):
        visit = BlockVisitID(f'{label}.{number}')
        visit_ids.append(visit)
        if previous is not None:
            source, index = previous
            rows['transfers'].append(ControlTransfer(source, index, visit))
        rows['visits'].append(BlockVisit(visit, segment, block_id))
        block = blocks[block_id]
        for formal in block.arguments:
            value = ValueOccurrence(ValueOccurrenceID(f'{label}.{number}.{formal.value}'), formal, visit)
            rows['values'].append(value)
            environment[formal] = value.id
        for operation_id in block.operations:
            operation = operations[operation_id]
            occurrence = OperationOccurrenceID(f'{label}.{number}.{operation_id.value}')
            operation_ids[operation_id] = occurrence
            rows['operations'].append(OperationOccurrence(occurrence, visit, operation_id))
            rows['uses'].extend(UseOccurrence(occurrence, use.id, environment[use.value])
                                for use in operation.uses)
            for result in operation.results:
                value = ValueOccurrence(ValueOccurrenceID(f'{label}.{number}.{result.value}'),
                                         result, occurrence)
                rows['values'].append(value)
                environment[result] = value.id
        previous = None if selected is None else (occurrence, selected)
    rows.update(activations=(RegionActivation(identity, region, point.process, point),),
                segments=(ExecutionSegment(segment, identity, thread, InitialEntry(point)),))
    return rows, identity, tuple(visit_ids), operation_ids


def _model(program, paths):
    source = MissingEvidence('hand-authored call pairing; not source/runtime identity evidence')
    run = RunID('calls')
    process = ProcessInstanceID('calls')
    thread = HostThreadInstanceID('calls')
    point = EvidencePoint(run, process, source)
    combined = {name: [] for name in ('activations', 'segments', 'visits', 'operations',
                                    'values', 'uses', 'transfers')}
    scopes = []
    for region, path, label in paths:
        rows, activation, visits, operations = _activation(program, region, path, label, point, thread)
        for name in combined:
            combined[name].extend(rows[name])
        scopes.append((activation, visits, operations))
    model = ExecutionModel(snapshot_for(program), runs=(ExecutionRun(run, source),),
        processes=(ProcessInstance(process, run, 10, source),),
        threads=(HostThreadInstance(thread, process, 11, source),),
        **{name: tuple(rows) for name, rows in combined.items()})
    return model, tuple(scopes), source


def shared_calls_execution():
    """Return (program, model, details): two calls to one body, distinct children."""
    program = shared_body_calls_program()
    model, scopes, source = _model(program, (
        (program.root, ((BlockID('caller.entry'), None),), 'caller'),
        (RegionID('callee'), ((BlockID('callee.entry'), None),), 'child.1'),
        (RegionID('callee'), ((BlockID('callee.entry'), None),), 'child.2'),
    ))
    caller_activation, caller_visits, caller_ops = scopes[0]
    callers = tuple(caller_ops[OperationID(f'call{number}')] for number in (1, 2))
    children = tuple(scope[0] for scope in scopes[1:])
    entries = tuple(scope[1][0] for scope in scopes[1:])
    completions = tuple(scope[2][OperationID('callee.done')] for scope in scopes[1:])
    links = tuple(CallActivation(CallActivationID(f'call{number}'), caller, child, entry,
                                 completion, source)
                  for number, (caller, child, entry, completion) in enumerate(
                      zip(callers, children, entries, completions, strict=True), 1))
    model = replace(model, call_activations=links)
    return program, model, {'caller': callers[0], 'callers': callers, 'children': children,
        'links': tuple(row.id for row in links), 'entries': entries, 'completions': completions,
        'caller_activation': caller_activation, 'caller_entry': caller_visits[0]}


def _invoke_program():
    caller, child = RegionID('call.parent'), RegionID('call.child')
    world = LocationID('call.world')
    parent_entry, child_entry = BlockID('call.parent.entry'), BlockID('call.child.entry')
    normal, failure = BlockID('call.parent.normal'), BlockID('call.parent.raise')
    child_normal, child_failure = BlockID('call.child.normal'), BlockID('call.child.raise')
    values, operations = [], []

    def value(name, owner, origin, kind):
        identity = ValueID(name)
        row = (StateVersionValue(identity, owner, origin, world) if kind == 'state' else
               ReferenceValue(identity, owner, origin) if kind == 'reference' else
               DataValue(identity, owner, origin, kind))
        values.append(row)
        return identity

    def arguments(block, owner, kinds):
        return tuple(value(block.value + f'.{index}', owner, BlockArgument(block, index), kind)
                     for index, kind in enumerate(kinds))

    def use(name, identity):
        row = next(row for row in values if row.id == identity)
        role = (UseRole.STATE_CONTENT if isinstance(row, StateVersionValue) else
                UseRole.REFERENCE if isinstance(row, ReferenceValue) else UseRole.DATA)
        return Use(UseID(name), identity, role)

    parent_args = arguments(parent_entry, caller, ('reference', 'state', 'builtins.bool'))
    child_args = arguments(child_entry, child, ('reference', 'state', 'builtins.bool'))
    normal_args = arguments(normal, caller, ('state', 'reference'))
    failure_args = arguments(failure, caller, ('builtins.str', 'state'))
    child_normal_args = arguments(child_normal, child, ('reference', 'state'))
    child_failure_args = arguments(child_failure, child, ('state',))
    error = value('call.child.error', child, LiteralOrigin('declared failure'), 'builtins.str')
    state_type = ValueType(ValueKind.STATE, location=world)
    normal_types = (ValueType(ValueKind.REFERENCE), state_type)
    raise_types = (state_type, ValueType(ValueKind.DATA, 'builtins.str'))
    invoke_uses = tuple(use(f'call.parent.invoke.{index}', identity)
                        for index, identity in enumerate(parent_args))
    invocation = Operation(OperationID('call.parent.invoke'), 'invoke exact child',
        (Behavior.CONTROL, Behavior.READ, Behavior.WRITE), invoke_uses,
        completions=(CompletionSignature(ExitKind.NORMAL, normal_types),
                     CompletionSignature(ExitKind.RAISE, raise_types)),
        invoke_arguments=tuple(row.id for row in invoke_uses), callee=child,
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, normal, (CompletionResult(1), CompletionResult(0))),
            CompletionSuccessor(ExitKind.RAISE, failure, (CompletionResult(1), CompletionResult(0))),
        )))
    operations.append(invocation)
    selected = use('call.child.choose.condition', child_args[2])
    forwards = tuple(use(f'call.child.choose.{index}', identity)
                     for index, identity in enumerate((*child_args[:2], child_args[1])))
    choose = Operation(OperationID('call.child.choose'), 'real child branch',
        (Behavior.CONTROL,), (selected, *forwards), effects_complete=True,
        terminator=Terminator(TerminatorKind.BRANCH, (
            Successor(child_normal, tuple(row.id for row in forwards[:2])),
            Successor(child_failure, (forwards[2].id,)),
        ), condition=selected.id))
    operations.append(choose)

    child_blocks = [Block(child_entry, child_args, (choose.id,))]
    for block, args, state_position, kind in (
        (child_normal, child_normal_args, 1, TerminatorKind.RETURN),
        (child_failure, child_failure_args, 0, TerminatorKind.RAISE),
    ):
        write_id = OperationID(block.value + '.write')
        after = value(block.value + '.after', child, OperationResult(write_id, 0), 'state')
        before = use(block.value + '.before', args[state_position])
        write = Operation(write_id, 'actual child state transition', (Behavior.READ, Behavior.WRITE),
            (before,), (after,), (StateAccess(world, before.id, AccessMode.READ_WRITE, after),),
            effects_complete=True)
        identities = (args[0], after) if kind is TerminatorKind.RETURN else (after, error)
        uses = tuple(use(block.value + f'.out.{index}', identity)
                     for index, identity in enumerate(identities))
        terminal = Operation(OperationID(block.value + '.done'), 'actual child completion',
            (Behavior.CONTROL,), uses, terminator=Terminator(kind,
                exit='normal' if kind is TerminatorKind.RETURN else 'raise',
                values=tuple(row.id for row in uses)))
        operations.extend((write, terminal))
        child_blocks.append(Block(block, args, (write.id, terminal.id)))

    parent_blocks = [Block(parent_entry, parent_args, (invocation.id,))]
    for block, args, kind in ((normal, normal_args, TerminatorKind.RETURN),
                               (failure, failure_args, TerminatorKind.RAISE)):
        identities = (args[1], args[0])
        uses = tuple(use(block.value + f'.out.{index}', identity)
                     for index, identity in enumerate(identities))
        terminal = Operation(OperationID(block.value + '.done'), 'caller actual completion',
            (Behavior.CONTROL,), uses, terminator=Terminator(kind,
                exit='normal' if kind is TerminatorKind.RETURN else 'raise',
                values=tuple(row.id for row in uses)))
        operations.append(terminal)
        parent_blocks.append(Block(block, args, (terminal.id,)))
    exits = (ExitPort('normal', ExitKind.NORMAL, normal_types),
             ExitPort('raise', ExitKind.RAISE, raise_types))
    parent_region = Region(caller, 'synchronous caller', parent_entry, tuple(parent_blocks), exits)
    child_region = Region(child, 'ordinary raising child, no BodyDrive', child_entry,
                          tuple(child_blocks), exits, parent=caller)
    return ProgramGraph(caller, (parent_region, child_region), tuple(operations), tuple(values),
                        (StateLocation(world, 'current shared call state'),))


def invoke_call_execution(*, raised=False, caller_transfer=True):
    """Actual child RETURN/RAISE; optionally leave caller post unobserved.

    Returns (program, model, details). With caller_transfer=False, no caller
    landing/formal/transfer is fabricated, while the child completion remains.
    """
    program = _invoke_program()
    index = 1 if raised else 0
    label = 'raise' if raised else 'normal'
    parent_target = BlockID('call.parent.' + label)
    caller_path = ((BlockID('call.parent.entry'), index), (parent_target, None)) if caller_transfer else (
        (BlockID('call.parent.entry'), None),)
    child_path = ((BlockID('call.child.entry'), index), (BlockID('call.child.' + label), None))
    model, scopes, source = _model(program, (
        (program.root, caller_path, 'invoke.caller'),
        (RegionID('call.child'), child_path, 'invoke.child'),
    ))
    root, root_visits, caller_ops = scopes[0]
    child, child_visits, child_ops = scopes[1]
    caller = caller_ops[OperationID('call.parent.invoke')]
    completion = child_ops[OperationID('call.child.' + label + '.done')]
    link = CallActivation(CallActivationID('invoke.call'), caller, child,
                          child_visits[0], completion, source)
    model = replace(model, call_activations=(link,))
    details = {'caller': caller, 'callers': (caller,), 'child': child, 'children': (child,),
        'link': link.id, 'links': (link.id,), 'entries': (link.entry,),
        'completions': (completion,), 'caller_activation': root, 'caller_entry': root_visits[0],
        'normal_target': BlockID('call.parent.normal'), 'raise_target': BlockID('call.parent.raise'),
        'taken_target': parent_target if caller_transfer else None, 'caller_transfer': caller_transfer}
    return program, model, details


__all__ = ['shared_calls_execution', 'invoke_call_execution']
