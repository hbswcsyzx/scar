"""Strict sidecar replay against actual v1 frame captures; protocol mutations only."""
from copy import deepcopy
from dataclasses import replace
import dis
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import scar.analysis.call_operand_reader as reader
from scar.analysis.call_trace_reader import CollectingCallSink, scan_call_trace
from scar.ir.program.call_edges import CallEdgeBudget
from scar.ir.program.call_operands import CallOperandBudget
from scar.ir.record_codec import encode
from scar.trace.call_edges import CallEdgeRecorder
from scar.trace.code_snapshot import describe_code, site


def _frame_scan(output, root):
    sink = CollectingCallSink()
    scan = scan_call_trace(output, root, CallEdgeBudget(), sink=sink)
    return scan, sink


def _write_sidecar(output, root, rows, *, metadata_changes=None):
    scan, _ = _frame_scan(output, root)
    process = scan.metadata[0]["process_id"]
    path = output / f"call-operands.{process}.jsonl"
    payload = "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows).encode()
    path.write_bytes(payload)
    loads = references = 0
    for row in rows:
        for load in row.get("loads", ()):
            loads += 1
            references += load["reference"] is not None
            references += load["callable_shape"]["reference"] is not None
        if row["kind"] == "CALL_ATTEMPT":
            references += row["dispatch"]["reference"] is not None
            references += row["arg0"] is not None
    meta = {
        "schema": "scar.call-operands-trace", "schema_version": 1, "process_id": process,
        "project_root": str(root), "python": sys.version, "implementation": "cpython",
        "rule": "CPYTHON_LOAD_OCCURRENCES_V1",
        "limits": {"max_events": 100000, "max_bytes": 32000000, "max_loads": 64,
                   "max_namespace_items": 4096, "max_references": 8192},
        "events": len(rows), "event_attempts": max((row["index"] for row in rows), default=0),
        "instructions": sum(row["kind"] == "INSTRUCTION" for row in rows),
        "call_attempts": sum(row["kind"] == "CALL_ATTEMPT" for row in rows),
        "handshakes": sum(row["kind"] == "ENTRY_HANDSHAKE" for row in rows),
        "gaps": sum(row["kind"] == "GAP" for row in rows), "loads": loads,
        "references": references, "bytes": len(payload), "dropped_events": 0,
        "errors": [], "io_failed": False, "previous_profile": False,
        "base_manifest": encode(scan.files), "reference_contents_observed": False,
        "callable_environment_established": False, "transformation_authorized": False,
    }
    meta["dropped_events"] = meta["event_attempts"] - meta["events"]
    if metadata_changes:
        meta.update(metadata_changes)
    meta_path = output / f"call-operand-meta.{process}.json"
    meta_path.write_text(json.dumps(meta) + "\n", encoding="utf-8")
    return path, meta_path, meta


