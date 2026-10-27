"""Provider declarations add a capability without reinterpreting old wire."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from scar.ir.program import dumps, loads
from tests.fixtures.program_control_graphs import shared_pending_graph
from tests.fixtures.program_provider_graphs import definition_provider_graph
from tests.unit.test_program_control_codec import _old


FIXTURES = Path(__file__).parents[1] / "fixtures"
FIELDS = {"provider_envelopes", "provider_regions", "provider_bindings"}


@pytest.mark.parametrize("version", [2, 3, 4, 5, 6])
def test_original_wires_keep_their_exact_encoding_and_no_provider_claim(version):
    payload = (FIXTURES / f"program_graph_v{version}_frozen.json").read_text().rstrip("\n")
    graph = loads(payload)
    assert not graph.provider_envelopes and not graph.provider_regions and not graph.provider_bindings
    assert dumps(graph) == payload
    assert not FIELDS.intersection(json.loads(payload))


def test_v6_fixture_was_frozen_with_the_original_codec_and_unchanged_bytes():
    payload = (FIXTURES / "program_graph_v6_frozen.json").read_bytes()
    proof = json.loads((FIXTURES / "program_graph_v6_frozen.proof.json").read_text())
    assert proof["revision"] == "624560e102cc655ca2dca0362af5b646e5359d01"
    assert hashlib.sha256(payload).hexdigest() == proof["file_sha256"]
    assert hashlib.sha256(payload.rstrip(b"\n")).hexdigest() == proof["wire_sha256"]
    assert proof["wire_sha256"] == "03fe4ff31daf44a390be8f6ab30f4201a55706e581594be84fb27f116e9fcf20"


@pytest.mark.parametrize("version", [1, 2, 3, 4, 5, 6])
@pytest.mark.parametrize("field", sorted(FIELDS))
def test_historical_reader_rejects_even_empty_future_provider_tables(version, field):
    document = _old(version)
    loads(json.dumps(document))
    document[field] = []
    with pytest.raises(ValueError, match="top-level fields"):
        loads(json.dumps(document))


def test_provider_and_control_capabilities_compose_with_existing_core():
    core = shared_pending_graph()
    provider = definition_provider_graph().provider_envelopes[0]
    # Unmapped artifacts are allowed; availability and extraction are unproved.
    graph = replace(core, provider_envelopes=(provider,))
    document = json.loads(dumps(graph))
    assert document["schema_version"] == 7
    assert document["control_scopes"] and document["pending_completions"]
    assert loads(json.dumps(document)) == graph


@pytest.mark.parametrize("field", sorted(FIELDS))
def test_v7_requires_every_table(field):
    document = json.loads(dumps(definition_provider_graph()))
    del document[field]
    with pytest.raises(ValueError, match="top-level fields"):
        loads(json.dumps(document))


def test_empty_v7_relabel_and_downgrade_with_new_fields_are_rejected():
    document = _old(6)
    document["schema_version"] = 7
    document.update({name: [] for name in FIELDS})
    with pytest.raises(ValueError, match="requires explicit provider"):
        loads(json.dumps(document))
    document = json.loads(dumps(definition_provider_graph()))
    document["schema_version"] = 6
    with pytest.raises(ValueError, match="top-level fields"):
        loads(json.dumps(document))


@pytest.mark.parametrize("destination", ["envelope", "coverage", "binding", "document"])
def test_input_cannot_add_an_authority_flag(destination):
    document = json.loads(dumps(definition_provider_graph(complete_claims=True)))
    targets = {"envelope": document["provider_envelopes"][0],
               "coverage": document["provider_envelopes"][0]["coverage"][0],
               "binding": document["provider_bindings"][0], "document": document}
    targets[destination]["transformation_authorized"] = True
    with pytest.raises(ValueError):
        loads(json.dumps(document))


def test_nested_path_and_digest_fields_retain_strict_wire_types():
    document = json.loads(dumps(definition_provider_graph()))
    binding = next(row for row in document["provider_bindings"] if row["external"]["kind"] == "USE")
    binding["external"]["path"][0]["index"] = True
    with pytest.raises(ValueError):
        loads(json.dumps(document))
    document = json.loads(dumps(definition_provider_graph()))
    document["provider_envelopes"][0]["artifact"]["sha256"] = "sha256:" + "a" * 64
    with pytest.raises(ValueError):
        loads(json.dumps(document))
