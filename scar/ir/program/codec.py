"""Strict JSON codec for the immutable program graph records."""
from __future__ import annotations

from dataclasses import fields
import json
from typing import Any

from scar.ir.record_codec import decode, encode, loads as _loads
from scar.ir.v2._validation import record_errors

from scar.ir.program.model import LocalBindingValue, Operation, ProgramGraph, ProtocolValue, TerminatorKind
from scar.ir.program.control import (
    PendingDispatchTerminator, ProtocolValueKind, ProtocolValueType,
)
from scar.ir.program.cleanup import CleanupRouteTerminator
from scar.ir.program.resumption import (
    ResumeInput, SavedInput, SuspendTerminator,
)
from scar.ir.program.drivers import BodyDriveResult, BodyDriveTerminator
from scar.ir.program.state_addresses import STATE_ADDRESS_RECORD_TAGS
from scar.ir.program.literal_sources import ExactLiteralOrigin, LITERAL_SOURCE_RECORD_TAGS
from scar.ir.program.model import InvokeLiteralResult
from scar.ir.program.protocols import (
    ADMISSION_RECORD_TAGS, AdmissionPredicate, PROTOCOL_RECORD_TAGS,
)
from scar.ir.program.protocol_connections import (
    LOOKUP_FALLBACK_RECORD_TAGS, PROTOCOL_CONNECTION_RECORD_TAGS,
    SessionOccupancyCondition,
    has_async_initial_control_capability, has_delegated_method_lookup_capability,
    has_lookup_fallback_capability,
    has_protocol_connection_capability,
)
from scar.ir.program.exception_matches import EXCEPTION_MATCH_RECORD_TAGS
from scar.ir.program.protocol_await_records import (
    AWAIT_ACQUISITION_RECORD_TAGS, has_await_acquisition_capability,
)
from scar.ir.program.call_effect_expansion import CALL_EFFECT_EXPANSION_RECORD_TAGS


SCHEMA = "scar.program-graph"
SCHEMA_VERSION = 26
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
_PUBLICATION_FIELDS = frozenset({"driver_lifecycles", "body_outcome_commits"})
_NO_BODY_FIELDS = frozenset({"created_close_tests", "no_body_finishes"})
_SESSION_RELEASE_FIELDS = frozenset({"session_updates", "terminal_frame_releases"})
_STATE_ADDRESS_FIELDS = frozenset({"state_address_refinements"})
_LITERAL_FIELDS = frozenset({"literal_evaluations"})
_PROTOCOL_FIELDS = frozenset({"protocol_scopes", "protocol_operations"})
_CONNECTION_FIELDS = frozenset({"protocol_call_inputs", "protocol_result_consumers",
                                "protocol_bindings"})
