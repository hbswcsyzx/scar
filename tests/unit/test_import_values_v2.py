"""Generic non-executing import value provenance tests."""
from dataclasses import replace
from pathlib import Path

import pytest

from scar.analysis.constants_v2 import (
    ConstantRuntimeRequirement,
    EvaluationBudget,
)
from scar.analysis.import_values_v2 import (
    ImportConditionKind,
    ImportConditionStatus,
    ImportResolutionStatus,
    ImportStepKind,
    ImportValueReport,
    ImportValueStatus,
    SourceReplayStatus,
    resolve_import_values,
)
from scar.analysis.source_semantics_v2 import extract_source_semantics
from scar.ir import semantics_v2 as sm
from scar.ir.frontend_v2 import build_semantic
from scar.ir.v2.semantic import SemanticEndpoint, SemanticNodeKind, SemanticRelation


def analyze(tmp_path, files, entry="main.py", *, budget=EvaluationBudget()):
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    source = tmp_path / entry
    semantic = build_semantic(source, project_root=tmp_path).graph
    model = extract_source_semantics(semantic)
    report = resolve_import_values(semantic, model, budget=budget)
    return source, semantic, model, report


def operation_at(model, source, opcode, *, latest=False):
    matches = [operation for operation in model.operations.values()
               if operation.opcode is opcode and operation.source.path == str(source)]
    assert matches
    return max(matches, key=lambda item: (item.source.end_column or -1, item.position)) if latest else matches[0]


def import_operations(model, source):
    return [operation for operation in model.operations.values()
            if operation.opcode is sm.Opcode.IMPORT and operation.source.path == str(source)]


def test_relative_reexport_attribute_and_immutable_indices_keep_the_whole_path(tmp_path):
    marker = tmp_path / "import_was_executed"
    source, semantic, model, report = analyze(tmp_path, {
        "fixture_pkg/__init__.py": "from .values import TABLE as PUBLIC\n",
        "fixture_pkg/values.py": f"open({str(marker)!r}, 'w').write('executed')\nTABLE = ((2, 7), (3, 8))\n",
        "main.py": "import fixture_pkg as package\nanswer = package.PUBLIC[0][1]\n",
    })

    outer = operation_at(model, source, sm.Opcode.INDEX, latest=True)
    fact = report.facts[outer.result]
    assert fact.status is ImportValueStatus.CONDITIONAL
    assert fact.literal.to_python() == 7
    assert not marker.exists()
    assert report.source_replay is SourceReplayStatus.NOT_CHECKED
    assert report.guidance[outer.result].import_deletion.value == "NOT_PROVEN"
    assert report.guidance[outer.result].applied is False

    proof = report.provenances[fact.provenance_id]
    kinds = [step.kind for step in proof.steps]
    assert {ImportStepKind.IMPORT_MODULE, ImportStepKind.REEXPORT,
            ImportStepKind.ATTRIBUTE} <= set(kinds)
    assert kinds.count(ImportStepKind.INDEX) == 2
    assert all(model.operations[model.values[value].producer].opcode is not sm.Opcode.LITERAL
               for value in report.guidance)


def test_dotted_import_records_root_binding_and_explicit_alias(tmp_path):
    source, semantic, model, report = analyze(tmp_path, {
        "namespace/__init__.py": "",
        "namespace/submodule.py": "DATA = (5, 9)\n",
        "main.py": (
            "import namespace.submodule\n"
            "first = namespace.submodule.DATA[1]\n"
            "import namespace.submodule as explicit\n"
            "second = explicit.DATA[1]\n"
        ),
    })

    imports = import_operations(model, source)
    assert len(imports) == 2
    specs = [operation.import_spec for operation in imports]
    assert all(spec.requested == "namespace.submodule" for spec in specs)
    modules_by_id = semantic.modules
    root = next(module for module in modules_by_id.values() if module.name == "namespace")
    child = next(module for module in modules_by_id.values() if module.name == "namespace.submodule")
    assert specs[0].bound_name == "namespace" and specs[0].bound_module == root.id
    assert specs[1].bound_name == "explicit" and specs[1].bound_module == child.id

    contracts = [report.contracts[operation.operation] for operation in imports]
    assert all(contract.status is ImportResolutionStatus.LOCAL_MODULE_CANDIDATE
               for contract in contracts)
    targets = [operation for operation in model.operations.values()
               if operation.opcode is sm.Opcode.INDEX and operation.source.path == str(source)]
    assert len(targets) == 2
    assert all(report.facts[target.result].literal.to_python() == 9 for target in targets)


