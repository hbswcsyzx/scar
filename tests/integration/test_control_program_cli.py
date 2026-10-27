"""Public static protocol checks never grant source/cleanup/runtime authority."""
import json

from scar.ir.program import dumps
from tests.fixtures.program_control_graphs import shared_pending_graph
from tests.integration.test_check_program_cli import run_check


def test_public_control_graph_check_reports_only_structural_success(tmp_path):
    graph = shared_pending_graph()
    source, out = tmp_path / "control.json", tmp_path / "report.json"
    payload = dumps(graph)
    source.write_text(payload)
    process = run_check(source, "--out", out)
    assert process.returncode == 0, process.stderr
    report = json.loads(process.stdout)
    assert report == json.loads(out.read_text())
    assert report["status"] == "WELL_FORMED"
    assert report["counts"]["control_scopes"] == len(graph.control_scopes)
    assert report["counts"]["exception_packets"] == 1
    assert report["counts"]["pending_completions"] == 2
    for key in ("source_recovery", "transformation_authorized", "lexical_source_verified",
                "cleanup_unwinding_verified", "exception_context_verified",
                "pending_runtime_realization_verified"):
        assert report[key] is False
    assert source.read_text() == payload


def test_public_control_check_rejects_missing_dispatch_case(tmp_path):
    document = json.loads(dumps(shared_pending_graph()))
    term = next(o["terminator"] for o in document["operations"]
                if o["terminator"] is not None and "pending" in o["terminator"])
    term["successors"] = term["successors"][:1]
    # Keep the CFG structurally complete: the case-specific landing now becomes
    # unreachable, which is already a sufficient rejection before case analysis.
    source = tmp_path / "missing-case.json"
    source.write_text(json.dumps(document))
    process = run_check(source)
    assert process.returncode == 2
    assert json.loads(process.stdout)["status"] == "INVALID"