_EXCEPTION_MATCH_FIELDS = frozenset({"exception_matches"})
_CALL_EFFECT_FIELDS = frozenset({"call_effect_expansions"})
_V26_GRAPH_FIELDS = _GRAPH_FIELDS
_V25_GRAPH_FIELDS = _V26_GRAPH_FIELDS
_V24_GRAPH_FIELDS = _V25_GRAPH_FIELDS - _CALL_EFFECT_FIELDS
_V23_GRAPH_FIELDS = _V24_GRAPH_FIELDS
_V22_GRAPH_FIELDS = _V23_GRAPH_FIELDS
_V21_GRAPH_FIELDS = _V22_GRAPH_FIELDS
_V20_GRAPH_FIELDS = _V21_GRAPH_FIELDS - _EXCEPTION_MATCH_FIELDS
_V19_GRAPH_FIELDS = _V20_GRAPH_FIELDS
_V18_GRAPH_FIELDS = _V19_GRAPH_FIELDS - _CONNECTION_FIELDS
_V17_GRAPH_FIELDS = _V18_GRAPH_FIELDS
_V16_GRAPH_FIELDS = _V17_GRAPH_FIELDS - _PROTOCOL_FIELDS
_V15_GRAPH_FIELDS = _V16_GRAPH_FIELDS - _LITERAL_FIELDS
_V14_GRAPH_FIELDS = _V15_GRAPH_FIELDS - _STATE_ADDRESS_FIELDS
_V13_GRAPH_FIELDS = _V14_GRAPH_FIELDS - _SESSION_RELEASE_FIELDS
_V12_GRAPH_FIELDS = _V13_GRAPH_FIELDS - _NO_BODY_FIELDS
_V11_GRAPH_FIELDS = _V12_GRAPH_FIELDS - _PUBLICATION_FIELDS
_V10_GRAPH_FIELDS = _V11_GRAPH_FIELDS - _DRIVER_FIELDS
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
_V11_ENVELOPE_FIELDS = frozenset({"schema", "schema_version"}) | _V11_GRAPH_FIELDS
_V12_ENVELOPE_FIELDS = frozenset({"schema", "schema_version"}) | _V12_GRAPH_FIELDS
_V13_ENVELOPE_FIELDS = frozenset({"schema", "schema_version"}) | _V13_GRAPH_FIELDS
_V14_ENVELOPE_FIELDS = frozenset({"schema", "schema_version"}) | _V14_GRAPH_FIELDS
_V15_ENVELOPE_FIELDS = frozenset({"schema", "schema_version"}) | _V15_GRAPH_FIELDS
_V16_ENVELOPE_FIELDS = frozenset({"schema", "schema_version"}) | _V16_GRAPH_FIELDS
_V17_ENVELOPE_FIELDS = frozenset({"schema", "schema_version"}) | _V17_GRAPH_FIELDS
_V18_ENVELOPE_FIELDS = frozenset({"schema", "schema_version"}) | _V18_GRAPH_FIELDS
_V19_ENVELOPE_FIELDS = frozenset({"schema", "schema_version"}) | _V19_GRAPH_FIELDS
_V20_ENVELOPE_FIELDS = frozenset({"schema", "schema_version"}) | _V20_GRAPH_FIELDS
_V21_ENVELOPE_FIELDS = frozenset({"schema", "schema_version"}) | _V21_GRAPH_FIELDS
_V22_ENVELOPE_FIELDS = frozenset({"schema", "schema_version"}) | _V22_GRAPH_FIELDS
_V23_ENVELOPE_FIELDS = frozenset({"schema", "schema_version"}) | _V23_GRAPH_FIELDS
_V24_ENVELOPE_FIELDS = frozenset({"schema", "schema_version"}) | _V24_GRAPH_FIELDS
_V25_ENVELOPE_FIELDS = frozenset({"schema", "schema_version"}) | _V25_GRAPH_FIELDS
_V26_ENVELOPE_FIELDS = frozenset({"schema", "schema_version"}) | _V26_GRAPH_FIELDS
_V19_CONNECTION_RECORD_TAGS = {record: tag for record, tag in PROTOCOL_CONNECTION_RECORD_TAGS.items()
                              if record is not SessionOccupancyCondition}
_V17_PROTOCOL_RECORD_TAGS = {record: tag for record, tag in PROTOCOL_RECORD_TAGS.items()
                             if record not in ADMISSION_RECORD_TAGS}
_LITERAL_RECORD_TAGS = {**LITERAL_SOURCE_RECORD_TAGS,
                        InvokeLiteralResult: ("kind", "INVOKE_LITERAL_RESULT")}
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


def _has_publication_capability(graph: ProgramGraph) -> bool:
    """Only the two implemented D2.1 tables select publication wire v12."""
    return any(getattr(graph, name) for name in _PUBLICATION_FIELDS)


def _has_no_body_capability(graph: ProgramGraph) -> bool:
    """Include predicate-only declarations without asserting a finish exists."""
    return any(getattr(graph, name) for name in _NO_BODY_FIELDS)


