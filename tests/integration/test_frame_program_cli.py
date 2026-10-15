"""Automatic raw-source reference queries through the versioned public CLI."""
import gzip
import json
import subprocess
import sys

import pytest

from scar.analysis.frame_queries import query_return_references
from scar.analysis.program_lowering import lower_source
from scar.ir.program.functions import BodyLoweringProfile


def run(*args):
    return subprocess.run([sys.executable, "-m", "scar.cli", *map(str, args)],
                          text=True, capture_output=True, timeout=30)


def source(tmp_path, text):
    path = tmp_path / "sample.py"
    path.write_text(text)
    return path


def document(tmp_path, text):
    return lower_source(source(tmp_path, text), "f", profile=BodyLoweringProfile.BOUND_FRAME).to_dict()


@pytest.mark.parametrize("suffix", [".json", ".json.gz"])
def test_public_default_build_replay_and_query_never_execute_source(tmp_path, suffix):
    marker = tmp_path / "executed"
    path = source(tmp_path, f"open({str(marker)!r}, 'w').write('executed')\n"
                  "def f(unused, x):\n    y = x\n    return y\n")
    before = path.read_bytes()
    out = tmp_path / ("report" + suffix)
    build = run("model-program", path, "--entry", "f", "--out", out)
    assert build.returncode == 0, build.stdout + build.stderr
    with (gzip.open(out, "rt") if suffix.endswith("gz") else out.open()) as stream:
        saved = json.load(stream)
    assert saved["schema_version"] == 2
    assert saved["profile"] == "BOUND_FRAME_V1"
    assert run("check-source-program", out).returncode == 0
    process = run("query-frame-refs", out)
    assert process.returncode == 0, process.stdout + process.stderr
    report = json.loads(process.stdout)
    assert report["status"] == "REPLAYED_CONDITIONAL_ROUTES"
    assert len(report["completions"]) == 1
    assert report["completions"][0]["kind"] == "RETURN"
    origins = report["completions"][0]["reference_origins"]
    assert len(origins) == 1 and origins[0]["kind"] == "FORMAL_REFERENCE"
    assert report["incomplete_effect_operations"]
    assert report["frame_rules"]["condition_status"] == "UNKNOWN"
    assert report["frame_rules"]["termination"] == "MAY_NOT_COMPLETE"
    assert report["contents_or_effects_established"] is False
    assert report["transformation_authorized"] is False
    assert not marker.exists() and path.read_bytes() == before


def test_branch_query_keeps_separate_predecessor_reference_routes(tmp_path):
    saved = document(tmp_path, "def f(flag, a, b):\n    if flag:\n        y = a\n    else:\n        y = b\n    return y\n")
    report = query_return_references(saved)
    normal = [c for c in report["completions"] if c["kind"] == "RETURN"]
    assert len(normal) == 1
    origins = normal[0]["reference_origins"]
    assert len(origins) == 2 and {o["kind"] for o in origins} == {"FORMAL_REFERENCE"}
    assert len({o["slot"] for o in origins}) == 2
    assert all(o["path"] for o in origins)
    assert origins[0]["path"] != origins[1]["path"]
    assert any(c["kind"] == "RAISE" for c in report["completions"])


def test_opaque_result_does_not_alias_all_its_reference_inputs(tmp_path):
    report = query_return_references(document(tmp_path, "def f(x):\n    return mutate(x)\n"))
    normal, = [c for c in report["completions"] if c["kind"] == "RETURN"]
    assert {o["kind"] for o in normal["reference_origins"]} == {"COMPLETION_RESULT_BOUNDARY"}
    assert not any(o["kind"] == "FORMAL_REFERENCE" for o in normal["reference_origins"])
    assert report["transformation_authorized"] is False


def test_query_budget_is_explicit_and_does_not_claim_all_routes(tmp_path):
    report = query_return_references(document(tmp_path,
        "def f(flag, a, b):\n    if flag:\n        y = a\n    else:\n        y = b\n    return y\n"), max_reference_steps=1)
    assert report["status"] == "QUERY_BUDGET"
    assert report["reference_steps"] == 1
    assert any(o["kind"] == "QUERY_BUDGET" for c in report["completions"] for o in c["reference_origins"])
    assert not report["transformation_authorized"]