def test_self_from_import_uses_only_prior_namespace_binding_or_child_fallback(tmp_path):
    source, _, model, report = analyze(tmp_path, {
        "fixture_pkg/__init__.py": "from . import child\n",
        "fixture_pkg/child.py": "VALUE = 7\n",
        "main.py": "from fixture_pkg import child\nanswer = child.VALUE\n",
    })

    init_source = tmp_path / "fixture_pkg/__init__.py"
    child_import = next(operation for operation in import_operations(model, init_source)
                        if operation.import_spec.symbol == "child")
    contract = report.contracts[child_import.operation]
    assert contract.status is ImportResolutionStatus.LOCAL_SUBMODULE_CANDIDATE
    answer = operation_at(model, source, sm.Opcode.ATTRIBUTE, latest=True)
    fact = report.facts[answer.result]
    assert fact.status is ImportValueStatus.CONDITIONAL
    assert fact.literal.to_python() == 7
    proof_kinds = {step.kind for step in report.provenances[fact.provenance_id].steps}
    assert ImportStepKind.SUBMODULE in proof_kinds
    assert ImportStepKind.ATTRIBUTE in proof_kinds
    assert {ImportStepKind.IMPORT_EXPORT, ImportStepKind.REEXPORT} <= proof_kinds
    assert not any(condition.kind is ImportConditionKind.IMPORT_CYCLE
                   for condition in fact.conditions)


def test_self_from_import_does_not_read_a_later_binding(tmp_path):
    source, _, model, report = analyze(tmp_path, {
        "fixture_pkg/__init__.py": "from . import ITEM\nITEM = 4\n",
        "main.py": "from fixture_pkg import ITEM\nanswer = ITEM\n",
    })
    internal_import = next(operation for operation in import_operations(
        model, tmp_path / "fixture_pkg/__init__.py")
        if operation.import_spec.symbol == "ITEM")
    fact = report.facts[internal_import.result]
    assert fact.status in {ImportValueStatus.UNRESOLVED, ImportValueStatus.BLOCKED}
    assert fact.literal is None
    assert internal_import.result not in report.guidance


def test_same_module_attribute_uses_the_binding_at_that_operation_time(tmp_path):
    source, _, model, report = analyze(tmp_path, {
        "phase_pkg/__init__.py": (
            "import phase_pkg as current\n"
            "TOKEN = 1\n"
            "OBSERVED = current.TOKEN\n"
            "TOKEN = 2\n"
        ),
        "main.py": "from phase_pkg import OBSERVED\nanswer = OBSERVED\n",
    })
    init_source = tmp_path / "phase_pkg/__init__.py"
    observed = next(operation for operation in model.operations.values()
                    if operation.opcode is sm.Opcode.ATTRIBUTE
                    and operation.source.path == str(init_source))
    fact = report.facts[observed.result]
    assert fact.status is ImportValueStatus.CONDITIONAL
    assert fact.literal.to_python() == 1
    assert any(condition.kind is ImportConditionKind.MODULE_INITIALIZATION_COMPLETE
               for condition in report.facts[
                   next(operation for operation in import_operations(model, source)
                        if operation.import_spec.symbol == "OBSERVED").result].conditions)


def test_module_lazy_getattr_and_mutable_escape_are_not_literal_paths(tmp_path):
    source, _, model, report = analyze(tmp_path, {
        "lazy_pkg/__init__.py": "def __getattr__(name):\n    return 13\n",
        "mutable_pkg/__init__.py": "VALUE = [13]\n",
        "main.py": (
            "import lazy_pkg as lazy\n"
            "dynamic_value = lazy.MISSING\n"
            "import mutable_pkg as mutable\n"
            "escaped_value = mutable.VALUE[0]\n"
        ),
    })

    attributes = [operation for operation in model.operations.values()
                  if operation.opcode is sm.Opcode.ATTRIBUTE and operation.source.path == str(source)]
    assert len(attributes) == 2
    lazy_fact = report.facts[attributes[0].result]
    assert lazy_fact.status is ImportValueStatus.BLOCKED
    assert any(item.kind is ImportConditionKind.LAZY_MODULE_ATTRIBUTE
               for item in lazy_fact.conditions)
    index = operation_at(model, source, sm.Opcode.INDEX)
    mutable_fact = report.facts[index.result]
    assert mutable_fact.status is ImportValueStatus.BLOCKED
    assert mutable_fact.literal is None
    assert index.result not in report.guidance


def test_branch_writes_and_true_module_cycles_block_constant_substitution(tmp_path):
    source, _, model, report = analyze(tmp_path, {
        "cycle_pkg/__init__.py": "",
        "cycle_pkg/a.py": "from .b import VALUE\n",
        "cycle_pkg/b.py": "from .a import VALUE\n",
        "branch_pkg/__init__.py": "",
        "branch_pkg/values.py": (
            "if condition:\n    VALUE = (1, 7)\n"
            "else:\n    VALUE = (2, 8)\n"
        ),
        "main.py": (
            "from cycle_pkg.a import VALUE as cyclic\n"
            "import branch_pkg as branch\n"
            "answer = branch.values.VALUE[0][1]\n"
        ),
    })
    cyc_import = next(operation for operation in import_operations(model, source)
                      if operation.import_spec.requested == "cycle_pkg.a")
    assert report.facts[cyc_import.result].status in {ImportValueStatus.BLOCKED, ImportValueStatus.UNRESOLVED}
    outer = operation_at(model, source, sm.Opcode.INDEX, latest=True)
    fact = report.facts[outer.result]
    assert fact.status in {ImportValueStatus.BLOCKED, ImportValueStatus.UNRESOLVED}
    assert fact.literal is None
    assert outer.result not in report.guidance


