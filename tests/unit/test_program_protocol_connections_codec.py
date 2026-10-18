"""Program 19 wire profile for the closed P4 protocol connection records."""
import json
from dataclasses import replace
from pathlib import Path

import pytest

from scar.ir import record_codec
from scar.ir.program import codec
from scar.ir.program.codec import _LITERAL_RECORD_TAGS
from scar.ir.program.literal_sources import LITERAL_SOURCE_RECORD_TAGS
from scar.ir.program.model import InvokeLiteralResult
from scar.ir.program.model import (
    Behavior, Operation, OperationResult, ReferenceValue, Use, UseRole, ValueID,
)
from scar.ir.program.ids import OperationID, UseID
from scar.ir.program.control import ProtocolValueKind
from scar.ir.program.drivers import RawRequestDefinition, RawRequestKind
from scar.ir.program.model import ProtocolValue
from scar.ir.program.protocols import (
    ProtocolClause, ProtocolOperation, RequestProcessing, RequestProcessingRule,
)
from scar.ir.program.protocol_connections import (
    PROTOCOL_CONNECTION_RECORD_TAGS, RawOperandSource, RequestAssociation,
    has_protocol_connection_capability,
)
from scar.ir.program.protocols import (
    ADMISSION_RECORD_TAGS, PROTOCOL_RECORD_TAGS, ProtocolProfile,
)
from scar.ir.program.state_addresses import STATE_ADDRESS_RECORD_TAGS
from scar.ir.program.resumption import ResumableKind, SuspensionFlavor, SuspendTerminator
from tests.fixtures.program_admission_graphs import admission_program
from tests.fixtures.program_async_connections import async_driver_program
from tests.fixtures.program_continuation_graphs import (
    continuation_site_program, with_continuation_connections,
)
from tests.fixtures.program_protocol_graphs import generator_protocol_program


def _connection_tags():
    return {
        **PROTOCOL_RECORD_TAGS,
        **ADMISSION_RECORD_TAGS,
        **STATE_ADDRESS_RECORD_TAGS,
        **LITERAL_SOURCE_RECORD_TAGS,
        **_LITERAL_RECORD_TAGS,
        **PROTOCOL_CONNECTION_RECORD_TAGS,
    }


def test_nested_connection_records_roundtrip_with_closed_local_tags():
    graph, details = continuation_site_program(kind="await", request="send", exhaustion=True)
    graph, _ = with_continuation_connections(graph, details)
    # Pick a row containing both a block formal and raw-ordinal projection.
    row = next(item for item in graph.protocol_call_inputs
               if any(type(argument) is RawOperandSource
                      for case in item.cases for argument in case.arguments))
    tags = _connection_tags()
    encoded = record_codec.encode(row, record_tags=tags)
    decoded = record_codec.decode(type(row), encoded, record_tags=tags)
    assert decoded == row
    assert encoded["kind"] == "PROTOCOL_CALL_INPUTS"
    assert encoded["cases"][0]["kind"] == "PROTOCOL_CALL_INPUT_CASE"

    malformed = json.loads(json.dumps(encoded))
    malformed["cases"][0]["arguments"][0]["kind"] = "PROTOCOL_OWNED_USE"
    with pytest.raises(ValueError):
        record_codec.decode(type(row), malformed, record_tags=tags)
    malformed = json.loads(json.dumps(encoded))
    malformed["extra"] = True
    with pytest.raises(ValueError):
        record_codec.decode(type(row), malformed, record_tags=tags)


def test_request_association_and_task_status_wire_variants_keep_original_ports():
    graph, _ = async_driver_program(association=True, session=True, attach_records=True)
    request_row = next(row for row in graph.protocol_operations
                       if isinstance(row.contract, RequestAssociation))
    tags = _connection_tags()
    encoded = record_codec.encode(request_row.contract, record_tags=tags)
    decoded = record_codec.decode(RequestAssociation, encoded, record_tags=tags)
    assert decoded == request_row.contract
    assert type(decoded.body) is InvokeLiteralResult
    assert type(decoded.latent) is InvokeLiteralResult
    assert decoded.body.edge == decoded.latent.edge


