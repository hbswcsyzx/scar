import pytest

from scar.ir.literals import MAX_LITERAL_DEPTH, LiteralKind, PythonLiteral
from scar.ir.record_codec import decode, encode
from scar.ir.semantics_v2 import Opcode, OperationSemantics
from scar.ir.v2.codec import _python_literal, _wire_type
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import OperationDefinitionID, SourceAtomID, StaticValueID
from scar.ir.v2.optimization import StaticValueSubstitution


def _legacy_operation(literal):
    source = SourceReference(SourceAtomID("source"), "fixture.py", "sha256:" + "0" * 64, 1, 1)
    return OperationSemantics(
        OperationDefinitionID("literal"), OperationDefinitionID("scope"), "entry", 0,
        Opcode.LITERAL, (), StaticValueID("result"), source, literal=literal)


@pytest.mark.parametrize("literal", (
    PythonLiteral(LiteralKind.COMPLEX128, "00000000000000000000000000000000"),
    PythonLiteral(LiteralKind.TUPLE, items=(
        PythonLiteral(LiteralKind.STR_CODEPOINTS, "0000d800"),)),
))
def test_legacy_source_semantics_constructor_rejects_new_kinds_recursively(literal):
    with pytest.raises(ValueError, match="legacy literal schema"):
        _legacy_operation(literal)


def test_legacy_source_wire_decoder_rejects_new_kinds_but_keeps_raw_surrogate_str():
    exact = PythonLiteral.from_python("\ud800\udc00", exact=True)
    with pytest.raises(ValueError, match="legacy literal schema"):
        _python_literal(exact.as_dict())
    with pytest.raises(ValueError, match="legacy literal schema"):
        _wire_type(exact.as_dict(), PythonLiteral, "literal")

    old_raw = PythonLiteral.from_python("\ud800\udc00")
    assert old_raw.kind is LiteralKind.STR
    assert _python_literal(old_raw.as_dict()) == old_raw


def test_legacy_optimization_constructor_does_not_accept_exact_only_kinds():
    source = SourceReference(SourceAtomID("source"), "fixture.py", "sha256:" + "0" * 64, 1, 1)
    literal = PythonLiteral.from_python(1j, exact=True)
    with pytest.raises(ValueError, match="legacy literal schema"):
        StaticValueSubstitution(StaticValueID("value"), OperationDefinitionID("op"),
                                source, literal)

    substitution = StaticValueSubstitution(
        StaticValueID("value"), OperationDefinitionID("op"), source,
        PythonLiteral.from_python(1))
    object.__setattr__(substitution, "literal", literal)
    with pytest.raises(ValueError, match="legacy literal schema"):
        substitution.as_dict()


def test_all_wire_decoders_preflight_nested_literals_before_building_records():
    wire = {"kind": "none", "payload": None, "items": []}
    for _ in range(MAX_LITERAL_DEPTH + 1):
        wire = {"kind": "tuple", "payload": None, "items": [wire]}
    with pytest.raises(ValueError, match="depth budget"):
        PythonLiteral.from_dict(wire)
    with pytest.raises(ValueError, match="depth budget"):
        decode(PythonLiteral, wire)

    cyclic = {"kind": "tuple", "payload": None, "items": []}
    cyclic["items"].append(cyclic)
    with pytest.raises(ValueError, match="cyclic"):
        PythonLiteral.from_dict(cyclic)
    with pytest.raises(ValueError, match="cyclic"):
        decode(PythonLiteral, cyclic)


def test_generic_codec_applies_registered_literal_tag_to_every_nested_node():
    literal = PythonLiteral.from_python((1, ("nested", 2j)), exact=True)
    tags = {PythonLiteral: ("$record", "python_literal")}
    wire = encode(literal, record_tags=tags)
    assert wire["$record"] == "python_literal"
    assert wire["items"][1]["$record"] == "python_literal"
    assert wire["items"][1]["items"][0]["$record"] == "python_literal"
    assert decode(PythonLiteral, wire, record_tags=tags) == literal

    wrong_child_tag = {**wire, "items": list(wire["items"])}
    wrong_nested = {**wrong_child_tag["items"][1],
                    "items": list(wrong_child_tag["items"][1]["items"])}
    wrong_grandchild = dict(wrong_nested["items"][0])
    wrong_grandchild["$record"] = "another_record"
    wrong_nested["items"][0] = wrong_grandchild
    wrong_child_tag["items"][1] = wrong_nested
    with pytest.raises(ValueError, match="discriminator mismatch"):
        decode(PythonLiteral, wrong_child_tag, record_tags=tags)

    missing_child_tag = {**wire, "items": list(wire["items"])}
    missing_child_tag["items"][1] = {
        key: value for key, value in missing_child_tag["items"][1].items()
        if key != "$record"
    }
    with pytest.raises(ValueError, match="exact kind/payload/items fields"):
        decode(PythonLiteral, missing_child_tag, record_tags=tags)
    with pytest.raises(ValueError, match="exact kind/payload/items fields"):
        PythonLiteral.from_dict(wire)
