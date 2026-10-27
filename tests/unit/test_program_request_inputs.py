"""The raw pack and a separately passed input must share their original call route."""
from dataclasses import replace

import pytest

from scar.ir.program.control import ProtocolValueKind
from scar.ir.program.drivers import RawRequestKind
from scar.ir.program.ids import OperationID, UseID, ValueID
from scar.ir.program.model import LiteralOrigin, ProtocolValue, ReferenceValue, Use, UseRole
from scar.ir.program.protocols import OwnedUse, ReferenceIsNoneCondition
from scar.ir.program.queries import ProgramIndex
from tests.fixtures.program_generator_admission_graphs import generator_admission_program
from tests.fixtures.program_input_origin_graphs import input_origin_program


@pytest.mark.parametrize('send_none', (True, False))
def test_raw_operand_and_separate_is_none_input_join_through_the_same_actual_formal_call(send_none):
    graph, details = generator_admission_program(kind=RawRequestKind.SEND, send_none=send_none)
    index = ProgramIndex(graph)
    row = next(row for row in graph.protocol_operations
               if type(getattr(row.contract, 'subject', None)) is ReferenceIsNoneCondition)
    caller = index.operations[details['call']]
    raw_use = next(use for use in caller.uses if use.id in caller.invoke_arguments
                  and use.value == details['raw'])
    report = index.request_input_binding(OwnedUse(caller.id, raw_use.id),
        OwnedUse(row.operation, row.contract.subject.input_use), budget=50000)
    assert len(report['bindings']) == 1
    binding, = report['bindings']
    assert binding['declared_operand_is_none'] is send_none
    assert binding['definition'].kind is RawRequestKind.SEND
    assert binding['raw_consumer_forward']['actual'] is raw_use
    assert binding['raw_consumer_forward']['formal'].id != raw_use.value
    assert binding['input'].operation == row.operation
    assert binding['caller_context'][-1][0] == caller.id
    assert binding['operand'].id != row.contract.subject.input_use
    assert report['transformation_authorized'] is report['source_runtime_verified'] is False


def _two_input_consumers(graph):
    """Expose each middle actual as a real root operation, with no extra producers."""
    calls = [op for op in graph.operations if op.id in (
        OperationID('inputs.call.none'), OperationID('inputs.call.value'))]
    consumers = []
    from scar.ir.program.model import Behavior, Operation
    for number, call in enumerate(calls):
        payload = next(use for use in call.uses if use.id == call.call_arguments[1])
        consumer = Operation(OperationID(f'request.observe.{number}'), 'an original input observer',
            (Behavior.COMPUTE,), (Use(UseID(f'request.observe.{number}.input'), payload.value, payload.role),),
            effects_complete=True)
        consumers.append(consumer)
    root = next(region for region in graph.regions if region.id == graph.root)
    block = next(block for block in root.blocks if block.id == root.entry)
    changed = replace(graph, operations=(*graph.operations, *consumers),
        regions=tuple(replace(region, blocks=tuple(replace(item,
            operations=(*item.operations[:-1], *(op.id for op in consumers), item.operations[-1]))
            if item.id == block.id else item for item in region.blocks)) if region.id == root.id else region
            for region in graph.regions))
    return changed, calls, consumers


def test_same_typed_input_from_the_other_callers_pack_is_not_a_request_binding():
    graph, _ = input_origin_program()
    graph, calls, consumers = _two_input_consumers(graph)
    index = ProgramIndex(graph)
    raw = OwnedUse(calls[0].id, calls[0].call_arguments[0])
    correct = index.request_input_binding(raw, OwnedUse(consumers[0].id, consumers[0].uses[0].id))
    wrong = index.request_input_binding(raw, OwnedUse(consumers[1].id, consumers[1].uses[0].id))
    assert correct['bindings'] and correct['bindings'][0]['declared_operand_is_none'] is True
    assert wrong['bindings'] == ()
    assert 'request_input_binding_unresolved' in {gap['code'] for gap in wrong['gaps']}


def test_equal_none_contents_at_different_original_producers_do_not_replace_a_dependency_join():
    graph, details = generator_admission_program(kind=RawRequestKind.SEND)
    row = next(row for row in graph.protocol_operations
               if type(getattr(row.contract, 'subject', None)) is ReferenceIsNoneCondition)
    predicate = next(op for op in graph.operations if op.id == row.operation)
    region = next(value.region for value in graph.values if value.id == predicate.uses[0].value)
    unrelated = ReferenceValue(ValueID('request.unrelated.none'), region, LiteralOrigin(None), targets=())
    changed = replace(graph, values=(*graph.values, unrelated), operations=tuple(
        replace(op, uses=tuple(replace(use, value=unrelated.id)
            if use.id == row.contract.subject.input_use else use for use in op.uses))
        if op.id == predicate.id else op for op in graph.operations))
    index = ProgramIndex(changed)
    caller = index.operations[details['call']]
    raw_use = next(use for use in caller.uses if use.id in caller.invoke_arguments
                   and use.value == details['raw'])
    report = index.request_input_binding(OwnedUse(caller.id, raw_use.id),
        OwnedUse(predicate.id, row.contract.subject.input_use), budget=50000)
    assert report['bindings'] == ()
    assert report['source_runtime_verified'] is False


def test_joint_query_uses_one_budget_and_keeps_unresolved_work_on_truncation():
    graph, details = generator_admission_program(kind=RawRequestKind.SEND)
    index = ProgramIndex(graph)
    row = next(row for row in graph.protocol_operations
               if type(getattr(row.contract, 'subject', None)) is ReferenceIsNoneCondition)
    caller = index.operations[details['call']]
    raw_use = next(use for use in caller.uses if use.id in caller.invoke_arguments
                   and use.value == details['raw'])
    limited = index.request_input_binding(OwnedUse(caller.id, raw_use.id),
        OwnedUse(row.operation, row.contract.subject.input_use), budget=1)
    assert limited['bindings'] == () and limited['cursor']
    assert limited['budget']['truncated'] and limited['budget']['used'] == 1
    assert limited['transformation_authorized'] is False


def test_protocol_ledger_exposes_joint_recipe_without_revalidating_or_granting_native_identity(monkeypatch):
    graph, _ = generator_admission_program(kind=RawRequestKind.SEND)
    index = ProgramIndex(graph)
    def unexpected_revalidation(*args, **kwargs):
        raise AssertionError('a prepared query must reuse its ProgramIndex')
    monkeypatch.setattr(ProgramIndex, '__init__', unexpected_revalidation)
    report = index.protocol_obligations(budget=50000)
    predicate = next(row['predicate'] for scope in report['scopes'] for clause in scope['obligations']
                     for row in clause['rows'] if row['predicate'] is not None
                     and type(row['record'].contract.subject) is ReferenceIsNoneCondition)
    joint, = predicate['request_input_bindings']
    binding, = joint['report']['bindings']
    assert binding['declared_operand_is_none'] is True
    assert joint['carrier_uses']
    assert joint['report']['status'] == 'PARTIAL'
    assert predicate['status'] == 'PARTIAL'
    assert 'admission_request_input_routes_unresolved' in predicate['gaps']
    assert report['budget']['used'] >= joint['report']['budget']['used']
    assert report['transformation_authorized'] is report['source_runtime_verified'] is False