def _has_session_release_capability(graph: ProgramGraph) -> bool:
    """Only implemented session-post/reference-release declarations select v14."""
    return any(getattr(graph, name) for name in _SESSION_RELEASE_FIELDS)


def _has_literal_capability(graph: ProgramGraph) -> bool:
    return bool(graph.literal_evaluations) or any(
        isinstance(value.origin, ExactLiteralOrigin) for value in graph.values)


def _has_protocol_capability(graph: ProgramGraph) -> bool:
    return any(getattr(graph, name) for name in _PROTOCOL_FIELDS)


_has_protocol_connection_capability = has_protocol_connection_capability


def _has_admission_capability(graph: ProgramGraph) -> bool:
    return any(type(row.contract) is AdmissionPredicate for row in graph.protocol_operations)


def _has_session_occupancy_capability(graph: ProgramGraph) -> bool:
    """Only the new read subject selects Program24; old async scopes do not."""
    return any(type(row.contract) is AdmissionPredicate
               and type(row.contract.subject) is SessionOccupancyCondition
               for row in graph.protocol_operations)


def _has_invoke_subset_capability(graph: ProgramGraph) -> bool:
    return any(operation.terminator is not None
               and operation.terminator.kind is TerminatorKind.INVOKE
               and len(operation.terminator.successors) == 1 for operation in graph.operations)