def test_program19_roundtrips_full_continuation_and_async_connections():
    graph, details = continuation_site_program(kind="await", request="next", exhaustion=True)
    graph, _ = with_continuation_connections(graph, details)
    wire = codec.dumps(graph)
    document = json.loads(wire)
    assert document["schema_version"] == 19
    assert document["protocol_call_inputs"]
    assert document["protocol_result_consumers"]
    decoded = codec.loads(wire)
    assert decoded == graph
    assert codec.dumps(decoded) == wire

    async_graph, _ = async_driver_program(association=True, session=True, attach_records=True)
    async_wire = codec.dumps(async_graph)
    async_document = json.loads(async_wire)
    assert async_document["schema_version"] == 19
    assert async_document["protocol_bindings"]
    decoded_async = codec.loads(async_wire)
    assert decoded_async == async_graph
    assert codec.dumps(decoded_async) == async_wire


def test_program19_requires_a_real_connection_capability_and_does_not_downgrade():
    graph, details = continuation_site_program(kind="delegate", request="next")
    connected, _ = with_continuation_connections(graph, details)
    document = json.loads(codec.dumps(connected))
    assert document["schema_version"] == 19
    with pytest.raises(ValueError, match="top-level fields"):
        codec.loads(json.dumps({key: value for key, value in document.items()
                                if key not in {"protocol_call_inputs", "protocol_result_consumers",
                                               "protocol_bindings"}}))

    empty = json.loads(codec.dumps(connected))
    empty["protocol_call_inputs"] = []
    empty["protocol_result_consumers"] = []
    empty["protocol_bindings"] = []
    with pytest.raises(ValueError, match="requires explicit protocol connection"):
        codec.loads(json.dumps(empty))


def test_historical_v18_oracle_retains_exact_fields_tags_and_bytes():
    fixture_dir = Path(__file__).resolve().parents[1] / "fixtures"
    wire = (fixture_dir / "program_graph_v18_frozen.json").read_bytes()
    proof = json.loads((fixture_dir / "program_graph_v18_frozen.proof.json").read_text())
    assert proof["source_revision"] == "add4ba84c9529e1f864e4029bd7c145cfacdfafc"
    assert proof["schema_version"] == 18
    import hashlib
    assert hashlib.sha256(wire).hexdigest() == proof["fixture_sha256"]
    assert len(wire) == proof["fixture_bytes"]
    document = json.loads(wire)
    assert "protocol_call_inputs" not in document
    assert "protocol_result_consumers" not in document
    assert "protocol_bindings" not in document
    assert codec.dumps(codec.loads(wire.decode("utf-8"))).encode("utf-8") == wire


def test_old_protocol_only_scope_still_selects_its_historical_profile():
    graph, _ = generator_protocol_program(target="start")
    wire = codec.dumps(graph)
    assert json.loads(wire)["schema_version"] == 17
    assert "protocol_call_inputs" not in json.loads(wire)
    assert codec.loads(wire) == graph


