"""Independent public source facts, not an inferred optimization approval."""
import gzip
import json
import subprocess
import sys

from scar.analysis.proof_models_report_v2 import report_source_proof_models


def source_fixture(tmp_path):
    source = tmp_path / "program.py"
    sentinel = tmp_path / "executed"
    source.write_text(
        f"open({str(sentinel)!r}, 'w').write('executed')\n"
        "def stage(left, right, values):\n"
        "    alias = left\n"
        "    same = left is right\n"
        "    different = left is not right\n"
        "    for item in values:\n"
        "        if item is left:\n"
        "            continue\n"
        "        break\n"
        "    try:\n"
        "        callback(left)\n"
        "    finally:\n"
        "        cleanup()\n"
        "    return alias, same, different\n"
        "raise RuntimeError('never execute this source')\n"
    )
    return source, sentinel


def test_public_source_models_cli_preserves_target_and_discloses_no_legality(tmp_path):
    source, sentinel = source_fixture(tmp_path)
    original = source.read_bytes()
    output = tmp_path / "models.json.gz"
    run = subprocess.run([sys.executable, "-m", "scar.cli", "proof-models-v2", str(source),
                          "--out", str(output)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    report = json.loads(gzip.decompress(output.read_bytes()))
    assert report["schema"] == "scar.source-proof-models-report"
    assert report["decision"] == {"selection_status": "NOT_SELECTED", "cost_status": "PENDING",
                                  "legality_status": "NOT_EVALUATED", "applied": False}
    assert report["summary"]["files"] == 1
    assert report["control_flow"] and report["primitive_semantics"]
    assert report["file_selection"]["import_reachability_proven"] is False
    assert source.read_bytes() == original and not sentinel.exists()
    assert json.loads(run.stdout)["decision"] == report["decision"]


def test_source_proof_models_library_and_cli_match_except_host_timing(tmp_path):
    source, sentinel = source_fixture(tmp_path)
    output = tmp_path / "models.json"
    run = subprocess.run([sys.executable, "-m", "scar.cli", "proof-models-v2", str(source),
                          "--out", str(output)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    report = json.loads(output.read_text())
    library = report_source_proof_models(source)
    report.pop("measurement")
    library.pop("measurement")
    assert report == library
    assert not sentinel.exists()


def test_new_static_models_do_not_import_torch_or_create_gpu_context(tmp_path):
    source, sentinel = source_fixture(tmp_path)
    output = tmp_path / "models.json"
    script = "import sys\nfrom scar.cli import main\nassert 'torch' not in sys.modules\nmain()\nassert 'torch' not in sys.modules\n"
    run = subprocess.run([sys.executable, "-c", script, "proof-models-v2", str(source),
                          "--out", str(output)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert output.exists() and not sentinel.exists()


def test_public_source_models_strict_roundtrip_replays_and_rejects_changed_source(tmp_path):
    from scar.ir.control_flow_v2 import SourceControlFlowGraph
    from scar.analysis.control_flow_v2 import validate_source_control_flow
    from scar.analysis.primitive_semantics_v2 import PrimitiveSemanticsReport
    from scar.ir.semantics_v2 import SourceSemanticsGraph
    from scar.ir.v2.codec import semantic_from_dict
    source, sentinel = source_fixture(tmp_path)
    report = report_source_proof_models(source)
    semantic = semantic_from_dict(report["semantic"])
    overlay = SourceSemanticsGraph.from_dict(report["source_semantics"], semantic)
    control = SourceControlFlowGraph.from_dict(report["control_flow"])
    assert validate_source_control_flow(control, semantic, overlay)["valid"]
    primitive = PrimitiveSemanticsReport.from_dict(report["primitive_semantics"],
        semantic=semantic, source_semantics=overlay)
    assert primitive.to_dict() == report["primitive_semantics"]
    assert primitive.summary()["certificate_count"] == 3
    source.write_text(source.read_text().replace("left is right", "left == right"))
    assert not validate_source_control_flow(control, semantic, overlay)["valid"]
    assert not primitive.validate()["valid"]
    assert not sentinel.exists()
