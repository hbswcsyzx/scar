"""New v16 capability and independently frozen historical wire boundaries."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from scar.ir.program import ExactLiteralOrigin
from scar.ir.program.codec import SCHEMA_VERSION, dumps, loads
from tests.fixtures.program_literals import literal_program
from tests.fixtures.program_state_addresses import state_address_program


@pytest.mark.parametrize("exact,attachments", [(True, False), (False, True), (True, True)])
def test_either_capability_selects_v16(exact, attachments):
    graph, _ = literal_program(exact=exact, attachments=attachments)
    wire = dumps(graph)
    assert SCHEMA_VERSION == 19
    assert json.loads(wire)["schema_version"] == 16
    assert loads(wire) == graph
    assert dumps(loads(wire)) == wire


@pytest.mark.parametrize("payload", ["\ud800", "\ud800\udc00", "\U00010000", "a\x00é",
                                      complex(-0.0, float("nan")), (None, b"\x00\xff", Ellipsis)])
def test_exact_escaped_payload_survives_utf8_snapshot(payload):
    graph, _ = literal_program(payload=payload)
    wire = dumps(graph)
    assert wire.isascii()
    assert loads(wire.encode("utf8").decode("utf8")) == graph
    original = next(v for v in graph.values if isinstance(v.origin, ExactLiteralOrigin))
    recovered = next(v for v in loads(wire).values if isinstance(v.origin, ExactLiteralOrigin))
    assert recovered.origin.literal == original.origin.literal
    assert recovered.origin.literal.to_python() == payload or isinstance(payload, complex)


def test_independent_v15_golden_bytes_and_current_factory_unchanged():
    root = Path(__file__).resolve().parents[1] / "fixtures"
    wire = (root / "program_graph_v15_frozen.json").read_bytes()
    proof = json.loads((root / "program_graph_v15_frozen.proof.json").read_text())
    assert proof["source_revision"] == "13201ad24e0d8236623e28709f86e13a887ed4fb"
    assert proof["schema_version"] == 15
    assert hashlib.sha256(wire).hexdigest() == proof["fixture_sha256"]
    assert len(wire) == proof["fixture_bytes"]
    assert dumps(loads(wire.decode())).encode() == wire
    current, _ = state_address_program()
    assert dumps(current).encode() == wire


@pytest.mark.parametrize("version", range(1, 16))
def test_old_schemas_reject_even_empty_new_table(version):
    graph, _ = literal_program()
    doc = json.loads(dumps(graph))
    doc["schema_version"] = version
    doc["literal_evaluations"] = []
    with pytest.raises(ValueError):
        loads(json.dumps(doc))


def test_old_schema_rejects_new_origin_even_without_new_table():
    graph, _ = literal_program(attachments=False)
    doc = json.loads(dumps(graph))
    del doc["literal_evaluations"]
    doc["schema_version"] = 15
    with pytest.raises(ValueError):
        loads(json.dumps(doc))


def test_v16_requires_capability_and_rejects_unknown_or_forged_fields():
    graph, _ = literal_program(exact=False, attachments=False)
    doc = json.loads(dumps(graph))
    doc["schema_version"] = 16
    # v2 emitted only old fields; supply all current fields from a v16 document.
    full = json.loads(dumps(literal_program()[0]))
    for key in full:
        doc.setdefault(key, [])
    with pytest.raises(ValueError, match="requires exact literal"):
        loads(json.dumps(doc))
    full["literal_evaluations"][0]["verified"] = True
    with pytest.raises(ValueError):
        loads(json.dumps(full))


def test_wrong_variant_tag_and_missing_field_are_not_structural_fallbacks():
    doc = json.loads(dumps(literal_program()[0]))
    del doc["literal_evaluations"][0]["definition"]
    with pytest.raises(ValueError):
        loads(json.dumps(doc))
    doc = json.loads(dumps(literal_program()[0]))
    doc["literal_evaluations"][2]["site"]["kind"] = "EXACT_LITERAL_ORIGIN"
    with pytest.raises(ValueError):
        loads(json.dumps(doc))