def _async_generator_close_normalizer_graph():
    """Add one explicit normalizer operation to the original async driver CFG."""
    graph, _ = async_driver_program(
        target="start", association=False, session=False, attach_records=False)
    interface, = graph.driver_interfaces
    region = next(row for row in graph.regions if row.id == interface.region)
    entry = next(block for block in region.blocks if block.id == region.entry)
    raw_operation_id = OperationID("driver.close.raw_pack")
    raw_value = ProtocolValue(
        ValueID("driver.close.raw"), region.id,
        OperationResult(raw_operation_id, 0), ProtocolValueKind.RAW_DRIVER_REQUEST)
    raw_operation = Operation(
        raw_operation_id, "zero-operand latent CLOSE request pack",
        (Behavior.COMPUTE,), (), (raw_value.id,), effects_complete=True)
    operation_id = OperationID("driver.close.normalize")
    use = Use(UseID("driver.close.normalize.raw"), raw_value.id, UseRole.PROTOCOL)
    result = ReferenceValue(
        ValueID("driver.close.normalize.result"), region.id,
        OperationResult(operation_id, 0))
    operation = Operation(
        operation_id, "source-relative CLOSE to GeneratorExit normalizer",
        (Behavior.COMPUTE,), (use,), (result.id,), effects_complete=True)
    regions = tuple(replace(item, blocks=tuple(
        replace(block, operations=(raw_operation_id, operation_id, *block.operations))
        if item.id == region.id and block.id == entry.id else block
        for block in item.blocks)) if item.id == region.id else item
        for item in graph.regions)
    scope, = graph.protocol_scopes
    row = ProtocolOperation(
        scope.id, ProtocolClause.ASYNC_REQUEST_DELIVERY, operation_id, 0,
        RequestProcessing(
            use.id, (), OperationResult(operation_id, 0), (),
            RequestProcessingRule.NORMALIZE_GENERATOR_EXIT),
        scope.source)
    return replace(graph, regions=regions,
                   operations=(*graph.operations, raw_operation, operation),
                   values=(*graph.values, raw_value, result),
                   raw_driver_requests=(*graph.raw_driver_requests,
                                        RawRequestDefinition(raw_value.id, RawRequestKind.CLOSE, ())),
                   protocol_operations=(*graph.protocol_operations, row))


def test_async_generator_close_normalizer_selects_v19_and_old_wire_is_rejected():
    old_graph, _ = async_driver_program(
        target="packet", association=False, session=False, attach_records=False)
    old_wire = codec.dumps(old_graph)
    assert json.loads(old_wire)["schema_version"] in (17, 18)
    assert not has_protocol_connection_capability(old_graph)

    graph = _async_generator_close_normalizer_graph()
    assert has_protocol_connection_capability(graph)
    wire = codec.dumps(graph)
    document = json.loads(wire)
    assert document["schema_version"] == 19
    assert codec.loads(wire) == graph

    # The record shape existed earlier, but this profile/rule applicability
    # did not. Keep it from being reinterpreted under historical schema 17.
    legacy = dict(document)
    legacy["schema_version"] = 17
    for field in ("protocol_call_inputs", "protocol_result_consumers", "protocol_bindings"):
        legacy.pop(field)
    with pytest.raises(ValueError, match="historical schema cannot contain protocol connection capability"):
        codec.loads(json.dumps(legacy))


@pytest.mark.parametrize("subject", ["body", "none"])
def test_old_generator_admission_predicates_remain_v18(subject):
    graph, _ = admission_program(subject=subject)
    assert not has_protocol_connection_capability(graph)
    assert json.loads(codec.dumps(graph))["schema_version"] == 18


@pytest.mark.parametrize(
    ("profile", "kind"),
    [
        (ProtocolProfile.COROUTINE_BODY_V1, ResumableKind.COROUTINE),
        (ProtocolProfile.GENERATOR_COROUTINE_BODY_V1, ResumableKind.GENERATOR_COROUTINE),
    ],
)
@pytest.mark.parametrize("subject", ["body", "none"])
def test_new_body_profile_applicability_of_old_admission_shape_selects_v19(
        profile, kind, subject):
    graph, _ = admission_program(subject=subject)
    graph = replace(
        graph,
        protocol_scopes=tuple(replace(row, profile=profile) for row in graph.protocol_scopes),
        resumable_bodies=tuple(replace(row, kind=kind) for row in graph.resumable_bodies),
        operations=tuple(replace(row, terminator=replace(row.terminator, flavor=SuspensionFlavor.AWAIT))
                         if kind is ResumableKind.COROUTINE
                         and type(row.terminator) is SuspendTerminator else row
                         for row in graph.operations),
    )
    assert has_protocol_connection_capability(graph)
    wire = codec.dumps(graph)
    assert json.loads(wire)["schema_version"] == 19
    assert codec.loads(wire) == graph
