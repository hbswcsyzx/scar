"""Original packet-forwarding calls inside a supplied await result path.

H only forwards packet/world/context. The original extractor, its N/R edges,
and the final targets remain separate operations. These declarations establish
neither native exception semantics nor a captured invocation.
"""
from dataclasses import replace

from scar.ir.program.ids import BlockID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, CompletionResult, ExitKind, ExitPort,
    InvokeLiteralResult, Operation, OperationResult, ProtocolValue, Region,
    StateVersionValue, Terminator, TerminatorKind, Use, UseRole, value_type,
)
from scar.ir.program.protocols import HostTerminal, OwnedUse
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.program_await_outcome_graphs import completion_adapter_program
from tests.fixtures.program_protocol_graphs import _scope


def _uses(name, values):
    return tuple(Use(UseID(f'{name}.use.{slot}'), value.id,
        UseRole.STATE_CONTENT if type(value) is StateVersionValue else UseRole.PROTOCOL)
        for slot, value in enumerate(values))


def _call(name, caller, callee, values):
    identity = OperationID(name)
    actuals = _uses(name, values)
    outputs = tuple(replace(value, id=ValueID(f'{name}.result.{slot}'), region=caller,
        origin=OperationResult(identity, slot)) for slot, value in enumerate(values))
    operation = Operation(identity, 'declared synchronous forwarding call',
        (Behavior.CONTROL,), actuals, tuple(value.id for value in outputs),
        effects_complete=True, callee=callee,
        call_arguments=tuple(use.id for use in actuals))
    return operation, outputs


def await_consumer_call_program(*, zero_cut=True, depth=1, final_adapters=True):
    """Return ``(program, details)`` with one or two real forwarding callees.

    The first call consumes the exact advance RAISE packet and the current two
    state versions. Its own outputs, rather than the old caller operands, feed
    the unchanged extraction UseIDs. Packet call results are output carriers;
    no local ExceptionPacketDefinition is fabricated for these call results.
    """
    if type(zero_cut) is not bool or type(final_adapters) is not bool:
        raise TypeError('await consumer switches require exact bools')
    if type(depth) is not int or depth not in (1, 2):
        raise ValueError('the supplied call path has one or two helpers')
    graph, original = completion_adapter_program(
        zero_cut=zero_cut, final_adapters=final_adapters)
    operations = {operation.id: operation for operation in graph.operations}
    values = {value.id: value for value in graph.values}
    extractor = original['extract']
    owned = {use.id: use for use in extractor.uses}
    incoming = tuple(values[owned[identity].value] for identity in extractor.invoke_arguments)
    if (len(incoming) != 3 or type(incoming[0]) is not ProtocolValue
            or any(type(value) is not StateVersionValue for value in incoming[1:])):
        raise AssertionError('the original extractor must consume packet/world/context')
    types = tuple(value_type(value) for value in incoming)
    extra_regions, extra_operations, extra_values, extra_scopes = [], [], [], []
    helper_records = {}

    def helper(level, parent):
        name = f'await.consumer.helper.{level}'
        identity, entry = RegionID(name), BlockID(name + '.entry')
        formals = tuple(replace(value, id=ValueID(f'{name}.input.{slot}'),
            region=identity, origin=BlockArgument(entry, slot))
            for slot, value in enumerate(incoming))
        extra_values.extend(formals)
        local_operations, returned, nested_call = [], formals, None
        if level < depth:
            nested = helper(level + 1, identity)
            nested_call, returned = _call(name + '.call', identity, nested, formals)
            local_operations.append(nested_call)
            extra_values.extend(returned)
        return_uses = _uses(name + '.return', returned)
        terminal = Operation(OperationID(name + '.return'), 'the original helper RETURN',
            (Behavior.CONTROL,), return_uses, effects_complete=True,
            terminator=Terminator(TerminatorKind.RETURN, exit='normal',
                values=tuple(use.id for use in return_uses)))
        local_operations.append(terminal)
        block = Block(entry, tuple(value.id for value in formals),
                      tuple(operation.id for operation in local_operations))
        region = Region(identity, 'packet and state forwarding helper', entry,
            (block,), (ExitPort('normal', ExitKind.NORMAL, types),), parent=parent)
        extra_regions.append(region)
        extra_operations.extend(local_operations)
        extra_scopes.append(_scope(identity, (block,)))
        helper_records[level] = {
            'region': region, 'formals': formals, 'terminal': terminal,
            'nested_call': nested_call,
            'exit_uses': tuple(OwnedUse(terminal.id, use.id) for use in return_uses),
        }
        return identity

    caller = original['caller']
    first_callee = helper(1, caller.id)
    first_call, outputs = _call('await.consumer.forward', caller.id, first_callee, incoming)
    replacements = {identity: value.id for identity, value in zip(extractor.invoke_arguments, outputs)}
    extractor = replace(extractor, uses=tuple(replace(use, value=replacements[use.id])
        if use.id in replacements else use for use in extractor.uses))
    caller = replace(caller, blocks=tuple(replace(block, operations=tuple(
        item for identity in block.operations
        for item in ((first_call.id, identity) if identity == extractor.id else (identity,))))
        if extractor.id in block.operations else block for block in caller.blocks))
    graph = replace(graph,
        regions=tuple(caller if region.id == caller.id else region for region in graph.regions)
                + tuple(extra_regions),
        operations=tuple(extractor if operation.id == extractor.id else operation
            for operation in graph.operations) + (first_call, *extra_operations),
        values=(*graph.values, *outputs, *extra_values),
        control_scopes=(*graph.control_scopes, *extra_scopes))

    advance = operations[original['advance_operation']]
    raised = tuple((number, edge) for number, edge in enumerate(advance.terminator.successors)
                   if edge.kind is ExitKind.RAISE)
    if len(raised) != 1:
        raise AssertionError('the exact advance must keep its original RAISE completion')
    number, _ = raised[0]
    signature = next(row for row in advance.completions if row.kind is ExitKind.RAISE)
    payload_slots = tuple(slot for slot, type_ in enumerate(signature.types) if type_ == types[0])
    if len(payload_slots) != 1:
        raise AssertionError('the advance needs one original whole-packet result slot')
    root_source = InvokeLiteralResult(ControlEdgeReference(advance.id, number),
                                     CompletionResult(payload_slots[0]))
    calls = (first_call, *(helper_records[level]['nested_call']
                           for level in range(1, depth)))
    records = tuple(helper_records[level] for level in range(1, depth + 1))
    blocks = {block.id: block for region in graph.regions for block in region.blocks}
    all_operations = {operation.id: operation for operation in graph.operations}
    extraction_targets = {
        ControlEdgeReference(extractor.id, number): HostTerminal(
            all_operations[blocks[edge.block].operations[-1]].id)
        for number, edge in enumerate(extractor.terminator.successors)
    }
    return graph, {**original, 'caller': caller, 'extract': extractor,
        'root_source': root_source, 'original_extract': original['extract'],
        'helper_calls': calls, 'helper_records': records,
        'helper_regions': tuple(record['region'] for record in records),
        'helper_inputs': tuple(tuple(OwnedUse(call.id, identity) for identity in call.call_arguments)
                               for call in calls),
        'helper_exit_uses': tuple(record['exit_uses'] for record in records),
        'forwarded_values': outputs, 'extraction_targets': extraction_targets, 'depth': depth}


__all__ = ['await_consumer_call_program']
