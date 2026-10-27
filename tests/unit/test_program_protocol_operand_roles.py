"""Owned input Uses and owned edge forwards perform different operations."""
from dataclasses import replace

from scar.ir.program.ids import UseID, ValueID
from scar.ir.program.model import BlockArgument, ReferenceValue, Use
from scar.ir.program.protocols import ProtocolCall, ProtocolCallRule, RequestProcessing, OutcomeAdapter
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_protocol_graphs import generator_protocol_program, request_processing_program


def _codes(graph):
    require_valid(replace(graph, protocol_scopes=(), protocol_operations=()))
    return {issue.code for issue in validate(graph)}


def test_same_value_edge_forward_is_not_the_processing_calls_raw_argument():
    graph, details = generator_protocol_program(target='value')
    operation = next(op for op in graph.operations if op.id == details['processing'])
    actual = next(use for use in operation.uses if use.id == details['raw_use'])
    forward = next(use for use in operation.uses if use.value == actual.value and use.id not in operation.invoke_arguments)
    changed = replace(graph, protocol_operations=tuple(replace(row,
        contract=replace(row.contract, raw_use=forward.id))
        if row.operation == operation.id and isinstance(row.contract, RequestProcessing) else row
        for row in graph.protocol_operations))
    assert 'protocol_operand_role' in _codes(changed)


def test_an_ordinary_producer_cannot_be_labeled_as_an_actual_protocol_call():
    graph, details = request_processing_program()
    row = graph.protocol_operations[0]
    producer = next(op for op in graph.operations if op.id == row.operation)
    contract = ProtocolCall(producer.uses[1].id, (), row.contract.result, (),
                            ProtocolCallRule.EXCEPTION_CONSTRUCTOR)
    changed = replace(graph, protocol_operations=(replace(row, contract=contract),))
    assert 'protocol_call_shape' in _codes(changed)


def test_adapter_edge_forward_is_not_the_exception_constructors_input_argument():
    graph, details = generator_protocol_program(target='value')
    row = next(row for row in graph.protocol_operations if isinstance(row.contract, OutcomeAdapter))
    operation = next(op for op in graph.operations if op.id == row.operation)
    original = next(use for use in operation.uses if use.id == row.contract.input_use)
    edge = operation.terminator.successors[0]
    region = next(region for region in graph.regions if any(block.id == edge.block for block in region.blocks))
    block = next(block for block in region.blocks if block.id == edge.block)
    forward = Use(UseID('adapter.forward.only'), original.value, original.role)
    formal = ReferenceValue(ValueID('adapter.forwarded.payload'), region.id,
                             BlockArgument(block.id, len(block.arguments)))
    operation = replace(operation, uses=(*operation.uses, forward), terminator=replace(operation.terminator,
        successors=(replace(edge, arguments=(*edge.arguments, forward.id)), *operation.terminator.successors[1:])))
    changed = replace(graph, values=(*graph.values, formal),
        operations=tuple(operation if op.id == operation.id else op for op in graph.operations),
        regions=tuple(replace(item, blocks=tuple(replace(item_block,
            arguments=(*item_block.arguments, formal.id)) if item_block.id == block.id else item_block
            for item_block in item.blocks)) if item.id == region.id else item for item in graph.regions),
        protocol_operations=tuple(replace(item, contract=replace(item.contract, input_use=forward.id))
            if item == row else item for item in graph.protocol_operations))
    assert 'protocol_operand_role' in _codes(changed)
