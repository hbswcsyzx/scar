import math
import struct
import sys

import pytest

import scar.ir.literals as literal_module
from scar.ir.literals import (
    MAX_INT_BIT_LENGTH,
    MAX_INT_DECIMAL_DIGITS,
    MAX_LITERAL_DEPTH,
    MAX_LITERAL_NODES,
    MAX_LITERAL_PAYLOAD_BYTES,
    LiteralKind,
    PythonLiteral,
    literal_builtin_type,
    require_exact_literal,
    require_legacy_literal,
)
from scar.ir.record_codec import decode, encode
from scar.ir.v2._validation import record_errors


def test_legacy_and_exact_profiles_keep_distinct_kind_support():
    with pytest.raises(TypeError, match="complex"):
        PythonLiteral.from_python(1j)
    exact = PythonLiteral.from_python((1j, -0.0), exact=True)
    assert exact.items[0].kind is LiteralKind.COMPLEX128
    assert exact.items[0].payload == struct.pack(">dd", 0.0, 1.0).hex()
    assert exact.items[1].payload == "8000000000000000"
    assert literal_builtin_type(exact) is tuple
    assert type(exact.to_python()[0]) is complex
    assert math.copysign(1.0, exact.to_python()[1]) == -1.0
    require_exact_literal(exact)
    with pytest.raises(ValueError, match="legacy literal schema"):
        require_legacy_literal(exact)


@pytest.mark.parametrize("real_bits,imag_bits", (
    ("8000000000000000", "0000000000000000"),
    ("7ff8000000000001", "fff0000000000000"),
))
def test_complex_components_keep_binary64_bits(real_bits, imag_bits):
    real = struct.unpack(">d", bytes.fromhex(real_bits))[0]
    imag = struct.unpack(">d", bytes.fromhex(imag_bits))[0]
    literal = PythonLiteral.from_python(complex(real, imag), exact=True)
    assert literal.payload == real_bits + imag_bits
    restored = literal.to_python()
    assert struct.pack(">dd", restored.real, restored.imag).hex() == real_bits + imag_bits


def test_surrogate_profile_roundtrips_adjacent_codepoints_without_pair_merge():
    adjacent_surrogates = "\ud800\udc00"
    astral_codepoint = "\U00010000"
    legacy = PythonLiteral.from_python(adjacent_surrogates)
    exact = PythonLiteral.from_python(adjacent_surrogates, exact=True)
    assert legacy.kind is LiteralKind.STR
    assert exact.kind is LiteralKind.STR_CODEPOINTS
    assert exact.payload == "0000d8000000dc00"
    assert literal_builtin_type(exact) is str
    assert exact.to_python() == adjacent_surrogates
    assert exact.to_python() != astral_codepoint
    assert PythonLiteral.from_python(astral_codepoint, exact=True).kind is LiteralKind.STR
    with pytest.raises(ValueError, match="STR_CODEPOINTS"):
        require_exact_literal(legacy)
    require_legacy_literal(legacy)
    with pytest.raises(ValueError, match="legacy literal schema"):
        require_legacy_literal(exact)

    nested = PythonLiteral.from_python((adjacent_surrogates,), exact=True)
    require_exact_literal(nested)
    assert literal_builtin_type(nested.items[0]) is str
    with pytest.raises(ValueError, match="legacy literal schema"):
        require_legacy_literal(nested)


def test_generic_codec_and_record_validator_preflight_exact_literal_payloads():
    literal = PythonLiteral.from_python((1j, "\ud800\udc00"), exact=True)
    wire = encode(literal)
    restored = decode(PythonLiteral, wire)
    assert restored == literal
    assert restored.to_python() == (1j, "\ud800\udc00")
    assert record_errors(literal, PythonLiteral, "literal") == []

    malformed = PythonLiteral(LiteralKind.STR, "ok")
    object.__setattr__(malformed, "payload", "\ud800")
    assert record_errors(malformed, PythonLiteral, "literal") == []
    with pytest.raises(ValueError, match="STR_CODEPOINTS"):
        require_exact_literal(malformed)


@pytest.mark.parametrize("value", ([], {}, set(), [1], ([],), 1j,
                                    type("IntSubclass", (int,), {})(2)))
def test_mutable_complex_legacy_and_user_values_are_not_default_literals(value):
    with pytest.raises(TypeError):
        PythonLiteral.from_python(value)


def test_integer_chunk_conversion_obeys_digit_and_bit_bounds_without_formatting():
    original_limit = sys.get_int_max_str_digits()
    accepted = 10 ** (MAX_INT_DECIMAL_DIGITS - 1)
    literal = PythonLiteral.from_python(accepted)
    assert len(literal.payload) == MAX_INT_DECIMAL_DIGITS
    assert literal.to_python() == accepted

    with pytest.raises(ValueError, match="decimal digit budget"):
        PythonLiteral.from_python(10 ** MAX_INT_DECIMAL_DIGITS)
    with pytest.raises(ValueError, match="bit-length precheck"):
        PythonLiteral.from_python(1 << MAX_INT_BIT_LENGTH)
    assert sys.get_int_max_str_digits() == original_limit


