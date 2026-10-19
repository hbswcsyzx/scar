"""Two real incoming tuples carry the same iterator and distinct state ports."""
from dataclasses import replace

from scar.ir.program.ids import BlockID, OperationID, ValueID
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, DataValue, StateVersionValue, Successor,
    Terminator, TerminatorKind, UseRole, ValueKind, ValueType,
)
from scar.ir.program.protocol_connections import ProtocolCallInputCase
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.program_await_pipeline_graphs import await_self_pipeline_program
from tests.fixtures.program_driver_graphs import REFERENCE, _Builder, _use


def await_case_program(*, attach_link=True):
    graph, details = await_self_pipeline_program(attach_link=attach_link)
    factory = next(region for region in graph.regions if region.id == graph.root)
    entry = next(block for block in factory.blocks if block.id == factory.entry)
    old = next(block for block in factory.blocks if block.id == BlockID('factory.awaitable'))
    values = {value.id: value for value in graph.values}
    domains = tuple(values[value].location for value in old.arguments[1:])
    types = (REFERENCE, *(ValueType(ValueKind.STATE, location=domain) for domain in domains))
    builder = _Builder(factory.id.value, domains)
    arms = tuple(builder.formals(f'await.case.arm.{index}', types) for index in range(2))
    merged = builder.formals('await.case.merge', types)
    condition = DataValue(ValueID('await.case.condition'), factory.id,
        BlockArgument(entry.id, len(entry.arguments)), 'builtins.bool')
    condition_use = replace(_use('await.case.branch.condition', condition.id), role=UseRole.DATA)
    copies = tuple(tuple(_use(f'await.case.branch.copy.{arm}.{index}', value, state=index > 0)
                         for index, value in enumerate(old.arguments)) for arm in range(2))
    branch = builder.add('await.case.branch', (condition_use, *copies[0], *copies[1]), effects_complete=True,
        terminator=Terminator(TerminatorKind.BRANCH,
            tuple(Successor(BlockID(f'await.case.arm.{index}'), tuple(use.id for use in copies[index]))
                  for index in range(2)), condition=condition_use.id))
    jumps = []
    for index, arguments in enumerate(arms):
        uses = tuple(_use(f'await.case.jump.{index}.{number}', value, state=number > 0)
                     for number, value in enumerate(arguments))
        jump = builder.add(f'await.case.jump.{index}', uses, effects_complete=True,
            terminator=Terminator(TerminatorKind.JUMP,
                (Successor(BlockID('await.case.merge'), tuple(use.id for use in uses)),)))
        jumps.append(jump)
        builder.block(f'await.case.arm.{index}', arguments, (jump,))
    remap = dict(zip(old.arguments, merged, strict=True))
    call = replace(details['call'], uses=tuple(replace(use, value=remap.get(use.value, use.value))
                                             for use in details['call'].uses))
    builder.block('await.case.merge', merged, (call,))
    factory = replace(factory, blocks=tuple(
        replace(block, arguments=(*block.arguments, condition.id)) if block.id == entry.id else
        replace(block, operations=(branch.id,)) if block.id == old.id else block
        for block in factory.blocks) + tuple(builder.blocks))
    guards = tuple(ControlEdgeReference(jump.id, 0) for jump in jumps)
    attachments = tuple(replace(row, cases=tuple(replace(row.cases[0], guard=guard)
                                                for guard in guards))
                        if row.site.operation == call.id else row for row in graph.protocol_call_inputs)
    graph = replace(graph,
        regions=tuple(factory if region.id == factory.id else region for region in graph.regions),
        operations=tuple(call if op.id == call.id else op for op in graph.operations) + tuple(builder.operations),
        values=(*graph.values, condition, *builder.values),
        control_scopes=tuple(replace(scope, blocks=tuple(block.id for block in factory.blocks))
                             if scope.region == factory.id else scope for scope in graph.control_scopes),
        protocol_call_inputs=attachments)
    return graph, {**details, 'call': call, 'branch': branch,
                   'guards': guards, 'arms': arms, 'merged': merged, 'jumps': tuple(jumps)}
