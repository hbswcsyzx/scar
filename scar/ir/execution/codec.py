"""Strict, explicitly tagged JSON for execution records, without graph proof.

The closed wire vocabulary comes from ExecutionModel's declared field types.
Tags never cause imports, artifact access or provider execution. Constructors
and field types are rechecked; canonical ProgramGraph/external-artifact links
still require the separate execution validator.
"""
from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
from functools import lru_cache
import json
import math
from types import UnionType
from typing import Union, get_args, get_origin, get_type_hints

from scar.ir.v2.ids import Identifier
from .model import ExecutionModel


SCHEMA = "scar.execution-model"
SCHEMA_VERSION = 1


def _tag(cls):
    return cls.__module__ + "." + cls.__qualname__


@lru_cache(maxsize=None)
def _record_schema(cls):
    hints = get_type_hints(cls)
    return tuple((field.name, hints[field.name]) for field in fields(cls))


@lru_cache(maxsize=1)
def _vocabulary():
    """Only types reachable through the fixed model schema may have wire tags."""
    vocabulary, visited = {}, set()

    def visit(expected):
        if expected in visited:
            return
        visited.add(expected)
        if get_origin(expected) in (Union, UnionType, tuple):
            for child in get_args(expected):
                if child is not Ellipsis:
                    visit(child)
            return
        if expected in (str, int, bool, float, type(None)):
            return
        if not isinstance(expected, type):
            raise TypeError(f"unsupported execution schema type: {expected!r}")
        if not (issubclass(expected, (Identifier, Enum)) or is_dataclass(expected)):
            raise TypeError(f"unsupported execution schema type: {expected!r}")
        name = _tag(expected)
        if name in vocabulary and vocabulary[name] is not expected:
            raise TypeError(f"conflicting execution wire tag: {name}")
        vocabulary[name] = expected
        if not issubclass(expected, (Identifier, Enum)):
            for _, child in _record_schema(expected):
                visit(child)

    visit(ExecutionModel)
    return vocabulary


def _fail(path, message):
    raise ValueError(f"{path}: {message}")


def _object(value, keys, path):
    if type(value) is not dict or any(type(key) is not str for key in value):
        _fail(path, "expected exact JSON object with string keys")
    if set(value) != set(keys):
        _fail(path, "missing or unknown fields")


def _concrete(value, expected, path, *, wire):
    """Choose a Union by its declared tag; never guess by matching field shape."""
    choices = get_args(expected) if get_origin(expected) in (Union, UnionType) else (expected,)
    if wire:
        if type(value) is dict:
            markers = [key for key in ("$record", "$id", "$enum") if key in value]
            if len(markers) != 1 or type(value[markers[0]]) is not str:
                _fail(path, "expected exactly one typed tag")
            actual = _vocabulary().get(value[markers[0]])
            if actual is None:
                _fail(path, "unknown type tag")
        else:
            actual = type(value)
    else:
        actual = type(value)
    for choice in choices:
        if get_origin(choice) is tuple:
            if actual is (list if wire else tuple):
                return choice
        elif actual is choice:
            return choice
    _fail(path, "tag or type does not match the declared field")


def _encode(value, expected, path):
    expected = _concrete(value, expected, path, wire=False)
    if get_origin(expected) is tuple:
        arguments = get_args(expected)
        if len(arguments) == 2 and arguments[1] is Ellipsis:
            return [_encode(child, arguments[0], f"{path}[{index}]")
                    for index, child in enumerate(value)]
        if len(value) != len(arguments):
            _fail(path, "incorrect tuple length")
        return [_encode(child, kind, f"{path}[{index}]")
                for index, (child, kind) in enumerate(zip(value, arguments))]
    if expected in (str, int, bool, float, type(None)):
        if expected is float and not math.isfinite(value):
            _fail(path, "non-finite number")
        return value
    if _vocabulary().get(_tag(expected)) is not expected:
        _fail(path, "type is not in execution vocabulary")
    if issubclass(expected, Identifier):
        # Preserve the original canonical program/v2 namespace and wire form.
        if type(value.value) is not str:
            _fail(path, "identifier value must be an exact string")
        value.__post_init__()
        if value.prefix != expected.prefix or value.wire != expected.prefix + ":" + value.value:
            _fail(path, "identifier namespace has been changed")
        return {"$id": _tag(expected), "kind": expected.prefix,
                "value": value.value, "wire": value.wire}
    if issubclass(expected, Enum):
        if type(value.value) not in (str, int, bool):
            _fail(path, "unsupported enum payload")
        if expected(value.value) is not value:
            _fail(path, "invalid enum member")
        return {"$enum": _tag(expected), "value": value.value}
    result = {name: _encode(getattr(value, name), kind, path + "." + name)
              for name, kind in _record_schema(expected)}
    value.__post_init__()
    return {"$record": _tag(expected), "fields": result}


