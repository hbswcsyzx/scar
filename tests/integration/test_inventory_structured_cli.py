"""CLI v7 source/raw-calls recovery and replay; no workload-specific input."""
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def cli(*arguments, cwd=None):
    environment = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
    for name in ("SCAR_TRACE_DIR", "SCAR_TRACE_CALL_EDGES", "SCAR_CALL_TRACE_OWNER_PID", "SCAR_CALL_OPERANDS"):
        environment.pop(name, None)
    return subprocess.run([sys.executable, "-m", "scar.cli", *map(str, arguments)],
                          cwd=cwd or ROOT, env=environment, capture_output=True, text=True, timeout=90)


def read(path):
    with gzip.open(path, "rt") if path.suffix == ".gz" else path.open() as stream:
        return json.load(stream)


def test_public_structured_source_inventory_does_not_execute_and_replays(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    marker = project / "executed"
    entry = project / "entry.py"
    entry.write_text(
        f"open({str(marker)!r}, 'w').write('executed')\n"
        "def f(items):\n"
        "    result = None\n"
        "    for item in items:\n        result = item\n"
        "    return result\n",
        encoding="utf-8",
    )
    output = tmp_path / "source.json.gz"
    process = cli("inventory-program", entry, "--project-root", project,
                  "--body-profile", "structured", "--out", output)
    assert process.returncode == 0, process.stdout + process.stderr
    document = read(output)
    assert document["schema_version"] == 7
    assert document["summary"]["structured"]["loops"] == 1
    assert document["call_sources"] is document["call_source_scope"] is None
    replay = cli("check-inventory", output)
    assert replay.returncode == 0, replay.stdout + replay.stderr
    assert not marker.exists()
    archive = tmp_path / "source-layers"
    retained = cli("source-layers", "--inventory", output, "--out", archive)
    assert retained.returncode == 0, retained.stdout + retained.stderr
    assert read(archive / "index.json")["input"]["schema_version"] == 7


def test_actual_call_trace_enters_structured_inventory_and_replays(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    entry = project / "entry.py"
    entry.write_text(
        "def leaf(left, right):\n    return left\n"
        "def walk(items, shared):\n"
        "    result = shared\n"
        "    for item in items:\n        result = leaf(shared, shared)\n"
        "    return result\n"
        "shared = object()\nassert walk([1, 2], shared) is shared\n",
        encoding="utf-8",
    )
    trace = tmp_path / "trace"
    captured = cli("trace", "--calls-only", "--project-root", project, "--out", trace,
                   "--", sys.executable, entry, cwd=project)
    assert captured.returncode == 0, captured.stdout + captured.stderr
    output = tmp_path / "calls.json.gz"
    process = cli("inventory-program", entry, "--project-root", project, "--calls", trace,
                  "--body-profile", "structured", "--out", output)
    assert process.returncode == 0, process.stdout + process.stderr
    document = read(output)
    assert document["schema_version"] == 7 and document["runtime_scope"] is None
    admissions = document["call_source_scope"]["admissions"]
    assert len(admissions) == 2 and all(item["status"] == "CORE_LINKED" for item in admissions)
    assert len(document["structured"]) == 2
    assert json.loads(process.stdout)["source_analysis_measurements"]["source_prepare_max_per_path"] == 1
    replay = cli("check-inventory", output)
    assert replay.returncode == 0, replay.stdout + replay.stderr
    original = cli("inventory-program", entry, "--project-root", project, "--calls", trace,
                   "--out", tmp_path / "old.json")
    assert original.returncode == 0, original.stdout + original.stderr
    assert read(tmp_path / "old.json")["schema_version"] == 6
