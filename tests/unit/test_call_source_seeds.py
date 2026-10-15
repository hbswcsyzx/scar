"""Compact entry/source seeds replay raw records without reference routes."""
from copy import deepcopy
from dataclasses import replace
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest

from scar.analysis.call_seeds import CallSourceSeedReport, read_call_source_seeds
from scar.ir.program.call_edges import CallEdgeBudget, CallEdgeIssueKind, CallLinkStatus
from scar.trace.call_edges import CallEdgeRecorder


class Token:
    pass


def captured(tmp_path, monkeypatch, *, count=3, extra_locals=0, module_entry=False):
    helper = tmp_path / "helper.py"
    helper.write_text("def identity(value):\n    return value\n", encoding="utf-8")
    entry = tmp_path / "entry.py"
    locals_source = "".join(f"    local_{i} = value\n" for i in range(extra_locals))
    entry.write_text(
        "from helper import identity\n"
        "def run(value, count):\n" + locals_source +
        "    for index in range(count):\n"
        "        result = identity(value)\n"
        "    len((value,))\n"
        "    return result\n", encoding="utf-8")
    helper_module = ModuleType("helper")
    exec(compile(helper.read_text(), str(helper), "exec", dont_inherit=True), helper_module.__dict__)
    monkeypatch.setitem(sys.modules, "helper", helper_module)
    entry_module = ModuleType("entry")
    exec(compile(entry.read_text(), str(entry), "exec", dont_inherit=True), entry_module.__dict__)
    output = tmp_path / "trace"
    recorder = CallEdgeRecorder(output, tmp_path)
    old = sys.getprofile()
    sys.setprofile(recorder.profile)
    try:
        if module_entry:
            exec(compile("answer = 1\n", str(tmp_path / "module.py"), "exec", dont_inherit=True), {})
        else:
            assert entry_module.run(Token(), count) is not None
    finally:
        sys.setprofile(old)
        recorder.close()
    return output


def _meta(output):
    path, = output.glob("call-meta.*.json")
    return path, json.loads(path.read_text())


def _rewrite_events(output, change):
    path, = output.glob("call-events.*.jsonl")
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    change(rows)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    meta_path, meta = _meta(output)
    meta["bytes"] = sum(path.stat().st_size for family in ("codes", "events")
                        for path in output.glob(f"call-{family}.*.jsonl"))
    meta_path.write_text(json.dumps(meta), encoding="utf-8")


def test_real_repeated_entries_only_match_entered_codes_and_keep_no_routes(tmp_path, monkeypatch):
    output = captured(tmp_path, monkeypatch, count=5)
    import scar.analysis.call_edges as full
    original = full._Sources.code
    matched = []

    def source_match(self, code):
        matched.append(code.key)
        return original(self, code)

    def forbidden(*args, **kwargs):
        raise AssertionError("a seed read must not construct a full call/reference report")

    monkeypatch.setattr(full._Sources, "code", source_match)
    monkeypatch.setattr(full, "link_calls", forbidden)
    monkeypatch.setattr(full, "_references", forbidden)
    report = read_call_source_seeds(output, tmp_path)
    names = {capture.code.key: capture.code.qualname for capture in report.model.codes}
    groups = {names[group.code]: group for group in report.model.groups}
    assert groups["identity"].count == 5 and groups["run"].count == 1
    assert groups["identity"].first_anchor.index < groups["identity"].last_anchor.index
    assert groups["identity"].first_invocation != groups["identity"].last_invocation
    assert set(matched) == {group.code for group in report.model.groups}
    assert set(matched) < {capture.code.key for capture in report.model.codes}
    assert {names[group.code] for group in report.eligible_groups()} == {"identity", "run"}
    assert "len" not in groups
    document = report.to_dict()
    for flag in report.model.authority_flags():
        assert document[flag] is False and document["summary"][flag] is False
    assert document["target_executed_by_resolver"] is False
    assert "weak:" not in json.dumps(document)
    assert not hasattr(report.model, "references") and not hasattr(report.model, "reference_routes")
    assert CallSourceSeedReport.from_dict(document).to_dict() == document


