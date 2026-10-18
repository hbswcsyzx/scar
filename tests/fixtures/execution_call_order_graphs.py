"""Finite nested/recursive host call declarations, never native recovery."""
from dataclasses import replace

from scar.ir.execution.calls import CallActivation
from scar.ir.execution.ids import CallActivationID
from scar.ir.program.ids import BlockID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, DataValue, ExitKind, ExitPort, LiteralOrigin,
    Operation, ProgramGraph, Region, Successor, Terminator, TerminatorKind, Use,
)
from tests.fixtures.execution_call_graphs import _model


def nested_call_order_execution(*, recursive=False):
    """Return program/model/details for three frames, including a real base case."""
    if recursive:
        owner = RegionID('host.recursive')
        entry, base, step = (BlockID('host.recursive.' + name) for name in ('entry', 'base', 'step'))
        condition = DataValue(ValueID('host.condition'), owner, BlockArgument(entry, 0), 'builtins.bool')
        false = DataValue(ValueID('host.false'), owner, LiteralOrigin(False), 'builtins.bool')
        choose_use = Use(UseID('host.choose'), condition.id)
        call_use = Use(UseID('host.recur'), false.id)
        choose = Operation(OperationID('host.choose'), 'select recursive or base branch', (Behavior.CONTROL,),
            (choose_use,), effects_complete=True, terminator=Terminator(TerminatorKind.BRANCH,
                (Successor(step, ()), Successor(base, ())), condition=choose_use.id))
        call = Operation(OperationID('host.recur'), 'recursive synchronous call', (Behavior.CONTROL,),
            (call_use,), callee=owner, call_arguments=(call_use.id,))
        done = Operation(OperationID('host.outer.return'), 'return after inner activation',
            (Behavior.CONTROL,), terminator=Terminator(TerminatorKind.RETURN, exit='normal'))
        leaf = Operation(OperationID('host.base.return'), 'actual recursive base case',
            (Behavior.CONTROL,), terminator=Terminator(TerminatorKind.RETURN, exit='normal'))
        region = Region(owner, 'finite recursive call body', entry, (
            Block(entry, (condition.id,), (choose.id,)), Block(step, (), (call.id, done.id)),
            Block(base, (), (leaf.id,))), (ExitPort('normal', ExitKind.NORMAL, ()),))
        program = ProgramGraph(owner, (region,), (choose, call, done, leaf), (condition, false))
        paths = ((owner, ((entry, 0), (step, None)), 'host.outer'),
                 (owner, ((entry, 0), (step, None)), 'host.middle'),
                 (owner, ((entry, 1), (base, None)), 'host.leaf'))
        calls, returns = (call.id, call.id), (done.id, done.id, leaf.id)
    else:
        regions, operations, paths, calls, returns = [], [], [], [], []
        for number in range(3):
            owner = RegionID(f'host.level.{number}')
            block = BlockID(f'host.level.{number}.entry')
            body = []
            if number < 2:
                call = Operation(OperationID(f'host.call.{number}'), 'nested synchronous call',
                    (Behavior.CONTROL,), callee=RegionID(f'host.level.{number + 1}'))
                operations.append(call)
                body.append(call.id)
                calls.append(call.id)
            done = Operation(OperationID(f'host.return.{number}'), 'return this activation',
                (Behavior.CONTROL,), terminator=Terminator(TerminatorKind.RETURN, exit='normal'))
            operations.append(done)
            body.append(done.id)
            returns.append(done.id)
            regions.append(Region(owner, 'nested host frame', block, (Block(block, (), tuple(body)),),
                (ExitPort('normal', ExitKind.NORMAL, ()),),
                parent=None if number == 0 else RegionID(f'host.level.{number - 1}')))
            paths.append((owner, ((block, None),), f'host.frame.{number}'))
        program = ProgramGraph(regions[0].id, tuple(regions), tuple(operations), ())
    model, frames, source = _model(program, paths)
    links = tuple(CallActivation(CallActivationID(f'host.nested.{index}'),
        frames[index][2][calls[index]], frames[index + 1][0], frames[index + 1][1][0],
        frames[index + 1][2][returns[index + 1]], source) for index in range(2))
    model = replace(model, call_activations=links)
    return program, model, {'calls': tuple(row.caller for row in links),
        'returns': tuple(frame[2][identity] for frame, identity in zip(frames, returns, strict=True)),
        'entries': tuple(frame[1][0] for frame in frames), 'activations': tuple(frame[0] for frame in frames)}


__all__ = ['nested_call_order_execution']
