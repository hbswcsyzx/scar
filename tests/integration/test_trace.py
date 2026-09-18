import json
import subprocess
import sys
from pathlib import Path


def test_trace_and_analysis(tmp_path):
    out = tmp_path / "trace"
    root = Path(__file__).resolve().parents[2]
    program = tmp_path / "program.py"
    program.write_text("from scar.workloads.micro import run\nrun(3)\n")
    cmd = [sys.executable, "-m", "scar.cli", "trace", "--out", str(out), "--",
           sys.executable, str(program)]
    result = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (out / "events.jsonl").exists()
    assert list(out.glob("metadata.*.json"))
    assert list(out.glob("torch-profiler.*.json"))
    events = [json.loads(line) for line in (out / "events.jsonl").read_text().splitlines() if line.strip()]
    # The generic runtime should expose both control/module spans and the
    # profiler's operator aggregates for an arbitrary PyTorch workload.
    assert any(event["kind"] == "module_call" for event in events)
    python_calls = [event for event in events if event["kind"] == "python_call"]
    python_returns = [event for event in events if event["kind"] == "python_return"]
    assert python_calls and python_returns
    assert all(event["invocation_id"] is not None for event in python_returns)
    assert all("pycode-sha256:" in event["code_id"] for event in events
               if event["kind"] == "module_call" and event["code_id"])
    aggregate_ops = [event for event in events if event["kind"] == "torch_op"]
    assert aggregate_ops
    assert all("device_memory_usage" in event["resource"] for event in aggregate_ops)
    transfers = [event for event in events if event["kind"] == "transfer"]
    assert all("physical" in event["metadata"] for event in transfers)
    analyzed = subprocess.run([sys.executable, "-m", "scar.cli", "analyze", str(out),
                               "--link-source", str(tmp_path)],
                              cwd=root, capture_output=True, text=True)
    assert analyzed.returncode == 0, analyzed.stderr
    report = json.loads((out / "report.json").read_text())
    assert report["events"] > 0
    assert "opportunities" in report
    assert report["correspondence"]["source_files"] == 1
    assert report["correspondence"]["linked_events"] > 0
    assert report["correspondence"]["by_confidence"]
    graph_document = json.loads((out / "graph.json").read_text())
    assert any(edge["relation"] == "dynamic_instance"
               for edge in graph_document["edges"])
    summary = json.loads((out / "summary.json").read_text())
    assert summary["events"] == len(events)
    assert summary["transformation_applied"] is False
    assert summary["policy"]["closed_world"] is False
    assert summary["graph"]["nodes"] > 0


def test_trace_captures_user_calls_in_new_threads(tmp_path):
    out = tmp_path / "thread-trace"
    root = Path(__file__).resolve().parents[2]
    program = tmp_path / "thread_program.py"
    program.write_text(
        "import threading\n"
        "def worker():\n"
        "    print('worker')\n"
        "thread = threading.Thread(target=worker)\n"
        "thread.start()\n"
        "thread.join()\n"
    )
    cmd = [sys.executable, "-m", "scar.cli", "trace", "--out", str(out), "--",
           sys.executable, str(program)]
    result = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    events = [json.loads(line) for line in (out / "events.jsonl").read_text().splitlines()
              if line.strip()]
    worker_calls = [event for event in events
                    if event["kind"] == "python_call"
                    and event["metadata"].get("function") == "worker"]
    assert worker_calls
    assert any(event["metadata"].get("thread_id") != worker_calls[0]["metadata"].get("thread_id")
               for event in events if event["kind"] == "python_call"
               and event["metadata"].get("function") == "<module>")
    c_calls = [event for event in events if event["kind"] == "python_c_call"
               and event["metadata"].get("c_function") == "print"]
    assert c_calls
