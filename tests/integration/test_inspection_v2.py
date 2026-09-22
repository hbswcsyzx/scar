"""Public inspection connects evidence without executing or rewriting a target."""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import CodeType

import pytest

from scar.analysis.inspection_v2 import inspect_program
from scar.ir.ids import CodeID


def _codes(code):
    yield code
    for constant in code.co_consts:
        if isinstance(constant, CodeType):
            yield from _codes(constant)


@pytest.fixture
def captured_program(tmp_path):
    source = tmp_path / "program.py"
    marker = tmp_path / "target-executed"
    text = (f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
            "def compute(tensor):\n    return tensor\n"
            "raise RuntimeError('inspection must never execute this module')\n")
    source.write_text(text)
    # Retain the complete code tree, matching the source witness procedure;
    # neither module initialization nor the function is executed.
    codes = list(_codes(compile(text, str(source), "exec", dont_inherit=True)))
    loaded_code = next(code for code in codes if code.co_name == "compute")
    identity = CodeID.from_code(loaded_code).key()
    value = {"object_id": "py:1:tensor", "storage_id": "storage:1:tensor",
             "logical_version": "storage:1:tensor@0:v0", "shape": [4],
             "strides": [1], "offset": 0, "dtype": "torch.float32", "device": "cpu"}
    common = {"code_id": identity, "invocation_id": 1, "duration_ns": None,
              "resource": {}, "labels": []}
    metadata = {"process_id": 11, "thread_id": 22, "clock_domain": "perf_counter"}
    events = [
        {**common, "index": 0, "kind": "python_call", "ts_ns": 100,
         "inputs": [value], "outputs": [], "metadata": metadata,
         "effect": {"reads": [value["logical_version"]],
                    "collection_knowledge": {"reads": "UNKNOWN"}}},
        {**common, "index": 1, "kind": "python_return", "ts_ns": 200,
         "inputs": [], "outputs": [value],
         "metadata": {**metadata, "outcome": "return", "return_escape_evidence": "Observed"},
         "effect": {"escapes": [value["logical_version"]],
                    "collection_knowledge": {"escapes": "KNOWN"}}},
    ]
    trace = tmp_path / "events.jsonl"
    trace.write_text("".join(json.dumps(event, sort_keys=True) + "\n" for event in events))
    return source, trace, marker


def _invoke_inspector(source, trace, output):
    repository = Path(__file__).resolve().parents[2]
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("SCAR_")}
    environment["PYTHONPATH"] = str(repository)
    result = subprocess.run(
        [sys.executable, "-m", "scar.cli", "inspect-v2", str(source),
         "--trace", str(trace), "--project-root", str(source.parent),
         "--runtime-sources", "--out", str(output)],
        cwd=repository, env=environment, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout)
    assert response["out"] == str(output)
    report = json.loads(output.read_text())
    assert response["summary"] == report["summary"]
    return report


def test_inspect_cli_preserves_return_effects_and_code_only_witness_without_execution(captured_program):
    source, trace, marker = captured_program
    originals = {path: path.read_bytes() for path in (source, trace)}
    report = _invoke_inspector(source, trace, source.parent / "first.json")
    repeated = _invoke_inspector(source, trace, source.parent / "second.json")
    assert not marker.exists()
    assert all(path.read_bytes() == content for path, content in originals.items())
    assert report["schema"] == "scar.inspection.v2"
    assert report["trace_coverage"]["raw_records"] == 2
    assert report["trace_coverage"]["accounted_records"] == 2
    assert report["source_text_fingerprints"][str(source)]

    joined = report["correspondence"]
    assert joined["status_counts"]["VERIFIED"] == 1
    assert joined["instance_status_counts"]["VERIFIED"] == 1
    assert joined["target_executed"] is joined["runtime_mutated"] is False
    assert "no slot-version/effect/value equality inferred" in joined["scope"]
    witnesses = joined["rows"][0]["witnesses"]
    assert witnesses and all(witness["extent"] == "code_object_only" for witness in witnesses)
    assert all(witness["target_executed"] is False for witness in witnesses)
    links = report["correspondence_graph"]["records"]
    assert links and all(link["kind"] == "definition_instance" for link in links)
    assert all(link["value_version"] is None and link["value_slot"] is None for link in links)

    effects = report["runtime_effects"]
    assert effects["counts"]["reads"] == effects["counts"]["escapes"] == 1
    assert effects["counts"]["return_escape_occurrences"] == 1
    assert effects["legacy_assertions"]["return:escapes:KNOWN"] == 1
    assert effects["closed_scopes"] == effects["completed_effect_contracts"] == 0
    assert report["scopes"] and all(scope["mode"] == "dynamic_path" and not scope["closed"]
                                    for scope in report["scopes"])
    assert report["summary"]["selected_transformations"] == 0
    assert "TRANSFORM" not in report["summary"]["dispositions"]
    assessment = report["assessments"][0]
    assert assessment["effect_counts"] == {"reads": 1, "escapes": 1}
    decision = assessment["assessment"]["assessment"]
    assert decision["disposition"] == "KEEP"  # The observed escape cannot be silently deleted.
    assert decision["required_effects"]
    for identity in decision["required_effects"]:
        effect = report["required_effect_evidence"][identity]
        assert effect["dimension"] == "escapes" and effect["raw_references"]
        assert effect["evidence"]["kind"] == "Observed"
    assert decision["removal_effects_satisfied"] is False
    assert decision["ready_for_region_construction"] is False
    assert decision["requests"]  # A code witness does not prove complete runtime effects.
    assert "workload wall-clock speedup" in report["measurement"]["scope"]
    for document in (report, repeated):
        del document["measurement"]
    assert report == repeated


def test_inspection_source_change_keeps_effects_but_rejects_stale_code_witness(captured_program):
    source, trace, marker = captured_program
    source.write_text(source.read_text().replace("return tensor", "return tensor + 1"))
    report = inspect_program(source, trace, project_root=source.parent, runtime_sources=True)
    assert report["correspondence"]["status_counts"]["MISMATCH"] == 1
    assert report["correspondence"]["status_counts"]["VERIFIED"] == 0
    assert not report["correspondence_graph"]["records"]
    assert report["runtime_effects"]["counts"]["return_escape_occurrences"] == 1
    assert report["summary"]["selected_transformations"] == 0
    assert not marker.exists()


def test_missing_source_cannot_be_replaced_by_a_trace_selected_file(captured_program):
    source, trace, _ = captured_program
    with pytest.raises(FileNotFoundError):
        inspect_program(source.parent / "missing.py", trace,
                        project_root=source.parent, runtime_sources=True)


def test_out_of_root_source_is_rejected_even_with_runtime_source_selection(captured_program):
    source, trace, _ = captured_program
    root = source.parent / "different-root"
    root.mkdir()
    with pytest.raises(ValueError, match="source must be within an existing project root"):
        inspect_program(source, trace, project_root=root, runtime_sources=True)


def test_runtime_selected_directory_without_in_root_python_witness_is_explicit(captured_program):
    source, trace, _ = captured_program
    root = source.parent / "different-root"
    root.mkdir()
    # The trace is valid, but all its code identities point outside this root.
    with pytest.raises(ValueError, match="no trace-referenced Python files within root"):
        inspect_program(root, trace, project_root=root, runtime_sources=True)
