"""The native capability is schema v8; historical v7 bytes remain exact."""
import hashlib
import json
from pathlib import Path

import pytest

from scar.ir.program.codec import dumps, loads
from tests.fixtures.program_native_graphs import native_boundary_graph
from tests.unit.test_program_control_codec import _old


FIXTURES = Path(__file__).parents[1] / "fixtures"
NATIVE_FIELDS = {"native_boundaries", "boundary_relations"}


def test_native_boundary_graph_roundtrips_as_strict_v8():
    graph = native_boundary_graph()
    payload = dumps(graph)
    document = json.loads(payload)
    assert document["schema_version"] == 8
    assert NATIVE_FIELDS <= set(document)
    assert len(document["native_boundaries"]) == 2
    assert len(document["boundary_relations"]) == 1
    assert loads(payload) == graph


@pytest.mark.parametrize("field", sorted(NATIVE_FIELDS))
def test_v8_requires_both_native_tables(field):
    document = json.loads(dumps(native_boundary_graph()))
    del document[field]
    with pytest.raises(ValueError, match="top-level fields"):
        loads(json.dumps(document))


@pytest.mark.parametrize("version", range(1, 8))
@pytest.mark.parametrize("field", sorted(NATIVE_FIELDS))
def test_historical_v1_to_v7_reject_even_empty_native_tables(version, field):
    document = _old(version)
    loads(json.dumps(document))
    document[field] = []
    with pytest.raises(ValueError, match="top-level fields"):
        loads(json.dumps(document))


def test_original_v7_golden_keeps_frozen_encoding_and_has_no_native_capability():
    raw = (FIXTURES / "program_graph_v7_frozen.json").read_bytes()
    proof = json.loads((FIXTURES / "program_graph_v7_frozen.proof.json").read_text(encoding="utf-8"))
    assert proof["revision"] == "126d56eccf9a1b3d20e09af342e729b053193af1"
    assert hashlib.sha256(raw).hexdigest() == proof["file_sha256"]
    payload = raw.decode("utf-8").rstrip("\n")
    document = json.loads(payload)
    assert not NATIVE_FIELDS.intersection(document)
    assert dumps(loads(payload)) == payload


def test_v8_rejects_unknown_native_fields_and_cannot_be_downgraded():
    document = json.loads(dumps(native_boundary_graph()))
    document["native_boundaries"][0]["verified"] = True
    with pytest.raises(ValueError):
        loads(json.dumps(document))

    document = json.loads(dumps(native_boundary_graph()))
    document["schema_version"] = 7
    with pytest.raises(ValueError, match="top-level fields"):
        loads(json.dumps(document))


def test_empty_v8_relabel_cannot_claim_native_interface_capability():
    document = _old(7)
    document.update(schema_version=8, native_boundaries=[], boundary_relations=[])
    with pytest.raises(ValueError, match="requires explicit native boundary"):
        loads(json.dumps(document))


@pytest.mark.parametrize("target", ["relation", "obligation", "pair", "port"])
def test_nested_correspondence_cannot_self_assert_proof_or_accept_boolean_index(target):
    document = json.loads(dumps(native_boundary_graph()))
    relation = document["boundary_relations"][0]
    targets = {"relation": relation, "obligation": relation["obligations"][0],
               "pair": relation["ports"][0], "port": document["native_boundaries"][1]["outputs"][0]["port"]}
    if target == "port":
        targets[target]["index"] = False
    else:
        targets[target]["proven"] = True
    with pytest.raises(ValueError):
        loads(json.dumps(document))

