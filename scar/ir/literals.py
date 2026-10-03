"""Exact immutable Python literals shared by static and optimization IR.

This module intentionally has no dependency on IR v2, so both the static
semantics overlay and OIR can use the same typed literal record without an
import cycle.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
import struct


class LiteralKind(str, Enum):
    NONE = "none"
    BOOL = "bool"
    INT = "int"
    FLOAT64 = "float64"
    STR = "str"
    BYTES = "bytes"
    TUPLE = "tuple"
    ELLIPSIS = "ellipsis"


@dataclass(frozen=True, slots=True)
class PythonLiteral:
    """Exact builtin type/content, including float bits; never identity proof.

    Integers use canonical decimal strings and bytes use lowercase hexadecimal.
    Floats use big-endian IEEE754 binary64 hex, preserving signed zero/NaN bits.
    Mutable list/dict/set constructions are operation recipes, never literals.
    """

    kind: LiteralKind
    payload: str | bool | None = None
    items: tuple[PythonLiteral, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.kind, LiteralKind):
            raise TypeError("literal kind must be LiteralKind")
        if type(self.items) is not tuple or any(type(x) is not PythonLiteral for x in self.items):
            raise TypeError("literal items must be a tuple of PythonLiteral")
        if self.kind is not LiteralKind.TUPLE and self.items:
            raise ValueError("only tuple literals contain items")
        if self.kind in (LiteralKind.NONE, LiteralKind.ELLIPSIS, LiteralKind.TUPLE):
            if self.payload is not None:
                raise ValueError("this literal kind has no scalar payload")
        elif self.kind is LiteralKind.BOOL:
            if type(self.payload) is not bool:
                raise ValueError("bool literal requires a bool payload")
        elif type(self.payload) is not str:
            raise ValueError("literal requires a string payload")
        elif self.kind is LiteralKind.INT and not re.fullmatch(r"0|-?[1-9][0-9]*", self.payload):
            raise ValueError("integer payload must be canonical decimal")
        elif self.kind is LiteralKind.FLOAT64 and not re.fullmatch(r"[0-9a-f]{16}", self.payload):
            raise ValueError("float64 payload must be 16 lowercase hexadecimal digits")
        elif self.kind is LiteralKind.BYTES and not re.fullmatch(r"(?:[0-9a-f]{2})*", self.payload):
            raise ValueError("bytes payload must be canonical hexadecimal")

    @classmethod
    def from_python(cls, value) -> PythonLiteral:
        if value is None:
            return cls(LiteralKind.NONE)
        if value is Ellipsis:
            return cls(LiteralKind.ELLIPSIS)
        kind = type(value)
        if kind is bool:
            return cls(LiteralKind.BOOL, value)
        if kind is int:
            return cls(LiteralKind.INT, str(value))
        if kind is float:
            return cls(LiteralKind.FLOAT64, struct.pack(">d", value).hex())
        if kind is str:
            return cls(LiteralKind.STR, value)
        if kind is bytes:
            return cls(LiteralKind.BYTES, value.hex())
        if kind is tuple:
            return cls(LiteralKind.TUPLE, items=tuple(cls.from_python(item) for item in value))
        raise TypeError(f"unsupported immutable literal type: {kind.__name__}")

    def to_python(self):
        self.__post_init__()
        if self.kind is LiteralKind.NONE:
            return None
        if self.kind is LiteralKind.ELLIPSIS:
            return Ellipsis
        if self.kind is LiteralKind.TUPLE:
            return tuple(item.to_python() for item in self.items)
        if self.kind is LiteralKind.INT:
            return int(self.payload)
        if self.kind is LiteralKind.FLOAT64:
            return struct.unpack(">d", bytes.fromhex(self.payload))[0]
        if self.kind is LiteralKind.BYTES:
            return bytes.fromhex(self.payload)
        return self.payload

    def as_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "payload": self.payload,
            "items": [item.as_dict() for item in self.items],
        }


__all__ = ["LiteralKind", "PythonLiteral"]
