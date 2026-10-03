"""Strict wire facade for source fragment and move records.

The record types live with the core optimization IR so that TransformDelta can
reference them without importing the source-control-flow overlay. This module
provides schema-versioned, exact-field readers and writers for those records.
"""
from __future__ import annotations

from typing import Any

from .record_codec import decode, encode, loads
from .v2._validation import record_errors
from .v2.optimization import SourceFragment, StaticSourceMove


FRAGMENT_SCHEMA = "scar.source-fragment.v2"
MOVE_SCHEMA = "scar.static-source-move.v2"
SCHEMA_VERSION = 1


def _pack(schema: str, field: str, value: Any, expected: type) -> dict[str, Any]:
    errors = record_errors(value, expected, field)
    if errors:
        raise ValueError("invalid " + field + ": " + "; ".join(errors))
    return {"schema": schema, "schema_version": SCHEMA_VERSION,
            field: encode(value)}


def _unpack(document: Any, schema: str, field: str, expected: type):
    if (type(document) is not dict
            or set(document) != {"schema", "schema_version", field}
            or document["schema"] != schema
            or type(document["schema_version"]) is not int
            or document["schema_version"] != SCHEMA_VERSION):
        raise ValueError("unsupported " + field + " schema or fields")
    value = decode(expected, document[field])
    errors = record_errors(value, expected, field)
    if errors:
        raise ValueError("invalid " + field + ": " + "; ".join(errors))
    return value


def source_fragment_to_dict(fragment: SourceFragment) -> dict[str, Any]:
    return _pack(FRAGMENT_SCHEMA, "fragment", fragment, SourceFragment)


def source_fragment_from_dict(document: Any) -> SourceFragment:
    return _unpack(document, FRAGMENT_SCHEMA, "fragment", SourceFragment)


def source_fragment_to_json(fragment: SourceFragment) -> str:
    import json
    return json.dumps(source_fragment_to_dict(fragment), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def source_fragment_from_json(payload: str) -> SourceFragment:
    return source_fragment_from_dict(loads(payload))


def static_source_move_to_dict(move: StaticSourceMove) -> dict[str, Any]:
    return _pack(MOVE_SCHEMA, "move", move, StaticSourceMove)


def static_source_move_from_dict(document: Any) -> StaticSourceMove:
    return _unpack(document, MOVE_SCHEMA, "move", StaticSourceMove)


def static_source_move_to_json(move: StaticSourceMove) -> str:
    import json
    return json.dumps(static_source_move_to_dict(move), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def static_source_move_from_json(payload: str) -> StaticSourceMove:
    return static_source_move_from_dict(loads(payload))


__all__ = [
    "SourceFragment", "StaticSourceMove", "FRAGMENT_SCHEMA", "MOVE_SCHEMA",
    "SCHEMA_VERSION", "source_fragment_to_dict", "source_fragment_from_dict",
    "source_fragment_to_json", "source_fragment_from_json",
    "static_source_move_to_dict", "static_source_move_from_dict",
    "static_source_move_to_json", "static_source_move_from_json",
]
