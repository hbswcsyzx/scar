"""D1 wire capability is v11, independently of whether a body ever runs."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scar.ir.program.codec import SCHEMA_VERSION, dumps, loads
from scar.ir.program.control import ProtocolValueKind, ProtocolValueType
from scar.ir.program.drivers import BodyDriveResult, BodyDriveTerminator
from scar.ir.program.ids import ValueID
from scar.ir.program.model import OperationResult, ProtocolValue
from scar.ir.record_codec import encode
from tests.fixtures.program_driver_graphs import (
    async_request_program, create_only_program, driver_program, raw_only_program,
)


FIXTURES = Path(__file__).parents[1] / "fixtures"
DRIVER_FIELDS = {
    "resumable_creates", "raw_driver_requests", "async_request_creates",
    "request_association_reads", "driver_interfaces", "final_body_gates", "body_drives",
}


def _old(version):
    document = json.loads((FIXTURES / f"program_graph_v{max(2, version)}_frozen.json").read_text())
    if version == 1:
        document["schema_version"] = 1
        for operation in document["operations"]:
            operation.pop("completions", None)
            operation.pop("invoke_arguments", None)
    return document


@pytest.mark.parametrize("factory", [raw_only_program, create_only_program, driver_program, async_request_program])
def test_raw_only_create_without_drive_and_full_driver_each_select_v11(factory):
    graph = factory()
    payload = dumps(graph)
    document = json.loads(payload)
    assert SCHEMA_VERSION == 17
    assert document["schema_version"] == 11
    assert DRIVER_FIELDS <= set(document)
    assert loads(payload) == graph
    assert dumps(loads(payload)) == payload
    if factory is raw_only_program:
        assert graph.resumable_bodies == ()
    if factory is create_only_program:
        assert graph.resumable_creates and not graph.body_drives


def test_drive_and_projection_have_unambiguous_tags_without_changing_invoke_results():
    graph = driver_program(create=True, extra_domain=True)
    document = json.loads(dumps(graph))
    term = next(operation["terminator"] for operation in document["operations"]
                if operation["terminator"] and operation["terminator"].get("kind") == "BODY_DRIVE")
    assert set(term) == {"kind", "successors"}
    arguments = term["successors"][0]["arguments"]
    produced = [argument for argument in arguments if argument.get("kind") == "BODY_DRIVE_RESULT"]
    assert produced and all(set(argument) == {"kind", "index"} for argument in produced)
    invoke = next(operation["terminator"] for operation in document["operations"]
                  if operation["terminator"] and operation["terminator"].get("kind") == "INVOKE")
    invoke_results = [argument for edge in invoke["successors"] for argument in edge["arguments"]
                      if "index" in argument]
    assert invoke_results and all(set(argument) == {"index"} for argument in invoke_results)
    assert loads(json.dumps(document)) == graph

    for target, change in ((term, {"kind": "INVOKE"}), (produced[0], {"index": True})):
        original = dict(target)
        target.update(change)
        with pytest.raises((TypeError, ValueError)):
            loads(json.dumps(document))
        target.clear()
        target.update(original)
    produced[0].pop("kind")
    with pytest.raises((TypeError, ValueError)):
        loads(json.dumps(document))


@pytest.mark.parametrize("version", range(1, 11))
def test_every_legacy_schema_rejects_all_seven_driver_tables_even_when_empty(version):
    original = _old(version)
    for field in sorted(DRIVER_FIELDS):
        document = {**original, field: []}
        with pytest.raises(ValueError, match="top-level fields"):
            loads(json.dumps(document))


@pytest.mark.parametrize("version", range(1, 11))
def test_legacy_rejects_raw_value_exit_type_and_completion_type_without_tables(version):
    raw_type = encode(ProtocolValueType(ProtocolValueKind.RAW_DRIVER_REQUEST))
    document = _old(version)
    graph = loads(json.dumps(document))
    document["values"].append(encode(ProtocolValue(
        ValueID("smuggled.raw"), graph.root,
        OperationResult(graph.operations[0].id, 0), ProtocolValueKind.RAW_DRIVER_REQUEST)))
    with pytest.raises(ValueError, match="historical schema"):
        loads(json.dumps(document))

    document = _old(version)
    document["regions"][0]["exits"][0]["types"].append(raw_type)
    with pytest.raises(ValueError, match="historical schema"):
        loads(json.dumps(document))

    if version > 1:
        document = _old(version)
        document["operations"][0]["completions"] = [{"kind": "NORMAL", "types": [raw_type]}]
        with pytest.raises(ValueError, match="historical schema"):
            loads(json.dumps(document))


@pytest.mark.parametrize("version", range(1, 11))
def test_legacy_rejects_new_terminator_and_projection_tags_before_shape_coercion(version):
    document = _old(version)
    operation = next(item for item in document["operations"] if item["terminator"] is not None)
    operation["terminator"] = {"kind": "BODY_DRIVE", "successors": []}
    with pytest.raises(ValueError, match="historical schema"):
        loads(json.dumps(document))

    document = _old(version)
    operation = next(item for item in document["operations"] if item["terminator"] is not None)
    operation["terminator"] = {
        "kind": "JUMP", "successors": [{"arguments": [{"kind": "BODY_DRIVE_RESULT", "index": 0}]}],
    }
    with pytest.raises(ValueError, match="historical schema"):
        loads(json.dumps(document))


def test_v11_cannot_be_claimed_by_empty_tables_or_gain_authority_fields():
    document = _old(10)
    document.update(schema_version=11, **{field: [] for field in DRIVER_FIELDS})
    with pytest.raises(ValueError, match="requires explicit driver capability"):
        loads(json.dumps(document))
    document = json.loads(dumps(driver_program()))
    for field in DRIVER_FIELDS:
        missing = {name: value for name, value in document.items() if name != field}
        with pytest.raises(ValueError, match="top-level fields"):
            loads(json.dumps(missing))
    document["driver_interfaces"][0]["runtime_verified"] = True
    with pytest.raises((TypeError, ValueError)):
        loads(json.dumps(document))


@pytest.mark.parametrize("version", range(2, 11))
def test_legacy_golden_wires_remain_exact_without_driver_capability(version):
    payload = (FIXTURES / f"program_graph_v{version}_frozen.json").read_text().rstrip("\n")
    graph = loads(payload)
    assert not DRIVER_FIELDS & set(json.loads(payload))
    assert dumps(graph) == payload
    if version == 10:
        proof = json.loads((FIXTURES / "program_graph_v10_frozen.proof.json").read_text())
        assert proof["generated_from_current_worktree"] is False
        assert proof["logical_wire_sha256"] == hashlib.sha256(payload.encode()).hexdigest()


def test_record_mutation_cannot_bypass_v11_projection_validation():
    graph = driver_program()
    term = next(operation.terminator for operation in graph.operations
                if type(operation.terminator) is BodyDriveTerminator)
    result = next(argument for argument in term.successors[0].arguments
                  if type(argument) is BodyDriveResult)
    object.__setattr__(result, "index", True)
    with pytest.raises((TypeError, ValueError)):
        dumps(graph)


@pytest.mark.parametrize("factory", [raw_only_program, create_only_program, driver_program, async_request_program])
def test_program_cli_reports_only_driver_structure_and_keeps_proof_authority_false(factory, tmp_path, capsys):
    from scar.cli import _check_program

    graph = factory()
    source = tmp_path / "driver.json"
    source.write_text(dumps(graph), encoding="utf-8")
    assert _check_program(SimpleNamespace(graph=str(source), out=None)) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "WELL_FORMED"
    assert report["driver_structure_validated"] is True
    assert report["counts"]["raw_driver_requests"] == len(graph.raw_driver_requests)
    assert report["counts"]["body_drives"] == len(graph.body_drives)
    assert report["counts"]["body_drive_outcomes"] == sum(
        len(operation.terminator.successors) for operation in graph.operations
        if type(operation.terminator) is BodyDriveTerminator)
    for name in ("source_recovery", "transformation_authorized", "body_driver_verified",
                 "body_source_verified", "body_runtime_verified", "body_exclusivity_verified",
                 "driver_lifecycle_verified"):
        assert report[name] is False
