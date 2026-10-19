"""Program22 fallback associations preserve canonical ports and old wire."""
from dataclasses import fields, replace
import hashlib
import json
from pathlib import Path

import pytest

from scar.ir.program import codec
from scar.ir.program.model import ProgramGraph
from scar.ir.program.protocol_connections import (
    DelegateLookupFallback, InjectedPacketTrigger, LOOKUP_FALLBACK_RECORD_TAGS,
    NormalizedThrowSource, PROTOCOL_CONNECTION_RECORD_TAGS,
    has_lookup_fallback_capability,
)
from scar.ir.program.protocols import StaticGapReason, StaticProtocolGap
from scar.ir.program.validation import require_valid
from tests.fixtures.program_exception_match_graphs import exception_match_program
from tests.fixtures.program_lookup_fallback_graphs import lookup_fallback_program


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ORACLE_REVISION = "8585d7f2aa013896fa58c3759d540338b78d43a5"
ORACLE_PROFILE = "exception_match_program(mode='invoke', input_kind='packet')"


def _document(*, kind="close", matcher="ordinary", throw_arity=3):
    graph, _ = lookup_fallback_program(kind=kind, matcher=matcher, throw_arity=throw_arity)
    require_valid(graph)
    return graph, json.loads(codec.dumps(graph))


def _binding(document):
    return next(row for row in document["protocol_bindings"]
                if row["kind"] == "DELEGATE_LOOKUP_FALLBACK")


@pytest.mark.parametrize("kind", ("close", "throw"))
@pytest.mark.parametrize("matcher", ("ordinary", "invoke", "raise-only"))
def test_lookup_fallback_selects_program22_and_preserves_original_port_namespaces(kind, matcher):
    graph, document = _document(kind=kind, matcher=matcher)
    assert codec.SCHEMA_VERSION == 26
    assert has_lookup_fallback_capability(graph)
    assert document["schema_version"] == 22
    assert set(document) == ({field.name for field in fields(ProgramGraph)} - {"call_effect_expansions"}) | {"schema", "schema_version"}
    original, = (row for row in graph.protocol_bindings if type(row) is DelegateLookupFallback)
    encoded = _binding(document)
    assert encoded["lookup"]["kind"] == "PROTOCOL_OPERATION_REF"
    assert encoded["lookup"]["operation"]["wire"] == original.lookup.operation.wire
    assert encoded["matcher"]["wire"] == original.matcher.wire
    assert set(encoded) == {"kind", "lookup", "matcher", "request", "guard"}
    if kind == "throw":
        assert type(original.request) is NormalizedThrowSource
        assert encoded["request"]["kind"] == "NORMALIZED_THROW_SOURCE"
        assert encoded["request"]["raw"]["operation"]["wire"] == original.request.raw.operation.wire
        assert encoded["request"]["raw"]["use"]["wire"] == original.request.raw.use.wire
    else:
        assert type(original.request) is InjectedPacketTrigger
        assert encoded["request"]["kind"] == "INJECTED_PACKET_TRIGGER"
    wire = codec.dumps(graph)
    recovered = codec.loads(wire)
    assert recovered == graph and codec.dumps(recovered) == wire
    recovered_binding, = (row for row in recovered.protocol_bindings if type(row) is DelegateLookupFallback)
    assert recovered_binding == original
    assert type(recovered_binding.request) is type(original.request)
    assert recovered_binding.lookup == original.lookup and recovered_binding.matcher == original.matcher


@pytest.mark.parametrize("arity", (1, 2, 3))
def test_throw_source_roundtrip_keeps_the_exact_raw_anchor_and_whole_packet(arity):
    graph, _ = _document(kind="throw", throw_arity=arity)
    binding, = (row for row in graph.protocol_bindings if type(row) is DelegateLookupFallback)
    operations = {row.id: row for row in graph.operations}
    raw_use = next(use for use in operations[binding.request.raw.operation].uses
                   if use.id == binding.request.raw.use)
    raw = next(row for row in graph.raw_driver_requests if row.value == raw_use.value)
    assert len(raw.operands) == arity
    recovered = codec.loads(codec.dumps(graph))
    supplied, = (row for row in recovered.protocol_bindings if type(row) is DelegateLookupFallback)
    assert supplied.request.raw == binding.request.raw
    assert supplied.request.packet == binding.request.packet


def test_removing_new_binding_returns_to_the_old_matcher_family_without_erasing_core():
    graph, _ = _document()
    without = replace(graph, protocol_bindings=tuple(row for row in graph.protocol_bindings
                                                   if type(row) is not DelegateLookupFallback))
    require_valid(without)
    assert without.operations == graph.operations and without.exception_matches == graph.exception_matches
    assert not has_lookup_fallback_capability(without)
    wire = codec.dumps(without)
    assert json.loads(wire)["schema_version"] == 21
    assert codec.loads(wire) == without and codec.dumps(codec.loads(wire)) == wire


def test_an_explicit_missing_request_is_still_program22_capability():
    graph, _ = _document()
    binding, = (row for row in graph.protocol_bindings if type(row) is DelegateLookupFallback)
    partial = replace(graph, protocol_bindings=tuple(
        replace(row, request=StaticProtocolGap(StaticGapReason.PORT_UNCAPTURED))
        if row is binding else row for row in graph.protocol_bindings))
    require_valid(partial)
    wire = codec.dumps(partial)
    assert json.loads(wire)["schema_version"] == 22
    assert codec.loads(wire) == partial