def test_verified_module_without_definition_is_not_a_seed(tmp_path, monkeypatch):
    (tmp_path / "module.py").write_text("answer = 1\n", encoding="utf-8")
    output = captured(tmp_path, monkeypatch, module_entry=True)
    report = read_call_source_seeds(output, tmp_path)
    assert any(link.status is CallLinkStatus.VERIFIED and link.definition is None
               for link in report.model.code_links)
    assert report.eligible_groups() == () and report.eligible_code_links() == ()


def test_source_drift_recomputes_mismatch_and_rejects_old_report(tmp_path, monkeypatch):
    output = captured(tmp_path, monkeypatch)
    document = read_call_source_seeds(output, tmp_path).to_dict()
    (tmp_path / "helper.py").write_text("def identity(value):\n    return None\n", encoding="utf-8")
    changed = read_call_source_seeds(output, tmp_path)
    assert any(link.status is CallLinkStatus.MISMATCH for link in changed.model.code_links)
    with pytest.raises(ValueError, match="replay"):
        CallSourceSeedReport.from_dict(document)


def test_gzip_trace_replays_same_logical_raw_manifest(tmp_path, monkeypatch):
    output = captured(tmp_path, monkeypatch)
    before = read_call_source_seeds(output, tmp_path).to_dict()
    for path in tuple(output.iterdir()):
        with gzip.open(str(path) + ".gz", "wb") as stream:
            stream.write(path.read_bytes())
        path.unlink()
    assert read_call_source_seeds(output, tmp_path).to_dict() == before
    assert CallSourceSeedReport.from_dict(before).to_dict() == before


@pytest.mark.parametrize("field,value", [
    ("events", 999), ("bytes", 0), ("unknown_exits", 999),
])
def test_metadata_accounting_is_not_trusted(tmp_path, monkeypatch, field, value):
    output = captured(tmp_path, monkeypatch)
    path, meta = _meta(output)
    meta[field] = value
    path.write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(ValueError):
        read_call_source_seeds(output, tmp_path)


def test_unknown_metadata_is_hashed_but_not_copied_into_compact_report(tmp_path, monkeypatch):
    output = captured(tmp_path, monkeypatch)
    before = read_call_source_seeds(output, tmp_path).to_dict()
    path, meta = _meta(output)
    meta["future_diagnostic"] = ["not compact metadata"] * 10
    path.write_text(json.dumps(meta), encoding="utf-8")
    after = read_call_source_seeds(output, tmp_path).to_dict()
    assert "future_diagnostic" not in json.dumps(after)
    assert before["model"]["collection_metadata"] == after["model"]["collection_metadata"]
    assert before["model"]["files"] != after["model"]["files"]
    with pytest.raises(ValueError, match="replay"):
        CallSourceSeedReport.from_dict(before)


@pytest.mark.parametrize("kind", ["unknown_event", "bad_reference"])
def test_all_raw_event_and_reference_records_are_validated(tmp_path, monkeypatch, kind):
    output = captured(tmp_path, monkeypatch)

    def change(rows):
        if kind == "unknown_event":
            rows[0]["kind"] = "native_call"
        else:
            row = next(row for row in rows if row["kind"] == "call_enter" and row["parameters"])
            row["parameters"][0]["ref"] = "weak:99999999:1"

    _rewrite_events(output, change)
    with pytest.raises(ValueError):
        read_call_source_seeds(output, tmp_path)


@pytest.mark.parametrize("field", [
    "max_raw_bytes", "max_lines", "max_line_bytes", "max_codes", "max_events", "max_references",
])
def test_raw_budgets_remain_fatal(tmp_path, monkeypatch, field):
    output = captured(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="budget"):
        read_call_source_seeds(output, tmp_path, budget=replace(CallEdgeBudget(), **{field: 1}))


def test_source_cap_is_a_finite_boundary_not_an_eligible_seed(tmp_path, monkeypatch):
    output = captured(tmp_path, monkeypatch)
    report = read_call_source_seeds(output, tmp_path, budget=replace(CallEdgeBudget(), max_source_files=1))
    assert len(report.eligible_code_links()) == 1
    assert any(issue.kind is CallEdgeIssueKind.SOURCE_BOUNDARY
               for link in report.model.code_links for issue in link.issues)
    assert CallSourceSeedReport.from_dict(report.to_dict()).to_dict() == report.to_dict()