@pytest.fixture
def captured(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    source = root / "entry.py"
    source.write_text("def leaf(left, right):\n    return left\n"
                      "def run(x, y):\n    return leaf(x, y)\n", encoding="utf-8")
    namespace = {}
    exec(compile(source.read_text(), str(source), "exec", dont_inherit=True), namespace)
    output = root / "trace"
    recorder = CallEdgeRecorder(output, root)
    old_profile = sys.getprofile()
    sys.setprofile(recorder.profile)
    try:
        left, right = object(), object()
        assert namespace["run"](left, right) is left
    finally:
        sys.setprofile(old_profile)
        recorder.close()
    scan, sink = _frame_scan(output, root)
    names = {capture.code.key: capture.code.qualname for capture in scan.captures}
    entries = {names[entry.code]: entry for entry in sink.entries}
    run_entry, leaf_entry = entries["run"], entries["leaf"]
    process = run_entry.invocation.process_id
    run_code, leaf_code = namespace["run"].__code__, namespace["leaf"].__code__
    leaf_description = describe_code(leaf_code)
    function_shape = {
        "kind": "EXACT_FUNCTION", "reference": f"weak:{process}:999",
        "code": leaf_description["key"],
        "layout": {"argcount": leaf_code.co_argcount, "posonlyargcount": leaf_code.co_posonlyargcount,
                   "kwonlyargcount": leaf_code.co_kwonlyargcount, "flags": leaf_code.co_flags,
                   "parameters": leaf_description["parameters"]},
    }
    rows = []

    def common(kind, owner, watermark):
        return {"index": len(rows) + 1, "kind": kind, "process_id": process,
                "thread_id": owner.invocation.thread_id, "invocation_id": owner.invocation.invocation_id,
                "frame_index": watermark, "hook_epoch": 1}

    # These rows exercise protocol validation only; full production capture and
    # instruction-to-source routing have separate integration acceptance.
    for instruction in dis.get_instructions(run_code):
        row = common("INSTRUCTION", run_entry, run_entry.anchor.index)
        row.update(site=site(run_code, instruction.offset), loads=[])
        if instruction.opname == "LOAD_GLOBAL" and instruction.argval == "leaf":
            row["loads"].append({"suboperand": 0, "namespace": "GLOBAL", "slot": "leaf",
                                 "slot_index": None, "reference": function_shape["reference"],
                                 "callable_shape": deepcopy(function_shape)})
        elif instruction.opname.startswith("LOAD_FAST"):
            slots = instruction.argval if type(instruction.argval) is tuple else (instruction.argval,)
            for suboperand, name in enumerate(slots):
                reference = f"operand-snapshot:{process}:{row['index']}:{suboperand + 1}"
                row["loads"].append({"suboperand": suboperand, "namespace": "FAST_LOCAL", "slot": name,
                                     "slot_index": run_code.co_varnames.index(name), "reference": reference,
                                     "callable_shape": {"kind": "OTHER", "reference": reference,
                                                        "code": None, "layout": None}})
        rows.append(row)
        if instruction.opname.startswith("CALL"):
            attempt = common("CALL_ATTEMPT", run_entry, run_entry.anchor.index)
            attempt.update(site=site(run_code, instruction.offset), dispatch=deepcopy(function_shape),
                           arg0=None, arg0_missing=True)
            rows.append(attempt)
            handshake = common("ENTRY_HANDSHAKE", leaf_entry, leaf_entry.anchor.index)
            handshake.update(attempt_index=attempt["index"], entry_index=leaf_entry.anchor.index)
            rows.append(handshake)
            break
    paths = _write_sidecar(output, root, rows)
    return root, output, rows, paths, scan, sink


def _read(captured, **kwargs):
    root, output, *_ = captured
    return reader.read_call_operands(output, root, **kwargs)


def test_reader_preserves_original_raw_anchors_and_separate_sidecar_occurrences(captured):
    root, output, rows, paths, old_scan, sink = captured
    result = _read(captured)
    assert result.frame_scan == old_scan
    assert result.entries == tuple(sink.entries) and result.exits == tuple(sink.exits)
    assert len(result.attempts) == len(result.handshakes) == 1 and not result.issues
    handshake = result.handshakes[0]
    entry = next(entry for entry in result.entries if entry.invocation == handshake.invocation)
    assert handshake.entry_index == entry.anchor.index
    assert handshake.anchor.path != entry.anchor.path
    assert handshake.anchor.index == handshake.index
    for record, raw in zip(result.events, paths[0].read_bytes().splitlines(keepends=True)):
        assert record.anchor.line_sha256 == hashlib.sha256(raw).hexdigest()
    fast = [(record.key, load.suboperand, load.slot) for record in result.instructions
            for load in record.loads if load.namespace.value == "FAST_LOCAL"]
    assert [item[2] for item in fast] == ["x", "y"]
    assert len(set(item[:2] for item in fast)) == 2
    assert _frame_scan(output, root)[0] == old_scan  # legacy scanning ignores sidecars


def test_gzip_sidecars_keep_logical_paths_hashes_and_original_frame_manifest(captured):
    before = _read(captured)
    root, output, rows, paths, *_ = captured
    for path in paths[:2]:
        with gzip.open(str(path) + ".gz", "wb") as stream:
            stream.write(path.read_bytes())
        path.unlink()
    assert _read(captured) == before


@pytest.mark.parametrize("field", ["events", "event_attempts", "bytes", "instructions", "call_attempts",
                                   "handshakes", "gaps", "loads", "references"])
def test_actual_counts_are_recomputed_instead_of_trusted(captured, field):
    root, output, rows, paths, *_ = captured
    meta = deepcopy(paths[2])
    meta[field] += 1
    paths[1].write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(ValueError):
        _read(captured)


@pytest.mark.parametrize("mutation", ["hash", "bytes", "lines", "path", "missing", "wrong_pid"])
def test_base_manifest_must_match_before_operand_event_io(captured, monkeypatch, mutation):
    root, output, rows, paths, *_ = captured
    meta = deepcopy(paths[2])
    item = meta["base_manifest"][0]
    if mutation == "hash":
        item["raw_sha256"] = "f" * 64
    elif mutation == "bytes":
        item["raw_bytes"] += 1
    elif mutation == "lines":
        item["lines"] += 1
    elif mutation == "path":
        item["path"] += ".other"
    elif mutation == "missing":
        meta["base_manifest"].pop()
    else:
        item["process_id"] += 1
    paths[1].write_text(json.dumps(meta), encoding="utf-8")
    original = reader.open_binary

    def checked(path):
        assert not path.name.startswith("call-operands."), "must reject manifest before events are opened"
        return original(path)

    monkeypatch.setattr(reader, "open_binary", checked)
    with pytest.raises(ValueError):
        _read(captured)


@pytest.mark.parametrize("field,value", [
    ("schema_version", True), ("schema_version", 2), ("rule", "trusted"),
    ("previous_profile", 1), ("reference_contents_observed", True),
    ("callable_environment_established", True), ("transformation_authorized", True),
])
def test_metadata_types_and_authority_are_strict(captured, field, value):
    paths = captured[3]
    meta = deepcopy(paths[2])
    meta[field] = value
    paths[1].write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(ValueError):
        _read(captured)


@pytest.mark.parametrize("field", ["max_raw_bytes", "max_lines", "max_line_bytes", "max_events",
                                   "max_loads", "max_references", "max_metadata_bytes"])
def test_independent_sidecar_limits_bound_actual_work(captured, field):
    with pytest.raises(ValueError, match="budget"):
        _read(captured, budget=replace(CallOperandBudget(), **{field: 1}))


def test_invalid_budget_precedes_all_filesystem_work():
    class NoFilesystem:
        def __fspath__(self):
            pytest.fail("invalid budget must be rejected before filesystem access")
    with pytest.raises(ValueError, match="typed"):
        reader.read_call_operands(NoFilesystem(), NoFilesystem(), budget=True)


def test_small_metadata_budget_bounds_read_before_deserialization(captured, monkeypatch):
    requests = []
    original = reader.open_binary

    class BoundedStream:
        def __init__(self, path):
            self.stream = original(path)
        def __enter__(self):
            self.stream.__enter__()
            return self
        def __exit__(self, *args):
            return self.stream.__exit__(*args)
        def readline(self, size):
            requests.append(size)
            return self.stream.readline(size)

    monkeypatch.setattr(reader, "open_binary", BoundedStream)
    with pytest.raises(ValueError, match="metadata byte budget"):
        _read(captured, budget=replace(CallOperandBudget(), max_metadata_bytes=8))
    assert requests == [9]


@pytest.mark.parametrize("mode", ["wrong_pid", "wrong_event", "old_snapshot"])
def test_snapshot_identity_cannot_escape_its_operand_observation(captured, mode):
    root, output, rows, *_ = captured
    row = next(row for row in rows if any(load["namespace"] == "FAST_LOCAL" for load in row.get("loads", ())))
    load = row["loads"][0]
    reference = {
        "wrong_pid": f"operand-snapshot:{row['process_id'] + 1}:{row['index']}:1",
        "wrong_event": f"operand-snapshot:{row['process_id']}:{row['index'] + 1}:1",
        "old_snapshot": f"snapshot:{row['process_id']}:{row['index']}:1",
    }[mode]
    load["reference"] = load["callable_shape"]["reference"] = reference
    _write_sidecar(output, root, rows)
    with pytest.raises(ValueError):
        _read(captured)


@pytest.mark.parametrize("mode", ["unknown_owner", "wrong_process", "wrong_thread", "late_watermark", "backwards_watermark",
                                  "site_code", "missing_attempt", "wrong_entry", "epoch_without_gap"])
def test_record_relationship_tampering_is_fatal(captured, mode):
    root, output, rows, paths, scan, sink = captured
    attempt, handshake = rows[-2:]
    if mode == "unknown_owner":
        rows[0]["invocation_id"] = 99999
    elif mode == "wrong_process":
        rows[0]["process_id"] += 1
    elif mode == "wrong_thread":
        handshake["thread_id"] += 1
    elif mode == "late_watermark":
        attempt["frame_index"] = scan.metadata[0]["event_attempts"] + 1
    elif mode == "backwards_watermark":
        attempt["frame_index"] = 0
    elif mode == "site_code":
        rows[0]["site"]["code"] = "pycode-v2:" + "f" * 64
    elif mode == "missing_attempt":
        handshake["attempt_index"] = 1
    elif mode == "wrong_entry":
        handshake["entry_index"] = handshake["frame_index"] = 1
    else:
        handshake["hook_epoch"] = 2
    _write_sidecar(output, root, rows)
    with pytest.raises(ValueError):
        _read(captured)


def test_older_same_site_attempt_cannot_claim_a_later_entry(captured):
    root, output, rows, *_ = captured
    earlier, handshake = rows[-2:]
    newer = deepcopy(earlier)
    newer["index"] += 1
    handshake["index"] += 1
    rows.insert(-1, newer)
    _write_sidecar(output, root, rows)
    with pytest.raises(ValueError, match="stale|superseded"):
        _read(captured)


def test_caller_resumption_expires_attempt_even_at_same_call_site(captured):
    root, output, rows, *_ = captured
    attempt, handshake = rows[-2:]
    resumed = {**deepcopy(attempt), "kind": "INSTRUCTION", "index": attempt["index"] + 1, "loads": []}
    for field in ("dispatch", "arg0", "arg0_missing"):
        del resumed[field]
    handshake["index"] += 1
    rows.insert(-1, resumed)
    _write_sidecar(output, root, rows)
    with pytest.raises(ValueError, match="stale|superseded"):
        _read(captured)


def test_one_attempt_and_entry_cannot_be_handshaken_twice(captured):
    root, output, rows, *_ = captured
    duplicate = deepcopy(rows[-1])
    duplicate["index"] += 1
    rows.append(duplicate)
    _write_sidecar(output, root, rows)
    with pytest.raises(ValueError, match="reused"):
        _read(captured)


def test_original_parent_tampering_cannot_be_hidden_by_rehashed_base_manifest(captured):
    root, output, rows, paths, scan, sink = captured
    event_file = next(Path(file.path) for file in scan.files if file.family == "events")
    base_rows = [json.loads(raw) for raw in event_file.read_text().splitlines()]
    entry_index = rows[-1]["entry_index"]
    entered = next(row for row in base_rows if row["index"] == entry_index)
    entered["caller_invocation_id"] = entered["ancestor_invocation_id"] = 99999
    event_file.write_text("".join(json.dumps(row) + "\n" for row in base_rows), encoding="utf-8")
    meta_file = next(Path(file.path) for file in scan.files if file.family == "meta")
    base_meta = json.loads(meta_file.read_text())
    base_meta["bytes"] = sum(Path(file.path).stat().st_size for file in scan.files
                             if file.family in ("codes", "events"))
    meta_file.write_text(json.dumps(base_meta), encoding="utf-8")
    _write_sidecar(output, root, rows)
    with pytest.raises(ValueError, match="direct active caller"):
        _read(captured)


@pytest.mark.parametrize("mode", ["code", "layout"])
def test_code_or_layout_disagreement_stays_a_boundary_not_verified_routing(captured, mode):
    root, output, rows, paths, scan, sink = captured
    dispatch = rows[-2]["dispatch"]
    if mode == "code":
        parent = next(capture.code for capture in scan.captures if capture.code.qualname == "run")
        dispatch["code"] = parent.key
        dispatch["layout"]["parameters"] = list(parent.parameters)
        dispatch["layout"]["flags"] = parent.flags
    else:
        dispatch["layout"]["parameters"].reverse()
    _write_sidecar(output, root, rows)
    result = _read(captured)
    assert any(issue.kind == ("CODE_MISMATCH" if mode == "code" else "LAYOUT_MISMATCH") for issue in result.issues)


def test_previous_profile_and_explicit_gap_are_visible_boundaries(captured):
    root, output, rows, *_ = captured
    gap = {key: value for key, value in rows[-1].items() if key not in ("attempt_index", "entry_index")}
    gap.update(index=gap["index"] + 1, kind="GAP", invocation_id=None, hook_epoch=2,
               reason="instruction callback replaced")
    rows.append(gap)
    _write_sidecar(output, root, rows, metadata_changes={"previous_profile": True})
    result = _read(captured)
    assert {issue.kind for issue in result.issues} == {"PREVIOUS_PROFILE", "HOOK_OR_OBSERVATION_GAP"}
    assert len(result.gaps) == 1


@pytest.mark.parametrize("mode", ["truncated", "duplicate_key", "anchor", "unknown_field", "boolean_index"])
def test_malformed_raw_events_are_rejected(captured, mode):
    root, output, rows, paths, *_ = captured
    if mode == "truncated":
        paths[0].write_bytes(paths[0].read_bytes()[:-1])
    elif mode == "duplicate_key":
        payload = paths[0].read_text().replace('"kind":', '"index":1,"kind":', 1)
        paths[0].write_text(payload)
    else:
        rows[0][{"anchor": "anchor", "unknown_field": "trusted", "boolean_index": "index"}[mode]] = True
        _write_sidecar(output, root, rows)
    with pytest.raises(ValueError):
        _read(captured)


@pytest.mark.parametrize("mode", ["ambiguous_gzip", "symlink", "missing_pair"])
def test_sidecar_file_admission_is_strict(captured, mode):
    path = captured[3][0]
    if mode == "ambiguous_gzip":
        with gzip.open(str(path) + ".gz", "wb") as stream:
            stream.write(path.read_bytes())
    elif mode == "symlink":
        saved = path.with_suffix(".saved")
        path.rename(saved)
        path.symlink_to(saved)
    else:
        path.unlink()
    with pytest.raises(ValueError):
        _read(captured)


def test_real_observer_discovers_two_file_shared_argument_occurrences_without_manual_rows(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "helper.py").write_text("def leaf(left, right):\n    return left\n", encoding="utf-8")
    entry = project / "entry.py"
    entry.write_text("from helper import leaf\n"
                     "def run(x, y):\n    return leaf(x, y)\n"
                     "shared = []\nassert run(shared, shared) is shared\n", encoding="utf-8")
    output = tmp_path / "trace"
    repository = Path(__file__).resolve().parents[2]
    environment = {name: value for name, value in os.environ.items() if not name.startswith("SCAR_")}
    environment.update(PYTHONPATH=str(repository), PYTHONDONTWRITEBYTECODE="1")
    script = (
        "import runpy, sys\n"
        "from scar.trace.call_edges import install as frames\n"
        "from scar.trace.call_operands import install as operands\n"
        "recorder = frames(sys.argv[1], sys.argv[2])\n"
        "observer = operands(recorder)\n"
        "sys.path.insert(0, sys.argv[2])\n"
        "runpy.run_path(sys.argv[3], run_name='__main__')\n"
    )
    executed = subprocess.run([sys.executable, "-c", script, str(output), str(project), str(entry)],
                              cwd=repository, env=environment, capture_output=True, text=True, timeout=30)
    assert executed.returncode == 0, executed.stdout + executed.stderr
    observed = reader.read_call_operands(output, project)
    names = {capture.code.key: capture.code.qualname for capture in observed.frame_scan.captures}
    owners = {entry.invocation for entry in observed.entries if names[entry.code] == "run"}
    assert len(owners) == 1
    loads = [(event.key, load.suboperand, load.slot) for event in observed.instructions
             if event.invocation in owners for load in event.loads if load.slot in ("x", "y")]
    assert [load[2] for load in loads] == ["x", "y"]
    assert len({load[:2] for load in loads}) == 2
    leaf_entries = {entry.invocation for entry in observed.entries if names[entry.code] == "leaf"}
    assert len(leaf_entries) == 1
    assert any(handshake.invocation in leaf_entries for handshake in observed.handshakes)
    assert all(not meta.errors and not meta.dropped_events and not meta.previous_profile for meta in observed.metadata)
