"""Program20 wire boundary for expanded delegate method lookup rules."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from scar.ir.program import codec
from scar.ir.program.protocol_connections import (
    has_delegated_method_lookup_capability,
    has_protocol_connection_capability,
)
from scar.ir.program.protocols import ProtocolCallRule
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid
from tests.fixtures.program_method_lookup_graphs import method_lookup_program


@pytest.mark.parametrize(
    ("request_kind", "rule"),
    [
        ("next", ProtocolCallRule.DELEGATE_NEXT_LOOKUP),
        ("send", ProtocolCallRule.DELEGATE_SEND_LOOKUP),
        ("throw", ProtocolCallRule.DELEGATE_THROW_LOOKUP),
        ("close", ProtocolCallRule.DELEGATE_CLOSE_LOOKUP),
    ],
)
def test_program20_method_lookup_rules_roundtrip_original_ports(request_kind, rule):
    graph, details = method_lookup_program(request=request_kind)
    assert has_delegated_method_lookup_capability(graph)
    assert has_protocol_connection_capability(graph)

    wire = codec.dumps(graph)
    document = json.loads(wire)
    assert document["schema_version"] == 20
    serialized_rules = {
        row["contract"]["rule"] for row in document["protocol_operations"]
        if row["operation"]["wire"] == details["method"]["operation"].id.wire
    }
    assert serialized_rules == {rule.value}

    decoded = codec.loads(wire)
    assert decoded == graph
    assert codec.dumps(decoded) == wire


def test_program20_capability_survives_missing_connection_tables():
    graph, details = method_lookup_program(request="send")
    partial = replace(graph, protocol_call_inputs=(), protocol_result_consumers=(),
                      protocol_bindings=())

    # Missing connection rows are an explicit gap. They must not erase the
    # rule that selects Program20 or make an incomplete graph fail structurally.
    require_valid(partial)
    assert has_delegated_method_lookup_capability(partial)
    wire = codec.dumps(partial)
    document = json.loads(wire)
    assert document["schema_version"] == 20
    assert document["protocol_call_inputs"] == []
    assert document["protocol_result_consumers"] == []
    assert document["protocol_bindings"] == []

    decoded = codec.loads(wire)
    assert decoded == partial
    assert codec.dumps(decoded) == wire

    obligations = ProgramIndex(decoded).protocol_obligations(details["scope"])
    common = obligations["connections"]["families"]["common"]
    method_id = details["method"]["operation"].id
    input_row = next(row for row in common["inputs"] if row["site"].operation == method_id)
    assert input_row["status"] == "MISSING"
    assert "protocol_call_inputs_missing" in input_row["gaps"]
    consumer_rows = [row for row in common["consumers"] if row["site"].operation == method_id]
    assert consumer_rows
    assert all("protocol_result_consumers_missing" in row["gaps"]
               for row in consumer_rows)


def test_program19_independent_oracle_retains_its_exact_bytes():
    fixture_dir = Path(__file__).resolve().parents[1] / "fixtures"
    wire = (fixture_dir / "program_graph_v19_frozen.json").read_bytes()
    proof = json.loads((fixture_dir / "program_graph_v19_frozen.proof.json").read_text())
    assert proof["source_revision"] == "7dd8c54b8d8cfdb3454b9f3b671f3412d1a914f0"
    assert proof["schema_version"] == 19
    assert len(wire) == proof["fixture_bytes"]
    assert hashlib.sha256(wire).hexdigest() == proof["fixture_sha256"]
    document = json.loads(wire)
    assert document["schema_version"] == 19
    assert document["protocol_call_inputs"]
    assert document["protocol_result_consumers"]

    decoded = codec.loads(wire.decode("ascii"))
    assert not has_delegated_method_lookup_capability(decoded)
    assert json.loads(codec.dumps(decoded))["schema_version"] == 19
    assert codec.dumps(decoded).encode("ascii") == wire


def test_program19_rejects_a_program20_method_lookup_rule():
    graph, _ = method_lookup_program(request="send")
    document = json.loads(codec.dumps(graph))
    assert document["schema_version"] == 20
    document["schema_version"] = 19
    with pytest.raises(ValueError, match="historical schema cannot contain delegated method lookup capability"):
        codec.loads(json.dumps(document))


def test_program20_requires_its_new_capability():
    fixture_dir = Path(__file__).resolve().parents[1] / "fixtures"
    document = json.loads((fixture_dir / "program_graph_v19_frozen.json").read_text())
    document["schema_version"] = 20
    with pytest.raises(ValueError, match="schema version 20 requires explicit delegated method lookup capability"):
        codec.loads(json.dumps(document))


@pytest.mark.parametrize("version", [25, True])
def test_program_graph_rejects_future_or_boolean_schema_versions(version):
    fixture_dir = Path(__file__).resolve().parents[1] / "fixtures"
    document = json.loads((fixture_dir / "program_graph_v19_frozen.json").read_text())
    document["schema_version"] = version
    with pytest.raises(ValueError, match="unsupported program graph schema version"):
        codec.loads(json.dumps(document))
