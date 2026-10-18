"""Strict wire encoding for small typed analysis records, independent of graphs."""
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from enum import Enum
from functools import lru_cache
import json
import math
from types import UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

from .literals import PythonLiteral, _preflight_literal
from .v2.ids import Identifier, LogicalValueID, ValueVersionID
from .v2._validation import record_errors


@lru_cache(maxsize=None)
def _schema(cls):
    return fields(cls), get_type_hints(cls)


def _record_tags(tags):
    """Validate local, explicit record discriminators without a global registry."""
    if tags is None:
        return {}
    if not isinstance(tags, Mapping):
        raise TypeError("record_tags must be a mapping of dataclass types to tags")
    result, seen = {}, set()
    for cls, tag in tags.items():
        if (not isinstance(cls, type) or not is_dataclass(cls)
                or issubclass(cls, (Identifier, Enum)) or cls is ValueVersionID):
            raise TypeError("record tag keys must be ordinary dataclass types")
        if (type(tag) is not tuple or len(tag) != 2
                or any(type(item) is not str or not item for item in tag)):
            raise ValueError("record tags must be pairs of nonempty exact strings")
        if tag[0] in {field.name for field in fields(cls)}:
            raise ValueError("record tag conflicts with a dataclass field")
        if tag in seen:
            raise ValueError("record discriminator tags must be distinct")
        seen.add(tag)
        result[cls] = tag
    return result


def encode(value, *, record_tags=None):
    """Encode records, optionally tagging exact dataclass variants locally.

    The default representation is unchanged. Tags are wire-only fields and
    never become dataclass constructor arguments or an authority registry.
    """
    return _encode(value, _record_tags(record_tags))


def _encode(value, tags):
    if type(value) is PythonLiteral:
        _preflight_literal(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (Identifier, ValueVersionID)):
        return value.as_dict()
    if is_dataclass(value):
        document = {item.name: _encode(getattr(value, item.name), tags) for item in fields(value)}
        tag = tags.get(type(value))
        if tag is not None:
            document[tag[0]] = tag[1]
        return document
    if isinstance(value, (tuple, list)):
        return [_encode(item, tags) for item in value]
    if isinstance(value, dict):
        if any(type(key) is not str for key in value):
            raise ValueError("wire object keys must be strings")
        return {key: _encode(item, tags) for key, item in value.items()}
    if type(value) is float and not math.isfinite(value):
        raise ValueError("non-finite wire number")
    if value is None or type(value) in (str, int, float, bool):
        return value
    raise ValueError(f"unsupported wire value: {type(value).__name__}")


def decode(expected, value, *, record_tags=None):
    """Decode exact fields and optional local variant tags before construction."""
    return _decode(expected, value, _record_tags(record_tags))


def _decode(expected, value, tags):
    origin, arguments = get_origin(expected), get_args(expected)
    if expected is Any:
        return _encode(value, tags)
    if origin in (Union, UnionType):
        for choice in arguments:
            try:
                return _decode(choice, value, tags)
            except (ValueError, TypeError):
                pass
        raise ValueError("value does not match union type")
    if origin in (tuple, list):
        if type(value) is not list:
            raise ValueError("sequence must be a wire array")
        if origin is tuple and not (len(arguments) == 2 and arguments[1] is Ellipsis):
            if len(arguments) != len(value):
                raise ValueError("incorrect fixed tuple length")
            return tuple(_decode(kind, item, tags) for kind, item in zip(arguments, value))
        result = [_decode(arguments[0], item, tags) for item in value]
        return tuple(result) if origin is tuple else result
    if origin is dict:
        if type(value) is not dict:
            raise ValueError("mapping must be a wire object")
        return {_decode(arguments[0], key, tags): _decode(arguments[1], item, tags)
                for key, item in value.items()}
    if expected is PythonLiteral:
        tag = tags.get(PythonLiteral)
        return PythonLiteral.from_dict(value, _record_tag=tag)
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
        result = ValueVersionID(_decode(LogicalValueID, value["logical_value"], tags),
                                _decode(int, value["version"], tags))
        if result.wire != value["wire"]:
            raise ValueError("value-version wire mismatch")
        return result
    if is_dataclass(expected):
        members, hints = _schema(expected)
        tag = tags.get(expected)
        field_names = {item.name for item in members}
        expected_fields = field_names | ({tag[0]} if tag is not None else set())
        if type(value) is not dict or set(value) != expected_fields:
            raise ValueError("typed record fields mismatch")
        if tag is not None and (type(value[tag[0]]) is not str or value[tag[0]] != tag[1]):
            raise ValueError("typed record discriminator mismatch")
        result = expected(**{item.name: _decode(hints[item.name], value[item.name], tags)
                             for item in members})
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
