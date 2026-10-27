"""Public graph validation reports native declarations without proof authority."""
import json

from scar.ir.program.codec import dumps
from tests.fixtures.program_native_graphs import native_boundary_graph
from tests.integration.test_check_program_cli import run_check


def test_check_program_reports_native_boundaries_and_unproved_replay_flags(tmp_path):
    graph = native_boundary_graph()
    source, destination = tmp_path / "native-program.json", tmp_path / "check-report.json"
    original = dumps(graph)
    source.write_text(original, encoding="utf-8")

    process = run_check(source, "--out", destination)
    assert process.returncode == 0, process.stderr
    stdout_report = json.loads(process.stdout)
    output_report = json.loads(destination.read_text(encoding="utf-8"))
    assert stdout_report == output_report
    assert stdout_report["status"] == "WELL_FORMED"
    assert stdout_report["counts"]["native_boundaries"] == 2
    assert stdout_report["counts"]["boundary_relations"] == 1
    for flag in (
        "native_signature_replay_verified",
        "native_tree_mapping_verified",
        "native_state_binding_verified",
        "boundary_relations_verified",
        "transformation_authorized",
    ):
        assert stdout_report[flag] is False
    assert source.read_text(encoding="utf-8") == original

