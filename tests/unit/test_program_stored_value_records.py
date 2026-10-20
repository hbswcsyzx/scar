"""Stored payload declarations attach to original state and result ports."""
from dataclasses import FrozenInstanceError, fields, replace
import json
from typing import get_type_hints

import pytest

from scar.ir.program.codec import dumps, loads
from scar.ir.program.ids import OperationID, UseID, ValueID
from scar.ir.program.model import (
    AccessMode, BlockArgument, CompletionResult, CompletionSignature,
    ExitKind, InvokeLiteralResult, OperationResult, ReferenceValue,
    ValueKind, ValueType,
)
from scar.ir.program.state_addresses import AddressEffect, Element, ObjectField, ReferenceOwner
from scar.ir.program.stored_values import (
    STORED_VALUE_RECORD_TAGS, StoredValueRead, StoredValueWrite,
    has_stored_value_capability, stored_value_errors,
)
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_state_addresses import state_address_program


def _program(*, invoke=False):
    graph, details = state_address_program()
    require_valid(graph)
    original = graph
    operations = {row.id: row for row in graph.operations}
    values = list(graph.values)
    if invoke:
        operation = operations[details['invoke_operation']]
        normal = operation.terminator.successors[0]
        region = graph.regions[0]
        block = next(row for row in region.blocks if row.id == normal.block)
        value = ReferenceValue(ValueID('stored.own.normal'), region.id,
                               BlockArgument(block.id, 0))
        values = [replace(row, origin=BlockArgument(block.id, 1))
                  if row.id == block.arguments[0] else row for row in values]
        values.append(value)
        changed_block = replace(block, arguments=(value.id, *block.arguments))
        region = replace(region, blocks=tuple(changed_block if row.id == block.id else row
                                              for row in region.blocks))
        signature = next(row for row in operation.completions if row.kind is ExitKind.NORMAL)
        signature = CompletionSignature(ExitKind.NORMAL,
            (*signature.types, ValueType(ValueKind.REFERENCE)))
        operation = replace(operation,
            terminator=replace(operation.terminator, successors=(
                replace(normal, arguments=(CompletionResult(1), CompletionResult(0))),
                *operation.terminator.successors[1:])),
            completions=tuple(signature if row.kind is ExitKind.NORMAL else row
                              for row in operation.completions))
        operations[operation.id] = operation
        graph = replace(graph, regions=(region,))
        site = graph.state_address_refinements[1].site
        read = StoredValueRead(site, 0, InvokeLiteralResult(
            ControlEdgeReference(operation.id, 0), CompletionResult(1)))
        # The payload is this INVOKE's real Reference argument, not a forwarded
        # landing prefix or an operand borrowed from the earlier access.
        payload = next(use.id for use in operation.uses
                       if use.id in operation.invoke_arguments
                       and type(next(row for row in values if row.id == use.value)) is ReferenceValue)
        writes = tuple(StoredValueWrite(site, 0, payload,
            ControlEdgeReference(operation.id, number)) for number in (0, 1))
    else:
        operation = operations[details['root_operation']]
        port = OperationResult(operation.id, len(operation.results))
        value = ReferenceValue(ValueID('stored.own.ordinary'), graph.root, port)
        values.append(value)
        operations[operation.id] = replace(operation, results=(*operation.results, value.id))
        site = graph.state_address_refinements[0].site
        read = StoredValueRead(site, 0, port)
        writes = (StoredValueWrite(site, 1, details['root_reference_uses'][0]),)
    graph = replace(graph, operations=tuple(operations[row.id] for row in graph.operations),
                    values=tuple(values))
    require_valid(graph)
    return replace(graph, stored_value_writes=writes, stored_value_reads=(read,)), original


def test_records_are_frozen_exact_and_annotations_resolve_to_canonical_ports():
    graph, _ = _program()
    write, = graph.stored_value_writes
    read, = graph.stored_value_reads
    assert tuple(row.name for row in fields(write)) == ('site', 'effect_index', 'payload', 'completion')
    assert tuple(row.name for row in fields(read)) == ('site', 'effect_index', 'result')
    assert get_type_hints(StoredValueRead)['result'] == OperationResult | InvokeLiteralResult
    assert not hasattr(write, '__dict__') and not hasattr(read, '__dict__')
    with pytest.raises(FrozenInstanceError):
        write.payload = UseID('different')
    with pytest.raises(TypeError):
        replace(write, payload=write.payload.wire)
    with pytest.raises(ValueError):
        replace(write, effect_index=True)
    with pytest.raises(TypeError):
        replace(read, result=read.result.index)
    assert dict(STORED_VALUE_RECORD_TAGS) == {
        StoredValueWrite: ('kind', 'STORED_VALUE_WRITE'),
        StoredValueRead: ('kind', 'STORED_VALUE_READ')}
    with pytest.raises(TypeError):
        STORED_VALUE_RECORD_TAGS[StoredValueRead] = ('kind', 'OTHER')


@pytest.mark.parametrize('invoke', (False, True), ids=('ordinary', 'invoke'))
def test_original_pre_post_ports_roundtrip_without_literals_or_protocol_profiles(invoke):
    graph, original = _program(invoke=invoke)
    require_valid(graph)
    assert stored_value_errors(graph) == ()
    assert has_stored_value_capability(graph)
    assert graph.protocol_scopes == graph.literal_evaluations == ()
    assert loads(dumps(graph)) == graph
    wire = json.loads(dumps(graph))
    assert wire['schema_version'] == 27
    assert wire['stored_value_reads'][0]['kind'] == 'STORED_VALUE_READ'
    if invoke:
        read, = graph.stored_value_reads
        assert read.result.result.index == 1
        assert wire['stored_value_reads'][0]['result']['kind'] == 'INVOKE_LITERAL_RESULT'
        assert tuple(row.completion.successor_index for row in graph.stored_value_writes) == (0, 1)
    removed = replace(graph, stored_value_writes=(), stored_value_reads=())
    old_wire = json.loads(dumps(removed))
    assert old_wire['schema_version'] == json.loads(dumps(original))['schema_version'] == 15
    assert 'stored_value_writes' not in old_wire and 'stored_value_reads' not in old_wire
    assert removed.operations == graph.operations
    assert all(old.effects_complete == new.effects_complete
               for old, new in zip(original.operations, graph.operations))


