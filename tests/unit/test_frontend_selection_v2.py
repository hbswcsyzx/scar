from pathlib import Path

import pytest

from scar.ir.frontend_v2 import build_semantic, build_semantic_files
from scar.ir.v2 import OperationKind, canonical_json


def test_explicit_selection_deduplicates_sorts_and_never_executes(tmp_path):
    marker = tmp_path / "executed"
    first = tmp_path / "a.py"
    second = tmp_path / "b.py"
    first.write_text(f"open({str(marker)!r}, 'w').write('bad')\n")
    second.write_text("x = 2\n")
    (tmp_path / "unselected.py").write_text("not valid Python!\n")
    result = build_semantic_files((second, first, second), tmp_path)
    assert result.coverage["files"] == [str(first), str(second)]
    assert result.coverage["selection_scope"] == "explicit_files_not_reachability"
    assert not result.coverage["target_executed"]
    assert not marker.exists()
    assert canonical_json(result.graph) == canonical_json(build_semantic_files(("b.py", "a.py"), tmp_path).graph)


def test_unselected_imported_module_remains_an_opaque_boundary(tmp_path):
    selected = tmp_path / "app.py"
    selected.write_text("import dependency\nresult = dependency.compute(1)\n")
    (tmp_path / "dependency.py").write_text("this file deliberately cannot parse!\n")
    result = build_semantic_files((selected,), tmp_path)
    external = next(module for module in result.graph.modules.values() if module.name == "dependency")
    assert external.initializer is None
    calls = [operation for operation in result.graph.definitions.values() if operation.label == "Call"]
    assert calls[0].kind is OperationKind.OPAQUE
    assert "target_candidate" not in calls[0].metadata


def test_selected_source_identity_matches_whole_project_snapshot(tmp_path):
    first, second = tmp_path / "a.py", tmp_path / "b.py"
    first.write_text("x = 1\n")
    second.write_text("y = 2\n")
    whole = build_semantic(tmp_path)
    selected = build_semantic_files((first,), tmp_path)
    atom_ids = {atom.id for atom in whole.graph.source_atoms.values() if atom.reference.path == str(first)}
    assert set(selected.graph.source_atoms) == atom_ids


@pytest.mark.parametrize("selection", [[], ["missing.py"], ["text.txt"], ["."], "one.py"])
def test_explicit_selection_rejects_missing_non_python_and_empty_inputs(tmp_path, selection):
    (tmp_path / "text.txt").write_text("data")
    with pytest.raises(ValueError):
        build_semantic_files(selection, tmp_path)


def test_explicit_selection_rejects_outside_root_and_symlink_escape(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("x = 1\n")
    link = root / "linked.py"
    link.symlink_to(outside)
    for path in (outside, link):
        with pytest.raises(ValueError, match="within project_root"):
            build_semantic_files((path,), root)
