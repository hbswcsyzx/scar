"""Streaming call trace decoding preserves the strict v1 reader contract."""
import gzip
import json
from pathlib import Path

import pytest

from scar.analysis.call_edges import _read_trace
from scar.analysis.call_trace_reader import CollectingCallSink, scan_call_trace
from scar.ir.program.call_edges import CallEdgeBudget


def _jsonl(rows):
    return b"".join(json.dumps(row, sort_keys=True, separators=(",", ":")).encode() + b"\n"
                    for row in rows)


def _code(key, *, filename, qualname, parameters=()):
    return {"key": "pycode-v2:" + key * 64, "filename": filename,
            "qualname": qualname, "first_line": 1, "flags": 0,
            "parameters": list(parameters)}


def _enter(process, invocation, code, index, *, parameters=(), path=(), caller=None,
           caller_invocation=None, ancestor_invocation=None, path_complete=True,
           caller_locals=(), parameters_complete=True, caller_locals_complete=True,
           suspended=False):
    return {
        "index": index, "kind": "call_enter", "process_id": process,
        "thread_id": 7, "invocation_id": invocation, "code": code,
        "parameters": list(parameters), "parameters_complete": parameters_complete,
        "caller": caller, "caller_invocation_id": caller_invocation,
        "ancestor_invocation_id": ancestor_invocation,
        "path": list(path), "path_complete": path_complete,
        "caller_locals": list(caller_locals),
        "caller_locals_complete": caller_locals_complete, "suspended": suspended,
    }


def _exit(process, invocation, code, index, *, completion="NORMAL", return_ref=None,
          locals=(), locals_complete=True):
    return {
        "index": index, "kind": "call_exit", "process_id": process,
        "thread_id": 7, "invocation_id": invocation, "code": code,
        "return_site": {"code": code, "offset": 0, "opname": "RETURN_VALUE",
                        "position": [1, 1, 0, 1]},
        "completion": completion,
        "return_ref": return_ref or f"weak:{process}:{invocation}",
        "locals": list(locals), "locals_complete": locals_complete,
    }


