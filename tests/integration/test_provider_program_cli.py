"""Public provider declaration checks never execute an artifact or a workload."""
import json

from scar.ir.program import dumps
from tests.fixtures.program_provider_graphs import definition_provider_graph, execution_observation_graph
from tests.integration.test_check_program_cli import run_check


def test_cli_reports_declared_providers_without_authority_or_artifact_io(tmp_path):
    graph = definition_provider_graph(complete_claims=True)
    source, report = tmp_path / "provider.json", tmp_path / "report.json"
    payload = dumps(graph)
    source.write_text(payload)
    process = run_check(source, "--out", report)
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    assert result == json.loads(report.read_text())
    assert result["status"] == "WELL_FORMED"
    assert result["counts"]["provider_envelopes"] == 1
    assert result["counts"]["provider_regions"] == 1
    assert result["counts"]["provider_bindings"] == len(graph.provider_bindings)
    for flag in ("provider_artifact_replay_verified", "provider_conditions_verified",
                 "provider_source_correspondence_verified", "cross_representation_equivalence_verified",
                 "provider_runtime_correspondence_verified", "transformation_authorized", "source_recovery"):
        assert result[flag] is False
    assert source.read_text() == payload


def test_cli_observation_scopes_do_not_need_fabricated_static_bindings(tmp_path):
    graph = execution_observation_graph()
    source = tmp_path / "observation.json"
    source.write_text(dumps(graph))
    process = run_check(source)
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    assert result["counts"]["provider_bindings"] == 0
    assert result["provider_runtime_correspondence_verified"] is False


def test_cli_rejects_a_dynamic_provider_disguised_as_definition_owner(tmp_path):
    document = json.loads(dumps(execution_observation_graph()))
    document["provider_regions"][0]["relation"] = "DEFINES_REPRESENTATION"
    source = tmp_path / "wrong-owner.json"
    source.write_text(json.dumps(document))
    process = run_check(source)
    assert process.returncode == 2
    result = json.loads(process.stdout)
    assert result["status"] == "INVALID"
    assert result["transformation_authorized"] is False
    assert any("provider_region_kind" in message for message in result["errors"])
