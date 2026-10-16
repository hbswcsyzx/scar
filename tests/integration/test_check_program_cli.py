"""Real public entry point: typed graph input, no source execution or approval."""
import json
import subprocess
import sys

from scar.ir.program.codec import dumps
from tests.fixtures.program_graphs import branch_state_program


def run_check(source, *args):
    return subprocess.run([sys.executable, "-m", "scar.cli", "check-program", str(source), *map(str, args)],
                          capture_output=True, text=True, timeout=30)


def test_cli_validates_persisted_complete_program_and_preserves_input(tmp_path):
    graph = branch_state_program()
    source, destination = tmp_path / "graph.json", tmp_path / "check.json"
    original = dumps(graph)
    source.write_text(original)
    process = run_check(source, "--out", destination)
    assert process.returncode == 0, process.stderr
    report = json.loads(destination.read_text())
    assert report == json.loads(process.stdout)
    assert report["status"] == "WELL_FORMED"
    assert report["counts"]["blocks"] == 3
    assert report["counts"]["locations"] == 2
    assert report["counts"]["uses"] == sum(len(op.uses) for op in graph.operations)
    assert report["counts"]["declared_incomplete_effects"] > 0
    assert report["transformation_authorized"] is False
    assert report["source_recovery"] is False
    assert source.read_text() == original


def test_cli_rejects_structurally_typed_but_stale_state(tmp_path):
    document = json.loads(dumps(branch_state_program()))
    operation = next(op for op in document["operations"] if op["id"]["value"] == "done")
    use = next(use for use in operation["uses"] if use["id"]["value"] == "done.buffer")
    use["value"] = next(value["id"] for value in document["values"] if value["id"]["value"] == "buffer.normal")
    source = tmp_path / "stale.json"
    source.write_text(json.dumps(document))
    process = run_check(source)
    assert process.returncode == 2
    report = json.loads(process.stdout)
    assert report["status"] == "INVALID"
    assert "stale_state" in report["errors"][0]


def test_cli_does_not_execute_input_or_overwrite_it_as_report(tmp_path):
    marker, source = tmp_path / "executed", tmp_path / "not-a-graph.py"
    payload = f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
    source.write_text(payload)
    process = run_check(source)
    assert process.returncode == 2
    assert json.loads(process.stdout)["status"] == "INVALID"
    assert not marker.exists()
    process = run_check(source, "--out", source)
    assert process.returncode == 2
    assert source.read_text() == payload


def test_cli_accepts_resource_interfaces_without_claiming_runtime_realization(tmp_path):
    from tests.unit.test_program_resources import resource_graph

    source = tmp_path / "resources.json"
    payload = dumps(resource_graph())
    source.write_text(payload)
    assert json.loads(payload)["schema_version"] == 4
    process = run_check(source)
    assert process.returncode == 0, process.stderr
    report = json.loads(process.stdout)
    assert report["status"] == "WELL_FORMED"
    assert report["source_recovery"] is False
    assert report["transformation_authorized"] is False
    assert report["resource_realization_verified"] is False
    assert report["readiness_verified"] is False
    assert report["counts"]["resources"] == 1
    assert source.read_text() == payload


def test_cli_rejects_forged_resource_endpoint(tmp_path):
    from scar.ir.program import ResourceRequirementID
    from scar.ir.record_codec import encode
    from tests.unit.test_program_resources import resource_graph

    document = json.loads(dumps(resource_graph()))
    document["resource_uses"][0]["requirement"] = encode(ResourceRequirementID("missing"))
    source = tmp_path / "forged-resource.json"
    source.write_text(json.dumps(document))
    process = run_check(source)
    assert process.returncode == 2
    assert json.loads(process.stdout)["status"] == "INVALID"


def test_cli_handles_local_bindings_and_resources_together(tmp_path):
    from dataclasses import replace
    from scar.ir.program import (ExternalResource, ResourceDefinition, ResourceDefinitionID,
                                 ResourceKind, ResourceRole)
    from tests.unit.test_program_bindings import _bound_graph

    graph = _bound_graph()
    graph = replace(graph, resources=(ResourceDefinition(
        ResourceDefinitionID("executor"), ResourceKind.CPU, ResourceRole.EXECUTOR,
        ExternalResource(graph.root, "executor")),))
    source = tmp_path / "binding-and-resource.json"
    source.write_text(dumps(graph))
    process = run_check(source)
    assert process.returncode == 0, process.stderr
    report = json.loads(process.stdout)
    assert report["counts"]["value_kinds"]["LOCAL_BINDING"] == 1
    assert report["counts"]["resources"] == 1
    assert report["transformation_authorized"] is False