def _write_trace(root: Path, trace: Path, per_process, *, gzip_families=()):
    trace.mkdir()
    for process, codes, events, overrides in per_process:
        code_raw, event_raw = _jsonl(codes), _jsonl(events)
        for family, raw in (("codes", code_raw), ("events", event_raw)):
            suffix = ".jsonl.gz" if family in gzip_families else ".jsonl"
            path = trace / f"call-{family}.{process}{suffix}"
            if suffix.endswith(".gz"):
                with gzip.open(path, "wb") as stream:
                    stream.write(raw)
            else:
                path.write_bytes(raw)
        entries = [row for row in events if row["kind"] == "call_enter"]
        exits = [row for row in events if row["kind"] == "call_exit"]
        entered = {(row["process_id"], row["thread_id"], row["invocation_id"]) for row in entries}
        exited = {(row["process_id"], row["thread_id"], row["invocation_id"]) for row in exits}
        meta = {
            "schema": "scar.call-edge-trace", "schema_version": 1,
            "process_id": process, "project_root": str(root.resolve()),
            "reference_contents_observed": False,
            "callable_environment_established": False,
            "events": len(events), "invocations": len(entries), "codes": len(codes),
            "bytes": len(code_raw) + len(event_raw), "dropped_events": 0,
            "dropped_codes": 0,
            "unknown_exits": sum(row["completion"] == "UNKNOWN" for row in exits),
            "suspended_exits": sum(row["completion"] == "SUSPENDED" for row in exits),
            "open_invocations": len(entered - exited), "errors": [],
            "limits": {"max_events": 1000, "max_bytes": 1_000_000,
                       "max_codes": 100, "max_values": 100, "max_path": 16},
            "event_attempts": len(events), "invocation_attempts": len(entries),
            "active_frames": len(entered - exited), "path_gaps": 0,
        }
        meta.update(overrides)
        (trace / f"call-meta.{process}.json").write_text(
            json.dumps(meta, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    return trace


def _single_trace(tmp_path, *, parameters=(), gzip_families=(), overrides=None):
    root = tmp_path / "project"
    root.mkdir()
    trace = tmp_path / "trace"
    key = "a"
    code = _code(key, filename=str(root / "module.py"), qualname="run",
                 parameters=tuple(item["name"] for item in parameters))
    events = [_enter(17, 1, code["key"], 0, parameters=parameters),
              _exit(17, 1, code["key"], 1)]
    return root, _write_trace(root, trace, [(17, [code], events, overrides or {})],
                              gzip_families=gzip_families)


def _legacy_result(path, root, budget):
    return _read_trace(path, root.resolve(), budget)


def _scan_result(path, root, budget, sink):
    result = scan_call_trace(path, root.resolve(), budget, sink=sink)
    return (result.directory, result.files, result.captures,
            tuple(sink.entries), tuple(sink.exits), result.metadata, result.issues)


def test_streaming_scan_matches_legacy_valid_fixture_and_gzip_manifest(tmp_path):
    root, trace = _single_trace(tmp_path, gzip_families=("codes", "events"))
    budget = CallEdgeBudget()
    sink = CollectingCallSink()
    assert _scan_result(trace, root, budget, sink) == _legacy_result(trace, root, budget)
    assert [item.family for item in sink.entries and scan_call_trace(
        trace, root.resolve(), budget, sink=CollectingCallSink()).files] == ["codes", "events", "meta"]


def test_later_process_codes_are_retained_in_process_file_order(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    trace = tmp_path / "trace"
    first = _code("b", filename=str(root / "first.py"), qualname="first")
    later = _code("c", filename=str(root / "later.py"), qualname="later")
    p17_events = [_enter(17, 1, later["key"], 0), _exit(17, 1, later["key"], 1)]
    p17 = (17, [], p17_events, {"open_invocations": 0})
    p18_events = [_enter(18, 1, later["key"], 0), _exit(18, 1, later["key"], 1)]
    p18 = (18, [later, first], p18_events, {})
    _write_trace(root, trace, [p17, p18])
    sink = CollectingCallSink()
    result = scan_call_trace(trace, root.resolve(), CallEdgeBudget(), sink=sink)
    assert [entry.code for entry in sink.entries] == [later["key"], later["key"]]
    assert len(result.captures) == 2


@pytest.mark.parametrize("damage", [
    "missing-event-field", "bad-reference-scope", "bad-metadata-count", "nonfinite-json",
])
def test_damaged_trace_is_rejected_by_both_readers(tmp_path, damage):
    root, trace = _single_trace(tmp_path)
    events_path = trace / "call-events.17.jsonl"
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    meta_path = trace / "call-meta.17.json"
    meta = json.loads(meta_path.read_text())
    if damage == "missing-event-field":
        del events[0]["path_complete"]
        raw = _jsonl(events)
        events_path.write_bytes(raw)
        meta["bytes"] = (trace / "call-codes.17.jsonl").stat().st_size + len(raw)
    elif damage == "bad-reference-scope":
        events[0]["parameters"] = [{"name": "x", "ref": "weak:99:1"}]
        events[0]["parameters_complete"] = False
        raw = _jsonl(events)
        events_path.write_bytes(raw)
        meta["bytes"] = (trace / "call-codes.17.jsonl").stat().st_size + len(raw)
    elif damage == "bad-metadata-count":
        meta["events"] += 1
    else:
        events_path.write_bytes(events_path.read_bytes().replace(b"\"index\":0", b"\"index\":NaN", 1))
        raw = events_path.read_bytes()
        meta["bytes"] = (trace / "call-codes.17.jsonl").stat().st_size + len(raw)
    meta_path.write_text(json.dumps(meta, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    budget = CallEdgeBudget()
    with pytest.raises((ValueError, TypeError)):
        _legacy_result(trace, root, budget)
    sink = CollectingCallSink()
    with pytest.raises((ValueError, TypeError)):
        scan_call_trace(trace, root.resolve(), budget, sink=sink)
    assert sink.entries == [] and sink.exits == []


def test_reference_budget_is_enforced_even_though_scan_result_does_not_retain_refs(tmp_path):
    parameters = tuple({"name": f"p{i}", "ref": f"weak:17:{i + 1}"} for i in range(12))
    root, trace = _single_trace(tmp_path, parameters=parameters)
    budget = CallEdgeBudget(max_references=25)
    legacy = _legacy_result(trace, root, budget)
    sink = _DropSink()
    result = scan_call_trace(trace, root.resolve(), budget, sink=sink)
    assert len(legacy[3][0].parameters) == 12
    assert sink.parameter_count == 12
    assert not hasattr(result, "entries") and not hasattr(result, "references")
    with pytest.raises(ValueError, match="captured reference budget exceeded"):
        scan_call_trace(trace, root.resolve(), CallEdgeBudget(max_references=12), sink=_DropSink())


def test_sink_failure_propagates_and_collecting_sink_is_rolled_back(tmp_path):
    root, trace = _single_trace(tmp_path)
    sink = _FailingSink()
    with pytest.raises(RuntimeError, match="sink failed"):
        scan_call_trace(trace, root.resolve(), CallEdgeBudget(), sink=sink)
    assert sink.aborted


class _DropSink:
    def __init__(self):
        self.entry_count = self.exit_count = self.parameter_count = 0

    def entry(self, value):
        self.entry_count += 1
        self.parameter_count += len(value.parameters)

    def exit(self, value):
        self.exit_count += 1


class _FailingSink(_DropSink):
    def __init__(self):
        super().__init__()
        self.aborted = False

    def entry(self, value):
        self.entry_count += 1
        raise RuntimeError("sink failed")

    def abort(self):
        self.entry_count = self.exit_count = self.parameter_count = 0
        self.aborted = True