def dumps(graph: ProgramGraph) -> str:
    """Select only present capabilities; preserve historical field/tag/byte profiles."""
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
    has_publication = _has_publication_capability(graph)
    has_no_body = _has_no_body_capability(graph)
    has_session_release = _has_session_release_capability(graph)
    has_addresses = bool(graph.state_address_refinements)
    has_literals = _has_literal_capability(graph)
    has_protocols = _has_protocol_capability(graph)
    has_protocol_connections = _has_protocol_connection_capability(graph)
    has_method_lookup = has_delegated_method_lookup_capability(graph)
    has_exception_matches = bool(graph.exception_matches)
    has_lookup_fallback = has_lookup_fallback_capability(graph)
    has_await_acquisition = has_await_acquisition_capability(graph)
    has_session_occupancy = _has_session_occupancy_capability(graph)
    has_call_effect_expansions = bool(graph.call_effect_expansions)
    has_async_initial_control = has_async_initial_control_capability(graph)
    has_admission = _has_admission_capability(graph)
    has_invoke_subset = _has_invoke_subset_capability(graph)
    tags = (_V11_RECORD_TAGS if has_driver else
            _V10_RECORD_TAGS if has_resumption else _CLEANUP_RECORD_TAGS)
    if has_addresses or has_protocols or has_exception_matches:
        tags = {**tags, **STATE_ADDRESS_RECORD_TAGS}
    if has_literals or has_protocols or has_exception_matches:
        tags = {**tags, **_LITERAL_RECORD_TAGS}
    if has_protocols or has_protocol_connections or has_exception_matches:
        tags = {**tags, **(PROTOCOL_RECORD_TAGS if has_admission else _V17_PROTOCOL_RECORD_TAGS)}
    if has_protocol_connections or has_exception_matches:
        tags = {**tags, **PROTOCOL_CONNECTION_RECORD_TAGS}
    if has_exception_matches or has_lookup_fallback:
        tags = {**tags, **EXCEPTION_MATCH_RECORD_TAGS}
    if has_lookup_fallback:
        tags = {**tags, **LOOKUP_FALLBACK_RECORD_TAGS}
    if has_await_acquisition:
        tags = {**tags, **AWAIT_ACQUISITION_RECORD_TAGS}
    if has_call_effect_expansions:
        tags = {**tags, **CALL_EFFECT_EXPANSION_RECORD_TAGS}
    encoded = encode(graph, record_tags=tags)
    if has_async_initial_control:
        document = {"schema": SCHEMA, "schema_version": 26,
                    **{name: encoded[name] for name in _V26_GRAPH_FIELDS}}
    elif has_call_effect_expansions:
        document = {"schema": SCHEMA, "schema_version": 25,
                    **{name: encoded[name] for name in _V25_GRAPH_FIELDS}}
    elif has_session_occupancy:
        document = {"schema": SCHEMA, "schema_version": 24,
                    **{name: encoded[name] for name in _V24_GRAPH_FIELDS}}
    elif has_await_acquisition:
        document = {"schema": SCHEMA, "schema_version": 23,
                    **{name: encoded[name] for name in _V23_GRAPH_FIELDS}}
    elif has_lookup_fallback:
        document = {"schema": SCHEMA, "schema_version": 22,
                    **{name: encoded[name] for name in _V22_GRAPH_FIELDS}}
    elif has_exception_matches:
        document = {"schema": SCHEMA, "schema_version": 21,
                    **{name: encoded[name] for name in _V21_GRAPH_FIELDS}}
    elif has_method_lookup:
        document = {"schema": SCHEMA, "schema_version": 20,
                    **{name: encoded[name] for name in _V20_GRAPH_FIELDS}}
    elif has_protocol_connections:
        document = {"schema": SCHEMA, "schema_version": 19,
                    **{name: encoded[name] for name in _V19_GRAPH_FIELDS}}
    elif has_admission or has_invoke_subset:
        document = {"schema": SCHEMA, "schema_version": 18,
                    **{name: encoded[name] for name in _V18_GRAPH_FIELDS}}
    elif has_protocols:
        document = {"schema": SCHEMA, "schema_version": 17,
                    **{name: encoded[name] for name in _V17_GRAPH_FIELDS}}
    elif has_literals:
        document = {"schema": SCHEMA, "schema_version": 16,
                    **{name: encoded[name] for name in _V16_GRAPH_FIELDS}}
    elif has_addresses:
        document = {"schema": SCHEMA, "schema_version": 15,
                    **{name: encoded[name] for name in _V15_GRAPH_FIELDS}}
    elif has_session_release:
        document = {"schema": SCHEMA, "schema_version": 14,
                    **{name: encoded[name] for name in _V14_GRAPH_FIELDS}}
    elif has_no_body:
        document = {"schema": SCHEMA, "schema_version": 13,
                    **{name: encoded[name] for name in _V13_GRAPH_FIELDS}}
    elif has_publication:
        document = {"schema": SCHEMA, "schema_version": 12,
                    **{name: encoded[name] for name in _V12_GRAPH_FIELDS}}
    elif has_driver:
        document = {"schema": SCHEMA, "schema_version": 11,
                    **{name: encoded[name] for name in _V11_GRAPH_FIELDS}}
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
                      ensure_ascii=(has_literals or has_protocols or has_protocol_connections
                                    or has_exception_matches),
                      allow_nan=False)


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
    """Decode exact capability profiles v1–v26 without upgrading old wire."""
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
    if type(version) is not int or version not in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26):
        raise ValueError("unsupported program graph schema version")
    expected_fields = {1: _V1_V2_ENVELOPE_FIELDS, 2: _V1_V2_ENVELOPE_FIELDS,
                       3: _V3_ENVELOPE_FIELDS, 4: _V4_ENVELOPE_FIELDS,
                       5: _V5_ENVELOPE_FIELDS, 6: _V6_ENVELOPE_FIELDS,
                       7: _V7_ENVELOPE_FIELDS, 8: _V8_ENVELOPE_FIELDS,
                       9: _V9_ENVELOPE_FIELDS, 10: _V10_ENVELOPE_FIELDS,
                       11: _V11_ENVELOPE_FIELDS, 12: _V12_ENVELOPE_FIELDS,
                       13: _V13_ENVELOPE_FIELDS, 14: _V14_ENVELOPE_FIELDS,
                       15: _V15_ENVELOPE_FIELDS, 16: _V16_ENVELOPE_FIELDS,
                       17: _V17_ENVELOPE_FIELDS, 18: _V18_ENVELOPE_FIELDS,
                       19: _V19_ENVELOPE_FIELDS, 20: _V20_ENVELOPE_FIELDS,
                       21: _V21_ENVELOPE_FIELDS, 22: _V22_ENVELOPE_FIELDS,
                       23: _V23_ENVELOPE_FIELDS, 24: _V24_ENVELOPE_FIELDS,
                       25: _V25_ENVELOPE_FIELDS, 26: _V26_ENVELOPE_FIELDS}[version]
    if set(document) != expected_fields:
        raise ValueError("program graph document has incorrect top-level fields")
    graph_fields = {1: _V1_V2_GRAPH_FIELDS, 2: _V1_V2_GRAPH_FIELDS,
                    3: _V3_GRAPH_FIELDS, 4: _V4_GRAPH_FIELDS,
                    5: _V5_GRAPH_FIELDS, 6: _V6_GRAPH_FIELDS,
                    7: _V7_GRAPH_FIELDS, 8: _V8_GRAPH_FIELDS, 9: _V9_GRAPH_FIELDS,
                    10: _V10_GRAPH_FIELDS, 11: _V11_GRAPH_FIELDS,
                    12: _V12_GRAPH_FIELDS, 13: _V13_GRAPH_FIELDS,
                    14: _V14_GRAPH_FIELDS, 15: _V15_GRAPH_FIELDS, 16: _V16_GRAPH_FIELDS,
                    17: _V17_GRAPH_FIELDS, 18: _V18_GRAPH_FIELDS,
                    19: _V19_GRAPH_FIELDS, 20: _V20_GRAPH_FIELDS,
                    21: _V21_GRAPH_FIELDS, 22: _V22_GRAPH_FIELDS,
                    23: _V23_GRAPH_FIELDS, 24: _V24_GRAPH_FIELDS,
                    25: _V25_GRAPH_FIELDS, 26: _V26_GRAPH_FIELDS}[version]
    record = {name: document[name] for name in graph_fields}
    if version < 25:
        record.update({name: [] for name in _CALL_EFFECT_FIELDS})
    if version < 21:
        record.update({name: [] for name in _EXCEPTION_MATCH_FIELDS})
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
    if version < 12:
        record.update({name: [] for name in _PUBLICATION_FIELDS})
    if version < 13:
        record.update({name: [] for name in _NO_BODY_FIELDS})
    if version < 14:
        record.update({name: [] for name in _SESSION_RELEASE_FIELDS})
    if version < 17:
        record.update({name: [] for name in _PROTOCOL_FIELDS})
    if version < 19:
        record.update({name: [] for name in _CONNECTION_FIELDS})
    if version < 16:
        record.update({name: [] for name in _LITERAL_FIELDS})
    if version < 15:
        record.update({name: [] for name in _STATE_ADDRESS_FIELDS})
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
    tags = (_V11_RECORD_TAGS if version >= 11 else
            _V10_RECORD_TAGS if version == 10 else
            _CLEANUP_RECORD_TAGS if version == 9 else None)
    if version >= 15:
        tags = {**tags, **STATE_ADDRESS_RECORD_TAGS}
    if version >= 16:
        tags = {**tags, **_LITERAL_RECORD_TAGS}
    if version >= 17:
        tags = {**tags, **(PROTOCOL_RECORD_TAGS if version >= 18 else _V17_PROTOCOL_RECORD_TAGS)}
    if version >= 19:
        tags = {**tags, **(PROTOCOL_CONNECTION_RECORD_TAGS if version >= 24
                          else _V19_CONNECTION_RECORD_TAGS)}
    if version >= 21:
        tags = {**tags, **EXCEPTION_MATCH_RECORD_TAGS}
    if version >= 22:
        tags = {**tags, **LOOKUP_FALLBACK_RECORD_TAGS}
    if version >= 23:
        tags = {**tags, **AWAIT_ACQUISITION_RECORD_TAGS}
    if version >= 25:
        tags = {**tags, **CALL_EFFECT_EXPANSION_RECORD_TAGS}
    graph = decode(ProgramGraph, record, record_tags=tags)
    has_async_initial_control = has_async_initial_control_capability(graph)
    if version < 26 and has_async_initial_control:
        raise ValueError("historical schema cannot contain async initial control capability")
    if version == 26 and not has_async_initial_control:
        raise ValueError("schema version 26 requires explicit async initial control capability")
    if version == 25 and not graph.call_effect_expansions:
        raise ValueError("schema version 25 requires explicit call effect expansion capability")
    has_session_occupancy = _has_session_occupancy_capability(graph)
    if version < 24 and has_session_occupancy:
        raise ValueError("historical schema cannot contain session occupancy capability")
    if version == 24 and not has_session_occupancy:
        raise ValueError("schema version 24 requires explicit session occupancy capability")
    has_await_acquisition = has_await_acquisition_capability(graph)
    if version < 23 and has_await_acquisition:
        raise ValueError("historical schema cannot contain await acquisition capability")
    if version == 23 and not has_await_acquisition:
        raise ValueError("schema version 23 requires explicit await acquisition capability")
    has_lookup_fallback = has_lookup_fallback_capability(graph)
    if version < 22 and has_lookup_fallback:
        raise ValueError("historical schema cannot contain lookup fallback capability")
    if version == 22 and not has_lookup_fallback:
        raise ValueError("schema version 22 requires explicit lookup fallback capability")
    if version < 21 and graph.exception_matches:
        raise ValueError("historical schema cannot contain exception matcher capability")
    if version == 21 and not graph.exception_matches:
        raise ValueError("schema version 21 requires explicit exception matcher capability")
    has_method_lookup = has_delegated_method_lookup_capability(graph)
    if version < 20 and has_method_lookup:
        raise ValueError("historical schema cannot contain delegated method lookup capability")
    if version < 18 and _has_admission_capability(graph):
        raise ValueError("historical schema cannot contain admission predicate capability")
    if version < 18 and _has_invoke_subset_capability(graph):
        raise ValueError("historical schema cannot contain single-completion INVOKE capability")
    if version == 18 and not (_has_admission_capability(graph) or _has_invoke_subset_capability(graph)):
        raise ValueError("schema version 18 requires explicit admission predicate capability or single-completion INVOKE")
    if version < 19 and _has_protocol_connection_capability(graph):
        raise ValueError("historical schema cannot contain protocol connection capability")
    if version == 19 and not _has_protocol_connection_capability(graph):
        raise ValueError("schema version 19 requires explicit protocol connection capability")
    if version == 20 and not has_method_lookup:
        raise ValueError("schema version 20 requires explicit delegated method lookup capability")
    if version < 17 and _has_protocol_capability(graph):
        raise ValueError("historical schema cannot contain protocol capability")
    if version == 17 and not _has_protocol_capability(graph):
        raise ValueError("schema version 17 requires explicit protocol capability")
    if version < 16 and _has_literal_capability(graph):
        raise ValueError("historical schema cannot contain exact literal capability")
    if version == 16 and not _has_literal_capability(graph):
        raise ValueError("schema version 16 requires exact literal capability")
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
    if version == 12 and not _has_publication_capability(graph):
        raise ValueError("schema version 12 requires explicit body-publication capability")
    if version == 13 and not _has_no_body_capability(graph):
        raise ValueError("schema version 13 requires explicit no-body capability")
    if version == 14 and not _has_session_release_capability(graph):
        raise ValueError("schema version 14 requires explicit session/release capability")
    if version == 15 and not graph.state_address_refinements:
        raise ValueError("schema version 15 requires explicit state-address capability")
    _require_record_and_graph_valid(graph)
    return graph


__all__ = ["SCHEMA", "SCHEMA_VERSION", "dumps", "loads"]
