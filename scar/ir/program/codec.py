"""Strict JSON codec for the immutable program graph records."""
from __future__ import annotations

from dataclasses import fields
import json
from typing import Any

from scar.ir.record_codec import decode, encode, loads as _loads
from scar.ir.v2._validation import record_errors

from scar.ir.program.model import ProgramGraph


SCHEMA = "scar.program-graph"
SCHEMA_VERSION = 1
_GRAPH_FIELDS = frozenset(item.name for item in fields(ProgramGraph))
_ENVELOPE_FIELDS = frozenset({"schema", "schema_version"}) | _GRAPH_FIELDS


def _require_record_and_graph_valid(graph: ProgramGraph) -> None:
    if type(graph) is not ProgramGraph:
        raise TypeError("program graph must be ProgramGraph")
    errors = record_errors(graph, ProgramGraph, "ProgramGraph")
    if errors:
        raise ValueError("invalid program graph record: " + "; ".join(errors))
    # Keep the record vocabulary importable separately from graph queries.
    # Serialization always runs the complete bounded graph validator.
    from scar.ir.program.validation import require_valid

    require_valid(graph)


def dumps(graph: ProgramGraph) -> str:
    """Encode a fully validated ProgramGraph using the fixed N1 envelope."""
    _require_record_and_graph_valid(graph)
    document = {"schema": SCHEMA, "schema_version": SCHEMA_VERSION, **encode(graph)}
    return json.dumps(document, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def loads(payload: str) -> ProgramGraph:
    """Decode exact fields, retain tuples, and reject duplicate registry IDs."""
    if type(payload) is not str:
        raise TypeError("program graph JSON payload must be str")
    document: Any = _loads(payload)
    if type(document) is not dict or set(document) != _ENVELOPE_FIELDS:
        raise ValueError("program graph document has incorrect top-level fields")
    if document["schema"] != SCHEMA:
        raise ValueError("unsupported program graph schema")
    version = document["schema_version"]
    if type(version) is not int or version != SCHEMA_VERSION:
        raise ValueError("unsupported program graph schema version")
    record = {name: document[name] for name in _GRAPH_FIELDS}
    graph = decode(ProgramGraph, record)
    _require_record_and_graph_valid(graph)
    return graph


__all__ = ["SCHEMA", "SCHEMA_VERSION", "dumps", "loads"]
