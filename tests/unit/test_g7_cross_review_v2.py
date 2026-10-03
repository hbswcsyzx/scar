"""Independent adversarial checks for G7 import targets and budgets."""
from dataclasses import replace

import pytest

from scar.analysis.constants_v2 import EvaluationBudget
from scar.analysis.import_values_v2 import (
    ImportConditionKind,
    ImportResolutionStatus,
    ImportStepKind,
    ImportValueStatus,
    resolve_import_values,
)
from scar.analysis.source_semantics_v2 import extract_source_semantics, validate_source_semantics
from scar.ir.frontend_v2 import build_semantic
from scar.ir.semantics_v2 import Opcode
from scar.ir.v2.semantic import SemanticEndpoint, SemanticNodeKind, SemanticRelation


def _source_model(tmp_path):
    (tmp_path / "a.py").write_text("X = 11\n")
    (tmp_path / "b.py").write_text("X = 99\n")
    source = tmp_path / "main.py"
    source.write_text("from a import X\nanswer = X\n")
    frontend = build_semantic(source, project_root=tmp_path)
    semantic = frontend.graph
    overlay = extract_source_semantics(semantic)
    return semantic, overlay


def test_import_edge_target_must_agree_with_replayed_from_name(tmp_path):
    semantic, overlay = _source_model(tmp_path)
    assert validate_source_semantics(overlay, semantic)["valid"]

    import_operation = next(item for item in overlay.operations.values()
                            if item.opcode is Opcode.IMPORT)
    import_edge = next(edge for edge in semantic.edges.values()
                       if edge.relation is SemanticRelation.IMPORTS
                       and edge.source.id == import_operation.operation)
    module_b = next(item.id for item in semantic.modules.values() if item.name == "b")

    # This edge mutation is schema-valid. The source replay only replays the
    # source-semantics overlay, so it currently accepts the unchanged `from a`
    # syntax while the import resolver is handed a typed edge to module b.
    semantic.edges[import_edge.edge_id] = replace(
        import_edge,
        target=SemanticEndpoint(SemanticNodeKind.MODULE, module_b),
    )
    assert semantic.validate()["valid"]
    assert overlay.validate(semantic)["valid"]
    assert validate_source_semantics(overlay, semantic)["valid"]

    report = resolve_import_values(
        semantic, overlay, targets=(import_operation.result,))
    fact = report.facts[import_operation.result]

    # The source requests module a, whose X is 11. A schema-valid but
    # mismatching IMPORTS edge must not yield b.X (99) as a replacement value.
    contract = report.contracts[import_operation.operation]
    assert contract.status is ImportResolutionStatus.BLOCKED
    assert any(item.kind is ImportConditionKind.SOURCE_FILE_SELECTION
               and item.status.value == "SOURCE_BLOCKER"
               for item in contract.conditions)
    assert fact.literal is None or fact.literal.to_python() != 99


def test_relative_import_cannot_escape_package_and_fall_back_to_top_level(tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()
    init = package / "__init__.py"
    init.write_text("from ..x import X\n")
    (tmp_path / "x.py").write_text("X = 99\n")

    semantic = build_semantic(init, project_root=tmp_path).graph
    overlay = extract_source_semantics(semantic)
    assert validate_source_semantics(overlay, semantic)["valid"]
    operation = next(item for item in overlay.operations.values()
                     if item.opcode is Opcode.IMPORT)

    report = resolve_import_values(semantic, overlay, targets=(operation.result,))
    assert report.contracts[operation.operation].status in {
        ImportResolutionStatus.BLOCKED,
        ImportResolutionStatus.UNRESOLVED,
    }
    assert report.facts[operation.result].literal is None


def test_relative_from_import_without_module_keeps_local_child_fallback(tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()
    init = package / "__init__.py"
    init.write_text("from . import child\n")
    (package / "child.py").write_text("VALUE = 7\n")
    source = tmp_path / "main.py"
    source.write_text("from pkg import child\nanswer = child.VALUE\n")

    semantic = build_semantic(source, project_root=tmp_path).graph
    overlay = extract_source_semantics(semantic)
    assert validate_source_semantics(overlay, semantic)["valid"]
    package_import = next(item for item in overlay.operations.values()
                          if item.opcode is Opcode.IMPORT and item.source.path == str(init))
    target = next(item for item in overlay.operations.values()
                  if item.opcode is Opcode.ATTRIBUTE and item.attribute == "VALUE")

    report = resolve_import_values(
        semantic, overlay, targets=(package_import.result, target.result))
    assert report.contracts[package_import.operation].status is ImportResolutionStatus.LOCAL_SUBMODULE_CANDIDATE
    fact = report.facts[target.result]
    blockers = tuple((item.kind.value, item.reason) for item in fact.conditions
                     if item.status.value == "SOURCE_BLOCKER")
    assert fact.status is ImportValueStatus.CONDITIONAL, (
        fact.gaps,
        blockers,
    )
    assert fact.literal.to_python() == 7
    provenance = report.provenances[fact.provenance_id]
    assert ImportStepKind.SUBMODULE in {item.kind for item in provenance.steps}


def test_target_count_is_bounded_by_node_report_budget(tmp_path):
    semantic, overlay = _source_model(tmp_path)
    targets = tuple(overlay.values)
    assert len(targets) > 1
    with pytest.raises(ValueError):
        resolve_import_values(
            semantic,
            overlay,
            targets=targets,
            budget=EvaluationBudget(max_nodes=1),
        )


def test_step_budget_exhaustion_never_emits_a_literal_fact(tmp_path):
    semantic, overlay = _source_model(tmp_path)
    target = next(item.result for item in overlay.operations.values()
                  if item.opcode is Opcode.LITERAL)
    budget = EvaluationBudget(max_nodes=8, max_steps=1)

    report = resolve_import_values(semantic, overlay, targets=(target,), budget=budget)
    fact = report.facts[target]

    assert fact.status is ImportValueStatus.BLOCKED
    assert any(item.kind.value == "BUDGET" for item in fact.gaps)
    assert target not in report.guidance
    assert report.usage.steps <= budget.max_steps


def test_serialized_report_output_obeys_output_byte_budget(tmp_path):
    semantic, overlay = _source_model(tmp_path)
    target = next(item.result for item in overlay.operations.values()
                  if item.opcode is Opcode.LITERAL)

    with pytest.raises(ValueError):
        resolve_import_values(
            semantic,
            overlay,
            targets=(target,),
            budget=EvaluationBudget(max_nodes=8, max_steps=8,
                                    max_total_output_bytes=1),
        )


def test_float_constant_path_keeps_floating_environment_requirement(tmp_path):
    source = tmp_path / "float_math.py"
    source.write_text("answer = 0.1 + 0.2\n")
    semantic = build_semantic(source, project_root=tmp_path).graph
    overlay = extract_source_semantics(semantic)
    operation = next(item for item in overlay.operations.values()
                     if item.opcode is Opcode.ADD)

    report = resolve_import_values(semantic, overlay, targets=(operation.result,))
    fact = report.facts[operation.result]
    kinds = {item.kind for item in fact.conditions}

    assert ImportConditionKind.BUILTIN_RUNTIME_MATCH in kinds
    assert ImportConditionKind.FLOATING_ENVIRONMENT_MATCH in kinds
