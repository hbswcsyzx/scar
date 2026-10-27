"""The public source archive entry reads code without executing the target."""
import json
import subprocess
import sys


def test_inventory_to_source_archive_uses_original_graphs_and_refuses_overwrite(tmp_path):
    source = tmp_path / "application.py"
    source.write_text('raise RuntimeError("source must never execute")\n'
                      'def evaluate(x):\n'
                      '    y = x + 1\n'
                      '    for i in range(2):\n'
                      '        y = y + i\n'
                      '    return y\n')
    report = tmp_path / "inventory.json.gz"
    inventory = subprocess.run([sys.executable, "-m", "scar.cli", "inventory-program", str(source),
        "--project-root", str(tmp_path), "--out", str(report)], text=True, capture_output=True)
    assert inventory.returncode == 0, inventory.stderr + inventory.stdout
    original_source, original_inventory = source.read_bytes(), report.read_bytes()
    archive = tmp_path / "source-graphs"
    command = [sys.executable, "-m", "scar.cli", "source-layers", "--inventory", str(report), "--out", str(archive)]
    result = subprocess.run(command, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr + result.stdout
    receipt = json.loads(result.stdout)
    assert receipt["complete"] and receipt["whole_program_graph_established"] is False
    from scar.analysis.source_layers import load_source_layers
    view = load_source_layers(archive, str(source))
    assert view.semantics.operations and view.control.nodes
    assert any(operation.operands for operation in view.semantics.operations.values())
    assert any(edge.kind.value == "loop_backedge" for edge in view.control.edges.values())
    repeat = subprocess.run(command, text=True, capture_output=True)
    assert repeat.returncode != 0
    assert source.read_bytes() == original_source and report.read_bytes() == original_inventory


def test_invalid_source_archive_budget_does_not_create_output(tmp_path):
    destination = tmp_path / "archive"
    result = subprocess.run([sys.executable, "-m", "scar.cli", "source-layers",
        "--inventory", str(tmp_path / "absent.json"), "--out", str(destination),
        "--max-files", "0"], text=True, capture_output=True)
    assert result.returncode != 0 and not destination.exists()
