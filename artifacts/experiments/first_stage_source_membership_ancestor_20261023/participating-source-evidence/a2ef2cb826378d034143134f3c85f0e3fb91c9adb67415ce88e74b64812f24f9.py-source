"""Bounded immutable Python literal payloads with legacy and exact profiles.

Literal payloads have one fixed, non-configurable budget.  The preflight code
is iterative so malformed or forged cyclic trees are rejected before any
recursive record codec can descend into them.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import struct
from typing import Any


MAX_LITERAL_DEPTH = 64                 # root is depth zero
MAX_LITERAL_NODES = 16_384             # expanded occurrences, not identities
MAX_LITERAL_PAYLOAD_BYTES = 1_048_576  # aggregate scalar content
MAX_INT_DECIMAL_DIGITS = 4_096
MAX_INT_BIT_LENGTH = 13_608

_DECIMAL_CHUNK_BASE = 1_000_000_000
_DECIMAL_CHUNK_DIGITS = 9


class LiteralKind(str, Enum):
    NONE = "none"
    BOOL = "bool"
    INT = "int"
    FLOAT64 = "float64"
    COMPLEX128 = "complex128"
    STR = "str"
    STR_CODEPOINTS = "str_codepoints"
    BYTES = "bytes"
    TUPLE = "tuple"
    ELLIPSIS = "ellipsis"


def _canonical_integer(text: str) -> bool:
    if type(text) is not str or not text:
        return False
    if text == "0":
        return True
    digits = text[1:] if text.startswith("-") else text
    if not digits or digits[0] == "0":
        return False
    return all("0" <= char <= "9" for char in digits)


def _is_lower_hex(text: str) -> bool:
    return all(("0" <= char <= "9") or ("a" <= char <= "f") for char in text)


def _has_surrogate(text: str) -> bool:
    return any(0xD800 <= ord(char) <= 0xDFFF for char in text)


def _utf8_surrogatepass_size(text: str, remaining: int | None = None) -> int:
    """Count UTF-8/surrogatepass bytes without allocating an encoded copy."""
    size = 0
    for char in text:
        codepoint = ord(char)
        if codepoint <= 0x7F:
            size += 1
        elif codepoint <= 0x7FF:
            size += 2
        elif codepoint <= 0xFFFF:
            size += 3
        else:
            size += 4
        if remaining is not None and size > remaining:
            return size
    return size


def _int_to_decimal(value: int) -> str:
    """Convert a bounded integer without CPython's global decimal limit."""
    if type(value) is not int:
        raise TypeError("integer literal requires an exact int")
    if value.bit_length() > MAX_INT_BIT_LENGTH:
        raise ValueError("integer literal exceeds the bit-length precheck")
    if value == 0:
        return "0"
    negative = value < 0
    remainder = -value if negative else value
    chunks: list[int] = []
    while remainder:
        remainder, chunk = divmod(remainder, _DECIMAL_CHUNK_BASE)
        chunks.append(chunk)
        if len(chunks) > (MAX_INT_DECIMAL_DIGITS + _DECIMAL_CHUNK_DIGITS - 1) // _DECIMAL_CHUNK_DIGITS:
            raise ValueError("integer literal exceeds the decimal digit budget")
    head = str(chunks[-1])  # at most nine digits; independent of global setting
    digits = head + "".join(f"{chunk:09d}" for chunk in reversed(chunks[:-1]))
    if len(digits) > MAX_INT_DECIMAL_DIGITS:
        raise ValueError("integer literal exceeds the decimal digit budget")
    return "-" + digits if negative else digits


def _decimal_to_int(text: str) -> int:
    """Parse canonical decimal in bounded chunks, without a global setting."""
    if not _canonical_integer(text):
        raise ValueError("integer payload must be canonical decimal")
    digits = text[1:] if text.startswith("-") else text
    if len(digits) > MAX_INT_DECIMAL_DIGITS:
        raise ValueError("integer literal exceeds the decimal digit budget")
    result = 0
    for start in range(0, len(digits), _DECIMAL_CHUNK_DIGITS):
        chunk = digits[start:start + _DECIMAL_CHUNK_DIGITS]
        result = result * (10 ** len(chunk)) + int(chunk)
    if text.startswith("-"):
        result = -result
    if result.bit_length() > MAX_INT_BIT_LENGTH:
        raise ValueError("integer literal exceeds the bit-length precheck")
    return result


