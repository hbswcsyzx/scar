"""C2 body wire is v10; old schemas remain strict and byte stable."""
import hashlib
import json
from pathlib import Path

import pytest

from scar.ir.program.codec import SCHEMA_VERSION, dumps, loads
from scar.ir.program.control import ProtocolValueKind
from scar.ir.program.ids import ValueID
from scar.ir.program.model import BlockArgument, ProtocolValue
from scar.ir.record_codec import encode
from tests.fixtures.program_resumption_graphs import resumption_program
from tests.fixtures.program_cleanup_graphs import resume_multistate_graph


FIXTURES = Path(__file__).parents[1] / "fixtures"
RESUMPTION_FIELDS = {
    "resumable_bodies", "frame_context_initials", "frame_context_attaches",
    "frame_context_detaches",
}


def _v10_document():
    return json.loads(dumps(resumption_program()))


def _old_document(version):
    source_version = max(2, version)
    if version == 9:
        document = json.loads((FIXTURES / "program_graph_v9_frozen.json").read_text())
    else:
        document = json.loads((FIXTURES / f"program_graph_v{source_version}_frozen.json").read_text())
    if version == 1:
        document["schema_version"] = 1
        for operation in document["operations"]:
            operation.pop("completions", None)
            operation.pop("invoke_arguments", None)
    return document


def test_resumption_graph_uses_strict_v10_tagged_wire_and_roundtrips():
    graph = resumption_program()
    payload = dumps(graph)
    document = json.loads(payload)
    assert SCHEMA_VERSION == 12
    assert document["schema_version"] == 10
    assert RESUMPTION_FIELDS <= set(document)
    assert all(document[name] for name in RESUMPTION_FIELDS)
    terms = [operation["terminator"] for operation in document["operations"]
             if operation["terminator"] is not None]
    suspend = [term for term in terms if term.get("kind") == "SUSPEND"]
    assert suspend
    assert all(set(term) == {
        "kind", "flavor", "exported", "saved", "handoff", "successors"
    } for term in suspend)
    assert loads(payload) == graph
    assert dumps(loads(payload)) == payload


def test_saved_and_resume_inputs_are_disjoint_strict_union_records():
    document = _v10_document()
    term = next(operation["terminator"] for operation in document["operations"]
                if operation["terminator"] is not None
                and operation["terminator"].get("kind") == "SUSPEND")
    projections = [argument for edge in term["successors"] for argument in edge["arguments"]]
    assert any(set(item) == {"saved_slot"} for item in projections)
    assert any(set(item) == {"resume_slot"} for item in projections)

    malformed = json.loads(json.dumps(document))
    term = next(operation["terminator"] for operation in malformed["operations"]
                if operation["terminator"] is not None
                and operation["terminator"].get("kind") == "SUSPEND")
    projection = next(argument for edge in term["successors"] for argument in edge["arguments"]
                     if set(argument) == {"saved_slot"})
    projection["resume_slot"] = 0
    with pytest.raises((TypeError, ValueError)):
        loads(json.dumps(malformed))

    malformed = json.loads(json.dumps(document))
    term = next(operation["terminator"] for operation in malformed["operations"]
                if operation["terminator"] is not None
                and operation["terminator"].get("kind") == "SUSPEND")
    term["unrecognized"] = True
    with pytest.raises((TypeError, ValueError)):
        loads(json.dumps(malformed))


def test_v9_golden_isolated_from_mutable_codec_and_remains_byte_stable():
    raw = (FIXTURES / "program_graph_v9_frozen.json").read_bytes()
    proof = json.loads((FIXTURES / "program_graph_v9_frozen.proof.json").read_text())
    assert proof["source_revision"] == "b4bc1a4"
    assert proof["generated_from_current_worktree"] is False
    assert hashlib.sha256(raw).hexdigest() == proof["fixture_file_sha256"]
    assert hashlib.sha256(raw[:-1]).hexdigest() == proof["logical_wire_sha256"]
    payload = raw[:-1].decode("utf-8")
    assert json.loads(payload)["schema_version"] == 9
    assert not RESUMPTION_FIELDS & set(json.loads(payload))
    assert dumps(loads(payload)) == payload
    assert dumps(resume_multistate_graph()) == payload


@pytest.mark.parametrize("version", range(1, 10))
@pytest.mark.parametrize("field", sorted(RESUMPTION_FIELDS))
def test_v1_to_v9_reject_each_new_top_level_capability_table(version, field):
    document = _old_document(version)
    document[field] = []
    with pytest.raises(ValueError, match="top-level fields"):
        loads(json.dumps(document))


@pytest.mark.parametrize("version", range(1, 10))
def test_v1_to_v9_reject_suspend_tag(version):
    document = _old_document(version)
    operation = next(item for item in document["operations"]
                     if item["terminator"] is not None)
    operation["terminator"] = {"kind": "SUSPEND"}
    with pytest.raises(ValueError, match="historical schema"):
        loads(json.dumps(document))


@pytest.mark.parametrize("version", range(1, 10))
def test_v1_to_v9_reject_new_protocol_values(version):
    old = _old_document(version)
    graph = loads(json.dumps(old))
    old["values"].append(encode(ProtocolValue(
        ValueID("smuggled.frame-context"), graph.root,
        BlockArgument(graph.regions[0].entry, 0), ProtocolValueKind.FRAME_CONTEXT)))
    with pytest.raises(ValueError, match="historical schema"):
        loads(json.dumps(old))


def test_v10_cannot_be_claimed_by_empty_resumption_tables():
    document = json.loads((FIXTURES / "program_graph_v9_frozen.json").read_text())
    document["schema_version"] = 10
    document.update({field: [] for field in RESUMPTION_FIELDS})
    with pytest.raises(ValueError, match="requires explicit resumable-body"):
        loads(json.dumps(document))

    document = _v10_document()
    document["resumable_bodies"] = []
    with pytest.raises(ValueError, match="requires explicit resumable body"):
        loads(json.dumps(document))
