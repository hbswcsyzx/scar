"""Original zero/two-cut completion and final-consumer declaration variants.

The constructors, packets, driver calls and extraction operation stay in the
canonical graph. Optional semantic rows do not select their original Uses.
These supplied graphs do not establish native behavior or runtime identity.
"""
from dataclasses import replace

from scar.ir.program.lifecycle import DriveOutcomeRef
from scar.ir.program.model import CompletionResult, ExitKind, InvokeLiteralResult
from scar.ir.program.protocol_connections import ProtocolOperationRef
from scar.ir.program.protocols import DriveResult, OutcomeAdapter, OutcomeAdapterRule
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.program_await_resume_graphs import await_resume_program, with_final_adapter


def await_outcome_program(*, zero_cut=True, final_adapters=True, wrong_final=False):
    """Return ``(graph, details)`` using only original producer/result ports.

    ``final_adapters=False`` removes the complete final-adapter declarations
    and their receipts. ``wrong_final`` changes only the original RETURN's
    payload Use to another available Reference from this caller's entry.
    """
    if any(type(value) is not bool for value in (zero_cut, final_adapters, wrong_final)):
        raise TypeError('outcome fixture switches require exact bools')
    base, details = await_resume_program(zero_cut=zero_cut)
    graph, final_rows = with_final_adapter(base, details)
    final_sites = tuple(ProtocolOperationRef(row.scope, row.clause, row.operation, row.slot)
                        for row in final_rows)
    if not final_adapters:
        graph = replace(graph,
            protocol_operations=tuple(row for row in graph.protocol_operations if row not in final_rows),
            protocol_result_consumers=tuple(receipt for receipt in graph.protocol_result_consumers
                                            if receipt.site not in final_sites))

    last = details['drivers'][-1]
    outcome = DriveOutcomeRef(last['drive'].operation, last['outcome_source'])
    payload = DriveResult(outcome, 0)
    conversion_rows = tuple(row for row in graph.protocol_operations
        if type(row.contract) is OutcomeAdapter
        and row.contract.rule in (OutcomeAdapterRule.GENERATOR_RETURN_TO_STOP_ITERATION,
                                  OutcomeAdapterRule.COROUTINE_RETURN_TO_STOP_ITERATION)
        and row.contract.input == payload)
    producer_ids = {row.operation for row in conversion_rows}
    if len(producer_ids) != 1:
        raise AssertionError('the exact BodyReturn needs one original conversion operation')
    operations = {operation.id: operation for operation in graph.operations}
    conversion = operations[next(iter(producer_ids))]
    source_row = next(row for row in details['get_rows']
        if details['get'].terminator.successors[row.slot].kind is ExitKind.NORMAL)
    source = ProtocolOperationRef(source_row.scope, source_row.clause, source_row.operation, source_row.slot)
    extractor = details['extract']
    final = details['final']
    if wrong_final:
        payload_use = final.terminator.values[0]
        final = replace(final, uses=tuple(replace(use, value=details['sent_value'])
            if use.id == payload_use else use for use in final.uses))
        graph = replace(graph, operations=tuple(final if operation.id == final.id else operation
                                                for operation in graph.operations))
    conversion_ports = tuple(InvokeLiteralResult(ControlEdgeReference(conversion.id, index),
                                                CompletionResult(0))
                             for index in range(len(conversion.terminator.successors)))
    extraction_ports = tuple(InvokeLiteralResult(ControlEdgeReference(extractor.id, index),
                                                CompletionResult(0))
                             for index in range(len(extractor.terminator.successors)))
    return graph, {**details, 'final': final, 'source': source, 'drive_outcome': outcome,
        'payload': payload, 'advance_operation': last['caller_call'].id,
        'conversion': conversion, 'conversion_rows': conversion_rows,
        'conversion_ports': conversion_ports, 'extraction_ports': extraction_ports,
        'final_rows': final_rows, 'final_sites': final_sites,
        'final_adapters': final_adapters, 'wrong_final': wrong_final,
        'original_final': details['final'], 'original_final_value': details['final_value']}


__all__ = ['await_outcome_program']


def completion_adapter_program(*, zero_cut=True, final_adapters=True, producer_adapter=True):
    """Pair original conversion rows with accurate receipts, then omit both.

    NORMAL's Reference is consumed by the original packet's exception Use.
    RAISE's whole packet is consumed by its actual host RAISE. Neither receipt
    declares a Reference-to-packet copy or selects the final extractor.
    """
    from scar.ir.program.model import OperationResult, TerminatorKind
    from scar.ir.program.protocol_connections import ProtocolResultConsumers
    from scar.ir.program.protocols import HostTerminal, OwnedUse

    if type(producer_adapter) is not bool:
        raise TypeError('producer_adapter must be an exact bool')
    graph, details = await_outcome_program(zero_cut=zero_cut, final_adapters=final_adapters)
    operations = {row.id: row for row in graph.operations}
    blocks = {block.id: block for region in graph.regions for block in region.blocks}
    values = {row.id: row for row in graph.values}
    receipts, sites = [], []
    for row in details['conversion_rows']:
        site = ProtocolOperationRef(row.scope, row.clause, row.operation, row.slot)
        sites.append(site)
        operation = operations[row.operation]
        edge = operation.terminator.successors[row.slot]
        if edge.kind is ExitKind.NORMAL:
            payload, = tuple(formal for actual, formal in zip(edge.arguments, blocks[edge.block].arguments)
                             if type(actual) is CompletionResult
                             and actual.index == row.contract.output.result.index)
            targets = []
            for packet in graph.exception_packets:
                origin = values[packet.value].origin
                if type(origin) is not OperationResult:
                    continue
                pack = operations[origin.operation]
                component = next(use for use in pack.uses if use.id == packet.exception)
                if component.value == payload:
                    targets.append(OwnedUse(pack.id, component.id))
            if len(targets) != 1:
                raise AssertionError('the conversion NORMAL needs its exact packet exception component')
            target, = targets
        else:
            terminal = operations[blocks[edge.block].operations[-1]]
            if terminal.terminator.kind is not TerminatorKind.RAISE:
                raise AssertionError('this original constructor failure must keep its actual RAISE')
            target = HostTerminal(terminal.id)
        receipts.append(ProtocolResultConsumers(site, (target,)))
    graph = replace(graph, protocol_result_consumers=(*graph.protocol_result_consumers, *receipts))
    if not producer_adapter:
        graph = replace(graph,
            protocol_operations=tuple(row for row in graph.protocol_operations
                                      if row not in details['conversion_rows']),
            protocol_result_consumers=tuple(receipt for receipt in graph.protocol_result_consumers
                                            if receipt.site not in sites))
    return graph, {**details, 'producer_adapter': producer_adapter,
                   'conversion_sites': tuple(sites), 'conversion_receipts': tuple(receipts)}


__all__.append('completion_adapter_program')
