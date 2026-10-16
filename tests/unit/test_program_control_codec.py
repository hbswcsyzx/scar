"""New protocol capability cannot silently reinterpret historical graph wires."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from scar.ir.program import (
    BlockID, ControlScope, ControlScopeID, ControlScopeKind, OperationResult,
    ProtocolValue, ProtocolValueKind, ValueID, dumps, loads,
)
from scar.ir.program.queries import ProgramIndex
from scar.ir.record_codec import encode
from tests.fixtures.program_control_graphs import (
    shared_pending_graph, loop_pending_graph, loop_transfer_graph,
)


FIXTURES = Path(__file__).parents[1] / "fixtures"
CONTROL_FIELDS = {"control_scopes", "control_ports", "exception_packets", "pending_completions"}


def _old(version):
    document = json.loads((FIXTURES / f"program_graph_v{max(2, version)}_frozen.json").read_text())
    if version == 1:
        document["schema_version"] = 1
        for operation in document["operations"]:
            del operation["completions"]
            del operation["invoke_arguments"]
    return document


@pytest.mark.parametrize("version", [2, 3, 4, 5])
def test_exact_original_wires_retain_original_capability(version):
    payload = (FIXTURES / f"program_graph_v{version}_frozen.json").read_text().rstrip("\n")
    graph = loads(payload)
    assert graph.control_scopes == ()
    assert dumps(graph) == payload
    assert not CONTROL_FIELDS & set(json.loads(payload))


@pytest.mark.parametrize("version", [1, 2, 3, 4, 5])
@pytest.mark.parametrize("field", sorted(CONTROL_FIELDS))
def test_old_envelope_rejects_even_empty_future_control_tables(version, field):
    document = _old(version)
    loads(json.dumps(document))
    document[field] = []
    with pytest.raises(ValueError, match="top-level fields"):
        loads(json.dumps(document))


@pytest.mark.parametrize("version", [1, 2, 3, 4, 5])
def test_old_value_union_cannot_be_used_to_smuggle_protocol_capability(version):
    document = _old(version)
    graph = loads(json.dumps(document))
    document["values"].append(encode(ProtocolValue(
        ValueID("injected"), graph.root, OperationResult(graph.operations[0].id, 0),
        ProtocolValueKind.EXCEPTION_PACKET)))
    with pytest.raises(ValueError, match="historical schema"):
        loads(json.dumps(document))


@pytest.mark.parametrize("make_graph", [shared_pending_graph, loop_pending_graph, loop_transfer_graph])
def test_v6_protocol_graph_roundtrip_uses_its_own_exact_shapes(make_graph):
    graph = make_graph()
    document = json.loads(dumps(graph))
    assert document["schema_version"] == 6
    assert CONTROL_FIELDS <= document.keys()
    assert loads(json.dumps(document)) == graph
    dispatches = [o["terminator"] for o in document["operations"]
                  if o["terminator"] is not None and "pending" in o["terminator"]]
    assert dispatches and all(set(t) == {"pending", "successors"} for t in dispatches)
    assert "cleanup_unwinding_verified" not in document


@pytest.mark.parametrize("field", sorted(CONTROL_FIELDS))
def test_v6_cannot_omit_a_required_table(field):
    document = json.loads(dumps(shared_pending_graph()))
    del document[field]
    with pytest.raises(ValueError, match="top-level fields"):
        loads(json.dumps(document))


def test_v6_is_not_an_alias_for_v5_and_cannot_self_authorize_cleanup():
    document = _old(5)
    document["schema_version"] = 6
    document.update({name: [] for name in CONTROL_FIELDS})
    with pytest.raises(ValueError, match="requires explicit lexical"):
        loads(json.dumps(document))
    document = json.loads(dumps(shared_pending_graph()))
    document["cleanup_unwinding_verified"] = True
    with pytest.raises(ValueError, match="top-level fields"):
        loads(json.dumps(document))
    del document["cleanup_unwinding_verified"]
    document["control_scopes"][0]["cleanup_unwinding_verified"] = True
    with pytest.raises(ValueError):
        loads(json.dumps(document))


def test_v5_environment_and_c0_scope_declarations_share_one_core():
    payload = (FIXTURES / "program_graph_v5_frozen.json").read_text()
    graph = loads(payload)
    source = shared_pending_graph().control_scopes[0].source
    graph = replace(graph, control_scopes=tuple(ControlScope(
        ControlScopeID("scope." + r.id.value), r.id, None, ControlScopeKind.FUNCTION,
        source, tuple(b.id for b in r.blocks)) for r in graph.regions))
    assert loads(dumps(graph)) == graph
    assert json.loads(dumps(graph))["schema_version"] == 6
    assert graph.environments


def test_index_facts_are_derived_ports_and_exact_existing_lexical_records():
    graph = shared_pending_graph()
    index = ProgramIndex(graph)
    for value in graph.values:
        if isinstance(value, ProtocolValue) and value.protocol is ProtocolValueKind.PENDING_COMPLETION:
            fact = index.pending_facts(value.id)
            assert fact.complete and fact.value == value.id
            assert tuple(p.id for p in index.pending_ports(value.id)) == fact.ports
            assert all(any(p is original for original in graph.control_ports)
                       for p in index.pending_ports(value.id))
    for scope in graph.control_scopes:
        for block in scope.blocks:
            assert index.control_scope(block) is scope
    reference = next(v for v in graph.values if not isinstance(v, ProtocolValue))
    with pytest.raises(TypeError):
        index.pending_facts(reference.id)
    with pytest.raises(KeyError):
        index.control_scope(BlockID("absent"))
