"""Independent actual-profile boundary checks for the call-edge recorder."""
from contextlib import contextmanager
import errno
import gc
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import CodeType, FunctionType
import weakref

import pytest

from scar.trace.call_edges import CallEdgeRecorder


def _function(path, source, namespace=None):
    code = next(item for item in compile(source, str(path), "exec").co_consts if type(item) is CodeType)
    return FunctionType(code, dict(namespace or {}))


@contextmanager
def _record(tmp_path, *, threads=False, **limits):
    recorder = CallEdgeRecorder(tmp_path / "trace", tmp_path / "project", **limits)
    previous, previous_threads = sys.getprofile(), threading.getprofile()
    try:
        sys.setprofile(recorder.profile)
        if threads:
            threading.setprofile(recorder.profile)
        yield recorder
    finally:
        sys.setprofile(previous)
        if threads:
            threading.setprofile(previous_threads)
        recorder.close()


def _read(recorder):
    events = [json.loads(line) for line in recorder.event_path.read_text().splitlines()]
    codes = {code["key"]: code for code in map(json.loads, recorder.code_path.read_text().splitlines())}
    meta = json.loads((recorder.out / f"call-meta.{recorder.pid}.json").read_text())
    return events, codes, meta


def _entries(events, codes, name):
    return [event for event in events if event["kind"] == "call_enter"
            and codes[event["code"]]["qualname"] == name]


def test_exhausted_event_budget_reports_written_unpaired_entries(tmp_path):
    leaf = _function(tmp_path / "project" / "leaf.py", "def leaf(): return None\n")
    with _record(tmp_path, max_events=1) as recorder:
        leaf()
    events, _, meta = _read(recorder)
    entered = {event["invocation_id"] for event in events if event["kind"] == "call_enter"}
    exited = {event["invocation_id"] for event in events if event["kind"] == "call_exit"}
    assert entered and not exited
    assert meta["open_invocations"] == len(entered - exited)
    assert meta["invocations"] == len(entered)
    assert meta["dropped_events"] > 0
    assert recorder.active == {}


def _wrapper_chain(tmp_path):
    leaf = _function(tmp_path / "project" / "leaf.py", "def leaf(value): return value\n")
    second = _function(tmp_path / "external" / "two.py", "def second(value): return leaf(value)\n", {"leaf": leaf})
    first = _function(tmp_path / "external" / "one.py", "def first(value): return second(value)\n", {"second": second})
    run = _function(tmp_path / "project" / "entry.py", "def run(value): return first(value)\n", {"first": first})
    return run


def test_unrecorded_wrapper_is_not_relabelled_as_direct_recorded_caller(tmp_path):
    run = _wrapper_chain(tmp_path)
    with _record(tmp_path) as recorder:
        run(None)
    events, codes, _ = _read(recorder)
    leaf, = _entries(events, codes, "leaf")
    first, = _entries(events, codes, "first")
    assert not _entries(events, codes, "second")
    assert leaf["caller_invocation_id"] is None
    assert leaf["ancestor_invocation_id"] == first["invocation_id"]
    assert [codes[site["code"]]["qualname"] for site in leaf["path"]] == ["second", "first"]
    assert leaf["caller"] == leaf["path"][0]
    assert leaf["path_complete"]


def test_truncated_wrapper_path_does_not_invent_a_direct_or_ancestor_edge(tmp_path):
    run = _wrapper_chain(tmp_path)
    with _record(tmp_path, max_path=1) as recorder:
        run(None)
    events, codes, _ = _read(recorder)
    leaf, = _entries(events, codes, "leaf")
    assert len(leaf["path"]) == 1
    assert codes[leaf["caller"]["code"]]["qualname"] == "second"
    assert leaf["caller_invocation_id"] is leaf["ancestor_invocation_id"] is None
    assert not leaf["path_complete"]


