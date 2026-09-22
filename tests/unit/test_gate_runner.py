"""Exercise gate acceptance in isolated repositories, without any profiler.

Each invocation uses the real runner and real pytest exit/JUnit behavior.  The
fixture repository has no SCAR workload, so an empty selector cannot hide behind
an unrelated successful suite.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


RUNNER = Path(__file__).resolve().parents[2] / "scripts" / "run_gate.py"


@pytest.fixture
def gate_repo(tmp_path):
    for directory in ("scripts", "tests", "scar", "gates"):
        (tmp_path / directory).mkdir()
    shutil.copy2(RUNNER, tmp_path / "scripts/run_gate.py")
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n')
    (tmp_path / "scar/example.py").write_text("VALUE = 1\n")
    return tmp_path


def run_gate(repo, source, nodes=None, *, criteria=None):
    (repo / "tests/test_sample.py").write_text(source)
    if criteria is None:
        criteria = [{"id": "behavior", "tests": nodes or ["tests/test_sample.py"]}]
    manifest = {"gate": "FIXTURE", "scope": "isolated runner acceptance",
                "criteria": criteria}
    (repo / "gates/fixture.json").write_text(json.dumps(manifest))
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.name=Gate fixture",
                    "-c", "user.email=gate@example.invalid", "commit", "-qm", "fixture"],
                   cwd=repo, check=True)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo,
                                       text=True).strip()
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("SCAR_", "PYTEST_"))}
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    out = repo / "report.json"
    result = subprocess.run(
        [sys.executable, "scripts/run_gate.py", "gates/fixture.json", "--out", str(out)],
        cwd=repo, text=True, capture_output=True, env=env, timeout=30)
    assert out.exists(), f"runner did not write a gate report: {result.stdout}\n{result.stderr}"
    report = json.loads(out.read_text())
    assert (repo / "report.md").exists()
    assert report["revision"] == revision
    return result, report


def test_gate_pass_is_bound_to_revision_and_tested_file_hashes(gate_repo):
    result, report = run_gate(gate_repo, "def test_ok():\n    assert 2 + 2 == 4\n")
    assert result.returncode == 0
    assert report["status"] == "PASS"
    assert report["source_unchanged_during_test"] is True
    assert report["worktree_status"] == ""
    hashes = report["tested_files"]
    assert {"scar/example.py", "tests/test_sample.py", "scripts/run_gate.py",
            "gates/fixture.json", "pyproject.toml"} <= hashes.keys()
    for relative_path, digest in hashes.items():
        assert hashlib.sha256((gate_repo / relative_path).read_bytes()).hexdigest() == digest
    assert report["source_sha256"] == hashlib.sha256(
        json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    assert report["criteria"][0]["evidence"][0]["cases"] == [
        {"class": "tests.test_sample", "name": "test_ok", "status": "PASS"}]


@pytest.mark.parametrize("source", [
    "def test_bad():\n    assert False\n",
    "import pytest\n@pytest.mark.skip(reason='not executed')\ndef test_skip():\n    pass\n",
    "import pytest\n@pytest.mark.xfail(reason='known issue')\ndef test_xfail():\n    assert False\n",
])
def test_gate_fails_on_failure_skip_or_xfail(gate_repo, source):
    result, report = run_gate(gate_repo, source)
    assert result.returncode != 0
    assert report["status"] == "FAIL"
    assert report["criteria"][0]["status"] == "FAIL"
    assert report["criteria"][0]["evidence"][0]["cases"][0]["status"] == "FAIL"


def test_gate_missing_test_cannot_be_satisfied_by_another_case(gate_repo):
    result, report = run_gate(gate_repo, "def test_ok():\n    pass\n", nodes=[
        "tests/test_sample.py::test_ok", "tests/test_sample.py::test_nonexistent"])
    assert result.returncode != 0
    assert report["status"] == "FAIL"
    missing = next(item for item in report["criteria"][0]["evidence"]
                   if item["node"].endswith("test_nonexistent"))
    assert missing["status"] == "FAIL"
    assert missing["cases"] == []


def test_gate_selector_collecting_no_tests_fails(gate_repo):
    result, report = run_gate(gate_repo, "def helper():\n    return 42\n")
    assert result.returncode != 0
    assert report["status"] == "FAIL"
    assert report["criteria"][0]["evidence"][0]["cases"] == []


@pytest.mark.parametrize("criteria", [[], [{"id": "empty", "tests": []}]])
def test_gate_empty_requirements_fail_without_running_unrelated_tests(gate_repo, criteria):
    result, report = run_gate(
        gate_repo,
        "from pathlib import Path\ndef test_unrelated():\n    Path('was_executed').touch()\n",
        criteria=criteria)
    assert result.returncode != 0
    assert report["status"] == "FAIL"
    assert not (gate_repo / "was_executed").exists()


def test_gate_source_mutation_invalidates_successful_test_results(gate_repo):
    result, report = run_gate(
        gate_repo,
        "from pathlib import Path\ndef test_ok():\n"
        "    Path('scar/example.py').write_text('VALUE = 2\\n')\n")
    assert result.returncode != 0
    assert report["status"] == "FAIL"
    assert report["source_unchanged_during_test"] is False
    assert report["criteria"][0]["status"] == "PASS"
    assert report["tested_files"]["scar/example.py"] == hashlib.sha256(b"VALUE = 1\n").hexdigest()


def test_gate_parametrized_selector_accounts_for_every_case(gate_repo):
    result, report = run_gate(
        gate_repo,
        "import pytest\n@pytest.mark.parametrize('value', [1, 2])\n"
        "def test_values(value):\n    assert value > 0\n",
        nodes=["tests/test_sample.py::test_values"])
    assert result.returncode == 0
    assert report["status"] == "PASS"
    cases = report["criteria"][0]["evidence"][0]["cases"]
    assert {case["name"] for case in cases} == {"test_values[1]", "test_values[2]"}


def test_gate_class_method_selector_matches_its_junit_case(gate_repo):
    result, report = run_gate(
        gate_repo, "class TestExample:\n    def test_ok(self):\n        pass\n",
        nodes=["tests/test_sample.py::TestExample::test_ok"])
    assert result.returncode == 0
    assert report["status"] == "PASS"
    assert len(report["criteria"][0]["evidence"][0]["cases"]) == 1


def test_gate_file_selector_includes_class_methods(gate_repo):
    result, report = run_gate(
        gate_repo, "class TestExample:\n    def test_ok(self):\n        pass\n")
    assert result.returncode == 0
    assert report["status"] == "PASS"
    assert len(report["criteria"][0]["evidence"][0]["cases"]) == 1


def test_gate_class_selector_includes_each_method(gate_repo):
    result, report = run_gate(
        gate_repo, "class TestExample:\n    def test_first(self):\n        pass\n"
        "    def test_second(self):\n        pass\n",
        nodes=["tests/test_sample.py::TestExample"])
    assert result.returncode == 0
    assert report["status"] == "PASS"
    cases = report["criteria"][0]["evidence"][0]["cases"]
    assert {case["name"] for case in cases} == {"test_first", "test_second"}
