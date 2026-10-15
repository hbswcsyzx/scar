import gzip
import hashlib
import json

import pytest

from scar.analysis.runtime_sources import read_runtime_trace, resolve_runtime_seeds
from scar.ir.program.runtime_sources import (
    RuntimeFilenameSource, RuntimeSeedStatus, RuntimeTraceBudget,
    RuntimeTraceIssueKind,
)


def _code_id(source, *, qualname="fn", line=1, digest="a" * 64):
    return f"{source}:{qualname}:{line}:None:pycode-sha256:{digest}"


def _event(code_id, *, kind="python_call", process_id="unset", **extra):
    row = {"kind": kind, "code_id": code_id}
    if process_id != "unset":
        row["process_id"] = process_id
    row.update(extra)
    return row


def _write_jsonl(path, rows):
    payload = b"".join(json.dumps(row, separators=(",", ":")).encode() + b"\n"
                      for row in rows)
    path.write_bytes(payload)
    return payload


def test_streaming_reader_uses_gzip_fallback_and_groups_exact_codeid_process_pairs(tmp_path):
    source = str(tmp_path / "module.py")
    code_id = _code_id(source)
    rows = [
        _event(code_id, process_id=7, index=10, invocation_id="call-a",
               metadata={"file": source}),
        _event(code_id, process_id=7, kind="python_return", index=11,
               invocation_id="call-a", metadata={"filename": source}),
        _event(code_id, process_id="7", kind="module_call", index="12"),
        _event(code_id, kind="python_c_call", index=13),
        _event("bad-code-identity", process_id=7),
        _event("bad-code-identity", process_id=7, kind="python_return"),
        _event(None, kind="python_line", process_id=3),
        _event(None, kind="torch_op"),
    ]
    payload = b"".join(json.dumps(row, separators=(",", ":")).encode() + b"\n"
                      for row in rows)
    archive = tmp_path / "events.jsonl.gz"
    with gzip.open(archive, "wb") as stream:
        stream.write(payload)

    runtime = read_runtime_trace(tmp_path / "events.jsonl")

    assert runtime.manifest.logical_path == str(tmp_path / "events.jsonl")
    assert runtime.manifest.raw_sha256 == hashlib.sha256(payload).hexdigest()
    assert runtime.manifest.raw_bytes == len(payload)
    assert runtime.manifest.line_count == len(rows)
    assert runtime.manifest.record_count == len(rows)
    assert runtime.manifest.supported_event_count == 7
    assert runtime.manifest.ignored_event_count == 1
    assert {item.kind: item.count for item in runtime.manifest.event_counts} == {
        "module_call": 1, "python_c_call": 1, "python_call": 2,
        "python_line": 1, "python_return": 2, "torch_op": 1,
    }
    assert len(runtime.observations) == 4
    first = runtime.observations[0]
    assert (first.code_id, first.process_id, first.count) == (code_id, 7, 2)
    assert first.first.line_number == 1 and first.last.line_number == 2
    assert first.first.line_sha256 == hashlib.sha256(payload.splitlines(keepends=True)[0]).hexdigest()
    assert first.last.kind == "python_return"
    assert {(hint.value, hint.source) for hint in first.filename_hints} == {
        (source, RuntimeFilenameSource.METADATA_FILE),
        (source, RuntimeFilenameSource.METADATA_FILENAME),
    }
    assert runtime.observations[1].process_id == "7"
    assert runtime.observations[2].process_id is None
    assert len(runtime.issues) == 2
    assert runtime.issues[0].kind is RuntimeTraceIssueKind.CODE_ID_PARSE_FAILED
    assert runtime.issues[0].count == 2
    assert runtime.issues[1].kind is RuntimeTraceIssueKind.INVALID_CODE_ID