def test_unsupported_outer_code_keeps_known_callee_with_explicit_path_gap(tmp_path):
    leaf = _function(tmp_path / "project" / "leaf.py", "def leaf(value): return value\n")
    outside = _function(tmp_path / "external" / "wrapper.py", "def outside(value): return leaf(value)\n", {"leaf": leaf})
    outside.__code__ = outside.__code__.replace(co_consts=(*outside.__code__.co_consts, object()))
    with _record(tmp_path) as recorder:
        outside(None)
    events, codes, meta = _read(recorder)
    call, = _entries(events, codes, "leaf")
    assert call["caller"] is None and not call["path_complete"]
    assert call["caller_invocation_id"] is None
    assert meta["path_gaps"] >= 1
    assert any(event["kind"] == "call_exit" and event["invocation_id"] == call["invocation_id"]
               for event in events)


def test_handled_exception_and_finally_return_are_normal_but_unwind_is_not(tmp_path):
    bad = _function(tmp_path / "project" / "bad.py", "def bad(): raise ValueError('failure')\n")
    caught = _function(tmp_path / "project" / "caught.py", """
def caught():
    try:
        bad()
    except ValueError:
        return None
""", {"bad": bad})
    final = _function(tmp_path / "project" / "final.py", """
def final():
    try:
        bad()
    finally:
        return None
""", {"bad": bad})
    with _record(tmp_path) as recorder:
        assert caught() is None
        assert final() is None
    events, codes, meta = _read(recorder)
    exits = [event for event in events if event["kind"] == "call_exit"]
    assert all(event["completion"] == "UNKNOWN" for event in exits if codes[event["code"]]["qualname"] == "bad")
    assert all(event["completion"] == "NORMAL" for event in exits if codes[event["code"]]["qualname"] in {"caught", "final"})
    assert meta["unknown_exits"] == 2


def test_two_real_threads_keep_parent_pairing_and_do_not_retain_values(tmp_path):
    class Value:
        pass

    leaf = _function(tmp_path / "project" / "leaf.py", "def leaf(value): return value\n")
    worker = _function(tmp_path / "project" / "worker.py", "def worker(value, gate):\n    gate.wait()\n    return leaf(value)\n",
                       {"leaf": leaf})
    values = [Value(), Value()]
    references = [weakref.ref(value) for value in values]
    barrier = threading.Barrier(3)
    with _record(tmp_path, threads=True) as recorder:
        threads = [threading.Thread(target=worker, args=(value, barrier)) for value in values]
        for thread in threads:
            thread.start()
        barrier.wait(timeout=10)
        for thread in threads:
            thread.join(timeout=10)
            assert not thread.is_alive()
    events, codes, _ = _read(recorder)
    workers = _entries(events, codes, "worker")
    leaves = _entries(events, codes, "leaf")
    assert len(workers) == len(leaves) == 2
    assert len({event["thread_id"] for event in workers}) == 2
    by_invocation = {event["invocation_id"]: event for event in workers}
    for leaf_event in leaves:
        parent = by_invocation[leaf_event["caller_invocation_id"]]
        assert parent["thread_id"] == leaf_event["thread_id"]
        assert parent["parameters"][0]["ref"] == leaf_event["parameters"][0]["ref"]
    del values, threads
    gc.collect()
    assert all(reference() is None for reference in references)
    assert recorder.active == {}


