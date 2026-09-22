"""Strict wire encoding for small typed analysis records, independent of graphs."""
from dataclasses import fields, is_dataclass
from enum import Enum
from functools import lru_cache
import json
import math
from types import UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

from .v2.ids import Identifier, LogicalValueID, ValueVersionID
from .v2._validation import record_errors


@lru_cache(maxsize=None)
def _schema(cls):
    return fields(cls), get_type_hints(cls)


def encode(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (Identifier, ValueVersionID)):
        return value.as_dict()
    if is_dataclass(value):
        return {item.name: encode(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, (tuple, list)):
        return [encode(item) for item in value]
    if isinstance(value, dict):
        if any(type(key) is not str for key in value):
            raise ValueError("wire object keys must be strings")
        return {key: encode(item) for key, item in value.items()}
    if type(value) is float and not math.isfinite(value):
        raise ValueError("non-finite wire number")
    if value is None or type(value) in (str, int, float, bool):
        return value
    raise ValueError(f"unsupported wire value: {type(value).__name__}")


def decode(expected, value):
    origin, arguments = get_origin(expected), get_args(expected)
    if expected is Any:
        return encode(value)
    if origin in (Union, UnionType):
        for choice in arguments:
            try:
                return decode(choice, value)
            except (ValueError, TypeError):
                pass
        raise ValueError("value does not match union type")
    if origin in (tuple, list):
        if type(value) is not list:
            raise ValueError("sequence must be a wire array")
        if origin is tuple and not (len(arguments) == 2 and arguments[1] is Ellipsis):
            if len(arguments) != len(value):
                raise ValueError("incorrect fixed tuple length")
            return tuple(decode(kind, item) for kind, item in zip(arguments, value))
        result = [decode(arguments[0], item) for item in value]
        return tuple(result) if origin is tuple else result
    if origin is dict:
        if type(value) is not dict:
            raise ValueError("mapping must be a wire object")
        return {decode(arguments[0], key): decode(arguments[1], item) for key, item in value.items()}
    if isinstance(expected, type) and issubclass(expected, Enum):
        if type(value) is not str:
            raise ValueError("enum must be a string")
        return expected(value)
    if isinstance(expected, type) and issubclass(expected, Identifier):
        if type(value) is not dict or set(value) != {"kind", "value", "wire"}:
            raise ValueError("invalid typed ID fields")
        result = expected(value["value"])
        if value["kind"] != result.prefix or value["wire"] != result.wire:
            raise ValueError("typed ID namespace/wire mismatch")
        return result
    if expected is ValueVersionID:
        if type(value) is not dict or set(value) != {"logical_value", "version", "wire"}:
            raise ValueError("invalid value-version fields")
        result = ValueVersionID(decode(LogicalValueID, value["logical_value"]), decode(int, value["version"]))
        if result.wire != value["wire"]:
            raise ValueError("value-version wire mismatch")
        return result
    if is_dataclass(expected):
        members, hints = _schema(expected)
        if type(value) is not dict or set(value) != {item.name for item in members}:
            raise ValueError("typed record fields mismatch")
        result = expected(**{name: decode(hints[name], item) for name, item in value.items()})
        errors = record_errors(result, expected, expected.__name__)
        if errors:
            raise ValueError("; ".join(errors))
        return result
    if expected is float:
        if type(value) in (float, int) and math.isfinite(value):
            return value
        raise ValueError("expected finite numeric value")
    if type(value) is not expected:
        raise ValueError(f"expected {expected}, received {type(value)}")
    return value


def loads(payload):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result
    def finite_float(text):
        value = float(text)
        if not math.isfinite(value):
            raise ValueError("non-finite JSON number")
        return value
    return json.loads(payload, object_pairs_hook=unique, parse_float=finite_float,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("non-finite JSON number")))


__all__ = ["encode", "decode", "loads"]
