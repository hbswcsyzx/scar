"""The public commands expose v2 modeling without running target source."""
import json


def test_model_v2_cli_does_not_execute_source(tmp_path):
    from scar.cli import main
    from scar.ir.v2.codec import semantic_from_dict

    program = tmp_path / "entry.py"
    marker = tmp_path / "executed"
    program.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
        "def compute(x):\n    return x + 1\nresult = compute(2)\n")
    output, report = tmp_path / "sg.json", tmp_path / "coverage.json"
    assert main(["model-v2", str(program), "--out", str(output),
                 "--report", str(report)]) == 0
    graph = semantic_from_dict(json.loads(output.read_text()))
    assert graph.assert_valid()["valid"]
    assert graph.definitions and graph.slots and graph.edges
    assert report.exists()
    assert not marker.exists()


def test_normalize_cli_preserves_aggregate_without_fabricating_invocations(tmp_path):
    from scar.cli import main
    from scar.ir.v2 import IRBundle

    trace = tmp_path / "trace"
    trace.mkdir()
    event = {"index": 1, "kind": "torch_op", "code_id": "aten::mm",
             "invocation_id": None, "ts_ns": 100, "duration_ns": 2000,
             "inputs": [], "outputs": [], "labels": ["VAL"],
             "metadata": {"aggregate": True, "count": 7, "process_id": 1,
                          "thread_id": 2}, "resource": {}, "effects": {}}
    (trace / "events.jsonl").write_text(json.dumps(event) + "\n")
    output = tmp_path / "eeg.json"
    assert main(["normalize", str(trace), "--out", str(output)]) == 0
    bundle = IRBundle.from_json(output.read_text())
    assert bundle.assert_valid()["valid"]
    assert len(bundle.evidence.instances) == 0
    assert bundle.evidence.measurements
    assert bundle.optimization is None
    assert output.with_name("eeg.json.coverage.json").exists()
