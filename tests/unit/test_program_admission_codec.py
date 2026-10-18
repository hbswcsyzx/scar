"""Program18 isolates readonly predicates while original Program17 stays exact."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from scar.ir.execution.codec import SCHEMA_VERSION as EXECUTION_SCHEMA_VERSION
from scar.ir.program import codec
from scar.ir.program.protocols import BodyStateCondition
from scar.ir.program.validation import require_valid
from tests.fixtures.program_admission_graphs import admission_program
from tests.fixtures.program_literals import literal_program
from tests.fixtures.program_protocol_graphs import generator_protocol_program


@pytest.mark.parametrize("subject", ("body", "none"))
def test_sixth_variant_roundtrip_preserves_original_uses_and_branch_without_fake_inputs(subject):
    graph, details = admission_program(subject=subject)
    require_valid(graph)
    row, = graph.protocol_operations
    operation = next(op for op in graph.operations if op.id == details["predicate"])
    assert all(use.value != graph.driver_interfaces[0].scheduler_request for use in operation.uses)
    if subject == "body":
        assert len(operation.uses) == 2 and len(operation.accesses) == 1
        assert type(row.contract.subject) is BodyStateCondition
    else:
        assert len(operation.uses) == 1 and not operation.accesses
        assert row.contract.state_sites == ()
    wire = codec.dumps(graph)
    document = json.loads(wire)
    contract = document["protocol_operations"][0]["contract"]
    assert codec.SCHEMA_VERSION == document["schema_version"] == 18
    assert EXECUTION_SCHEMA_VERSION == 7
    assert contract["kind"] == "PROTOCOL_ADMISSION_PREDICATE"
    assert set(contract) == {"subject", "result", "branch", "kind"}
    assert contract["subject"]["kind"] == (
        "PROTOCOL_BODY_STATE_CONDITION" if subject == "body"
        else "PROTOCOL_REFERENCE_IS_NONE_CONDITION")
    if subject == "body":
        assert contract["subject"]["state_sites"][0]["kind"] == "EXISTING_ACCESS"
    decoded = codec.loads(wire)
    assert decoded == graph
    assert codec.dumps(decoded) == wire
    assert decoded.protocol_operations[0].contract.branch == details["branch"]
    assert next(op for op in decoded.operations if op.id == details["predicate"]).uses == operation.uses
    assert decoded.protocol_operations[0].contract.result == row.contract.result
    assert not graph.body_drives and not graph.no_body_finishes


def test_independent_v17_golden_and_current_original_f_factory_are_identical_bytes():
    directory = Path(__file__).parents[1] / "fixtures"
    payload = (directory / "program_graph_v17_frozen.json").read_bytes()
    proof = json.loads((directory / "program_graph_v17_frozen.proof.json").read_text())
    assert proof["source_revision"] == "b88670b8720875175550bbb60df42e6089960eca"
    assert proof["schema_version"] == 17
    assert proof["fixture_factory"] == "generator_protocol_program(target='value')"
    assert proof["fixture_bytes"] == len(payload)
    assert proof["fixture_sha256"] == hashlib.sha256(payload).hexdigest()
    assert json.loads(payload)["schema_version"] == 17
    assert codec.dumps(codec.loads(payload.decode())).encode() == payload
    graph, _ = generator_protocol_program(target="value")
    assert codec.dumps(graph).encode() == payload


@pytest.mark.parametrize("version", range(1, 18))
def test_new_predicate_cannot_be_downgraded_into_any_historical_schema(version):
    graph, _ = admission_program()
    document = json.loads(codec.dumps(graph))
    document["schema_version"] = version
    with pytest.raises(ValueError):
        codec.loads(json.dumps(document))


def test_v17_rejects_untagged_new_shape_as_well_as_new_nested_subject_tags():
    graph, _ = admission_program(subject="none")
    document = json.loads(codec.dumps(graph))
    document["schema_version"] = 17
    contract = document["protocol_operations"][0]["contract"]
    contract.pop("kind")
    contract["subject"].pop("kind")
    # A union shape fallback must not silently expand Program17 vocabulary.
    with pytest.raises(ValueError):
        codec.loads(json.dumps(document))


def test_v18_requires_the_new_variant_not_only_original_protocol_tables():
    graph, _ = generator_protocol_program(target="start")
    document = json.loads(codec.dumps(graph))
    assert document["schema_version"] == 17
    document["schema_version"] = 18
    with pytest.raises(ValueError, match="admission predicate capability"):
        codec.loads(json.dumps(document))


@pytest.mark.parametrize("mutation", ("subject-tag", "missing", "extra", "result-union", "site-id"))
def test_nested_wire_variants_exact_fields_and_owned_port_ids_do_not_fallback(mutation):
    graph, _ = admission_program()
    document = json.loads(codec.dumps(graph))
    contract = document["protocol_operations"][0]["contract"]
    if mutation == "subject-tag":
        contract["subject"]["kind"] = "PROTOCOL_REFERENCE_IS_NONE_CONDITION"
    elif mutation == "missing":
        contract.pop("branch")
    elif mutation == "extra":
        contract["verified"] = True
    elif mutation == "result-union":
        contract["result"] = {"kind": "STATIC_PROTOCOL_GAP", "reason": "PORT_UNCAPTURED"}
    else:
        contract["subject"]["state_sites"][0]["operation"]["kind"] = "program_value"
    with pytest.raises(ValueError):
        codec.loads(json.dumps(document))


def test_nested_record_mutation_is_revalidated_before_encode():
    graph, _ = admission_program()
    rule = graph.protocol_operations[0].contract.subject
    object.__setattr__(rule, "rule", "IS_RUNNING")
    with pytest.raises((TypeError, ValueError)):
        codec.dumps(graph)


def test_old_literal_or_operation_label_matching_a_new_tag_is_not_capability():
    literal, _ = literal_program(payload="PROTOCOL_ADMISSION_PREDICATE")
    wire = codec.dumps(literal)
    assert json.loads(wire)["schema_version"] == 16
    assert codec.loads(wire) == literal
    graph, details = generator_protocol_program(target="start")
    first = graph.operations[0]
    graph = replace(graph, operations=(replace(first, label="PROTOCOL_BODY_STATE_CONDITION"),
                                        *graph.operations[1:]))
    wire = codec.dumps(graph)
    assert json.loads(wire)["schema_version"] == 17
    assert codec.loads(wire) == graph


@pytest.mark.parametrize("version", range(2, 17))
def test_existing_golden_profiles_keep_their_original_bytes(version):
    directory = Path(__file__).parents[1] / "fixtures"
    payload = (directory / f"program_graph_v{version}_frozen.json").read_text()
    assert json.loads(payload)["schema_version"] == version
    if version <= 10:
        # Those historical fixture writers appended one transport LF; it was
        # never returned by the canonical encoder. Keep the fixture unchanged.
        assert payload.endswith("\n") and not payload.endswith("\n\n")
        payload = payload[:-1]
    assert codec.dumps(codec.loads(payload)) == payload
