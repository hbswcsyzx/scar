import gzip
import json
import subprocess
import sys

from scar.analysis.semantics_report_v2 import report_semantics


def test_public_semantics_command_derives_ordered_constants_without_running_target(tmp_path):
    path = tmp_path / "program.py"
    path.write_text("x = (10, 3)\ny = 10 - 3\nx = 4\nz = x + 2\nraise RuntimeError('never execute target')\n")
    before = path.read_bytes()
    out = tmp_path / "report.json.gz"
    run = subprocess.run([sys.executable, "-m", "scar.cli", "semantics-v2", str(path), "--out", str(out)],
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    report = json.loads(gzip.decompress(out.read_bytes()))
    assert path.read_bytes() == before
    assert report["summary"]["derived_constant_operations"] >= 4
    assert report["summary"]["selected_transformations"] == 0
    assert report["summary"]["applied"] is False
    assert report["constants"]["source_validation"] == "NOT_CHECKED"
    assert report["summary"]["modeled_operations"] + report["summary"]["unmodeled_operations"] == report["summary"]["sg_operations"]
    second = report_semantics(path)
    second.pop("measurement")
    report.pop("measurement")
    assert report == second


def test_budget_failure_is_explicit_and_does_not_allocate_huge_result(tmp_path):
    from scar.analysis.constants_v2 import EvaluationBudget
    source = tmp_path / "budget.py"
    source.write_text("value = 1 << 1000000000\n")
    report = report_semantics(source, budget=EvaluationBudget(max_int_bits=32))
    assert report["summary"]["constant_statuses"]["BUDGET_EXCEEDED"] >= 1
    assert report["summary"]["selected_transformations"] == 0


def test_public_semantics_command_rejects_invalid_budget(tmp_path):
    source = tmp_path / "input.py"
    source.write_text("x = 2\n")
    output = tmp_path / "no-report.json"
    run = subprocess.run([sys.executable, "-m", "scar.cli", "semantics-v2", str(source),
                          "--max-nodes", "0", "--out", str(output)], capture_output=True, text=True)
    assert run.returncode != 0
    assert not output.exists()


def test_explicit_caller_budget_and_required_execution_contracts_are_preserved(tmp_path):
    from scar.analysis.constants_v2 import EvaluationBudget
    path = tmp_path / "source.py"
    path.write_text("value = 2 + 3\n")
    report = report_semantics(path, budget=EvaluationBudget(max_int_bits=8192))
    assert report["constants"]["budget"]["max_int_bits"] == 8192
    assert report["constants"]["preconditions_status"] == "REQUIRED_CONTRACT"
    assert report["constants"]["required_preconditions"]
