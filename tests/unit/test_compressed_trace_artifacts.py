"""Archiving trace bytes preserves ingestion and content-based identities."""
import gzip
import json
from pathlib import Path

import pytest

from scar.ir import Event
from scar.trace.cuda import profiler_activities
from scar.trace.normalize_v2 import normalize_trace
from scar.trace.reader import load


def archive(path, payload):
    path.write_bytes(payload)
    target = Path(str(path) + ".gz")
    with gzip.open(target, "wb") as stream:
        stream.write(payload)
    return target


def event_payload():
    return (json.dumps(Event(kind="python_call", ts_ns=100, invocation_id=1,
                             code_id="function:v1", metadata={"process_id": 1, "thread_id": 1}).as_dict())
            + "\n\n" + json.dumps(Event(kind="python_return", ts_ns=200, invocation_id=1,
                                         code_id="function:v1", metadata={"process_id": 1, "thread_id": 1}).as_dict())
            + "\n").encode()


@pytest.mark.parametrize("input_form", ("directory", "original_name", "archive_name"))
def test_reader_automatically_loads_archived_events_without_whole_file_text_copy(tmp_path, monkeypatch, input_form):
    source = tmp_path / "events.jsonl"
    target = archive(source, event_payload())
    expected = [event.as_dict() for event in load(source).events]
    source.unlink()
    path = {"directory": tmp_path, "original_name": source, "archive_name": target}[input_form]
    def forbid_read_text(*args, **kwargs):
        raise AssertionError("trace reader must iterate its stream")
    monkeypatch.setattr(Path, "read_text", forbid_read_text)
    assert [event.as_dict() for event in load(path).events] == expected


def test_normalizer_uses_decompressed_bytes_for_namespace_and_malformed_line_accounting(tmp_path):
    source = tmp_path / "events.jsonl"
    payload = event_payload() + b'{"broken":\n'
    target = archive(source, payload)
    before = normalize_trace(source)
    source.unlink()
    after = normalize_trace(tmp_path)
    assert before.coverage["raw_records"] == after.coverage["raw_records"]
    assert before.coverage["accounted_records"] == after.coverage["accounted_records"]
    assert before.coverage["status_counts"] == after.coverage["status_counts"]
    assert set(before.bundle.evidence.instances) == set(after.bundle.evidence.instances)
    assert after.coverage["source"] == str(target)


def test_profiler_import_reads_the_same_physical_copy_from_a_gzip_archive(tmp_path):
    source = tmp_path / "torch-profiler.json"
    payload = json.dumps({"traceEvents": [
        {"ph": "X", "cat": "gpu_memcpy", "name": "Memcpy HtoD", "ts": 1, "dur": 2,
         "args": {"bytes": 64, "stream": 7, "device": 0}},
    ]}).encode()
    archive(source, payload)
    before = [event.as_dict() for event in profiler_activities(source, process_id=1)]
    source.unlink()
    assert [event.as_dict() for event in profiler_activities(source, process_id=1)] == before


def test_corrupt_archive_is_reported_without_creating_a_restored_copy(tmp_path):
    source = tmp_path / "events.jsonl"
    Path(str(source) + ".gz").write_bytes(b"corrupt gzip")
    with pytest.raises(OSError):
        load(tmp_path)
    assert not source.exists()
