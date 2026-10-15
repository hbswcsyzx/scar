"""Automatic source input and strict replay through the public command."""
from copy import deepcopy
import gzip
import json
import subprocess
import sys

import pytest

from scar.analysis.program_lowering import SourceProgram, lower_source


def run(*arguments):
    return subprocess.run([sys.executable, "-m", "scar.cli", *map(str, arguments)],
                          capture_output=True, text=True, timeout=30)


def source(tmp_path, body=None):
    path = tmp_path / "program.py"
    path.write_text(body or "def f(x):\n    if x:\n        y = 1\n    else:\n        y = 2\n    return y\n")
    return path


@pytest.mark.parametrize("suffix", [".json", ".json.gz"])
def test_automatic_cli_build_and_replay_without_target_execution(tmp_path, suffix):
    marker = tmp_path / "executed"
    path = source(tmp_path, f"open({str(marker)!r}, 'w').write('executed')\ndef f(x):\n    return x + x\n")
    before = path.read_bytes()
    output = tmp_path / ("report" + suffix)
    process = run("model-program", path, "--entry", "f", "--out", output)
    assert process.returncode == 0, process.stderr or process.stdout
    summary = json.loads(process.stdout)
    assert summary["status"] == "LOWERED_WITH_GAPS"
    assert summary["summary"]["counts"]["use_source_links"] == summary["summary"]["counts"]["uses"]
    assert summary["summary"]["whole_program_coverage_established"] is False
    assert summary["summary"]["runtime_target_verified"] is False
    if suffix.endswith(".gz"):
        with gzip.open(output, "rt") as stream:
            document = json.load(stream)
    else:
        document = json.loads(output.read_text())
    assert SourceProgram.from_dict(document).graph is not None
    replay = run("check-source-program", output)
    assert replay.returncode == 0, replay.stderr or replay.stdout
    assert json.loads(replay.stdout)["status"] == "REPLAYED"
    assert json.loads(replay.stdout)["transformation_authorized"] is False
    assert path.read_bytes() == before
    assert not marker.exists()


def test_unsupported_body_is_a_located_report_not_a_partial_complete_graph(tmp_path):
    path = source(tmp_path, "def f(x):\n    for y in x:\n        y()\n    return x\n")
    output = tmp_path / "report.json"
    process = run("model-program", path, "--entry", "f", "--out", output)
    assert process.returncode == 3
    document = json.loads(output.read_text())
    assert document["status"] == "UNSUPPORTED"
    assert document["graph"] is None
    assert not document["metadata"]["operation_links"]
    assert not document["metadata"]["value_links"]
    assert not document["metadata"]["use_links"]
    assert any(gap["kind"] == "UNSUPPORTED_SYNTAX" for gap in document["metadata"]["gaps"])
    replay = run("check-source-program", output)
    assert replay.returncode == 0, replay.stderr or replay.stdout
    assert json.loads(replay.stdout)["summary"]["graph_present"] is False


@pytest.mark.parametrize("kind", ["same", "hardlink", "symlink"])
def test_cli_never_overwrites_target_source(tmp_path, kind):
    path = source(tmp_path)
    output = path if kind == "same" else tmp_path / "report.json"
    if kind == "hardlink":
        output.hardlink_to(path)
    elif kind == "symlink":
        output.symlink_to(path)
    before = path.read_bytes()
    process = run("model-program", path, "--entry", "f", "--out", output)
    assert process.returncode == 2
    assert path.read_bytes() == before


def test_replay_rejects_source_drift_and_uses_independent_budget(tmp_path):
    path = source(tmp_path)
    output = tmp_path / "report.json"
    process = run("model-program", path, "--entry", "f", "--out", output)
    assert process.returncode == 0
    limited = run("check-source-program", output, "--max-operations", 1)
    assert limited.returncode == 2
    path.write_text(path.read_text().replace("y = 2", "y = 3"))
    drifted = run("check-source-program", output)
    assert drifted.returncode == 2
    assert json.loads(drifted.stdout)["status"] == "INVALID"


@pytest.mark.parametrize("field,value", [
    ("transformation_authorized", True),
    ("runtime_target_verified", True),
    ("schema_version", True),
    ("status", "COMPLETE"),
    ("scope", "whole program"),
    ("extra", "ignored"),
])
def test_persistence_cannot_forge_authority_or_scope(tmp_path, field, value):
    document = lower_source(source(tmp_path), "f").to_dict()
    document[field] = value
    with pytest.raises(ValueError):
        SourceProgram.from_dict(document)


@pytest.mark.parametrize("section", ["metadata", "graph", "semantic", "semantics", "control", "summary"])
def test_all_graph_layers_and_correspondences_replay(tmp_path, section):
    document = lower_source(source(tmp_path), "f").to_dict()
    damaged = deepcopy(document)
    if section == "metadata":
        damaged[section]["operation_links"].pop()
    elif section == "graph":
        damaged[section]["operations"][0]["label"] = "forged"
    elif section == "summary":
        damaged[section]["counts"]["operations"] = 0
    else:
        damaged[section]["extra"] = "must not be discarded"
    with pytest.raises((ValueError, TypeError)):
        SourceProgram.from_dict(damaged)


def test_candidate_parameter_binding_tamper_is_rejected(tmp_path):
    path = source(tmp_path, "def helper(a, b):\n    return a + b\ndef f(x, y):\n    return helper(x, y)\n")
    document = lower_source(path, "f").to_dict()
    target = document["metadata"]["call_targets"][0]
    assert len(target["arguments"]) == 3
    first, second = target["arguments"][:2]
    first["parameter"], second["parameter"] = second["parameter"], first["parameter"]
    with pytest.raises(ValueError):
        SourceProgram.from_dict(document)