def test_relative_trace_path_is_anchored_in_manifest_at_read_time(tmp_path, monkeypatch):
    path = tmp_path / "events.jsonl"
    _write_jsonl(path, [_event(_code_id("/a.py"))])
    monkeypatch.chdir(tmp_path)

    runtime = read_runtime_trace("events.jsonl")

    assert runtime.manifest.logical_path == str(path)


@pytest.mark.parametrize("payload,match", [
    (b'{"kind":"python_call","kind":"python_return"}\n', "duplicate JSON key"),
    (b'{"kind":"python_call","value":NaN}\n', "non-finite JSON constant"),
    (b'{"kind":"python_call","value":1e999}\n', "non-finite JSON number"),
    (b"\xff\n", "invalid UTF-8"),
    (b"[]\n", "must contain a JSON object"),
])
def test_invalid_json_never_returns_a_partial_trace(tmp_path, payload, match):
    path = tmp_path / "events.jsonl"
    path.write_bytes(payload)
    with pytest.raises(ValueError, match=match):
        read_runtime_trace(path)


@pytest.mark.parametrize("budget,payload,match", [
    (RuntimeTraceBudget(max_uncompressed_bytes=5), b'{"kind":"python_call"}\n', "byte budget"),
    (RuntimeTraceBudget(max_lines=1), b"\n\n", "line budget"),
    (RuntimeTraceBudget(max_line_bytes=8), b'{"kind":"python_call"}\n', "exceeds 8 bytes"),
    (RuntimeTraceBudget(max_codes=1), None, "code observation budget"),
])
def test_budget_exhaustion_raises_instead_of_returning_partial_results(tmp_path, budget, payload, match):
    path = tmp_path / "events.jsonl"
    if payload is None:
        rows = [_event(_code_id("/a.py")), _event(_code_id("/b.py"))]
        _write_jsonl(path, rows)
    else:
        path.write_bytes(payload)
    with pytest.raises(ValueError, match=match):
        read_runtime_trace(path, budget=budget)


def test_exact_integer_budget_validation_and_invalid_pid_issue(tmp_path):
    with pytest.raises(ValueError, match="exact integer"):
        RuntimeTraceBudget(max_codes=True)
    path = tmp_path / "events.jsonl"
    _write_jsonl(path, [_event(_code_id("/a.py"), process_id=True)])
    runtime = read_runtime_trace(path)
    assert runtime.observations == ()
    assert len(runtime.issues) == 1
    assert runtime.issues[0].kind is RuntimeTraceIssueKind.INVALID_PROCESS_ID


def test_reader_revalidates_budget_after_frozen_instance_mutation(tmp_path):
    path = tmp_path / "events.jsonl"
    _write_jsonl(path, [_event(_code_id("/a.py"))])
    budget = RuntimeTraceBudget()
    object.__setattr__(budget, "max_line_bytes", 0)

    with pytest.raises(ValueError, match="max_line_bytes must be an exact integer >= 1"):
        read_runtime_trace(path, budget=budget)


def test_metadata_process_id_is_preserved_and_conflicting_sources_are_rejected(tmp_path):
    code_id = _code_id("/a.py")
    rows = [
        _event(code_id, metadata={"process_id": 17}, index=1),
        _event(code_id, metadata={"process_id": 17}, index=2),
        _event(code_id, metadata={"process_id": "17"}, index=3),
        _event(code_id, process_id=17, metadata={"process_id": 17}, index=4),
        _event(code_id, process_id=17, metadata={"process_id": "17"}, index=5),
        _event(code_id, metadata={"process_id": True}, index=6),
    ]
    path = tmp_path / "events.jsonl"
    _write_jsonl(path, rows)

    runtime = read_runtime_trace(path)

    assert runtime.manifest.supported_event_count == len(rows)
    assert [(item.process_id, item.count) for item in runtime.observations] == [
        (17, 3), ("17", 1),
    ]
    assert [item.kind for item in runtime.issues] == [
        RuntimeTraceIssueKind.INVALID_PROCESS_ID,
        RuntimeTraceIssueKind.INVALID_PROCESS_ID,
    ]
    assert "event.process_id and metadata.process_id" in runtime.issues[0].detail
    assert "metadata.process_id must be exact int" in runtime.issues[1].detail