def test_depth_budget_counts_root_at_zero():
    value = 0
    for _ in range(MAX_LITERAL_DEPTH):
        value = (value,)
    assert PythonLiteral.from_python(value).to_python() == value
    value = (value,)
    with pytest.raises(ValueError, match="depth budget"):
        PythonLiteral.from_python(value)


def test_expanded_shared_subtrees_are_charged_repeatedly_and_cycles_rejected():
    leaf = PythonLiteral(LiteralKind.INT, "1")
    shared = PythonLiteral(LiteralKind.TUPLE, items=(leaf,))
    at_limit = PythonLiteral(LiteralKind.TUPLE,
                             items=(shared,) * ((MAX_LITERAL_NODES - 2) // 2) + (leaf,))
    assert len(at_limit.items) == 8_192
    require_exact_literal(at_limit)
    with pytest.raises(ValueError, match="node budget"):
        PythonLiteral(LiteralKind.TUPLE, items=(shared,) * (MAX_LITERAL_NODES // 2))

    cyclic = PythonLiteral(LiteralKind.TUPLE)
    object.__setattr__(cyclic, "items", (cyclic,))
    with pytest.raises(ValueError, match="cyclic"):
        cyclic.as_dict()
    with pytest.raises(ValueError, match="cyclic"):
        encode(cyclic)


def test_payload_budget_counts_string_bytes_and_codepoints():
    assert len(PythonLiteral.from_python("a" * MAX_LITERAL_PAYLOAD_BYTES).payload) == MAX_LITERAL_PAYLOAD_BYTES
    with pytest.raises(ValueError, match="payload budget"):
        PythonLiteral.from_python("a" * (MAX_LITERAL_PAYLOAD_BYTES + 1))

    exact_limit_codepoints = "\ud800" * (MAX_LITERAL_PAYLOAD_BYTES // 4)
    assert PythonLiteral.from_python(exact_limit_codepoints, exact=True).kind is LiteralKind.STR_CODEPOINTS
    with pytest.raises(ValueError, match="payload budget"):
        PythonLiteral.from_python(exact_limit_codepoints + "\ud800", exact=True)


def test_oversized_exact_string_is_rejected_before_surrogate_scan(monkeypatch):
    def unexpected_scan(_value):
        pytest.fail("oversized string reached the surrogate scan")

    monkeypatch.setattr(literal_module, "_has_surrogate", unexpected_scan)
    value = "x" * (MAX_LITERAL_PAYLOAD_BYTES + 1)
    with pytest.raises(ValueError, match="payload budget"):
        PythonLiteral.from_python(value, exact=True)


def test_scheduled_node_budget_precedes_deep_fanout_expansion():
    # Each representation has only about 16K actual child references, but
    # expanding the shared DAG would exceed the occurrence budget. The first
    # nested fanout also contains an over-deep child so an implementation that
    # counts only visited nodes reports depth before bounding its pending work.
    fanout = MAX_LITERAL_NODES // 2

    deep_value = None
    for _ in range(MAX_LITERAL_DEPTH + 1):
        deep_value = (deep_value,)
    value_branch = (deep_value,) * fanout
    value_root = (value_branch,) * fanout
    with pytest.raises(ValueError, match="node budget"):
        PythonLiteral.from_python(value_root)

    def forged_tuple(items):
        node = object.__new__(PythonLiteral)
        object.__setattr__(node, "kind", LiteralKind.TUPLE)
        object.__setattr__(node, "payload", None)
        object.__setattr__(node, "items", items)
        return node

    deep_literal = PythonLiteral(LiteralKind.NONE)
    for _ in range(MAX_LITERAL_DEPTH + 1):
        deep_literal = forged_tuple((deep_literal,))
    literal_branch = forged_tuple((deep_literal,) * fanout)
    literal_root = forged_tuple((literal_branch,) * fanout)
    with pytest.raises(ValueError, match="node budget"):
        literal_root.as_dict()

    def wire_tuple(items):
        return {"kind": "tuple", "payload": None, "items": items}

    deep_wire = wire_tuple([])
    for _ in range(MAX_LITERAL_DEPTH + 1):
        deep_wire = wire_tuple([deep_wire])
    wire_branch = wire_tuple([deep_wire] * fanout)
    wire_root = wire_tuple([wire_branch] * fanout)
    with pytest.raises(ValueError, match="node budget"):
        PythonLiteral.from_dict(wire_root)


def test_from_dict_rejects_oversized_or_noncanonical_payload_before_tree_build():
    wire = {"kind": "str_codepoints", "payload": "0000d800", "items": []}
    assert PythonLiteral.from_dict(wire).to_python() == "\ud800"
    for bad in (
        {"kind": "str_codepoints", "payload": "00010000", "items": []},
        {"kind": "str_codepoints", "payload": "0000D800", "items": []},
        {"kind": "complex128", "payload": "0" * 31, "items": []},
        {"kind": "int", "payload": "0" * (MAX_INT_DECIMAL_DIGITS + 1), "items": []},
    ):
        with pytest.raises((TypeError, ValueError)):
            PythonLiteral.from_dict(bad)

    assert MAX_LITERAL_NODES == 16_384
