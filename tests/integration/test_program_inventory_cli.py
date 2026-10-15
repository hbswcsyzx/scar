"""One entry discovers and models multiple source bodies without manual IR."""
import gzip
import json
import subprocess
import sys

import pytest

from scar.analysis.program_inventory import ProgramInventory, inventory_program
from scar.ir.program.discovery import DiscoveryGapKind


def run(*arguments):
    return subprocess.run([sys.executable, "-m", "scar.cli", *map(str, arguments)],
                          text=True, capture_output=True, timeout=40)


def fixture(tmp_path):
    marker = tmp_path / "executed"
    helper = tmp_path / "helper.py"
    helper.write_text(f"open({str(marker)!r}, 'w').write('executed')\ndef identity(value):\n    return value\n")
    entry = tmp_path / "entry.py"
    entry.write_text("from helper import identity\ndef first(x):\n    return identity(x)\ndef second(x):\n    return x\n")
    return entry, helper, marker


@pytest.mark.parametrize("suffix", [".json", ".json.gz"])
def test_public_entry_automatically_discovers_bodies_and_persists_call_witnesses(tmp_path, suffix):
    entry, helper, marker = fixture(tmp_path)
    before = {path:path.read_bytes() for path in (entry, helper)}
    output = tmp_path / ("inventory" + suffix)
    process = run("inventory-program", entry, "--project-root", tmp_path, "--out", output)
    assert process.returncode == 0, process.stdout + process.stderr
    summary = json.loads(process.stdout)["summary"]
    assert summary["source_files"] == 2
    assert summary["definitions"] == 3
    assert summary["body_statuses"]["LOWERED_WITH_GAPS"] == 3
    assert summary["cross_file_call_witnesses"] >= 1
    assert summary["whole_program_graph_established"] is False
    if suffix.endswith(".gz"):
        with gzip.open(output, "rt") as stream:
            document = json.load(stream)
    else:
        document = json.loads(output.read_text())
    assert ProgramInventory.from_dict(document).to_dict() == document
    replay = run("check-inventory", output)
    assert replay.returncode == 0, replay.stdout + replay.stderr
    assert json.loads(replay.stdout)["status"] == "REPLAYED"
    assert not marker.exists()
    assert all(path.read_bytes() == content for path, content in before.items())


@pytest.mark.parametrize("link", ["hardlink", "symlink"])
def test_report_output_cannot_overwrite_a_discovered_dependency(tmp_path, link):
    entry, helper, marker = fixture(tmp_path)
    output = tmp_path / "report.json"
    if link == "hardlink":
        output.hardlink_to(helper)
    else:
        output.symlink_to(helper)
    before = helper.read_bytes()
    result = run("inventory-program", entry, "--out", output)
    assert result.returncode == 2
    assert helper.read_bytes() == before
    assert not marker.exists()


def test_report_gaps_and_budget_are_replayed_without_claiming_full_coverage(tmp_path):
    entry, helper, marker = fixture(tmp_path)
    output = tmp_path / "limited.json.gz"
    result = run("inventory-program", entry, "--out", output, "--max-files", 1)
    assert result.returncode == 0, result.stdout + result.stderr
    with gzip.open(output, "rt") as stream:
        document = json.load(stream)
    assert any(gap["kind"] == "FILE_BUDGET" and gap["path"] == str(helper)
               for gap in document["discovery"]["gaps"])
    assert document["summary"]["whole_program_graph_established"] is False
    assert run("check-inventory", output).returncode == 0
    assert not marker.exists()


@pytest.mark.parametrize("field", ["target_executed", "transformation_authorized"])
def test_cli_rejects_forged_authority(tmp_path, field):
    entry, _, _ = fixture(tmp_path)
    document = inventory_program(entry).to_dict()
    document[field] = True
    output = tmp_path / "forged.json"
    output.write_text(json.dumps(document))
    result = run("check-inventory", output)
    assert result.returncode == 2
    assert json.loads(result.stdout)["status"] == "INVALID"


def test_strict_cli_json_rejects_duplicate_keys(tmp_path):
    report = tmp_path / "duplicate.json"
    report.write_text('{"schema":"scar.program-inventory","schema":"forged"}')
    result = run("check-inventory", report)
    assert result.returncode == 2
    assert "duplicate" in json.loads(result.stdout)["errors"][0]


def test_dynamic_source_loader_remains_located_without_executing_or_claiming_loaded_file(tmp_path):
    target = tmp_path / "payload.py"
    marker = tmp_path / "executed"
    target.write_text(f"open({str(marker)!r}, 'w').write('executed')\n")
    entry = tmp_path / "entry.py"
    entry.write_text("def launch(path):\n    exec(compile(path.read_text(), str(path), 'exec'))\n")
    result = inventory_program(entry)
    assert str(target) not in {file.snapshot.path for file in result.files}
    assert any(gap.kind is DiscoveryGapKind.DYNAMIC_EXECUTION and gap.source.start_line == 2
               for gap in result.discovery.gaps)
    assert not marker.exists()


def test_unaliased_dotted_import_does_not_bind_parent_attribute_to_child_body(tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("def work(x):\n    return 1\n")
    (package / "child.py").write_text("def work(x):\n    return 2\n")
    entry = tmp_path / "entry.py"
    entry.write_text("import pkg.child\ndef f(x):\n    return pkg.work(x)\n")
    result = inventory_program(entry)
    file = next(file for file in result.files if file.snapshot.path == str(entry))
    call, = file.calls
    child_ids = {definition.id for file in result.files if file.snapshot.path.endswith("child.py")
                 for definition in file.definitions}
    assert not child_ids.intersection(call.candidates)
