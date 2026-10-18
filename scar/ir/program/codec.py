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
from scar.ir.program.resumption import (
    ResumeInput, SavedInput, SuspendTerminator,
)
from scar.ir.program.drivers import BodyDriveResult, BodyDriveTerminator


SCHEMA = "scar.program-graph"
SCHEMA_VERSION = 11
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
_RESUMPTION_FIELDS = frozenset({"resumable_bodies", "frame_context_initials",
                                "frame_context_attaches", "frame_context_detaches"})
_DRIVER_FIELDS = frozenset({"resumable_creates", "raw_driver_requests",
                           "async_request_creates", "request_association_reads",
                           "driver_interfaces", "final_body_gates", "body_drives"})
_V10_GRAPH_FIELDS = _GRAPH_FIELDS - _DRIVER_FIELDS
_V9_GRAPH_FIELDS = _V10_GRAPH_FIELDS - _RESUMPTION_FIELDS
_V8_GRAPH_FIELDS = _V9_GRAPH_FIELDS - _CLEANUP_FIELDS
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
_V9_ENVELOPE_FIELDS = frozenset({"schema", "schema_version"}) | _V9_GRAPH_FIELDS
_V10_ENVELOPE_FIELDS = frozenset({"schema", "schema_version"}) | _V10_GRAPH_FIELDS
_V11_ENVELOPE_FIELDS = frozenset({"schema", "schema_version"}) | _GRAPH_FIELDS
_CLEANUP_RECORD_TAGS = {CleanupRouteTerminator: ("kind", "CLEANUP_ROUTE")}
_RESUMPTION_RECORD_TAGS = {SuspendTerminator: ("kind", "SUSPEND")}
_V10_RECORD_TAGS = {**_CLEANUP_RECORD_TAGS, **_RESUMPTION_RECORD_TAGS}
_DRIVER_RECORD_TAGS = {
    BodyDriveTerminator: ("kind", "BODY_DRIVE"),
    # CompletionResult has the same dataclass shape. The explicit new tag
    # prevents older wire formats from decoding this projection as that type.
    BodyDriveResult: ("kind", "BODY_DRIVE_RESULT"),
}
_V11_RECORD_TAGS = {**_V10_RECORD_TAGS, **_DRIVER_RECORD_TAGS}


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


def _has_resumption_capability(graph: ProgramGraph) -> bool:
    """Detect C2 records, tagged terminators, and protocol values/types."""
    new_protocols = {
        ProtocolValueKind.FRAME_CONTEXT,
        ProtocolValueKind.DRIVE_CALLER_CONTEXT,
    }
    return (
        any(getattr(graph, name) for name in _RESUMPTION_FIELDS)
        or any(type(operation.terminator) is SuspendTerminator
               for operation in graph.operations)
        or any(isinstance(value, ProtocolValue) and value.protocol in new_protocols
               for value in graph.values)
        or any(isinstance(value_type, ProtocolValueType)
               and value_type.protocol in new_protocols
               for region in graph.regions for port in region.exits for value_type in port.types)
        or any(isinstance(value_type, ProtocolValueType)
               and value_type.protocol in new_protocols
               for operation in graph.operations for signature in operation.completions
               for value_type in signature.types)
        or any(isinstance(actual, (SavedInput, ResumeInput))
               for operation in graph.operations
               for edge in getattr(operation.terminator, "successors", ())
               for actual in edge.arguments)
    )


def _has_driver_capability(graph: ProgramGraph) -> bool:
    """Include raw-only boundaries and markers omitted from interface tables."""
    raw = ProtocolValueKind.RAW_DRIVER_REQUEST
    return (
        any(getattr(graph, name) for name in _DRIVER_FIELDS)
        or any(isinstance(value, ProtocolValue) and value.protocol is raw
               for value in graph.values)
        or any(isinstance(value_type, ProtocolValueType) and value_type.protocol is raw
               for region in graph.regions for port in region.exits for value_type in port.types)
        or any(isinstance(value_type, ProtocolValueType) and value_type.protocol is raw
               for operation in graph.operations for signature in operation.completions
               for value_type in signature.types)
        or any(isinstance(operation.terminator, BodyDriveTerminator)
               for operation in graph.operations)
        or any(isinstance(actual, BodyDriveResult)
               for operation in graph.operations
               for edge in getattr(operation.terminator, "successors", ())
               for actual in edge.arguments)
    )


