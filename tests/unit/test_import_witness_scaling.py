"""Reexport path scaling and output budgets through the actual source pipeline."""
from pathlib import Path

import pytest

from scar.analysis.program_inventory import ProgramInventory, inventory_program


def write(root, name, source):
    path = root / name
    path.write_text(source, encoding="utf-8")
    return path


def entry_file(result, path):
    return next(file for file in result.files if file.snapshot.path == str(path))


@pytest.mark.parametrize("depth", (3, 12, 24))
def test_duplicate_reexports_keep_one_witness_without_losing_discovery_edges(tmp_path, depth):
    entry = write(tmp_path, "entry.py",
                  "from layer0 import chosen\ndef invoke(value):\n    return chosen(value)\n")
    for index in range(depth):
        write(tmp_path, f"layer{index}.py",
              f"from layer{index + 1} import chosen\n"
              f"from layer{index + 1} import chosen\n")
    leaf = write(tmp_path, f"layer{depth}.py", "def chosen(value):\n    return value\n")
    result = inventory_program(entry, project_root=tmp_path, source_roots=(tmp_path,),
                               max_lowered_bodies=1)
    assert len(result.files) == depth + 2
    assert len(result.discovery.imports) == 2 * depth + 1
    for index in range(depth):
        edges = [edge for edge in result.discovery.imports
                 if edge.source.path == str(tmp_path / f"layer{index}.py")]
        assert len(edges) == 2
        assert {edge.source.start_line for edge in edges} == {1, 2}
        assert len({edge.source.atom_id for edge in edges}) == 2
        assert all(any(candidate.path == str(tmp_path / f"layer{index + 1}.py")
                       for candidate in edge.candidates) for edge in edges)
    file = entry_file(result, entry)
    call, = file.calls
    witness, = call.candidate_witnesses
    assert call.candidates == (witness.definition,)
    assert witness.target_source.path == str(leaf)
    leaf_file = entry_file(result, leaf)
    assert witness.definition == leaf_file.definitions[0].id
    assert len(witness.through_imports) == depth + 1
    assert [Path(source.path).name for source in witness.through_imports] == [
        "entry.py", *(f"layer{index}.py" for index in range(depth))]
    assert all(source.start_line == 1 for source in witness.through_imports)
    assert set(witness.through_imports) <= {edge.source for edge in result.discovery.imports}
    assert not any("witness budget" in gap.detail for item in result.files for gap in item.gaps)
    # Source inventory remains candidate evidence, even after path compression.
    assert witness.conditions
    assert result.summary()["runtime_reachability_established"] is False
    for body in file.bodies:
        if body.graph is not None:
            assert all(operation.callee is None for operation in body.graph.operations)


@pytest.mark.parametrize("cap", (2, 4))
def test_witness_budget_is_global_across_targets_and_calls_and_reports_omissions(tmp_path, cap):
    entry = write(tmp_path, "entry.py", """from library import selected
def invoke(value):
    first = selected(value)
    return selected(first)
""")
    # Three distinct source definitions retain candidate identity; a repeated
    # spelling must not collapse them into one body before applying the cap.
    write(tmp_path, "library.py", """def selected(value):
    return value
def selected(value):
    return None
def selected(value):
    return 1
""")
    result = inventory_program(entry, project_root=tmp_path, source_roots=(tmp_path,),
                               max_call_witnesses=cap)
    file = entry_file(result, entry)
    assert len(file.calls) == 2
    assert sum(len(call.candidate_witnesses) for item in result.files for call in item.calls) == cap
    assert [len(call.candidate_witnesses) for call in file.calls] == [min(3, cap), max(0, cap - 3)]
    omitted = [call for index, call in enumerate(file.calls)
               if len(call.candidate_witnesses) < 3]
    issues = [gap for gap in file.gaps if "witness budget" in gap.detail]
    assert issues
    assert {call.source for call in omitted} <= {gap.source for gap in issues}
    for call in file.calls:
        assert call.candidates == tuple(witness.definition for witness in call.candidate_witnesses)
        assert len(set(call.candidates)) == len(call.candidates)
    assert len(result.discovery.imports) == 1
    library = entry_file(result, tmp_path / "library.py")
    assert len(library.definitions) == 3
    # Replay has its own upper bound and reproduces the same bounded witnesses.
    document = result.to_dict()
    assert ProgramInventory.from_dict(document, max_call_witnesses=cap).to_dict() == document
    with pytest.raises(ValueError, match="independent verifier budget"):
        ProgramInventory.from_dict(document, max_call_witnesses=cap - 1)
