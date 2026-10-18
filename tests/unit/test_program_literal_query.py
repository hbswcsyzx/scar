"""Queries retain original producers, completion arguments and ordered Uses."""
from dataclasses import replace

import pytest

from scar.ir.program import (CompletionResult, InvokeLiteralResult, OperationID,
                             OperationResult, UninterpretedConstant, ValueID)
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.program_literals import literal_program


def test_direct_query_keeps_original_objects_order_and_effects():
    graph, details = literal_program()
    index = ProgramIndex(graph)
    view = index.literal_evaluation(details["direct"])
    operation = index.operations[OperationID("direct")]
    assert view["operation"] is operation
    assert view["row"] is graph.literal_evaluations[0]
    assert view["result"] is index.values[ValueID("computed")]
    assert view["result"].origin == details["direct"]
    assert view["uses"] == tuple(index.use_site(u.id) for u in operation.uses)
    assert view["uses"][0].use is operation.uses[0]
    assert view["uses"][0].use.value == view["uses"][1].use.value
    assert view["uses"][0].use.id != view["uses"][1].use.id
    assert operation.effects_complete is False and operation.accesses
    assert view["successor_index"] is None and view["argument"] is None
    assert not view["source_runtime_verified"] and not view["value_identity_verified"]
    assert not view["transformation_authorized"]


@pytest.mark.parametrize("key,result_name,position", [("invoke", "normal.data", 2), ("invoke_reference", "normal.ref", 1)])
def test_invoke_query_uses_original_normal_slot_not_physical_prefix(key, result_name, position):
    graph, details = literal_program()
    index = ProgramIndex(graph)
    view = index.literal_evaluation(details[key])
    operation = index.operations[OperationID("invoke")]
    assert view["successor"] is operation.terminator.successors[0]
    assert view["successor_index"] == 0
    assert view["argument"] is operation.terminator.successors[0].arguments[position]
    assert view["result"] is index.values[ValueID(result_name)]
    assert view["result"].origin.index == position
    assert index.producer(view["result"].id) is view["result"].origin


def test_absent_attachment_retains_original_port_and_explicit_unknown():
    graph, details = literal_program(attachments=False)
    index = ProgramIndex(graph)
    view = index.literal_evaluation(details["invoke"])
    assert view["row"] is None and view["literal"] is None and view["definition"] is None
    assert view["result"] is index.values[ValueID("normal.data")]
    assert any("absent" in c for c in view["conditions"])


def test_uninterpreted_does_not_materialize_and_view_edits_do_not_edit_graph():
    graph, details = literal_program()
    index = ProgramIndex(graph)
    view = index.literal_evaluation(details["reference"])
    assert type(view["literal"]) is UninterpretedConstant
    view["result"] = "fake"
    assert index.literal_evaluation(details["reference"])["result"] is index.values[ValueID("constructed")]


@pytest.mark.parametrize("site", [OperationID("direct"), OperationResult(OperationID("missing"), 0),
    InvokeLiteralResult(ControlEdgeReference(OperationID("invoke"), 1), CompletionResult(0))])
def test_invalid_query_site_rejected_without_returning_other_payload(site):
    index = ProgramIndex(literal_program()[0])
    with pytest.raises((ValueError, TypeError)):
        index.literal_evaluation(site)
