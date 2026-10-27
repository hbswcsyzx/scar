"""L2 content/type/source ports; no source/runtime applicability claims."""
from dataclasses import FrozenInstanceError, replace

import pytest

from scar.ir.literals import PythonLiteral
from scar.ir.program import (
    BlockArgument, BlockID, CodeConstant, DataValue, ExactLiteralOrigin,
    InvokeLiteralResult, LiteralEvaluation, LocationID, OperationID, OperationResult,
    ReferenceValue, SourceExpression, StateVersionValue, UninterpretedConstant,
    UnlocatedLiteral, ValueID, is_literal_origin,
)
from scar.ir.program.model import CompletionResult
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.program.validation import require_valid, validate
from tests.fixtures.program_literals import literal_program


@pytest.mark.parametrize("payload", [None, False, 2**100, -0.0, complex(-0.0, float("inf")),
                                      "nul\x00é", "\ud800", "\ud800\udc00", b"\x00\xff", Ellipsis,
                                      (None, (1, b"bytes"))])
def test_exact_data_payload_family(payload):
    graph, _ = literal_program(payload=payload)
    require_valid(graph)
    constant = next(v for v in graph.values if v.id == ValueID("constant"))
    assert is_literal_origin(constant.origin)
    assert constant.origin.literal == PythonLiteral.from_python(payload, exact=True)


def test_exact_origin_cannot_preload_reference_state_or_wrong_data_type():
    graph, _ = literal_program()
    constant = next(v for v in graph.values if v.id == ValueID("constant"))
    with pytest.raises(ValueError, match="DataValue"):
        ReferenceValue(ValueID("bad"), graph.root, constant.origin)
    with pytest.raises(ValueError, match="DataValue"):
        StateVersionValue(ValueID("bad"), graph.root, constant.origin, LocationID("literal.world"))
    with pytest.raises(ValueError, match="exact literal DataValue type"):
        replace(constant, data_type="builtins.int")
    assert not is_literal_origin(graph.literal_evaluations[0])
    assert not is_literal_origin(graph.literal_evaluations[0].site)


@pytest.mark.parametrize("site", [
    OperationResult(OperationID("absent"), 0), OperationResult(OperationID("direct"), 9),
    OperationResult(OperationID("direct"), 2),
    InvokeLiteralResult(ControlEdgeReference(OperationID("direct"), 0), CompletionResult(0)),
    InvokeLiteralResult(ControlEdgeReference(OperationID("invoke"), 9), CompletionResult(0)),
    InvokeLiteralResult(ControlEdgeReference(OperationID("invoke"), 1), CompletionResult(0)),
    InvokeLiteralResult(ControlEdgeReference(OperationID("invoke"), 0), CompletionResult(2)),
    InvokeLiteralResult(ControlEdgeReference(OperationID("invoke"), 0), CompletionResult(9)),
])
def test_invalid_original_site_is_issue_not_inferred_producer(site):
    graph, _ = literal_program(attachments=False)
    graph = replace(graph, literal_evaluations=(LiteralEvaluation(site, UninterpretedConstant("unknown")),))
    issues = validate(graph)
    assert any(i.code == "literal_site" for i in issues), issues


def test_known_computed_data_type_checked_unknown_not_promoted():
    graph, d = literal_program(attachments=False)
    wrong = LiteralEvaluation(d["direct"], PythonLiteral.from_python(7, exact=True))
    assert any(i.code == "literal_type" for i in validate(replace(graph, literal_evaluations=(wrong,))))
    unknown = LiteralEvaluation(d["direct"], UninterpretedConstant("unresolved code constant"))
    require_valid(replace(graph, literal_evaluations=(unknown,)))


def test_duplicate_site_and_nested_mutation_rejected():
    graph, _ = literal_program()
    with pytest.raises(ValueError, match="duplicates"):
        replace(graph, literal_evaluations=(graph.literal_evaluations[0],) * 2)
    bad = PythonLiteral.from_python((1,), exact=True)
    object.__setattr__(bad, "items", (object(),))
    with pytest.raises((TypeError, ValueError)):
        ExactLiteralOrigin(bad)
    source = graph.literal_evaluations[0].definition.source
    malformed = replace(source)
    object.__setattr__(malformed, "start_line", True)
    with pytest.raises(TypeError, match="positions"):
        SourceExpression(malformed)


@pytest.mark.parametrize("bad", [True, -1, 1.0, "1"])
def test_code_slot_exact_nonnegative_integer(bad):
    _, d = literal_program()
    with pytest.raises((TypeError, ValueError)):
        CodeConstant(d["code_fact"], bad)


def test_definitions_uninterpreted_and_record_immutability():
    graph, _ = literal_program()
    require_valid(graph)
    row = graph.literal_evaluations[2]
    assert isinstance(row.definition, CodeConstant)
    assert row.definition.fact.locator == "#/code/0" and row.definition.index == 3
    assert isinstance(graph.literal_evaluations[1].literal, UninterpretedConstant)
    with pytest.raises(FrozenInstanceError):
        row.definition = UnlocatedLiteral()
    with pytest.raises((TypeError, ValueError)):
        UnlocatedLiteral("")
    with pytest.raises((TypeError, ValueError)):
        LiteralEvaluation(BlockArgument(BlockID("entry"), 0), row.literal)


def test_raw_surrogate_str_is_not_an_exact_payload():
    legacy = PythonLiteral.from_python("\ud800")
    with pytest.raises(ValueError):
        ExactLiteralOrigin(legacy)


def test_private_corruption_of_reference_origin_rechecked():
    graph, _ = literal_program()
    ref = replace(next(v for v in graph.values if v.id == ValueID("constructed")))
    object.__setattr__(ref, "origin", ExactLiteralOrigin(PythonLiteral.from_python(1, exact=True)))
    corrupted = replace(graph, values=tuple(ref if v.id == ref.id else v for v in graph.values))
    assert any(i.code == "schema" for i in validate(corrupted))
