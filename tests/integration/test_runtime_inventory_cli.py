"""Public runtime-seeded inventory, replay and input overwrite protection."""
import gzip
import json
import subprocess
import sys

import pytest

from tests.unit.test_runtime_inventory_adversarial import runtime_project


def run(*arguments):
    return subprocess.run([sys.executable, "-m", "scar.cli", *map(str, arguments)],
                          text=True, capture_output=True, timeout=45)


@pytest.mark.parametrize("trace_form", ("directory", "jsonl", "gzip"))
def test_cli_dynamic_sources_and_unobserved_branch_are_replayable(runtime_project, tmp_path, trace_form):
    root, entry, payload, trace, marker = runtime_project
    selected_trace = trace
    if trace_form == "directory":
        selected_trace = trace.parent
    elif trace_form == "gzip":
        selected_trace = trace.with_suffix(".jsonl.gz")
        with gzip.open(selected_trace, "wb") as stream:
            stream.write(trace.read_bytes())
    output = tmp_path / "runtime-inventory.json.gz"
    built = run("inventory-program", entry, "--project-root", root, "--trace", selected_trace,
                "--out", output, "--max-trace-records", 1000, "--max-compile-attempts", 20)
    assert built.returncode == 0, built.stdout + built.stderr
    with gzip.open(output, "rt") as stream:
        document = json.load(stream)
    assert document["schema_version"] == 2
    paths = {file["snapshot"]["path"] for file in document["files"]}
    assert paths == {str(entry), str(payload), str(root / "helper.py"), str(root / "dormant.py")}
    assert document["target_executed"] is False
    checked = run("check-inventory", output)
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert json.loads(checked.stdout)["status"] == "REPLAYED"
    limited = run("check-inventory", output, "--max-trace-records", 1)
    assert limited.returncode == 2
    assert not marker.exists()


@pytest.mark.parametrize("protected,alias", (("trace", "direct"), ("trace", "hardlink"),
                                           ("trace", "symlink"), ("source", "hardlink")))
def test_cli_runtime_inventory_cannot_overwrite_trace_or_discovered_source(runtime_project, tmp_path, protected, alias):
    root, entry, payload, trace, marker = runtime_project
    target = trace if protected == "trace" else payload
    before = target.read_bytes()
    output = target if alias == "direct" else tmp_path / "report.json"
    if alias == "hardlink":
        output.hardlink_to(target)
    elif alias == "symlink":
        output.symlink_to(target)
    process = run("inventory-program", entry, "--project-root", root, "--trace", trace, "--out", output)
    assert process.returncode == 2, process.stdout + process.stderr
    assert target.read_bytes() == before
    assert not marker.exists()
