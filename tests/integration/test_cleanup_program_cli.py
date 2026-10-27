"""The public checker validates declared C1 structure without execution authority."""
import json

from scar.ir.program import dumps
from tests.fixtures.program_cleanup_graphs import cleanup_return_resume_graph
from tests.integration.test_check_program_cli import run_check


def test_public_cli_reports_c1_structure_and_preserves_false_authority_fields(tmp_path):
    graph = cleanup_return_resume_graph()
    source, output = tmp_path / "cleanup-v9.json", tmp_path / "report.json"
    original = dumps(graph)
    source.write_text(original)
    process = run_check(source, "--out", output)
    assert process.returncode == 0, process.stderr
    report = json.loads(process.stdout)
    assert report == json.loads(output.read_text())
    assert report["status"] == "WELL_FORMED"
    assert report["counts"]["cleanup_interfaces"] == 1
    assert report["counts"]["cleanup_actions"] == 3
    assert report["counts"]["cleanup_routes"] == 3
    assert report["cleanup_structure_validated"] is True
    assert report["cleanup_unwinding_verified"] is False
    assert report["exception_context_verified"] is False
    assert report["pending_runtime_realization_verified"] is False
    assert report["source_recovery"] is False
    assert report["transformation_authorized"] is False
    assert source.read_text() == original


def test_public_cli_rejects_c1_route_bypass_without_executing_input(tmp_path):
    document = json.loads(dumps(cleanup_return_resume_graph()))
    route = next(operation for operation in document["operations"]
                 if operation["terminator"] is not None
                 and operation["terminator"].get("kind") == "CLEANUP_ROUTE")
    route["terminator"]["successors"][0]["block"] = {"value": "shared.dispatch.block"}
    source = tmp_path / "bypassed-cleanup.json"
    source.write_text(json.dumps(document))
    process = run_check(source)
    assert process.returncode == 2
    report = json.loads(process.stdout)
    assert report["status"] == "INVALID"
    assert not report.get("cleanup_structure_validated", False)
