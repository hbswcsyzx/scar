"""Strict JSON codec for the immutable program graph records."""
from __future__ import annotations

from dataclasses import fields
import json
from typing import Any

from scar.ir.record_codec import decode, encode, loads as _loads
from scar.ir.v2._validation import record_errors

from scar.ir.program.model import LocalBindingValue, Operation, ProgramGraph


SCHEMA = "scar.program-graph"
SCHEMA_VERSION = 5
_GRAPH_FIELDS = frozenset(item.name for item in fields(ProgramGraph))
_BINDING_FIELDS = frozenset({"binding_definitions", "binding_reads"})
_RESOURCE_FIELDS = frozenset({"resources", "resource_requirements", "resource_uses",
                              "resource_locations"})
_ENVIRONMENT_FIELDS = frozenset({"environments", "function_entries"})
_V4_GRAPH_FIELDS = _GRAPH_FIELDS - _ENVIRONMENT_FIELDS
_V1_V2_GRAPH_FIELDS = _V4_GRAPH_FIELDS - _BINDING_FIELDS - _RESOURCE_FIELDS
_V3_GRAPH_FIELDS = _V4_GRAPH_FIELDS - _RESOURCE_FIELDS
_V1_V2_ENVELOPE_FIELDS = frozenset({"schema", "schema_version"}) | _V1_V2_GRAPH_FIELDS
_V3_ENVELOPE_FIELDS = frozenset({"schema", "schema_version"}) | _V3_GRAPH_FIELDS
_V4_ENVELOPE_FIELDS = frozenset({"schema", "schema_version"}) | _V4_GRAPH_FIELDS
_V5_ENVELOPE_FIELDS = frozenset({"schema", "schema_version"}) | _GRAPH_FIELDS


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
    """Preserve v2/v3/v4 encoding; explicit environments require v5."""
    _require_record_and_graph_valid(graph)
    has_binding_capability = (
        bool(graph.binding_definitions or graph.binding_reads)
        or any(isinstance(value, LocalBindingValue) for value in graph.values))
    encoded = encode(graph)
    if graph.environments:
        document = {"schema": SCHEMA, "schema_version": 5, **encoded}
    elif any(getattr(graph, name) for name in _RESOURCE_FIELDS):
        document = {"schema": SCHEMA, "schema_version": 4,
                    **{name: encoded[name] for name in _V4_GRAPH_FIELDS}}
    elif has_binding_capability:
        document = {"schema": SCHEMA, "schema_version": 3,
                    **{name: encoded[name] for name in _V3_GRAPH_FIELDS}}
    else:
        document = {"schema": SCHEMA, "schema_version": 2,
                    **{name: encoded[name] for name in _V1_V2_GRAPH_FIELDS}}
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
    """Decode exact v5 fields or strictly migrate historical v1/v2/v3/v4."""
    if type(payload) is not str:
        raise TypeError("program graph JSON payload must be str")
    document: Any = _loads(payload)
    if type(document) is not dict:
        raise ValueError("program graph document has incorrect top-level fields")
    if not {"schema", "schema_version"} <= set(document):
        raise ValueError("program graph document has incorrect top-level fields")
    if document["schema"] != SCHEMA:
        raise ValueError("unsupported program graph schema")
    version = document["schema_version"]
    if type(version) is not int or version not in (1, 2, 3, 4, SCHEMA_VERSION):
        raise ValueError("unsupported program graph schema version")
    expected_fields = {1: _V1_V2_ENVELOPE_FIELDS, 2: _V1_V2_ENVELOPE_FIELDS,
                       3: _V3_ENVELOPE_FIELDS, 4: _V4_ENVELOPE_FIELDS,
                       5: _V5_ENVELOPE_FIELDS}[version]
    if set(document) != expected_fields:
        raise ValueError("program graph document has incorrect top-level fields")
    graph_fields = {1: _V1_V2_GRAPH_FIELDS, 2: _V1_V2_GRAPH_FIELDS,
                    3: _V3_GRAPH_FIELDS, 4: _V4_GRAPH_FIELDS,
                    5: _GRAPH_FIELDS}[version]
    record = {name: document[name] for name in graph_fields}
    if version == 1:
        record = _upgrade_v1_record(record)
    if version in (1, 2):
        record["binding_definitions"] = []
        record["binding_reads"] = []
    if version < 4:
        record.update({name: [] for name in _RESOURCE_FIELDS})
    if version < 5:
        record.update({name: [] for name in _ENVIRONMENT_FIELDS})
    graph = decode(ProgramGraph, record)
    if version == 3 and not (
            graph.binding_definitions or graph.binding_reads
            or any(isinstance(value, LocalBindingValue) for value in graph.values)):
        raise ValueError("schema version 3 requires local-binding graph capability")
    if version == 4 and not any(getattr(graph, name) for name in _RESOURCE_FIELDS):
        raise ValueError("schema version 4 requires explicit resource graph capability")
    if version == 5 and not graph.environments:
        raise ValueError("schema version 5 requires explicit environment graph capability")
    _require_record_and_graph_valid(graph)
    return graph


__all__ = ["SCHEMA", "SCHEMA_VERSION", "dumps", "loads"]
