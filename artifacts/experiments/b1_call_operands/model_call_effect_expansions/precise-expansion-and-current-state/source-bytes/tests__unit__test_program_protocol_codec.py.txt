"""F wire isolation; declared records never certify source/runtime behavior."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from scar.ir import record_codec
from scar.ir.execution import codec as execution_codec
from scar.ir.program import codec
from scar.ir.program.ids import NativeBoundaryID, OperationID, UseID
from scar.ir.program.model import CompletionResult, ExitKind, InvokeLiteralResult
from scar.ir.program.native import ExitPortRef
from scar.ir.program.protocols import (
    ContractResult, NativeExit, OutcomeAdapter, OutcomeAdapterRule, ProtocolCall,
    ProtocolCallRule, ProtocolClause, ProtocolOperation, PROTOCOL_RECORD_TAGS,
)
from scar.ir.program.state_addresses import STATE_ADDRESS_RECORD_TAGS
from scar.ir.program.structured import ControlEdgeReference
from tests.fixtures.program_literals import literal_program
from tests.fixtures.program_protocol_graphs import (
    generator_protocol_program, no_entry_throw_program, request_processing_program,
)


@pytest.mark.parametrize("target", ["start", "value", "packet"])
def test_f_capability_roundtrips_scope_only_and_n_r_port_graphs(target):
    graph, _ = generator_protocol_program(target=target)
    wire = codec.dumps(graph)
    document = json.loads(wire)
    assert codec.SCHEMA_VERSION == 25
    # F does not select O; the independent old execution still selects v7.
    assert execution_codec.SCHEMA_VERSION >= 7
    old_wire = (Path(__file__).parents[1] / "fixtures/execution_v7_frozen.json").read_bytes()
    old_execution = execution_codec.loads(old_wire.decode("utf-8"))
    assert execution_codec.to_dict(old_execution)["schema_version"] == 7
    assert execution_codec.dumps(old_execution).encode("utf-8") == old_wire
    assert document["schema_version"] == 17
    assert codec.loads(wire) == graph
    assert codec.dumps(codec.loads(wire)) == wire
    assert document["protocol_scopes"]
    if target == "start":
        assert document["protocol_operations"] == []
    else:
        assert not graph.state_address_refinements and not graph.literal_evaluations
        # Existing port types still carry their original tags when nested in F.
        contracts = [row["contract"] for row in document["protocol_operations"]
                     if row["contract"]["kind"] == "PROTOCOL_REQUEST_PROCESSING"]
        assert contracts
        assert all(c["result"]["kind"] == "INVOKE_LITERAL_RESULT" for c in contracts)
        assert {c["result"]["edge"]["successor_index"] for c in contracts} == {0, 1}
        assert all(site["kind"] == "INVOKE_STATE_OPERAND"
                   for contract in contracts for site in contract["state_sites"])


@pytest.mark.parametrize("loop", [False, True])
def test_packet_contract_reference_and_distinct_owned_use_roundtrip(loop):
    graph, _ = request_processing_program(loop=loop)
    decoded = codec.loads(codec.dumps(graph))
    assert decoded == graph
    first, second = decoded.protocol_operations
    assert type(second.contract.exception_source) is ContractResult
    assert second.contract.exception_source.operation == first.operation
    assert type(second.contract.traceback_source).__name__ == "OwnedUse"


@pytest.mark.parametrize("selected,reject", [(ExitKind.NORMAL, False), (ExitKind.RAISE, False),
                                            (ExitKind.NORMAL, True)])
def test_no_entry_preserves_accurate_selected_edge_and_host_raise(selected, reject):
    graph, details = no_entry_throw_program(selected=selected, reject=reject)
    decoded = codec.loads(codec.dumps(graph))
    assert not decoded.body_drives
    assert decoded.protocol_operations[0].contract.selected_edge.successor_index == details["selected_edge"]
    assert decoded == graph


def test_independent_frozen_v16_and_current_non_f_factory_are_exact_bytes():
    fixture_dir = Path(__file__).resolve().parents[1] / "fixtures"
    wire = (fixture_dir / "program_graph_v16_frozen.json").read_bytes()
    proof = json.loads((fixture_dir / "program_graph_v16_frozen.proof.json").read_text())
    assert proof["source_revision"] == "85aee70dd6217e61c03df54ef4ee154b0d662328"
    assert proof["schema_version"] == 16
    assert proof["codec_sha256"] == "6c2cfdd03cbc4f70f32a7bf483f5914e406d10171821792bb5234e821750e336"
    assert hashlib.sha256(wire).hexdigest() == proof["fixture_sha256"]
    assert len(wire) == proof["fixture_bytes"]
    assert "protocol_scopes" not in json.loads(wire)
    assert codec.dumps(codec.loads(wire.decode())).encode() == wire
    current, _ = literal_program(payload=(1, b"bytes", None, complex(-0.0, 2), "\ud800\udc00"))
    assert codec.dumps(current).encode() == wire


@pytest.mark.parametrize("version", range(1, 17))
def test_historical_schemas_reject_new_even_empty_fields(version):
    doc = json.loads(codec.dumps(generator_protocol_program()[0]))
    doc["schema_version"] = version
    doc["protocol_scopes"] = []
    doc["protocol_operations"] = []
    with pytest.raises(ValueError, match="top-level fields"):
        codec.loads(json.dumps(doc))


def test_empty_f_tables_do_not_upgrade_old_program_or_authorize_v17():
    graph, _ = literal_program()
    assert graph.protocol_scopes == () and graph.protocol_operations == ()
    wire = codec.dumps(graph)
    assert json.loads(wire)["schema_version"] == 16
    doc = json.loads(wire)
    doc.update(schema_version=17, protocol_scopes=[], protocol_operations=[])
    with pytest.raises(ValueError, match="requires explicit protocol capability"):
        codec.loads(json.dumps(doc))


@pytest.mark.parametrize("field", ["protocol_scopes", "protocol_operations"])
def test_v17_requires_both_tables_and_rejects_unknown_authority(field):
    doc = json.loads(codec.dumps(generator_protocol_program()[0]))
    del doc[field]
    with pytest.raises(ValueError, match="top-level fields"):
        codec.loads(json.dumps(doc))
    doc = json.loads(codec.dumps(generator_protocol_program()[0]))
    doc["protocol_scopes"][0]["verified"] = True
    with pytest.raises(ValueError):
        codec.loads(json.dumps(doc))


def test_new_protocol_tag_cannot_enter_legacy_origin_or_wrong_variant():
    graph, _ = literal_program()
    old = json.loads(codec.dumps(graph))
    old["values"][2]["origin"] = {"kind": "STATIC_PROTOCOL_GAP", "reason": "PORT_UNCAPTURED"}
    with pytest.raises(ValueError):
        codec.loads(json.dumps(old))
    doc = json.loads(codec.dumps(request_processing_program()[0]))
    doc["protocol_operations"][0]["contract"]["kind"] = "PROTOCOL_PACKET_CONSTRUCTION"
    with pytest.raises(ValueError):
        codec.loads(json.dumps(doc))


def test_model_tables_are_exact_recursive_and_have_correct_natural_keys():
    graph, _ = request_processing_program()
    first = graph.protocol_operations[0]
    with pytest.raises(ValueError, match="duplicates"):
        replace(graph, protocol_scopes=graph.protocol_scopes * 2)
    with pytest.raises(ValueError, match="duplicates"):
        replace(graph, protocol_operations=(*graph.protocol_operations, first))
    with pytest.raises(TypeError, match="tuple"):
        replace(graph, protocol_operations=list(graph.protocol_operations))
    # Same operation with a different clause/slot is not a duplicate natural key.
    replace(graph, protocol_operations=(first, replace(first, slot=1)))
    mutated = replace(first)
    object.__setattr__(mutated, "slot", True)
    with pytest.raises(TypeError):
        replace(graph, protocol_operations=(mutated,))
    mutated = replace(first.contract)
    object.__setattr__(mutated, "operand_bindings", [*mutated.operand_bindings])
    with pytest.raises(TypeError):
        replace(first, contract=mutated)


def test_all_five_contract_variants_have_strict_reachable_record_tags():
    """Record-only serialization checks; deliberately not graph applicability proof."""
    graph, details = request_processing_program()
    request, packet = graph.protocol_operations
    noentry_graph, _ = no_entry_throw_program()
    noentry = noentry_graph.protocol_operations[0]
    invocation = InvokeLiteralResult(ControlEdgeReference(OperationID("opaque.invoke"), 1), CompletionResult(0))
    call = replace(request, contract=ProtocolCall(UseID("receiver"), (UseID("argument"),),
        invocation, (), ProtocolCallRule.AWAIT_CALL))
    adapted = replace(request, contract=OutcomeAdapter(
        ContractResult(request.scope, request.clause, request.operation, request.slot,
                       request.contract.result), UseID("adapter.input"),
        NativeExit(NativeBoundaryID("endpoint"), ExitPortRef(graph.root, "failure", 0)),
        OutcomeAdapterRule.DELEGATE_ONLY_HOST_EXCEPTION))
    tags = {**codec._LITERAL_RECORD_TAGS, **STATE_ADDRESS_RECORD_TAGS, **PROTOCOL_RECORD_TAGS}
    for row in (request, packet, noentry, call, adapted):
        encoded = record_codec.encode(row, record_tags=tags)
        assert record_codec.decode(ProtocolOperation, encoded, record_tags=tags) == row
        assert encoded["contract"]["kind"].startswith("PROTOCOL_")
        forged = {**encoded, "contract": {**encoded["contract"], "authorized": True}}
        with pytest.raises(ValueError):
            record_codec.decode(ProtocolOperation, forged, record_tags=tags)
