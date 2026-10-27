"""C1 uses v9 route tags and leaves v1-v8 wire capabilities unchanged."""
import json
from pathlib import Path

import pytest

from scar.ir.program import dumps, loads
from scar.ir.program.model import OperationResult, ProtocolValue, ValueID
from scar.ir.program.control import ProtocolValueKind
from scar.ir.record_codec import encode
from tests.fixtures.program_cleanup_graphs import (
    cleanup_return_resume_graph, nested_cleanup_fallthrough_and_replace_graph,
)


FIXTURES = Path(__file__).parents[1] / "fixtures"
CLEANUP_FIELDS = {
    "handled_context_domains", "cleanup_interfaces", "cleanup_enters",
    "cleanup_resumes", "cleanup_replacements", "handled_context_reads",
}


@pytest.mark.parametrize("factory", [cleanup_return_resume_graph,
                                      nested_cleanup_fallthrough_and_replace_graph])
def test_c1_roundtrip_uses_v9_route_tag_and_keeps_c0_dispatch_distinct(factory):
    graph = factory()
    payload = dumps(graph)
    document = json.loads(payload)
    assert document["schema_version"] == 9
    terms = [operation["terminator"] for operation in document["operations"]
             if operation["terminator"] is not None]
    assert any(term.get("kind") == "CLEANUP_ROUTE" for term in terms)
    # C0 dispatch keeps its historical tagless {pending, successors} shape;
    # only the new C1 route has the explicit discriminator.
    assert any(set(term) == {"pending", "successors"} for term in terms)
    assert loads(payload) == graph
    assert dumps(loads(payload)) == payload


def test_local_loop_cleanup_graph_roundtrips_and_keeps_c0_dispatch():
    from tests.fixtures.program_cleanup_graphs import local_loop_transfers_in_cleanup_graph

    graph = local_loop_transfers_in_cleanup_graph()
    payload = dumps(graph)
    assert json.loads(payload)["schema_version"] == 9
    assert loads(payload) == graph


@pytest.mark.parametrize("version", range(1, 9))
def test_historical_envelopes_reject_even_empty_cleanup_tables(version):
    source_version = max(2, version)
    document = json.loads((FIXTURES / f"program_graph_v{source_version}_frozen.json").read_text())
    if version == 1:
        document["schema_version"] = 1
        for operation in document["operations"]:
            operation.pop("completions", None)
            operation.pop("invoke_arguments", None)
    document["handled_context_domains"] = []
    with pytest.raises(ValueError, match="top-level fields"):
        loads(json.dumps(document))


def test_v8_golden_wire_remains_byte_stable():
    payload = (FIXTURES / "program_graph_v8_frozen.json").read_text().rstrip("\n")
    graph = loads(payload)
    assert dumps(graph) == payload
    assert not CLEANUP_FIELDS & set(json.loads(payload))


def test_historical_v8_cannot_smuggle_cleanup_route_tag_or_saved_context_value():
    c1 = json.loads(dumps(cleanup_return_resume_graph()))
    c1["schema_version"] = 8
    for field in CLEANUP_FIELDS:
        del c1[field]
    with pytest.raises(ValueError, match="historical schema"):
        loads(json.dumps(c1))

    old = json.loads((FIXTURES / "program_graph_v8_frozen.json").read_text())
    from scar.ir.program.codec import loads as load_program
    old_graph = load_program(json.dumps(old))
    old["values"].append(encode(ProtocolValue(
        ValueID("smuggled.saved-context"), old_graph.root,
        OperationResult(old_graph.operations[0].id, 0),
        ProtocolValueKind.SAVED_HANDLED_CONTEXT)))
    with pytest.raises(ValueError, match="historical schema"):
        loads(json.dumps(old))