def test_independent_program21_oracle_keeps_the_original_encoder_bytes():
    wire = (FIXTURES / "program_graph_v21_frozen.json").read_bytes()
    proof = json.loads((FIXTURES / "program_graph_v21_frozen.proof.json").read_text())
    assert proof["source_revision"] == ORACLE_REVISION
    assert proof["schema_version"] == 21 and proof["fixture_profile"] == ORACLE_PROFILE
    assert len(wire) == proof["fixture_bytes"]
    assert hashlib.sha256(wire).hexdigest() == proof["fixture_sha256"]
    assert json.loads(wire)["schema_version"] == 21
    recovered = codec.loads(wire.decode("ascii"))
    assert not has_lookup_fallback_capability(recovered)
    assert codec.dumps(recovered).encode("ascii") == wire
    current, _ = exception_match_program(mode="invoke", input_kind="packet")
    assert codec.dumps(current).encode("ascii") == wire


@pytest.mark.parametrize("version", range(2, 22))
def test_historical_profiles_keep_their_exact_encoder_bytes(version):
    # Historical fixture separators are preserved on disk, as in prior gates.
    wire = (FIXTURES / f"program_graph_v{version}_frozen.json").read_bytes().rstrip(b"\n")
    recovered = codec.loads(wire.decode("utf8"))
    assert not has_lookup_fallback_capability(recovered)
    assert codec.dumps(recovered).encode("utf8") == wire


@pytest.mark.parametrize("version", (19, 20, 21))
def test_fallback_binding_cannot_be_downgraded_into_a_known_old_union(version):
    _, document = _document(kind="throw")
    document["schema_version"] = version
    if version < 21:
        del document["exception_matches"]
    with pytest.raises((TypeError, ValueError)):
        codec.loads(json.dumps(document))


@pytest.mark.parametrize("kind", ("close", "throw"))
def test_untagged_new_records_cannot_bypass_the_historical_capability_guard(kind):
    _, document = _document(kind=kind)
    document["schema_version"] = 21
    row = _binding(document)
    del row["kind"]
    if kind == "throw":
        del row["request"]["kind"]
    # New types are members of the in-memory union even for an old decoder.
    # Omitting their new tags must not sneak them through that union.
    with pytest.raises(ValueError, match="historical schema cannot contain lookup fallback capability"):
        codec.loads(json.dumps(document))


def test_program22_rejects_an_old_program21_without_the_new_binding():
    document = json.loads((FIXTURES / "program_graph_v21_frozen.json").read_text())
    document["schema_version"] = 22
    with pytest.raises(ValueError, match="requires explicit lookup fallback capability"):
        codec.loads(json.dumps(document))


@pytest.mark.parametrize("change", (
    "unknown_kind", "missing_request", "extra_authority", "boolean_slot", "wrong_matcher_namespace",
    "raw_trigger_as_request", "missing_packet", "wrong_packet_union", "boolean_guard",
))
def test_program22_rechecks_nested_shapes_and_closed_source_unions(change):
    _, document = _document(kind="throw")
    row = _binding(document)
    if change == "unknown_kind":
        row["kind"] = "UNREGISTERED_LOOKUP_FALLBACK"
    elif change == "missing_request":
        del row["request"]
    elif change == "extra_authority":
        row["verified"] = False
    elif change == "boolean_slot":
        row["lookup"]["slot"] = True
    elif change == "wrong_matcher_namespace":
        row["matcher"] = row["request"]["raw"]["use"]
    elif change == "raw_trigger_as_request":
        row["request"] = {"kind": "RAW_REQUEST_TRIGGER", "raw": row["request"]["raw"]}
    elif change == "missing_packet":
        del row["request"]["packet"]
    elif change == "wrong_packet_union":
        row["request"]["packet"] = row["lookup"]
    else:
        row["guard"] = {"operation": row["lookup"]["operation"], "successor_index": True}
    with pytest.raises((TypeError, ValueError)):
        codec.loads(json.dumps(document))


def test_fallback_natural_key_cannot_be_duplicated_in_the_existing_binding_table():
    _, document = _document()
    document["protocol_bindings"].append(_binding(document))
    with pytest.raises((TypeError, ValueError)):
        codec.loads(json.dumps(document))


def test_normalized_throw_source_does_not_silently_extend_the_old_call_trigger_union():
    _, document = _document(kind="throw")
    document["protocol_call_inputs"][0]["cases"][0]["trigger"] = _binding(document)["request"]
    with pytest.raises((TypeError, ValueError)):
        codec.loads(json.dumps(document))


def test_fallback_tags_are_separate_from_the_frozen_connection_tag_registry():
    assert DelegateLookupFallback not in PROTOCOL_CONNECTION_RECORD_TAGS
    assert NormalizedThrowSource not in PROTOCOL_CONNECTION_RECORD_TAGS
    assert LOOKUP_FALLBACK_RECORD_TAGS[DelegateLookupFallback] == ("kind", "DELEGATE_LOOKUP_FALLBACK")
    with pytest.raises(TypeError):
        LOOKUP_FALLBACK_RECORD_TAGS[DelegateLookupFallback] = ("kind", "ALTERED")


@pytest.mark.parametrize("version", (27, True))
def test_future_and_boolean_schema_versions_remain_rejected(version):
    document = json.loads((FIXTURES / "program_graph_v21_frozen.json").read_text())
    document["schema_version"] = version
    with pytest.raises(ValueError, match="unsupported program graph schema version"):
        codec.loads(json.dumps(document))
