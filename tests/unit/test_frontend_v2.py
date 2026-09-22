from pathlib import Path

import pytest

from scar.ir.frontend_v2 import build_semantic
from scar.ir.v2 import OperationKind, SemanticRelation, canonical_json


def project(tmp_path, files):
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return build_semantic(tmp_path)


def operations(result, label=None, role=None, module=None):
    return [operation for operation in result.graph.definitions.values()
            if (label is None or operation.label == label)
            and (role is None or operation.metadata.get("role") == role)
            and (module is None or operation.metadata.get("module") == module)]


def binding(result, name, module):
    initializer = next(item.initializer for item in result.graph.modules.values() if item.name == module)
    return next(slot.slot_id for slot in result.graph.slots.values()
                if slot.owner == initializer and slot.name == name)


def test_every_executable_atom_has_owner_including_explicit_opaque_syntax(tmp_path):
    result = project(tmp_path, {"program.py": '''
async def run(manager, source):
    async with manager as handle:
        values = [x + 1 for x in source if x]
        await handle(values)
        match values:
            case [first, *rest]:
                yield first
'''})
    assert result.coverage["source_atoms"] > 15
    assert result.coverage["owned_source_atoms"] == result.coverage["source_atoms"]
    assert result.coverage["unowned_source_atoms"] == 0
    assert result.coverage["opaque_operations"] > 0
    assert all(owners for owners in result.coverage["owners"].values())
    assert result.graph.assert_valid()["valid"]
    assert all(not effect.is_complete for effect in result.graph.effects.values())


def test_local_import_attribute_index_consumer_value_path_is_queryable(tmp_path):
    result = project(tmp_path, {
        "library/__init__.py": "from .constants import OPTIONS\n",
        "library/constants.py": "OPTIONS = {'mean': (1, 2, 3)}\n",
        "app.py": "import library as lib\nresult = consume(lib.OPTIONS['mean'])\n",
    })
    source = binding(result, "OPTIONS", "library.constants")
    target = binding(result, "result", "app")
    path = result.value_path(source, target)
    assert path
    labels = {result.graph.definitions[identifier].label
              for identifier in result.graph.definitions if identifier.wire in path}
    assert {"Attribute", "Subscript", "Call"} <= labels
    assert any(edge.relation is SemanticRelation.INITIALIZES_MODULE for edge in result.graph.edges.values())
    assert any(edge.relation is SemanticRelation.REEXPORTS for edge in result.graph.edges.values())


def test_unresolved_call_has_data_and_effect_boundary(tmp_path):
    result = project(tmp_path, {"program.py": "def run(callback, tensor):\n    return callback(tensor)\n"})
    call = operations(result, "Call")[0]
    assert call.kind is OperationKind.OPAQUE
    assert "target_candidate" not in call.metadata
    assert call.effect_summary in result.graph.effects
    assert call.output_slots
    assert any(edge.source.id == call.id and edge.relation is SemanticRelation.READS_SLOT
               for edge in result.graph.edges.values())
    assert not result.graph.effects[call.effect_summary].is_complete


def test_cross_function_actual_formal_return_result_paths_are_queryable(tmp_path):
    result = project(tmp_path, {
        "ops.py": "def transform(value):\n    return value + 1\n",
        "app.py": "from ops import transform as fn\ninput_value = 4\noutput_value = fn(input_value)\n",
    })
    function = next(item for item in operations(result, "transform") if item.kind is OperationKind.FUNCTION)
    source = binding(result, "input_value", "app")
    destination = binding(result, "output_value", "app")
    assert result.value_path(source, function.input_slots[0])
    assert result.value_path(function.input_slots[0], function.output_slots[0])
    assert result.value_path(function.output_slots[0], destination)
    assert operations(result, "Call", module="app")[0].metadata["target_candidate"] == function.id.wire


def test_branch_loop_exception_control_and_merge_are_explicit(tmp_path):
    result = project(tmp_path, {"program.py": '''
def run(flag, xs):
    if flag:
        value = 1
    else:
        value = 2
    for x in xs:
        value += x
    try:
        return consume(value)
    except ValueError as error:
        raise RuntimeError() from error
    finally:
        cleanup()
'''})
    kinds = {item.kind for item in result.graph.controls.values()}
    assert {"if_true", "if_false", "loop_body", "try_body", "except_0", "finally"} <= kinds
    assert operations(result, role="phi_like_merge")
    for operation in result.graph.definitions.values():
        if operation.control_region is not None:
            assert any(edge.relation is SemanticRelation.CONTROLS and edge.source.id == operation.control_region
                       and edge.target.id == operation.id for edge in result.graph.edges.values())
    assert any(item.kind is OperationKind.OPAQUE and item.label == "Raise"
               for item in result.graph.definitions.values())


