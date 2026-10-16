"""Strict JSON codec for the immutable program graph records."""
from __future__ import annotations

from dataclasses import fields
import json
from typing import Any

from scar.ir.record_codec import decode, encode, loads as _loads
from scar.ir.v2._validation import record_errors

from scar.ir.program.model import LocalBindingValue, Operation, ProgramGraph, ProtocolValue
from scar.ir.program.control import (
    PendingDispatchTerminator, ProtocolValueKind, ProtocolValueType,
)
from scar.ir.program.cleanup import CleanupRouteTerminator


SCHEMA = "scar.program-graph"
SCHEMA_VERSION = 9
_GRAPH_FIELDS = frozenset(item.name for item in fields(ProgramGraph))
_BINDING_FIELDS = frozenset({"binding_definitions", "binding_reads"})
_RESOURCE_FIELDS = frozenset({"resources", "resource_requirements", "resource_uses",
                              "resource_locations"})
_ENVIRONMENT_FIELDS = frozenset({"environments", "function_entries"})
_CONTROL_FIELDS = frozenset({"control_scopes", "control_ports", "exception_packets",
                             "pending_completions"})
_PROVIDER_FIELDS = frozenset({"provider_envelopes", "provider_regions", "provider_bindings"})
_NATIVE_FIELDS = frozenset({"native_boundaries", "boundary_relations"})
_CLEANUP_FIELDS = frozenset({"handled_context_domains", "cleanup_interfaces", "cleanup_enters",
                             "cleanup_resumes", "cleanup_replacements", "handled_context_reads"})
_V8_GRAPH_FIELDS = _GRAPH_FIELDS - _CLEANUP_FIELDS
_V7_GRAPH_FIELDS = _V8_GRAPH_FIELDS - _NATIVE_FIELDS
_V6_GRAPH_FIELDS = _V7_GRAPH_FIELDS - _PROVIDER_FIELDS
_V5_GRAPH_FIELDS = _V6_GRAPH_FIELDS - _CONTROL_FIELDS
_V4_GRAPH_FIELDS = _V5_GRAPH_FIELDS - _ENVIRONMENT_FIELDS
_V1_V2_GRAPH_FIELDS = _V4_GRAPH_FIELDS - _BINDING_FIELDS - _RESOURCE_FIELDS
_V3_GRAPH_FIELDS = _V4_GRAPH_FIELDS - _RESOURCE_FIELDS
_V1_V2_ENVELOPE_FIELDS = frozenset({"schema", "schema_version"}) | _V1_V2_GRAPH_FIELDS
_V3_ENVELOPE_FIELDS = frozenset({"schema", "schema_version"}) | _V3_GRAPH_FIELDS
_V4_ENVELOPE_FIELDS = frozenset({"schema", "schema_version"}) | _V4_GRAPH_FIELDS
_V5_ENVELOPE_FIELDS = frozenset({"schema", "schema_version"}) | _V5_GRAPH_FIELDS
_V6_ENVELOPE_FIELDS = frozenset({"schema", "schema_version"}) | _V6_GRAPH_FIELDS
_V7_ENVELOPE_FIELDS = frozenset({"schema", "schema_version"}) | _V7_GRAPH_FIELDS
_V8_ENVELOPE_FIELDS = frozenset({"schema", "schema_version"}) | _V8_GRAPH_FIELDS
_V9_ENVELOPE_FIELDS = frozenset({"schema", "schema_version"}) | _GRAPH_FIELDS
_CLEANUP_RECORD_TAGS = {CleanupRouteTerminator: ("kind", "CLEANUP_ROUTE")}


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


def _has_cleanup_capability(graph: ProgramGraph) -> bool:
    """Detect C1 even when declarations omit the required context domain."""
    return (
        any(getattr(graph, name) for name in _CLEANUP_FIELDS)
        or any(isinstance(value, ProtocolValue)
               and value.protocol is ProtocolValueKind.SAVED_HANDLED_CONTEXT
               for value in graph.values)
        or any(isinstance(operation.terminator, CleanupRouteTerminator)
               for operation in graph.operations)
        or any(isinstance(value_type, ProtocolValueType)
               and value_type.protocol is ProtocolValueKind.SAVED_HANDLED_CONTEXT
               for region in graph.regions for port in region.exits for value_type in port.types)
        or any(isinstance(value_type, ProtocolValueType)
               and value_type.protocol is ProtocolValueKind.SAVED_HANDLED_CONTEXT
               for operation in graph.operations for signature in operation.completions
               for value_type in signature.types)
    )