@pytest.mark.parametrize("mutation", ["schema", "authority", "summary", "group", "metadata", "extra"])
def test_compact_report_strict_replay_rejects_tampering(tmp_path, monkeypatch, mutation):
    output = captured(tmp_path, monkeypatch)
    document = deepcopy(read_call_source_seeds(output, tmp_path).to_dict())
    if mutation == "schema":
        document["schema_version"] = True
    elif mutation == "authority":
        document["data_connections_established"] = True
    elif mutation == "summary":
        document["summary"]["invented"] = 1
    elif mutation == "group":
        document["model"]["groups"][0]["count"] += 1
    elif mutation == "metadata":
        document["model"]["collection_metadata"][0]["bytes"] += 1
    else:
        document["model"]["invented"] = []
    with pytest.raises(ValueError):
        CallSourceSeedReport.from_dict(document)


def test_independent_budget_is_checked_before_any_raw_or_source_work(tmp_path, monkeypatch):
    output = captured(tmp_path, monkeypatch)
    document = read_call_source_seeds(output, tmp_path).to_dict()
    import scar.analysis.call_seeds as seeds

    def forbidden(*args, **kwargs):
        raise AssertionError("budget ceiling must be checked first")

    monkeypatch.setattr(seeds, "read_call_source_seeds", forbidden)
    with pytest.raises(ValueError, match="independent verifier budget: max_references"):
        CallSourceSeedReport.from_dict(document, verification_budget=replace(CallEdgeBudget(), max_references=1))


def test_more_reference_vectors_do_not_enlarge_seed_records_linearly(tmp_path, monkeypatch):
    small_root, large_root = tmp_path / "small", tmp_path / "large"
    small_root.mkdir()
    large_root.mkdir()
    small_trace = captured(small_root, monkeypatch, extra_locals=0)
    large_trace = captured(large_root, monkeypatch, extra_locals=48)
    small = read_call_source_seeds(small_trace, small_root).to_dict()
    large = read_call_source_seeds(large_trace, large_root).to_dict()
    small_raw = sum(file["raw_bytes"] for file in small["model"]["files"])
    large_raw = sum(file["raw_bytes"] for file in large["model"]["files"])
    assert large_raw - small_raw > 3000
    assert abs(len(json.dumps(large)) - len(json.dumps(small))) < 500
    assert len(small["model"]["groups"]) == len(large["model"]["groups"])


def test_real_processes_keep_separate_groups_and_process_budget(tmp_path):
    source = tmp_path / "source.py"
    source.write_text("def identity(value):\n    return value\n", encoding="utf-8")
    output = tmp_path / "trace"
    script = """import sys
from scar.trace.call_edges import CallEdgeRecorder
namespace = {}
exec(compile(open(sys.argv[1]).read(), sys.argv[1], 'exec', dont_inherit=True), namespace)
recorder = CallEdgeRecorder(sys.argv[2], sys.argv[3])
sys.setprofile(recorder.profile)
namespace['identity'](object())
sys.setprofile(None)
recorder.close()
"""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(Path(__file__).resolve().parents[2]))
    for _ in range(2):
        subprocess.run([sys.executable, "-c", script, str(source), str(output), str(tmp_path)],
                       check=True, env=env, capture_output=True, text=True)
    report = read_call_source_seeds(output, tmp_path)
    assert len(report.model.groups) == 2
    assert len({group.process_id for group in report.model.groups}) == 2
    assert len({group.code for group in report.model.groups}) == 1
    assert len(report.eligible_groups()) == 2 and len(report.eligible_code_links()) == 1
    assert CallSourceSeedReport.from_dict(report.to_dict()).to_dict() == report.to_dict()
    with pytest.raises(ValueError, match="process budget"):
        read_call_source_seeds(output, tmp_path, budget=replace(CallEdgeBudget(), max_processes=1))