def test_frontend_never_executes_target_and_excludes_environment_sources(tmp_path):
    sentinel = tmp_path / "executed"
    result = project(tmp_path, {
        "program.py": f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('bad')\nraise RuntimeError()\n",
        ".venv/broken.py": "this is not valid Python!",
        "__pycache__/broken.py": "this is not valid Python!",
    })
    assert not sentinel.exists()
    assert result.coverage["target_executed"] is False
    assert len(result.coverage["files"]) == 1


def test_generic_source_model_has_no_workload_name_dependency(tmp_path):
    one = tmp_path / "one"
    two = tmp_path / "two"
    one.mkdir()
    two.mkdir()
    text = "def compute(x):\n    return x * 2\nresult = compute(3)\n"
    left = project(one, {"apples.py": text})
    right = project(two, {"oranges.py": text})
    assert left.graph.validate()["counts"] == right.graph.validate()["counts"]
    assert sorted(item.kind.value for item in left.graph.definitions.values()) == sorted(item.kind.value for item in right.graph.definitions.values())


def test_content_versioned_ids_and_serialization_are_deterministic(tmp_path):
    result = project(tmp_path, {"b.py": "from a import x\ny = x\n", "a.py": "x = 1\n"})
    assert canonical_json(result.graph) == canonical_json(build_semantic(tmp_path).graph)
    first_atoms = set(result.graph.source_atoms)
    (tmp_path / "a.py").write_text("x = 2\n")
    changed = build_semantic(tmp_path)
    assert first_atoms != set(changed.graph.source_atoms)
    unchanged_b = {atom.id for atom in result.graph.source_atoms.values() if atom.reference.path.endswith("b.py")}
    assert unchanged_b <= set(changed.graph.source_atoms)


def test_definition_time_defaults_are_outside_deferred_body(tmp_path):
    result = project(tmp_path, {"program.py": "def target(value=prepare()):\n    return consume(value)\n"})
    function = operations(result, "target")[0]
    declaration = operations(result, "define target")[0]
    calls = operations(result, "Call")
    default_call = next(call for call in calls if call.source_start == 1)
    body_call = next(call for call in calls if call.source_start == 2)
    assert default_call.parent_id == declaration.parent_id
    assert body_call.parent_id == function.id
    assert default_call.parent_id != function.id
    assert declaration.metadata["phase"] == "definition_time"
    assert function.metadata["phase"] == "call_time"


@pytest.mark.parametrize("expression", ["target(1)", "target(value=1)"])
def test_locally_shadowed_callable_is_not_resolved_to_outer_function(tmp_path, expression):
    result = project(tmp_path, {"program.py": f"def target(value):\n    return value\ndef run(target):\n    return {expression}\n"})
    call = operations(result, "Call")[0]
    assert "target_candidate" not in call.metadata
    assert call.kind is OperationKind.OPAQUE


def test_root_package_relative_import_resolves_without_execution(tmp_path):
    package = tmp_path / "package"
    package.mkdir()
    result = project(package, {"__init__.py": "from .constants import X\n", "constants.py": "X = 2\n"})
    assert result.value_path(binding(result, "X", "package.constants"), binding(result, "X", "package"))


def test_frontend_validation_does_not_rescan_global_registries_per_operation(tmp_path):
    result = project(tmp_path, {"program.py": "\n".join(f"value_{index} = {index}" for index in range(150))})

    class CountIterations(dict):
        scans = 0

        def __iter__(self):
            self.scans += 1
            return super().__iter__()

    result.graph.slots = CountIterations(result.graph.slots)
    result.graph.source_atoms = CountIterations(result.graph.source_atoms)
    assert len(result.graph.definitions) > 300
    assert result.graph.assert_valid()["valid"]
    # One index build would also be linear; rebuilding a complete set for each
    # operation is forbidden, independent of machine speed or test timing.
    assert result.graph.slots.scans <= 1
    assert result.graph.source_atoms.scans <= 1
    assert result.coverage["selection_scope"] == "all_selected_project_python_files_not_entry_reachability"
