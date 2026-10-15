"""Strict JSON codec for the immutable program graph records."""
from __future__ import annotations

from dataclasses import fields
import json
from typing import Any

from scar.ir.record_codec import decode, encode, loads as _loads
from scar.ir.v2._validation import record_errors

from scar.ir.program.model import Operation, ProgramGraph


SCHEMA = "scar.program-graph"
SCHEMA_VERSION = 2
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
    """Encode a fully validated ProgramGraph using schema version 2."""
    _require_record_and_graph_valid(graph)
    document = {"schema": SCHEMA, "schema_version": SCHEMA_VERSION, **encode(graph)}
    return json.dumps(document, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def _upgrade_v1_record(record: dict[str, Any]) -> dict[str, Any]:
    """Add only the N2 Operation field omitted by historical schema v1."""
    operations = record.get("operations")
    if type(operations) is not list:
        # Let the strict typed decoder report malformed collection shapes.
        return record
    upgraded_operations = []
    for operation in operations:
        if type(operation) is not dict:
            # Let the strict typed decoder report malformed operation records.
            upgraded_operations.append(operation)
            continue
        if "completions" in operation:
            raise ValueError("schema version 1 cannot contain Operation.completions")
        if "invoke_arguments" in operation:
            raise ValueError("schema version 1 cannot contain Operation.invoke_arguments")
        terminator = operation.get("terminator")
        if type(terminator) is dict and terminator.get("kind") == "INVOKE":
            raise ValueError("schema version 1 cannot contain INVOKE terminators")
        upgraded = dict(operation)
        upgraded["completions"] = []
        upgraded["invoke_arguments"] = []
        upgraded_operations.append(upgraded)

    values = record.get("values")
    if type(values) is list:
        for value in values:
            if (type(value) is dict and "referent_identity" in value
                    and type(value.get("origin")) is dict
                    and set(value["origin"]) == {"value"}):
                raise ValueError("schema version 1 cannot contain literal ReferenceValue origins")

    upgraded_record = dict(record)
    upgraded_record["operations"] = upgraded_operations
    return upgraded_record


def loads(payload: str) -> ProgramGraph:
    """Decode exact v2 fields or strictly migrate historical v1 records."""
    if type(payload) is not str:
        raise TypeError("program graph JSON payload must be str")
    document: Any = _loads(payload)
    if type(document) is not dict or set(document) != _ENVELOPE_FIELDS:
        raise ValueError("program graph document has incorrect top-level fields")
    if document["schema"] != SCHEMA:
        raise ValueError("unsupported program graph schema")
    version = document["schema_version"]
    if type(version) is not int or version not in (1, SCHEMA_VERSION):
        raise ValueError("unsupported program graph schema version")
    record = {name: document[name] for name in _GRAPH_FIELDS}
    if version == 1:
        record = _upgrade_v1_record(record)
    graph = decode(ProgramGraph, record)
    _require_record_and_graph_valid(graph)
    return graph


__all__ = ["SCHEMA", "SCHEMA_VERSION", "dumps", "loads"]
