"""The public checker reports static C2 structure without runtime authority."""
import json
from pathlib import Path

from scar.ir.program.codec import dumps
from scar.ir.program.resumption import SuspendTerminator
from tests.fixtures.program_resumption_graphs import resumption_program
from tests.integration.test_check_program_cli import run_check


def test_public_cli_reports_resumption_structure_and_keeps_authority_false(tmp_path):
    graph = resumption_program()
    source, destination = tmp_path / "resumption-v10.json", tmp_path / "report.json"
    original = dumps(graph)
    source.write_text(original, encoding="utf-8")
    process = run_check(source, "--out", destination)
    assert process.returncode == 0, process.stderr
    report = json.loads(process.stdout)
    assert report == json.loads(destination.read_text(encoding="utf-8"))
    assert report["status"] == "WELL_FORMED"
    assert report["counts"]["resumable_bodies"] == len(graph.resumable_bodies)
    assert report["counts"]["suspensions"] == sum(
        type(operation.terminator) is SuspendTerminator
        for operation in graph.operations)
    assert report["counts"]["frame_context_actions"] == (
        len(graph.frame_context_initials) + len(graph.frame_context_attaches)
        + len(graph.frame_context_detaches))
    assert report["body_structure_validated"] is True
    for field in ("body_driver_verified", "body_source_verified", "body_runtime_verified",
                  "body_exclusivity_verified", "source_recovery", "transformation_authorized"):
        assert report[field] is False
    assert source.read_text(encoding="utf-8") == original


def test_public_cli_does_not_report_body_structure_for_v9_graph(tmp_path):
    source = tmp_path / "old-v9.json"
    source.write_bytes((Path(__file__).parents[1]
                        / "fixtures" / "program_graph_v9_frozen.json").read_bytes())
    process = run_check(source)
    assert process.returncode == 0, process.stderr
    report = json.loads(process.stdout)
    assert report["status"] == "WELL_FORMED"
    assert report["body_structure_validated"] is False
    assert report["body_driver_verified"] is False
    assert report["body_source_verified"] is False
    assert report["body_runtime_verified"] is False
    assert report["body_exclusivity_verified"] is False
    assert report["transformation_authorized"] is False