def test_partial_io_failure_cannot_escape_byte_budget_or_accounting(tmp_path, monkeypatch):
    leaf = _function(tmp_path / "project" / "leaf.py", "def leaf(): return None\n")
    original_write = os.write
    writes = 0
    recorder = CallEdgeRecorder(tmp_path / "trace", tmp_path / "project", max_bytes=1000)

    def interrupted_write(fd, payload):
        nonlocal writes
        if fd not in (recorder.events_fd, recorder.codes_fd):
            return original_write(fd, payload)
        writes += 1
        if writes % 2:
            return original_write(fd, payload[:80])
        raise OSError(errno.EIO, "injected short-write failure")

    monkeypatch.setattr(os, "write", interrupted_write)
    previous = sys.getprofile()
    try:
        sys.setprofile(recorder.profile)
        for _ in range(20):
            leaf()
    finally:
        sys.setprofile(previous)
        recorder.close()
    actual_bytes = recorder.event_path.stat().st_size + recorder.code_path.stat().st_size
    meta = json.loads((recorder.out / f"call-meta.{recorder.pid}.json").read_text())
    assert meta["errors"]
    assert actual_bytes <= recorder.limits["max_bytes"]
    assert meta["bytes"] == actual_bytes


def test_zero_byte_write_stops_recording_without_retry_loop(tmp_path, monkeypatch):
    leaf = _function(tmp_path / "project" / "leaf.py", "def leaf(): return None\n")
    recorder = CallEdgeRecorder(tmp_path / "trace", tmp_path / "project")
    original_write = os.write
    attempts = 0

    def zero_write(fd, payload):
        nonlocal attempts
        if fd not in (recorder.events_fd, recorder.codes_fd):
            return original_write(fd, payload)
        attempts += 1
        # Fail promptly if the implementation regresses into a retry loop.
        if attempts > 1:
            raise AssertionError("a zero-length write was retried")
        return 0

    monkeypatch.setattr(os, "write", zero_write)
    previous = sys.getprofile()
    try:
        sys.setprofile(recorder.profile)
        for _ in range(5):
            leaf()
    finally:
        sys.setprofile(previous)
        recorder.close()
    meta = json.loads((recorder.out / f"call-meta.{recorder.pid}.json").read_text())
    assert attempts == 1
    assert meta["io_failed"] is True
    assert "OSError" in meta["errors"]
    assert meta["bytes"] == recorder.event_path.stat().st_size == recorder.code_path.stat().st_size == 0


@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork is unavailable")
def test_install_stops_child_profiling_and_closes_inherited_trace_fds(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    runner = project / "runner.py"
    output = tmp_path / "trace"
    child_result = tmp_path / "child.json"
    runner.write_text(f"""
import json, os, sys
from scar.trace.call_edges import install
recorder = install({str(output)!r}, {str(project)!r})
def child_only():
    return None
child = os.fork()
if child == 0:
    child_only()
    closed_fds = []
    for fd in (recorder.events_fd, recorder.codes_fd):
        try:
            os.fstat(fd)
        except OSError:
            closed_fds.append(fd)
    with open({str(child_result)!r}, 'w') as stream:
        json.dump({{'unprofiled': sys.getprofile() is None, 'closed': recorder.closed,
                   'closed_fds': len(closed_fds)}}, stream)
    os._exit(0)
_, status = os.waitpid(child, 0)
assert os.waitstatus_to_exitcode(status) == 0
""", encoding="utf-8")
    environment = os.environ.copy()
    for name in ("SCAR_TRACE_DIR", "SCAR_OPTIMIZE", "SCAR_CALL_TRACE_OWNER_PID", "SCAR_RESOURCE_SAMPLER"):
        environment.pop(name, None)
    repository = Path(__file__).resolve().parents[2]
    environment["PYTHONPATH"] = str(repository) + os.pathsep + environment.get("PYTHONPATH", "")
    completed = subprocess.run([sys.executable, str(runner)], env=environment,
                               capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(child_result.read_text()) == {"unprofiled": True, "closed": True, "closed_fds": 2}
    metadata_files = list(output.glob("call-meta.*.json"))
    assert len(metadata_files) == 1
    metadata = json.loads(metadata_files[0].read_text())
    codes = {code["key"]: code for code in map(json.loads, (output / f"call-codes.{metadata['process_id']}.jsonl").read_text().splitlines())}
    assert all(code["qualname"] != "child_only" for code in codes.values())