def test_filename_hints_are_bounded_and_overflow_is_reported(tmp_path):
    path = tmp_path / "events.jsonl"
    code_id = _code_id("/a.py")
    rows = [
        _event(code_id, metadata={"file": "/a.py"}),
        _event(code_id, metadata={"filename": "/b.py", "source_file": "/c.py"}),
    ]
    _write_jsonl(path, rows)
    runtime = read_runtime_trace(path, budget=RuntimeTraceBudget(max_filename_hints_per_code=1))
    assert len(runtime.observations[0].filename_hints) == 1
    assert runtime.observations[0].dropped_filename_hints == 2
    issues = [item for item in runtime.issues if item.kind is RuntimeTraceIssueKind.FILENAME_HINT_LIMIT]
    assert len(issues) == 1 and issues[0].count == 2


def test_seed_resolution_uses_only_parsed_codeid_source_and_never_follows_symlinks(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    good = root / "good.py"
    good.write_bytes(b"\xff")  # classification must not read or decode source text
    outside = tmp_path / "outside.py"
    outside.write_text("x = 1\n")
    (root / "linked.py").symlink_to(outside)
    missing = root / "missing.py"
    paths = [
        str(good), "<generated-code>", "relative.py", str(outside),
        str(root / "linked.py"), str(missing), str(root / "notes.txt"),
    ]
    rows = [
        _event(_code_id(source), process_id=index,
               metadata={"file": str(good)})
        for index, source in enumerate(paths)
    ]
    rows.append(_event("malformed-code-id", process_id=8,
                       metadata={"file": str(good)}))
    trace_path = tmp_path / "events.jsonl"
    _write_jsonl(trace_path, rows)

    runtime = read_runtime_trace(trace_path)
    seeds = resolve_runtime_seeds(runtime, root)

    assert [seed.status for seed in seeds] == [
        RuntimeSeedStatus.AVAILABLE_PYTHON,
        RuntimeSeedStatus.GENERATED,
        RuntimeSeedStatus.RELATIVE_NO_CWD,
        RuntimeSeedStatus.OUTSIDE_PROJECT,
        RuntimeSeedStatus.SYMLINK,
        RuntimeSeedStatus.MISSING,
        RuntimeSeedStatus.NON_PYTHON,
        RuntimeSeedStatus.UNPARSEABLE_CODE_ID,
    ]
    # The metadata.file hint is retained for a later compile-filename trial;
    # it cannot replace missing.py or repair an unparseable CodeID source.
    assert seeds[5].candidate_path == str(missing)
    assert seeds[7].candidate_path == ""
    assert runtime.observations[5].filename_hints[0].value == str(good)
    assert runtime.observations[7].filename_hints[0].value == str(good)

    with pytest.raises(ValueError, match="project_root must be absolute"):
        resolve_runtime_seeds(runtime, "relative-root")


def test_noncanonical_absolute_source_path_is_retained_without_normalizing(tmp_path):
    root = tmp_path / "project"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "payload.py").write_text("x = 1\n")
    (outside / "payload.py").write_text("x = 2\n")
    (root / "link").symlink_to(outside, target_is_directory=True)
    candidate = f"{root}/link/../payload.py"
    trace_path = tmp_path / "events.jsonl"
    _write_jsonl(trace_path, [_event(_code_id(candidate))])

    runtime = read_runtime_trace(trace_path)
    seed, = resolve_runtime_seeds(runtime, root)

    assert seed.candidate_path == candidate
    assert seed.status is RuntimeSeedStatus.NON_CANONICAL_PATH
    assert "retained without normalization or filesystem access" in seed.reason
