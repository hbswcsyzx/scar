"""A real extraction interface implemented inside one or two called regions.

The parent OutcomeAdapter declares the extraction interface. Child operations
are implementation frontiers with original inputs, own N/R and exit Uses; no
child lookup/acquisition scope or duplicate extraction authority is invented.
"""
from dataclasses import replace

from scar.ir.program.ids import BlockID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, CompletionResult, CompletionSignature,
    CompletionSuccessor, ExitKind, ExitPort, InvokeLiteralResult, Operation,
    ProtocolValue, ReferenceValue, Region, StateVersionValue, Terminator,
    TerminatorKind, Use, UseRole, ValueKind, value_type,
)
from scar.ir.program.protocols import OwnedUse
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.program_await_outcome_graphs import completion_adapter_program
from tests.fixtures.program_protocol_graphs import _scope


def _use(name, value):
    return Use(UseID(name), value.id,
        UseRole.STATE_CONTENT if type(value) is StateVersionValue else
        UseRole.PROTOCOL if type(value) is ProtocolValue else UseRole.REFERENCE)


def await_final_region_program(*, zero_cut=True, depth=1, final_adapters=True,
                               wrong_child_exit=False):
    """Return ``(program, details)`` for an actual child extraction N/R path.

    At depth one the parent extraction call enters E, whose primitive INVOKE
    feeds the actual E RETURN/RAISE. At depth two E calls a second real helper
    containing that primitive. Both helpers have RAISE edge zero and NORMAL
    edge one. An independent forward of the original packet occupies landing
    formal zero; each own payload slot zero occupies formal one.

    ``wrong_child_exit`` retains all types, operands and CFG, but makes the
    leaf's RAISE return its forwarded input packet instead of its own R result.
    The mutation has no CleanupReplace or callback to declare an override.
    """
    if any(type(flag) is not bool for flag in
           (zero_cut, final_adapters, wrong_child_exit)):
        raise TypeError('final-region switches require exact bools')
    if type(depth) is not int or depth not in (1, 2):
        raise ValueError('the supplied implementation has one or two regions')
    graph, original = completion_adapter_program(
        zero_cut=zero_cut, final_adapters=final_adapters)
    values = {value.id: value for value in graph.values}
    parent = original['extract']
    actuals = {use.id: use for use in parent.uses}
    inputs = tuple(values[actuals[identity].value] for identity in parent.invoke_arguments)
    if (len(inputs) != 3 or type(inputs[0]) is not ProtocolValue
            or any(type(value) is not StateVersionValue for value in inputs[1:])):
        raise AssertionError('the original extraction interface needs packet and both states')
    signatures = {signature.kind: signature for signature in parent.completions}
    if set(signatures) != {ExitKind.NORMAL, ExitKind.RAISE}:
        raise AssertionError('the genuine extractor keeps its two actual completion kinds')
    regions, operations, added_values, scopes = [], [], [], []
    records = {}

    def make_region(level, lexical_parent):
        name = f'await.final.implementation.{level}'
        identity, entry_id = RegionID(name), BlockID(name + '.entry')
        formals = tuple(replace(value, id=ValueID(f'{name}.input.{slot}'),
            region=identity, origin=BlockArgument(entry_id, slot))
            for slot, value in enumerate(inputs))
        added_values.extend(formals)
        nested = make_region(level + 1, identity) if level < depth else None
        operation_id = OperationID(name + ('.call' if nested is not None else '.extract'))
        arguments = tuple(_use(f'{operation_id.value}.argument.{slot}', value)
                          for slot, value in enumerate(formals))
        forwards, edges, landing_blocks, terminal_map, own_results = [], [], {}, {}, {}
        result_ports, terminal_uses, forwarded_packets, paths = {}, {}, {}, {}
        landing_values = {}
        for edge_number, kind in enumerate((ExitKind.RAISE, ExitKind.NORMAL)):
            label = 'raise' if kind is ExitKind.RAISE else 'normal'
            landing_id = BlockID(f'{name}.{label}')
            preserved = replace(formals[0], id=ValueID(f'{name}.{label}.original.packet'),
                                origin=BlockArgument(landing_id, 0))
            produced = []
            for slot, type_ in enumerate(signatures[kind].types):
                value_id = ValueID(f'{name}.{label}.result.{slot}')
                origin = BlockArgument(landing_id, slot + 1)
                if type_.kind is ValueKind.REFERENCE:
                    value = ReferenceValue(value_id, identity, origin)
                elif type_.kind is ValueKind.STATE:
                    value = StateVersionValue(value_id, identity, origin, type_.location)
                else:
                    value = ProtocolValue(value_id, identity, origin, type_.protocol)
                produced.append(value)
            produced = tuple(produced)
            added_values.extend((preserved, *produced))
            forward = _use(f'{operation_id.value}.{label}.forward.packet', formals[0])
            forwards.append(forward)
            edge = ControlEdgeReference(operation_id, edge_number)
            edges.append(CompletionSuccessor(kind, landing_id,
                (forward.id, *(CompletionResult(slot) for slot in range(len(produced))))))
            actual_outputs = (preserved, *produced[1:]) if (
                wrong_child_exit and level == depth and kind is ExitKind.RAISE) else produced
            output_uses = tuple(_use(f'{name}.{label}.exit.use.{slot}', value)
                                for slot, value in enumerate(actual_outputs))
            terminal = Operation(OperationID(f'{name}.{label}.exit'),
                'the implementation region actual completion', (Behavior.CONTROL,),
                output_uses, effects_complete=True,
                terminator=Terminator(TerminatorKind.RAISE if kind is ExitKind.RAISE
                    else TerminatorKind.RETURN, exit=label,
                    values=tuple(use.id for use in output_uses)))
            block = Block(landing_id, (preserved.id, *(value.id for value in produced)),
                          (terminal.id,))
            operations.append(terminal)
            landing_blocks[kind], terminal_map[kind] = block, terminal
            result_ports[kind] = tuple(InvokeLiteralResult(edge, CompletionResult(slot))
                                       for slot in range(len(produced)))
            own_results[kind] = result_ports[kind][0]
            terminal_uses[kind] = tuple(OwnedUse(terminal.id, use.id) for use in output_uses)
            forwarded_packets[kind] = preserved
            landing_values[kind] = produced
            paths[kind] = ((entry_id, edge_number), (landing_id, None))
        operation = Operation(operation_id,
            'called implementation' if nested is not None else 'primitive extraction implementation frontier',
            (Behavior.CONTROL,), (*arguments, *forwards), effects_complete=False,
            callee=nested, invoke_arguments=tuple(use.id for use in arguments),
            completions=tuple(CompletionSignature(kind, signatures[kind].types)
                              for kind in (ExitKind.NORMAL, ExitKind.RAISE)),
            terminator=Terminator(TerminatorKind.INVOKE, tuple(edges)))
        entry = Block(entry_id, tuple(value.id for value in formals), (operation.id,))
        blocks = (entry, *(landing_blocks[kind] for kind in (ExitKind.RAISE, ExitKind.NORMAL)))
        region = Region(identity, 'actual final-extraction implementation', entry_id,
            blocks, tuple(ExitPort('raise' if kind is ExitKind.RAISE else 'normal',
                kind, signatures[kind].types) for kind in (ExitKind.NORMAL, ExitKind.RAISE)),
            parent=lexical_parent)
        regions.append(region)
        operations.append(operation)
        scopes.append(_scope(identity, blocks))
        records[level] = {
            'region': region, 'entry': entry, 'formals': formals, 'operation': operation,
            'input': OwnedUse(operation.id, arguments[0].id),
            'arguments': tuple(OwnedUse(operation.id, use.id) for use in arguments),
            'own_results': own_results, 'result_ports': result_ports,
            'landings': landing_blocks, 'landing_values': landing_values,
            'forwarded_packets': forwarded_packets,
            'terminals': terminal_map, 'terminal_uses': terminal_uses,
            'terminal_payloads': {kind: uses[0] for kind, uses in terminal_uses.items()},
            'paths': paths,
        }
        return identity

    implementation = make_region(1, original['caller'].id)
    parent_call = replace(parent, callee=implementation)
    graph = replace(graph, regions=(*graph.regions, *regions),
        operations=tuple(parent_call if operation.id == parent.id else operation
                         for operation in graph.operations) + tuple(operations),
        values=(*graph.values, *added_values),
        control_scopes=(*graph.control_scopes, *scopes))
    advance = next(operation for operation in graph.operations
                   if operation.id == original['advance_operation'])
    raised = tuple((number, edge) for number, edge in enumerate(advance.terminator.successors)
                   if edge.kind is ExitKind.RAISE)
    if len(raised) != 1:
        raise AssertionError('the source keeps exactly its actual RAISE completion')
    number, _ = raised[0]
    signature = next(row for row in advance.completions if row.kind is ExitKind.RAISE)
    slots = tuple(slot for slot, type_ in enumerate(signature.types)
                  if type_ == value_type(inputs[0]))
    if len(slots) != 1:
        raise AssertionError('the source packet needs its one logical completion slot')
    root_source = InvokeLiteralResult(ControlEdgeReference(advance.id, number),
                                     CompletionResult(slots[0]))
    ordered = tuple(records[level] for level in range(1, depth + 1))
    return graph, {**original, 'extract': parent_call, 'parent_call': parent_call,
        'original_extract': parent, 'root_source': root_source,
        'semantic_source': original['final_rows'][0].contract.input,
        'stage_records': ordered, 'stage_regions': tuple(row['region'] for row in ordered),
        'stage_operations': tuple(row['operation'] for row in ordered),
        'primitive': ordered[-1]['operation'], 'depth': depth,
        'wrong_child_exit': wrong_child_exit}


__all__ = ['await_final_region_program']