def test_graph_constructor_rejects_duplicate_write_keys_and_multiple_sources_for_one_read_result():
    graph, _ = _program()
    write, = graph.stored_value_writes
    read, = graph.stored_value_reads
    with pytest.raises(TypeError, match='tuple'):
        replace(graph, stored_value_writes=[write])
    with pytest.raises(TypeError, match='exact StoredValueRead'):
        replace(graph, stored_value_reads=(write,))
    with pytest.raises(ValueError, match='stored value write keys'):
        replace(graph, stored_value_writes=(write, write))
    with pytest.raises(ValueError, match='stored value read results'):
        replace(graph, stored_value_reads=(read, replace(read, effect_index=1)))


@pytest.mark.parametrize('fault,code', (
    ('effect-index', 'stored_value_effect'),
    ('foreign-payload', 'stored_value_payload'),
    ('read-only-write', 'stored_value_write_mode'),
    ('state-result', 'stored_value_result_type'),
    ('wrong-result-owner', 'stored_value_result'),
))
def test_relations_reject_wrong_original_effect_payload_or_own_result(fault, code):
    graph, _ = _program()
    require_valid(graph)
    write, = graph.stored_value_writes
    read, = graph.stored_value_reads
    if fault == 'effect-index':
        write = replace(write, effect_index=999)
    elif fault == 'foreign-payload':
        write = replace(write, payload=UseID('stored.not.owned'))
    elif fault == 'read-only-write':
        write = replace(write, effect_index=0)
    elif fault == 'state-result':
        read = replace(read, result=OperationResult(read.result.operation, 0))
    else:
        read = replace(read, result=OperationResult(OperationID('stored.missing'), 0))
    bad = replace(graph, stored_value_writes=(write,), stored_value_reads=(read,))
    assert code in {item[0] for item in stored_value_errors(bad)}
    assert code in {item.code for item in validate(bad)}


def test_same_final_slot_cannot_receive_two_post_facts_by_changing_effect_stage():
    graph, _ = _program()
    write, = graph.stored_value_writes
    refinement = graph.state_address_refinements[0]
    operation = next(row for row in graph.operations if row.id == write.site.operation)
    owner = next(use for use in operation.uses if use.id == write.payload)
    first = AddressEffect(ReferenceOwner(owner.id), (ObjectField('explicit_slot'),), AccessMode.WRITE, 0)
    second = replace(first, stage=1)
    refinement = replace(refinement, effects=(first, second))
    base = replace(graph, state_address_refinements=(refinement, *graph.state_address_refinements[1:]),
                   stored_value_writes=(), stored_value_reads=())
    require_valid(base)
    first_write = replace(write, effect_index=0)
    second_write = replace(write, effect_index=1,
        payload=next(use.id for use in operation.uses
                     if use.id != write.payload and type(next(value for value in graph.values
                         if value.id == use.value)) is ReferenceValue))
    bad = replace(base, stored_value_writes=(first_write, second_write))
    assert 'stored_value_post_conflict' in {item[0] for item in stored_value_errors(bad)}
    assert 'stored_value_post_conflict' in {item.code for item in validate(bad)}


def test_invoke_read_cannot_borrow_raise_result_or_treat_state_slot_as_payload():
    graph, _ = _program(invoke=True)
    require_valid(graph)
    read, = graph.stored_value_reads
    for result, code in (
        (replace(read.result, edge=replace(read.result.edge, successor_index=1),
                 result=CompletionResult(0)), 'stored_value_read_completion'),
        (replace(read.result, result=CompletionResult(0)), 'stored_value_result_type'),
    ):
        bad = replace(graph, stored_value_reads=(replace(read, result=result),))
        assert code in {item[0] for item in stored_value_errors(bad)}
        assert code in {item.code for item in validate(bad)}


def test_same_data_key_through_distinct_owned_uses_cannot_declare_two_final_payloads():
    graph, details = state_address_program()
    require_valid(graph)
    operation = next(row for row in graph.operations if row.id == details['root_operation'])
    key = next(use for use in operation.uses if use.id == details['root_dynamic_key_use'])
    alias = replace(key, id=UseID('stored.same.key.second.use'))
    operation = replace(operation, uses=(*operation.uses, alias))
    owner, other_payload = details['root_reference_uses']
    first = AddressEffect(ReferenceOwner(owner), (Element(key.id),), AccessMode.WRITE, 0)
    second = AddressEffect(ReferenceOwner(owner), (Element(alias.id),), AccessMode.WRITE, 1)
    refinement = replace(graph.state_address_refinements[0], effects=(first, second))
    base = replace(graph,
        operations=tuple(operation if row.id == operation.id else row for row in graph.operations),
        state_address_refinements=(refinement, *graph.state_address_refinements[1:]))
    require_valid(base)
    assert key.id != alias.id and key.value == alias.value
    writes = (StoredValueWrite(refinement.site, 0, owner),
              StoredValueWrite(refinement.site, 1, other_payload))
    bad = replace(base, stored_value_writes=writes)
    assert 'stored_value_post_conflict' in {item[0] for item in stored_value_errors(bad)}
    assert 'stored_value_post_conflict' in {item.code for item in validate(bad)}
