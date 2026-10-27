"""Public environment schema validation; no target execution or runtime authority."""
import json

from scar.ir.program import dumps
from tests.integration.test_check_program_cli import run_check
from tests.unit.test_program_environments import _environment_graph


def test_cli_checks_canonical_environment_graph_and_reports_unverified_realization(tmp_path):
    graph = _environment_graph()
    source, destination = tmp_path / "environment.json", tmp_path / "check.json"
    payload = dumps(graph)
    source.write_text(payload)
    process = run_check(source, "--out", destination)
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    assert result == json.loads(destination.read_text())
    assert result["status"] == "WELL_FORMED"
    assert result["counts"]["environments"] == 1
    assert result["counts"]["environment_members"] == 6
    assert result["counts"]["function_entries"] == 1
    assert result["counts"]["python_parameters"] == 1
    assert result["runtime_callable_verified"] is False
    assert result["environment_realization_verified"] is False
    assert result["environment_extraction_verified"] is False
    assert result["python_signature_binding_verified"] is False
    assert result["source_recovery"] is False
    assert result["transformation_authorized"] is False
    assert source.read_text() == payload


def test_cli_rejects_environment_actual_using_old_pre_call_state(tmp_path):
    document = json.loads(dumps(_environment_graph()))
    second = next(op for op in document["operations"] if op["id"]["value"] == "call2")
    state = next(use for use in second["uses"] if use["id"]["value"] == "call2.state")
    state["value"] = next(value["id"] for value in document["values"] if value["id"]["value"] == "caller.initial")
    source = tmp_path / "stale.json"
    source.write_text(json.dumps(document))
    process = run_check(source)
    assert process.returncode == 2
    result = json.loads(process.stdout)
    assert result["status"] == "INVALID"
    assert any("stale_state" in error for error in result["errors"])