def dumps(graph: ProgramGraph) -> str:
    """Preserve v2–v8 encoding; synchronous cleanup requires explicit v9."""
    _require_record_and_graph_valid(graph)
    if _has_cleanup_capability(graph) and not graph.handled_context_domains:
        raise ValueError("cleanup capability requires explicit handled-context domains")
    has_binding_capability = (
        bool(graph.binding_definitions or graph.binding_reads)
        or any(isinstance(value, LocalBindingValue) for value in graph.values))
    encoded = encode(graph, record_tags=_CLEANUP_RECORD_TAGS)
    if graph.handled_context_domains:
        document = {"schema": SCHEMA, "schema_version": 9, **encoded}
    elif graph.native_boundaries:
        document = {"schema": SCHEMA, "schema_version": 8,
                    **{name: encoded[name] for name in _V8_GRAPH_FIELDS}}
    elif graph.provider_envelopes:
        document = {"schema": SCHEMA, "schema_version": 7,
                    **{name: encoded[name] for name in _V7_GRAPH_FIELDS}}
    elif graph.control_scopes:
        document = {"schema": SCHEMA, "schema_version": 6,
                    **{name: encoded[name] for name in _V6_GRAPH_FIELDS}}
    elif graph.environments:
        document = {"schema": SCHEMA, "schema_version": 5,
                    **{name: encoded[name] for name in _V5_GRAPH_FIELDS}}
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
    """Decode exact v9 fields or strictly migrate historical v1–v8."""
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
    if type(version) is not int or version not in (1, 2, 3, 4, 5, 6, 7, 8, SCHEMA_VERSION):
        raise ValueError("unsupported program graph schema version")
    expected_fields = {1: _V1_V2_ENVELOPE_FIELDS, 2: _V1_V2_ENVELOPE_FIELDS,
                       3: _V3_ENVELOPE_FIELDS, 4: _V4_ENVELOPE_FIELDS,
                       5: _V5_ENVELOPE_FIELDS, 6: _V6_ENVELOPE_FIELDS,
                       7: _V7_ENVELOPE_FIELDS, 8: _V8_ENVELOPE_FIELDS,
                       9: _V9_ENVELOPE_FIELDS}[version]
    if set(document) != expected_fields:
        raise ValueError("program graph document has incorrect top-level fields")
    graph_fields = {1: _V1_V2_GRAPH_FIELDS, 2: _V1_V2_GRAPH_FIELDS,
                    3: _V3_GRAPH_FIELDS, 4: _V4_GRAPH_FIELDS,
                    5: _V5_GRAPH_FIELDS, 6: _V6_GRAPH_FIELDS,
                    7: _V7_GRAPH_FIELDS, 8: _V8_GRAPH_FIELDS, 9: _GRAPH_FIELDS}[version]
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
    if version < 6:
        record.update({name: [] for name in _CONTROL_FIELDS})
    if version < 7:
        record.update({name: [] for name in _PROVIDER_FIELDS})
    if version < 8:
        record.update({name: [] for name in _NATIVE_FIELDS})
    if version < 9:
        record.update({name: [] for name in _CLEANUP_FIELDS})
        # C0's dispatch wire is unchanged. C1 routes use an explicit new tag;
        # accepting it under an older schema would silently upgrade capability.
        operations = record.get("operations")
        if type(operations) is list:
            for operation in operations:
                term = operation.get("terminator") if type(operation) is dict else None
                if type(term) is dict and term.get("kind") == "CLEANUP_ROUTE":
                    raise ValueError("historical schema cannot contain cleanup protocol capability")
    graph = decode(ProgramGraph, record,
                   record_tags=_CLEANUP_RECORD_TAGS if version == 9 else None)
    if version < 9 and _has_cleanup_capability(graph):
        raise ValueError("historical schema cannot contain cleanup protocol capability")
    if version < 6 and (
            any(isinstance(v, ProtocolValue) for v in graph.values)
            or any(isinstance(o.terminator, PendingDispatchTerminator) for o in graph.operations)
            or any(isinstance(t, ProtocolValueType) for r in graph.regions for p in r.exits for t in p.types)
            or any(isinstance(t, ProtocolValueType) for o in graph.operations for s in o.completions for t in s.types)):
        raise ValueError("historical schema cannot contain control protocol capability")
    if version == 3 and not (
            graph.binding_definitions or graph.binding_reads
            or any(isinstance(value, LocalBindingValue) for value in graph.values)):
        raise ValueError("schema version 3 requires local-binding graph capability")
    if version == 4 and not any(getattr(graph, name) for name in _RESOURCE_FIELDS):
        raise ValueError("schema version 4 requires explicit resource graph capability")
    if version == 5 and not graph.environments:
        raise ValueError("schema version 5 requires explicit environment graph capability")
    if version == 6 and not graph.control_scopes:
        raise ValueError("schema version 6 requires explicit lexical control capability")
    if version == 7 and not graph.provider_envelopes:
        raise ValueError("schema version 7 requires explicit provider provenance capability")
    if version == 8 and not graph.native_boundaries:
        raise ValueError("schema version 8 requires explicit native boundary capability")
    if version == 9 and not graph.handled_context_domains:
        raise ValueError("schema version 9 requires explicit handled-context domain capability")
    _require_record_and_graph_valid(graph)
    return graph


__all__ = ["SCHEMA", "SCHEMA_VERSION", "dumps", "loads"]