def test_nonlocal_dependency_and_star_import_stay_unresolved_or_blocked(tmp_path):
    source, _, model, report = analyze(tmp_path, {
        "local_pkg/__init__.py": "VALUE = 5\n",
        "main.py": (
            "import external_package as external\n"
            "external_value = external.VALUE\n"
            "from local_pkg import *\n"
        ),
    })
    external_import = next(operation for operation in import_operations(model, source)
                           if operation.import_spec.requested == "external_package")
    assert report.facts[external_import.result].status in {
        ImportValueStatus.UNRESOLVED, ImportValueStatus.BLOCKED}
    star_imports = [operation for operation in model.operations.values()
                    if operation.opcode is sm.Opcode.IMPORT and operation.import_spec
                    and operation.import_spec.symbol == "*"]
    if star_imports:
        assert all(report.contracts[operation.operation].status is ImportResolutionStatus.BLOCKED
                   for operation in star_imports)


def test_semantic_import_edge_must_match_source_requested_module(tmp_path):
    source, semantic, model, _ = analyze(tmp_path, {
        "alpha_pkg/__init__.py": "VALUE = 3\n",
        "beta_pkg/__init__.py": "VALUE = 8\n",
        "main.py": "from alpha_pkg import VALUE\nanswer = VALUE\n",
    })
    operation = next(item for item in import_operations(model, source)
                     if item.import_spec.form is sm.ImportForm.FROM)
    edge = next(edge for edge in semantic.edges.values()
                if edge.relation is SemanticRelation.IMPORTS
                and edge.source.id == operation.operation)
    wrong_module = next(item for item in semantic.modules.values() if item.name == "beta_pkg")
    semantic.edges[edge.edge_id] = replace(edge,
        target=SemanticEndpoint(SemanticNodeKind.MODULE, wrong_module.id))
    assert semantic.validate()["valid"]
    report = resolve_import_values(semantic, model)
    contract = report.contracts[operation.operation]
    assert contract.status is ImportResolutionStatus.BLOCKED
    assert any(condition.status is ImportConditionStatus.SOURCE_BLOCKER
               for condition in contract.conditions)
    assert report.facts[operation.result].status is ImportValueStatus.BLOCKED


def test_floating_constant_propagates_each_typed_runtime_requirement(tmp_path):
    source, _, model, report = analyze(tmp_path, {"main.py": "answer = 0.1 + 0.2\n"})
    addition = operation_at(model, source, sm.Opcode.ADD)
    fact = report.facts[addition.result]
    assert fact.literal is not None
    requirements = {condition.runtime_requirement for condition in fact.conditions
                    if condition.runtime_requirement is not None}
    assert requirements == {
        ConstantRuntimeRequirement.BUILTIN_RUNTIME_MATCH,
        ConstantRuntimeRequirement.FLOATING_ENVIRONMENT_MATCH,
    }
    assert all(condition.status is ImportConditionStatus.REQUIRED_CONTRACT
               and condition.runtime is not None
               for condition in fact.conditions if condition.runtime_requirement is not None)


def test_report_rederives_provenance_and_source_replay_is_separate(tmp_path):
    source, semantic, model, report = analyze(tmp_path, {"main.py": "answer = (3, 9)[1]\n"})
    document = report.to_dict()
    restored = ImportValueReport.from_dict(document, semantic=semantic, source_semantics=model)
    assert restored.to_dict() == document
    assert restored.source_replay is SourceReplayStatus.NOT_CHECKED

    target = operation_at(model, source, sm.Opcode.INDEX).result
    fact = report.facts[target]
    forged = dict(document)
    forged_fact = next(item for item in forged["facts"] if item["value"] == target.as_dict())
    forged_fact["literal"] = {"kind": "int", "payload": "99", "items": []}
    with pytest.raises((ValueError, TypeError)):
        ImportValueReport.from_dict(forged, semantic=semantic, source_semantics=model)

    verified = report.validate_source_replay()
    assert verified.source_replay is SourceReplayStatus.VALID
    verified.assert_valid(verification_budget=EvaluationBudget())


def test_target_count_and_provenance_steps_obey_the_global_budget(tmp_path):
    source, semantic, model, _ = analyze(tmp_path, {"main.py": "left = 1\nright = 2\n"})
    values = tuple(model.values)
    assert len(values) > 1
    with pytest.raises(ValueError, match="target count"):
        resolve_import_values(semantic, model, targets=values[:2],
            budget=EvaluationBudget(max_nodes=1))

    literal = next(operation for operation in model.operations.values()
                   if operation.opcode is sm.Opcode.LITERAL)
    limited = resolve_import_values(semantic, model, targets=(literal.result,),
        budget=EvaluationBudget(max_steps=1))
    fact = limited.facts[literal.result]
    assert fact.status is ImportValueStatus.BLOCKED
    assert fact.literal is None
    assert any(gap.kind.value == "BUDGET" for gap in fact.gaps)