def dumps(graph: ProgramGraph) -> str:
    """Preserve historical encoding; driver boundaries require v11."""
    _require_record_and_graph_valid(graph)
    if _has_cleanup_capability(graph) and not graph.handled_context_domains:
        raise ValueError("cleanup capability requires explicit handled-context domains")
    has_binding_capability = (
        bool(graph.binding_definitions or graph.binding_reads)
        or any(isinstance(value, LocalBindingValue) for value in graph.values))
    has_resumption = _has_resumption_capability(graph)
    if has_resumption and not graph.resumable_bodies:
        raise ValueError("resumption capability requires an explicit resumable body")
    has_driver = _has_driver_capability(graph)
    encoded = encode(graph, record_tags=(_V11_RECORD_TAGS if has_driver else
                     _V10_RECORD_TAGS if has_resumption else _CLEANUP_RECORD_TAGS))
    if has_driver:
        document = {"schema": SCHEMA, "schema_version": 11, **encoded}
    elif has_resumption:
        document = {"schema": SCHEMA, "schema_version": 10,
                    **{name: encoded[name] for name in _V10_GRAPH_FIELDS}}
    elif graph.handled_context_domains:
        document = {"schema": SCHEMA, "schema_version": 9,
                    **{name: encoded[name] for name in _V9_GRAPH_FIELDS}}
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
    """Decode exact v11 fields or strictly migrate historical v1–v10."""
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
    if type(version) is not int or version not in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11):
        raise ValueError("unsupported program graph schema version")
    expected_fields = {1: _V1_V2_ENVELOPE_FIELDS, 2: _V1_V2_ENVELOPE_FIELDS,
                       3: _V3_ENVELOPE_FIELDS, 4: _V4_ENVELOPE_FIELDS,
                       5: _V5_ENVELOPE_FIELDS, 6: _V6_ENVELOPE_FIELDS,
                       7: _V7_ENVELOPE_FIELDS, 8: _V8_ENVELOPE_FIELDS,
                       9: _V9_ENVELOPE_FIELDS, 10: _V10_ENVELOPE_FIELDS,
                       11: _V11_ENVELOPE_FIELDS}[version]
    if set(document) != expected_fields:
        raise ValueError("program graph document has incorrect top-level fields")
    graph_fields = {1: _V1_V2_GRAPH_FIELDS, 2: _V1_V2_GRAPH_FIELDS,
                    3: _V3_GRAPH_FIELDS, 4: _V4_GRAPH_FIELDS,
                    5: _V5_GRAPH_FIELDS, 6: _V6_GRAPH_FIELDS,
                    7: _V7_GRAPH_FIELDS, 8: _V8_GRAPH_FIELDS, 9: _V9_GRAPH_FIELDS,
                    10: _V10_GRAPH_FIELDS, 11: _GRAPH_FIELDS}[version]
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
    if version < 10:
        record.update({name: [] for name in _RESUMPTION_FIELDS})
    if version < 11:
        record.update({name: [] for name in _DRIVER_FIELDS})
        # Inspect only canonical protocol-bearing fields. Capability rejection
        # must not depend on whether a containing legacy record constructs
        # successfully (for example a malformed completion signature).
        def raw_protocol(item):
            return type(item) is dict and item.get("protocol") == "RAW_DRIVER_REQUEST"

        values = record.get("values")
        if type(values) is list and any(raw_protocol(value) for value in values):
            raise ValueError("historical schema cannot contain driver capability")
        regions = record.get("regions")
        if type(regions) is list:
            for region in regions:
                ports = region.get("exits") if type(region) is dict else None
                if type(ports) is not list:
                    continue
                for port in ports:
                    types = port.get("types") if type(port) is dict else None
                    if type(types) is list and any(raw_protocol(item) for item in types):
                        raise ValueError("historical schema cannot contain driver capability")
        operations = record.get("operations")
        if type(operations) is list:
            for operation in operations:
                signatures = operation.get("completions") if type(operation) is dict else None
                if type(signatures) is list:
                    for signature in signatures:
                        types = signature.get("types") if type(signature) is dict else None
                        if type(types) is list and any(raw_protocol(item) for item in types):
                            raise ValueError("historical schema cannot contain driver capability")
                term = operation.get("terminator") if type(operation) is dict else None
                if type(term) is not dict:
                    continue
                if term.get("kind") == "BODY_DRIVE":
                    raise ValueError("historical schema cannot contain driver capability")
                edges = term.get("successors")
                if type(edges) is not list:
                    continue
                for edge in edges:
                    arguments = edge.get("arguments") if type(edge) is dict else None
                    if type(arguments) is list and any(
                            type(argument) is dict
                            and argument.get("kind") == "BODY_DRIVE_RESULT"
                            for argument in arguments):
                        raise ValueError("historical schema cannot contain driver capability")
    if version < 10:
        operations = record.get("operations")
        if type(operations) is list:
            for operation in operations:
                term = operation.get("terminator") if type(operation) is dict else None
                if type(term) is dict and term.get("kind") == "SUSPEND":
                    raise ValueError("historical schema cannot contain resumable-body capability")
    graph = decode(ProgramGraph, record,
                   record_tags=(_V11_RECORD_TAGS if version == 11 else
                                _V10_RECORD_TAGS if version == 10 else
                                _CLEANUP_RECORD_TAGS if version == 9 else None))
    if version < 11 and _has_driver_capability(graph):
        raise ValueError("historical schema cannot contain driver capability")
    if version < 9 and _has_cleanup_capability(graph):
        raise ValueError("historical schema cannot contain cleanup protocol capability")
    if version < 10 and _has_resumption_capability(graph):
        raise ValueError("historical schema cannot contain resumable-body capability")
    if _has_resumption_capability(graph) and not graph.resumable_bodies:
        raise ValueError("resumption capability requires explicit resumable body")
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
    if version == 10 and not _has_resumption_capability(graph):
        raise ValueError("schema version 10 requires explicit resumable-body capability")
    if version == 11 and not _has_driver_capability(graph):
        raise ValueError("schema version 11 requires explicit driver capability")
    _require_record_and_graph_valid(graph)
    return graph


__all__ = ["SCHEMA", "SCHEMA_VERSION", "dumps", "loads"]
