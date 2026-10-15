"""Runtime code candidates retain explicit links into emitted source inventories."""
from copy import deepcopy
import json

import pytest

from scar.analysis import program_inventory as inventory
from scar.analysis.runtime_inventory import RuntimeDefinitionKind
from scar.ir.ids import CodeID
from scar.ir.program.ids import RegionID
from scar.ir.record_codec import encode
from scar.ir.v2.ids import OperationDefinitionID
from tests.unit.test_runtime_inventory_adversarial import runtime_project, with_trace


def test_empty_module_candidate_has_a_snapshot_anchor_without_inventing_a_body(tmp_path):
    source = tmp_path / "empty.py"
    source.write_text("", encoding="utf-8")
    trace = tmp_path / "trace.jsonl"
    trace.write_text(json.dumps({
        "kind": "python_call",
        "code_id": CodeID(str(source), "<module>", 1, None, "unknown").key(),
        "metadata": {"process_id": 1},
    }) + "\n", encoding="utf-8")

    result = inventory.inventory_program(
        source, project_root=tmp_path, source_roots=(tmp_path,), runtime_trace=trace,
    )
    file = result.files[0]
    binding = result.runtime_scope.bindings[0]
    assert file.definitions == file.bodies == file.coverage == ()
    assert len(binding.candidate_definitions) == 1
    assert len(result.runtime_scope.definition_index) == 1
    anchor = result.runtime_scope.definition_index[0]
    assert anchor.definition == binding.candidate_definitions[0]
    assert anchor.kind is RuntimeDefinitionKind.MODULE_INITIALIZER
    assert anchor.qualname == "<module>"
    assert anchor.source_snapshot == binding.source_snapshot == file.snapshot
    assert anchor.source is None
    assert anchor.inventory_definition is None
    assert anchor.core_region is None
    assert binding.witnesses == ()
    assert binding.status.name == "MISSING"
    assert inventory.ProgramInventory.from_dict(result.to_dict()).to_dict() == result.to_dict()


def test_observed_function_links_to_source_definition_body_and_exact_root(runtime_project):
    result = with_trace(runtime_project)
    scope = result.runtime_scope
    payload = runtime_project[2]
    file = next(file for file in result.files if file.snapshot.path == str(payload))
    definition = next(item for item in file.definitions if item.qualname == "compute")
    body = next(item for item in file.bodies if item.definition == definition.id)
    assert body.graph is not None
    binding = next(binding for binding in scope.bindings
                   if CodeID.parse_key(scope.trace.observations[binding.observation_index].code_id).qualname == "compute")
    assert binding.status.name == "VERIFIED" and binding.witnesses
    assert binding.candidate_definitions == (definition.id,)
    index = {anchor.definition: anchor for anchor in scope.definition_index}
    anchor = index[definition.id]
    assert anchor.kind is RuntimeDefinitionKind.SOURCE_DEFINITION
    assert anchor.qualname == "compute"
    assert anchor.source == definition.source
    assert anchor.source_snapshot == file.snapshot == binding.source_snapshot
    assert anchor.inventory_definition == body.definition == definition.id
    assert anchor.core_region == body.graph.root
    assert all(operation.callee is None for operation in body.graph.operations)
    assert scope.summary()["callable_bindings_established"] is False
    assert scope.summary()["effect_equivalence_established"] is False
    for item in scope.bindings:
        for target in item.candidate_definitions:
            assert index[target].source_snapshot == item.source_snapshot
    assert inventory.ProgramInventory.from_dict(result.to_dict()).to_dict() == result.to_dict()


@pytest.mark.parametrize("change", ("candidate", "missing_anchor", "core_region"))
def test_replay_rejects_dangling_or_misdirected_runtime_definition_links(runtime_project, change):
    document = deepcopy(with_trace(runtime_project).to_dict())
    scope = document["runtime_scope"]
    binding = next(item for item in scope["bindings"] if item["candidate_definitions"])
    if change == "candidate":
        binding["candidate_definitions"] = [encode(OperationDefinitionID("review:dangling"))]
    elif change == "missing_anchor":
        target = binding["candidate_definitions"][0]
        scope["definition_index"] = [anchor for anchor in scope["definition_index"]
                                     if anchor["definition"] != target]
    else:
        anchor = next(item for item in scope["definition_index"] if item["core_region"] is not None)
        anchor["core_region"] = encode(RegionID("review:other-region"))

    with pytest.raises(ValueError):
        inventory.ProgramInventory.from_dict(document)


def test_failed_file_clears_definition_links_but_retains_spent_code_witness_work(runtime_project, monkeypatch):
    baseline = with_trace(runtime_project)
    payload = runtime_project[2]
    original = inventory._Inventory.index
    completed = []

    def fail_after_inventory(self):
        result = original(self)
        if self.context.path == payload:
            completed.append(result)
            raise ValueError("review: fail after code witnesses and file indexing")
        return result

    monkeypatch.setattr(inventory._Inventory, "index", fail_after_inventory)
    result = with_trace(runtime_project)
    assert len(completed) == 1
    scope = result.runtime_scope
    bindings = [item for item in scope.bindings if item.source_path == str(payload)]
    assert bindings and any(item.witnesses for item in bindings)
    assert all(item.status.name == "MISSING" and item.candidate_definitions == () for item in bindings)
    assert all(anchor.source_snapshot.path != str(payload) for anchor in scope.definition_index)
    assert scope.compilation_attempts == baseline.runtime_scope.compilation_attempts > 0
    file = next(file for file in result.files if file.snapshot.path == str(payload))
    assert file.definitions == file.bodies == ()
    assert any("review: fail after" in issue.detail for issue in file.gaps)
    indexed = {anchor.definition for anchor in scope.definition_index}
    assert all(target in indexed for item in scope.bindings for target in item.candidate_definitions)