@pytest.mark.parametrize("limit", [True, 0, -1, 1.5, 100001])
def test_reference_query_rejects_invalid_step_ceiling(tmp_path, limit):
    with pytest.raises(ValueError, match="steps"):
        query_return_references(document(tmp_path, "def f(x):\n    return x\n"), max_reference_steps=limit)


def test_public_legacy_option_retains_v1_and_query_rejects_it(tmp_path):
    path = source(tmp_path, "def f(x):\n    return x\n")
    out = tmp_path / "old.json"
    process = run("model-program", path, "--entry", "f", "--body-profile", "legacy", "--out", out)
    assert process.returncode == 0, process.stdout + process.stderr
    assert json.loads(out.read_text())["schema_version"] == 1
    assert run("check-source-program", out).returncode == 0
    query = run("query-frame-refs", out)
    assert query.returncode == 2
    assert "bound-frame" in json.loads(query.stdout)["errors"][0]


def test_query_rejects_drift_and_independent_source_budget(tmp_path):
    path = source(tmp_path, "def f(x):\n    y = x\n    return y\n")
    out = tmp_path / "new.json"
    assert run("model-program", path, "--entry", "f", "--out", out).returncode == 0
    assert run("query-frame-refs", out, "--max-operations", 1).returncode == 2
    path.write_text("def f(x):\n    y = 2\n    return y\n")
    process = run("query-frame-refs", out)
    assert process.returncode == 2 and json.loads(process.stdout)["status"] == "INVALID"


@pytest.mark.parametrize("command", ["check-source-program", "query-frame-refs"])
@pytest.mark.parametrize("suffix", [".json", ".json.gz"])
def test_source_readers_reject_conflicting_duplicate_fields_and_decompressed_overflow(tmp_path, command, suffix):
    saved = document(tmp_path, "def f(x):\n    return x\n")
    path = tmp_path / ("ambiguous" + suffix)
    canonical = json.dumps(saved)
    conflicting = '{"schema_version":999,"frame":{"rules":{"condition_status":"PROVEN"}},' + canonical[1:]
    if suffix.endswith("gz"):
        path.write_bytes(gzip.compress(conflicting.encode()))
    else:
        path.write_text(conflicting)
    duplicate = run(command, path)
    assert duplicate.returncode == 2
    assert "duplicate JSON field" in json.loads(duplicate.stdout)["errors"][0]
    if suffix.endswith("gz"):
        path.write_bytes(gzip.compress(canonical.encode()))
    else:
        path.write_text(canonical)
    limited = run(command, path, "--max-report-bytes", 1)
    assert limited.returncode == 2
    assert "read byte ceiling" in json.loads(limited.stdout)["errors"][0]


@pytest.mark.parametrize("suffix", [".json", ".json.gz"])
def test_model_output_overflow_preserves_existing_report_atomically(tmp_path, suffix):
    path = source(tmp_path, "def f(x):\n    return x\n")
    output = tmp_path / ("old" + suffix)
    output.write_bytes(b"previous report")
    process = run("model-program", path, "--entry", "f", "--out", output, "--max-report-bytes", 1)
    assert process.returncode == 2
    assert output.read_bytes() == b"previous report"
    assert not list(tmp_path.glob(".*.tmp"))


@pytest.mark.parametrize("construct", ["try:\n        pass\n    finally:\n        pass",
                                       "while x:\n        pass", "del x", "raise x"])
def test_frame_profile_rejects_unmodeled_lifetime_control_even_after_return(tmp_path, construct):
    saved = document(tmp_path, "def f(x):\n    return x\n    " + construct + "\n")
    assert saved["status"] == "UNSUPPORTED" and saved["graph"] is None
    assert saved["interface"] is None and saved["frame"] is None


def test_function_docstring_has_no_call_time_discard_or_new_value(tmp_path):
    saved = document(tmp_path, 'def f(x):\n    "declaration documentation"\n    return x\n')
    assert len(saved["frame"]["transitions"]) == 2  # ENTER and EXIT only.
    assert not any("reference" in item for item in saved["frame"]["transitions"])
    report = query_return_references(saved)
    assert report["completions"][0]["reference_origins"][0]["kind"] == "FORMAL_REFERENCE"
