"""Public report-only import path analysis with an arbitrary external testcase."""
import gzip
import json
import subprocess
import sys

from scar.analysis.import_report_v2 import report_import_values


def package(tmp_path, name="fixture_pkg", side_effect=False):
    pkg = tmp_path / name
    pkg.mkdir()
    (pkg / "__init__.py").write_text("from .values import TABLE as PUBLIC\n")
    marker = tmp_path / "target_was_executed"
    effect = f"open({str(marker)!r}, 'w').write('executed')\n" if side_effect else ""
    (pkg / "values.py").write_text(effect + "TABLE = ((2, 7), (3, 8))\n")
    source = tmp_path / "program.py"
    source.write_text(f"import {name} as p\nanswer = p.PUBLIC[0][1]\nraise RuntimeError('never execute')\n")
    return source, marker


def test_public_cli_follows_generic_package_without_execution_or_import_deletion(tmp_path):
    source, marker = package(tmp_path, side_effect=True)
    original = {path: path.read_bytes() for path in tmp_path.rglob("*.py")}
    out = tmp_path / "report.json.gz"
    run = subprocess.run([sys.executable, "-m", "scar.cli", "import-values-v2", str(source),
                          "--project-root", str(tmp_path), "--out", str(out)],
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    report = json.loads(gzip.decompress(out.read_bytes()))
    assert report["source_replay"]["valid"]
    assert report["summary"]["conditional_binding_uses"] >= 1
    assert report["summary"]["boundary_kinds"]["import"] >= 2
    assert report["decision"] == {"selection_status": "NOT_SELECTED", "cost_status": "PENDING",
                                  "applied": False, "import_deletion": "NOT_PROVEN"}
    from scar.analysis.import_values_v2 import ImportValueReport
    from scar.ir.semantics_v2 import SourceSemanticsGraph
    from scar.ir.v2.codec import semantic_from_dict
    semantic = semantic_from_dict(report["semantic"])
    model = SourceSemanticsGraph.from_dict(report["model"], semantic)
    restored = ImportValueReport.from_dict(report["import_values"], semantic=semantic, source_semantics=model)
    assert restored.to_dict() == report["import_values"]
    assert not marker.exists()
    assert original == {path: path.read_bytes() for path in tmp_path.rglob("*.py")}


def test_cli_and_library_reports_agree_and_are_deterministic(tmp_path):
    source, _ = package(tmp_path)
    out = tmp_path / "report.json"
    run = subprocess.run([sys.executable, "-m", "scar.cli", "import-values-v2", str(source),
                          "--project-root", str(tmp_path), "--out", str(out)],
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    command = json.loads(out.read_text())
    library = report_import_values(source, project_root=tmp_path)
    command.pop("measurement")
    library.pop("measurement")
    assert command == library
    assert command["summary"]["selected_transformations"] == 0


def test_invalid_budget_does_not_create_output(tmp_path):
    source, marker = package(tmp_path)
    output = tmp_path / "invalid.json"
    run = subprocess.run([sys.executable, "-m", "scar.cli", "import-values-v2", str(source),
                          "--max-nodes", "0", "--out", str(output)], capture_output=True, text=True)
    assert run.returncode != 0
    assert not output.exists() and not marker.exists()


def test_whole_project_scan_is_disclosed_and_does_not_import_unused_code(tmp_path):
    source, marker = package(tmp_path)
    unused = tmp_path / "unused.py"
    unused.write_text(f"open({str(marker)!r}, 'w').write('unused')\n")
    report = report_import_values(source, project_root=tmp_path)
    assert report["summary"]["files"] == 4
    assert report["file_selection"]["mode"] == "PROJECT_TREE"
    assert report["file_selection"]["import_reachability_proven"] is False
    assert not marker.exists()
    assert report["decision"]["applied"] is False


def test_explicit_caller_budget_is_preserved_without_default_verifier_escalation(tmp_path):
    from scar.analysis.constants_v2 import EvaluationBudget
    source, _ = package(tmp_path)
    report = report_import_values(source, project_root=tmp_path,
                                 budget=EvaluationBudget(max_int_bits=8192))
    assert report["import_values"]["budget"]["max_int_bits"] == 8192
    assert report["decision"]["applied"] is False


def test_guidance_targets_outer_index_and_retains_the_full_import_path(tmp_path):
    from scar.analysis.import_values_v2 import ImportStepKind, ImportValueReport, ImportValueStatus
    from scar.ir.semantics_v2 import Opcode, SourceSemanticsGraph
    from scar.ir.v2.codec import semantic_from_dict
    source, _ = package(tmp_path)
    report = report_import_values(source, project_root=tmp_path)
    semantic = semantic_from_dict(report["semantic"])
    model = SourceSemanticsGraph.from_dict(report["model"], semantic)
    values = ImportValueReport.from_dict(report["import_values"], semantic=semantic, source_semantics=model)
    outer = max((op for op in model.operations.values()
                 if op.opcode is Opcode.INDEX and op.source.path == str(source)),
                key=lambda op: op.source.end_column)
    fact = values.facts[outer.result]
    assert fact.status is ImportValueStatus.CONDITIONAL
    assert fact.literal.to_python() == 7
    guidance = values.guidance[outer.result]
    assert guidance.literal.to_python() == 7 and guidance.import_deletion.value == "NOT_PROVEN"
    proof = values.provenances[fact.provenance_id]
    kinds = [step.kind for step in proof.steps]
    assert {ImportStepKind.IMPORT_MODULE, ImportStepKind.REEXPORT, ImportStepKind.ATTRIBUTE} <= set(kinds)
    assert kinds.count(ImportStepKind.INDEX) == 2
    assert all(model.operations[model.values[identifier].producer].opcode is not Opcode.LITERAL
               for identifier in values.guidance)


def test_static_cli_does_not_load_torch_or_probe_cuda_for_unrelated_micro_workload(tmp_path):
    source, marker = package(tmp_path)
    output = tmp_path / "pure-static.json"
    script = ("import sys\nfrom scar.cli import main\n"
              "assert 'torch' not in sys.modules\n"
              "main()\nassert 'torch' not in sys.modules\n")
    run = subprocess.run([sys.executable, "-c", script, "import-values-v2", str(source),
                          "--project-root", str(tmp_path), "--out", str(output)],
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert output.exists() and not marker.exists()


def test_module_initializer_attribute_cannot_read_a_future_export_version(tmp_path):
    from scar.analysis.import_values_v2 import ImportValueStatus, resolve_import_values
    from scar.analysis.source_semantics_v2 import extract_source_semantics
    from scar.ir.frontend_v2 import build_semantic
    from scar.ir.semantics_v2 import Opcode
    pkg = tmp_path / "temporal_pkg"
    pkg.mkdir()
    initializer = pkg / "__init__.py"
    initializer.write_text("import temporal_pkg as p\nX = 1\nY = p.X\nX = 2\n")
    source = tmp_path / "program.py"
    source.write_text("import temporal_pkg\n")
    semantic = build_semantic(source, project_root=tmp_path).graph
    model = extract_source_semantics(semantic)
    attribute = next(op for op in model.operations.values() if op.opcode is Opcode.ATTRIBUTE)
    report = resolve_import_values(semantic, model, targets=(attribute.result,))
    fact = report.facts[attribute.result]
    if fact.status in {ImportValueStatus.CONDITIONAL, ImportValueStatus.EXACT_BUILTIN_LITERAL}:
        assert fact.literal.to_python() == 1, "The lookup occurs before the second X binding"
    else:
        assert fact.gaps, "Unsupported partial initialization must be diagnosed"
