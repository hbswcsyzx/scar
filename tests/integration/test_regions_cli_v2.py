import gzip
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scar.analysis.region_report_v2 import report_regions


def invoke(source, output, *arguments):
    repository = Path(__file__).resolve().parents[2]
    environment = {key: value for key, value in os.environ.items() if not key.startswith("SCAR_")}
    environment["PYTHONPATH"] = str(repository)
    result = subprocess.run([sys.executable, "-m", "scar.cli", "regions-v2", str(source),
                             "--out", str(output), *arguments], cwd=repository,
                            env=environment, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    with (gzip.open(output, "rt") if output.suffix == ".gz" else output.open()) as stream:
        report = json.load(stream)
    assert json.loads(result.stdout)["summary"] == report["summary"]
    return report


def test_source_region_cli_is_read_only_bounded_and_repeatable(tmp_path):
    marker = tmp_path / "executed"
    source = tmp_path / "program.py"
    source.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
                      "def process(x):\n    local = x + 1\n    return local\n")
    original = source.read_bytes()
    report = invoke(source, tmp_path / "regions.json.gz", "--max-depth", "1")
    repeated = invoke(source, tmp_path / "repeated.json", "--max-depth", "1")
    assert source.read_bytes() == original and not marker.exists()
    assert report["summary"]["regions"] > 1
    assert report["summary"]["ports"] > 0
    assert report["summary"]["selected_transformations"] == 0
    assert report["summary"]["original_alternatives"] == report["summary"]["regions"]
    assert report["selection"]["max_depth"] == 1
    assert "never dead" in report["selection"]["omission_means"]
    for item in (report, repeated):
        del item["measurement"]
    assert report == repeated


def test_execution_region_cli_preserves_distinct_calls_and_scope_selection(tmp_path):
    events = []
    for index, thread in enumerate((11, 22)):
        events.append({"kind": "module_call", "index": index, "code_id": "test.py:f:1:None:v1",
            "invocation_id": index + 1, "ts_ns": 100 * (index + 1), "duration_ns": 10,
            "labels": [], "inputs": [], "outputs": [], "effect": {}, "resource": {},
            "metadata": {"process_id": 1, "thread_id": thread, "clock_domain": "perf_counter"}})
    trace = tmp_path / "events.jsonl"
    trace.write_text("".join(json.dumps(event) + "\n" for event in events))
    before = trace.read_bytes()
    report = invoke(trace, tmp_path / "execution.json", "--view", "execution", "--root-limit", "1")
    assert trace.read_bytes() == before
    assert len(report["selection"]["available_scopes"]) == 2
    assert len(report["selection"]["selected_roots"]) == 1
    assert report["selection"]["selected_scope_members"] == 1
    other_scope = next(scope for scope in report["selection"]["available_scopes"] if scope != report["scope"])
    other = invoke(trace, tmp_path / "other.json", "--view", "execution", "--scope", other_scope)
    assert other["selection"]["selected_roots"] != report["selection"]["selected_roots"]
    assert report["summary"]["selected_transformations"] == other["summary"]["selected_transformations"] == 0


@pytest.mark.parametrize("arguments", [
    {"max_depth": -1}, {"max_depth": True}, {"root_limit": 0}, {"view": "mixed"},
])
def test_invalid_region_projection_options_rejected_before_source_read(arguments):
    with pytest.raises(ValueError):
        report_regions("missing.py", **arguments)


def test_unknown_explicit_root_is_not_silently_replaced(tmp_path):
    source = tmp_path / "program.py"
    source.write_text("x = 1\n")
    with pytest.raises(ValueError, match="roots must be unique"):
        report_regions(source, root_ids=("opdef:absent",))