def _literal_payload_size(kind: LiteralKind, payload: Any) -> int:
    if kind in (LiteralKind.NONE, LiteralKind.ELLIPSIS, LiteralKind.TUPLE):
        if payload is not None:
            raise ValueError("this literal kind has no scalar payload")
        return 0
    if kind is LiteralKind.BOOL:
        if type(payload) is not bool:
            raise ValueError("bool literal requires a bool payload")
        return 1
    if kind is LiteralKind.INT:
        if type(payload) is not str:
            raise ValueError("integer literal requires a string payload")
        # Reject overlong input before regexes or decimal conversion.
        if len(payload) > MAX_INT_DECIMAL_DIGITS + 1:
            raise ValueError("integer literal exceeds the decimal digit budget")
        if not _canonical_integer(payload):
            raise ValueError("integer payload must be canonical decimal")
        digits = len(payload) - (1 if payload.startswith("-") else 0)
        if digits > MAX_INT_DECIMAL_DIGITS:
            raise ValueError("integer literal exceeds the decimal digit budget")
        return len(payload)
    if kind is LiteralKind.FLOAT64:
        if type(payload) is not str or len(payload) != 16 or not _is_lower_hex(payload):
            raise ValueError("float64 payload must be 16 lowercase hexadecimal digits")
        return 8
    if kind is LiteralKind.COMPLEX128:
        if type(payload) is not str or len(payload) != 32 or not _is_lower_hex(payload):
            raise ValueError("complex128 payload must be 32 lowercase hexadecimal digits")
        return 16
    if kind is LiteralKind.STR:
        if type(payload) is not str:
            raise ValueError("string literal requires a string payload")
        return _utf8_surrogatepass_size(payload, MAX_LITERAL_PAYLOAD_BYTES)
    if kind is LiteralKind.STR_CODEPOINTS:
        if type(payload) is not str or not payload or len(payload) % 8:
            raise ValueError("str_codepoints payload must contain 8-hex code points")
        if len(payload) // 8 > MAX_LITERAL_PAYLOAD_BYTES // 4:
            raise ValueError("literal payload budget exceeded")
        if not _is_lower_hex(payload):
            raise ValueError("str_codepoints payload must be lowercase hexadecimal")
        saw_surrogate = False
        for start in range(0, len(payload), 8):
            codepoint = int(payload[start:start + 8], 16)
            if codepoint > 0x10FFFF:
                raise ValueError("str_codepoints contains an invalid Unicode code point")
            saw_surrogate |= 0xD800 <= codepoint <= 0xDFFF
        if not saw_surrogate:
            raise ValueError("str_codepoints encoding is reserved for surrogate strings")
        return (len(payload) // 8) * 4
    if kind is LiteralKind.BYTES:
        if type(payload) is not str:
            raise ValueError("bytes literal requires a string payload")
        if len(payload) % 2:
            raise ValueError("bytes payload must have an even number of hex digits")
        if len(payload) // 2 > MAX_LITERAL_PAYLOAD_BYTES:
            raise ValueError("literal payload budget exceeded")
        if not _is_lower_hex(payload):
            raise ValueError("bytes payload must be canonical hexadecimal")
        return len(payload) // 2
    raise ValueError(f"unsupported literal kind: {kind!r}")


def _literal_children(value: PythonLiteral) -> tuple[PythonLiteral, ...]:
    if type(value) is not PythonLiteral:
        raise TypeError("literal tree nodes must be exact PythonLiteral records")
    if type(value.kind) is not LiteralKind:
        raise TypeError("literal kind must be LiteralKind")
    if type(value.items) is not tuple:
        raise TypeError("literal items must be a tuple")
    if value.kind is not LiteralKind.TUPLE and value.items:
        raise ValueError("only tuple literals contain items")
    if len(value.items) > MAX_LITERAL_NODES - 1:
        raise ValueError("literal node budget exceeded")
    if any(type(item) is not PythonLiteral for item in value.items):
        raise TypeError("literal items must be a tuple of PythonLiteral")
    return value.items


def _preflight_literal(root: PythonLiteral) -> None:
    """Validate a materialized tree without recursion or identity deduping."""
    stack: list[tuple[PythonLiteral, int, bool]] = [(root, 0, False)]
    active: set[int] = set()
    expanded_nodes = 0
    scheduled_nodes = 1
    payload_bytes = 0
    while stack:
        node, depth, leaving = stack.pop()
        identity = id(node)
        if leaving:
            active.remove(identity)
            continue
        if identity in active:
            raise ValueError("cyclic PythonLiteral tree")
        if depth > MAX_LITERAL_DEPTH:
            raise ValueError("literal depth budget exceeded")
        expanded_nodes += 1
        if expanded_nodes > MAX_LITERAL_NODES:
            raise ValueError("literal node budget exceeded")
        children = _literal_children(node)
        payload_bytes += _literal_payload_size(node.kind, node.payload)
        if payload_bytes > MAX_LITERAL_PAYLOAD_BYTES:
            raise ValueError("literal payload budget exceeded")
        if len(children) > MAX_LITERAL_NODES - scheduled_nodes:
            raise ValueError("literal node budget exceeded")
        scheduled_nodes += len(children)
        active.add(identity)
        stack.append((node, depth, True))
        for child in reversed(children):
            stack.append((child, depth + 1, False))


def _wire_node(data: Any, record_tag: tuple[str, str] | None = None
               ) -> tuple[LiteralKind, Any, list[Any]]:
    expected_fields = {"kind", "payload", "items"}
    if record_tag is not None:
        expected_fields.add(record_tag[0])
    if type(data) is not dict or set(data) != expected_fields:
        raise ValueError("python_literal: expected exact kind/payload/items fields")
    if record_tag is not None:
        tag_key, tag_value = record_tag
        if type(data[tag_key]) is not str or data[tag_key] != tag_value:
            raise ValueError("typed record discriminator mismatch")
    if type(data["kind"]) is not str:
        raise TypeError("literal wire kind must be an exact string")
    kind = LiteralKind(data["kind"])
    items = data["items"]
    if type(items) is not list:
        raise TypeError("literal wire items must be an array")
    if kind is not LiteralKind.TUPLE and items:
        raise ValueError("only tuple literals contain items")
    if len(items) > MAX_LITERAL_NODES - 1:
        raise ValueError("literal node budget exceeded")
    _literal_payload_size(kind, data["payload"])
    return kind, data["payload"], items


def _preflight_literal_dict(root: dict, *,
                            record_tag: tuple[str, str] | None = None) -> None:
    """Validate wire trees before constructing any nested record/tuple."""
    stack: list[tuple[dict, int, bool]] = [(root, 0, False)]
    active: set[int] = set()
    expanded_nodes = 0
    scheduled_nodes = 1
    payload_bytes = 0
    while stack:
        data, depth, leaving = stack.pop()
        identity = id(data)
        if leaving:
            active.remove(identity)
            continue
        if identity in active:
            raise ValueError("cyclic PythonLiteral wire tree")
        if depth > MAX_LITERAL_DEPTH:
            raise ValueError("literal depth budget exceeded")
        expanded_nodes += 1
        if expanded_nodes > MAX_LITERAL_NODES:
            raise ValueError("literal node budget exceeded")
        kind, payload, items = _wire_node(data, record_tag)
        payload_bytes += _literal_payload_size(kind, payload)
        if payload_bytes > MAX_LITERAL_PAYLOAD_BYTES:
            raise ValueError("literal payload budget exceeded")
        if len(items) > MAX_LITERAL_NODES - scheduled_nodes:
            raise ValueError("literal node budget exceeded")
        scheduled_nodes += len(items)
        for child in items:
            if type(child) is not dict:
                raise TypeError("literal wire items must contain exact objects")
        active.add(identity)
        stack.append((data, depth, True))
        for child in reversed(items):
            stack.append((child, depth + 1, False))


def _postorder(root, children_of, make_node):
    """Build one result per expanded occurrence using an explicit stack."""
    stack: list[tuple[Any, bool]] = [(root, False)]
    values: list[Any] = []
    while stack:
        node, leaving = stack.pop()
        children = children_of(node)
        if not leaving:
            stack.append((node, True))
            for child in reversed(children):
                stack.append((child, False))
            continue
        count = len(children)
        if count:
            child_values = values[-count:]
            del values[-count:]
        else:
            child_values = []
        values.append(make_node(node, child_values))
    if len(values) != 1:
        raise ValueError("invalid literal tree traversal")
    return values[0]


def _check_python_value_tree(root: Any, *, exact: bool) -> None:
    """Bound exact Python builtin trees before conversion to literal records."""
    stack: list[tuple[Any, int, bool]] = [(root, 0, False)]
    active: set[int] = set()
    expanded_nodes = 0
    scheduled_nodes = 1
    payload_bytes = 0
    while stack:
        value, depth, leaving = stack.pop()
        if leaving:
            active.remove(id(value))
            continue
        if depth > MAX_LITERAL_DEPTH:
            raise ValueError("literal depth budget exceeded")
        expanded_nodes += 1
        if expanded_nodes > MAX_LITERAL_NODES:
            raise ValueError("literal node budget exceeded")
        value_type = type(value)
        children: tuple[Any, ...] = ()
        if value is None or value is Ellipsis:
            size = 0
        elif value_type is bool:
            size = 1
        elif value_type is int:
            size = len(_int_to_decimal(value))
        elif value_type is float:
            size = 8
        elif value_type is complex:
            if not exact:
                raise TypeError("unsupported immutable literal type: complex")
            size = 16
        elif value_type is str:
            if len(value) > MAX_LITERAL_PAYLOAD_BYTES:
                raise ValueError("literal payload budget exceeded")
            if exact and _has_surrogate(value):
                size = 4 * len(value)
            else:
                size = _utf8_surrogatepass_size(value, MAX_LITERAL_PAYLOAD_BYTES)
        elif value_type is bytes:
            size = len(value)
        elif value_type is tuple:
            size = 0
            if id(value) in active:
                raise ValueError("cyclic Python tuple literal")
            children = value
            if len(children) > MAX_LITERAL_NODES - scheduled_nodes:
                raise ValueError("literal node budget exceeded")
            scheduled_nodes += len(children)
            active.add(id(value))
            stack.append((value, depth, True))
        else:
            raise TypeError(f"unsupported immutable literal type: {value_type.__name__}")
        payload_bytes += size
        if payload_bytes > MAX_LITERAL_PAYLOAD_BYTES:
            raise ValueError("literal payload budget exceeded")
        for child in reversed(children):
            stack.append((child, depth + 1, False))


def _python_scalar(value: Any, *, exact: bool) -> tuple[LiteralKind, str | bool | None]:
    value_type = type(value)
    if value is None:
        return LiteralKind.NONE, None
    if value is Ellipsis:
        return LiteralKind.ELLIPSIS, None
    if value_type is bool:
        return LiteralKind.BOOL, value
    if value_type is int:
        return LiteralKind.INT, _int_to_decimal(value)
    if value_type is float:
        return LiteralKind.FLOAT64, struct.pack(">d", value).hex()
    if value_type is complex:
        if not exact:
            raise TypeError("unsupported immutable literal type: complex")
        return LiteralKind.COMPLEX128, struct.pack(">dd", value.real, value.imag).hex()
    if value_type is str:
        if exact and _has_surrogate(value):
            return LiteralKind.STR_CODEPOINTS, "".join(f"{ord(char):08x}" for char in value)
        return LiteralKind.STR, value
    if value_type is bytes:
        return LiteralKind.BYTES, value.hex()
    raise TypeError(f"unsupported immutable literal type: {value_type.__name__}")


@dataclass(frozen=True, slots=True)
class PythonLiteral:
    """Builtin type/content; never an identity or execution proof.

    Integer payloads are bounded canonical decimal; floats use 16 lowercase
    hexadecimal IEEE-754 bits; complex values use real then imaginary binary64
    bits; bytes use lowercase hex. ``from_python`` defaults to the historical
    literal subset; pass ``exact=True`` for complex and lossless surrogate
    codepoint payloads.
    """

    kind: LiteralKind
    payload: str | bool | None = None
    items: tuple[PythonLiteral, ...] = ()

    def __post_init__(self) -> None:
        _preflight_literal(self)

    @classmethod
    def from_python(cls, value: Any, *, exact: bool = False) -> PythonLiteral:
        if type(exact) is not bool:
            raise TypeError("exact must be bool")
        _check_python_value_tree(value, exact=exact)

        def make(node: Any, children: list[PythonLiteral]) -> PythonLiteral:
            if type(node) is tuple:
                return cls(LiteralKind.TUPLE, items=tuple(children))
            kind, payload = _python_scalar(node, exact=exact)
            return cls(kind, payload)

        return _postorder(value, lambda node: node if type(node) is tuple else (), make)

    @classmethod
    def from_dict(cls, data: dict, *,
                  _record_tag: tuple[str, str] | None = None) -> PythonLiteral:
        """Decode the exact literal wire record after bounded iterative preflight."""
        if _record_tag is not None:
            if (type(_record_tag) is not tuple or len(_record_tag) != 2
                    or any(type(part) is not str or not part for part in _record_tag)
                    or _record_tag[0] in {"kind", "payload", "items"}):
                raise ValueError("invalid local PythonLiteral discriminator")
        _preflight_literal_dict(data, record_tag=_record_tag)

        def make(node: dict, children: list[PythonLiteral]) -> PythonLiteral:
            kind, payload, _ = _wire_node(node, _record_tag)
            return cls(kind, payload, tuple(children))

        return _postorder(data, lambda node: node["items"], make)

    def to_python(self) -> Any:
        _preflight_literal(self)

        def make(node: PythonLiteral, children: list[Any]) -> Any:
            kind, payload = node.kind, node.payload
            if kind is LiteralKind.NONE:
                return None
            if kind is LiteralKind.ELLIPSIS:
                return Ellipsis
            if kind is LiteralKind.TUPLE:
                return tuple(children)
            if kind is LiteralKind.BOOL or kind is LiteralKind.STR:
                return payload
            if kind is LiteralKind.STR_CODEPOINTS:
                return "".join(chr(int(payload[start:start + 8], 16))
                               for start in range(0, len(payload), 8))
            if kind is LiteralKind.INT:
                return _decimal_to_int(payload)
            if kind is LiteralKind.FLOAT64:
                return struct.unpack(">d", bytes.fromhex(payload))[0]
            if kind is LiteralKind.COMPLEX128:
                real, imag = struct.unpack(">dd", bytes.fromhex(payload))
                return complex(real, imag)
            if kind is LiteralKind.BYTES:
                return bytes.fromhex(payload)
            raise ValueError(f"unsupported literal kind: {kind!r}")

        return _postorder(self, lambda node: node.items, make)

    def as_dict(self) -> dict:
        _preflight_literal(self)

        def make(node: PythonLiteral, children: list[dict]) -> dict:
            return {"kind": node.kind.value, "payload": node.payload, "items": children}

        return _postorder(self, lambda node: node.items, make)


def literal_builtin_type(literal: PythonLiteral) -> type:
    """Return the exact builtin type named by a literal without materializing it."""
    _preflight_literal(literal)
    return {
        LiteralKind.NONE: type(None),
        LiteralKind.BOOL: bool,
        LiteralKind.INT: int,
        LiteralKind.FLOAT64: float,
        LiteralKind.COMPLEX128: complex,
        LiteralKind.STR: str,
        LiteralKind.STR_CODEPOINTS: str,
        LiteralKind.BYTES: bytes,
        LiteralKind.TUPLE: tuple,
        LiteralKind.ELLIPSIS: type(Ellipsis),
    }[literal.kind]


def require_exact_literal(literal: PythonLiteral) -> None:
    """Require the lossless payload profile used by the new Program core."""
    _preflight_literal(literal)
    pending = [literal]
    while pending:
        node = pending.pop()
        if node.kind is LiteralKind.STR and _has_surrogate(node.payload):
            raise ValueError("exact literal requires STR_CODEPOINTS for surrogate strings")
        pending.extend(reversed(node.items))


def require_legacy_literal(literal: PythonLiteral) -> None:
    """Reject kinds unavailable to historical SourceSemantics/OIR schemas."""
    _preflight_literal(literal)
    pending = [literal]
    while pending:
        node = pending.pop()
        if node.kind in (LiteralKind.COMPLEX128, LiteralKind.STR_CODEPOINTS):
            raise ValueError(f"legacy literal schema does not support {node.kind.value}")
        pending.extend(reversed(node.items))


__all__ = ["LiteralKind", "PythonLiteral", "literal_builtin_type",
           "require_exact_literal", "require_legacy_literal"]