def _decode(value, expected, path):
    expected = _concrete(value, expected, path, wire=True)
    if get_origin(expected) is tuple:
        arguments = get_args(expected)
        if len(arguments) == 2 and arguments[1] is Ellipsis:
            return tuple(_decode(child, arguments[0], f"{path}[{index}]")
                         for index, child in enumerate(value))
        if len(value) != len(arguments):
            _fail(path, "incorrect array length")
        return tuple(_decode(child, kind, f"{path}[{index}]")
                     for index, (child, kind) in enumerate(zip(value, arguments)))
    if expected in (str, int, bool, float, type(None)):
        if expected is float and not math.isfinite(value):
            _fail(path, "non-finite number")
        return value
    if issubclass(expected, Identifier):
        _object(value, ("$id", "kind", "value", "wire"), path)
        if value["$id"] != _tag(expected) or type(value["value"]) is not str:
            _fail(path, "invalid identifier tag or value")
        result = expected(value["value"])
        if (type(value["kind"]) is not str or value["kind"] != expected.prefix
                or type(value["wire"]) is not str or value["wire"] != result.wire):
            _fail(path, "identifier namespace or wire form does not match")
        return result
    if issubclass(expected, Enum):
        _object(value, ("$enum", "value"), path)
        if value["$enum"] != _tag(expected):
            _fail(path, "invalid enum tag")
        member = expected(value["value"])
        if type(value["value"]) is not type(member.value):
            _fail(path, "invalid enum payload type")
        return member
    _object(value, ("$record", "fields"), path)
    if value["$record"] != _tag(expected):
        _fail(path, "invalid record tag")
    schema = _record_schema(expected)
    _object(value["fields"], (name for name, _ in schema), path + ".fields")
    return expected(**{name: _decode(value["fields"][name], kind, path + "." + name)
                       for name, kind in schema})


def to_dict(model: ExecutionModel) -> dict:
    """Recheck record shape/local invariants; do not perform graph validation."""
    try:
        return {"schema": SCHEMA, "schema_version": SCHEMA_VERSION,
                "model": _encode(model, ExecutionModel, "model")}
    except (TypeError, AttributeError, RecursionError) as error:
        raise ValueError(f"invalid execution record: {error}") from error


def from_dict(data: dict) -> ExecutionModel:
    """Decode only the fixed tagged schema; no defaults hide missing fields."""
    try:
        _object(data, ("schema", "schema_version", "model"), "document")
        if type(data["schema"]) is not str or data["schema"] != SCHEMA:
            _fail("document", "unexpected schema")
        if type(data["schema_version"]) is not int or data["schema_version"] != SCHEMA_VERSION:
            _fail("document", "unsupported schema_version")
        return _decode(data["model"], ExecutionModel, "model")
    except (TypeError, AttributeError, RecursionError) as error:
        raise ValueError(f"invalid execution document: {error}") from error


def dumps(model: ExecutionModel) -> str:
    return json.dumps(to_dict(model), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _constant(value):
    raise ValueError(f"non-finite JSON number: {value}")


def loads(text: str) -> ExecutionModel:
    if type(text) is not str:
        raise ValueError("execution JSON text must be an exact string")
    try:
        data = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
    except RecursionError as error:
        raise ValueError("execution JSON nesting is too deep") from error
    return from_dict(data)


__all__ = ["SCHEMA", "SCHEMA_VERSION", "to_dict", "from_dict", "dumps", "loads"]
