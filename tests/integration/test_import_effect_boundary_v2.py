"""Import effects remain separate from constant-value paths.

All closure facts below are explicit fixture contracts. This test does not
infer module purity, execute imports or authorize a source transformation.
"""
from scar.analysis.contracts_v2 import Disposition, EffectPolicy, evaluate_removal
from scar.analysis.effects_v2 import (
    EffectClosureEngine, EffectCoverage, EffectDimension, EffectOccurrence,
    ObservationScope, OperationEffects, ScopeMode,
)
from scar.ir.frontend_v2 import build_semantic
from scar.ir.v2 import (
    Completeness, EffectTarget, EffectTargetKind, EvidenceClaim, EvidenceKind,
    SemanticRelation,
)


def test_constant_consumer_preserves_import_effects_and_requests_lazy_attribute_contract(tmp_path):
    package = tmp_path / "fixture_library"
    package.mkdir()
    sentinel = tmp_path / "import-was-executed.txt"
    (package / "constants.py").write_text("OPTIONS = (2, 3, 5)\n")
    (package / "__init__.py").write_text(
        "from .constants import OPTIONS\n"
        "import os\n"
        "mode = os.environ.get('FIXTURE_MODE', 'default')\n"
        f"with open({str(sentinel)!r}, 'w') as stream:\n"
        "    stream.write(mode)\n"
        "def __getattr__(name):\n"
        "    return dynamic_provider(name)\n"
    )
    application = tmp_path / "app.py"
    application.write_text(
        "import fixture_library as lib\n"
        "selected = lib.OPTIONS[0]\n"
        "lazy = lib.RUNTIME_VALUE\n"
    )
    result = build_semantic(tmp_path)
    graph = result.graph
    modules = {item.name: item for item in graph.modules.values()}
    pure_init = modules["fixture_library.constants"].initializer
    effectful_init = modules["fixture_library"].initializer
    app_init = modules["app"].initializer
    options = next(item.slot_id for item in graph.slots.values()
                   if item.owner == pure_init and item.name == "OPTIONS")
    selected = next(item.slot_id for item in graph.slots.values()
                    if item.owner == app_init and item.name == "selected")
    value_path = result.value_path(options, selected)
    assert value_path
    assert any(edge.relation is SemanticRelation.INITIALIZES_MODULE for edge in graph.edges.values())
    constant_access = next(item for item in graph.definitions.values()
                           if item.source_file == str(application) and item.source_start == 2
                           and item.label == "Subscript")
    assert constant_access.id.wire in value_path
    lazy_access = next(item for item in graph.definitions.values()
                      if item.source_file == str(application) and item.source_start == 3
                      and item.label == "Attribute")
    assert not sentinel.exists()  # Building the source graph executes no module.
    assert not graph.effects[graph.definitions[pure_init].effect_summary].is_complete

    scope = "fixture-import-initialization"
    declaration = EvidenceClaim(EvidenceKind.DECLARED,
        references=("fixture:reviewed-module-body-effect-contract", modules["fixture_library"].fingerprint),
        scope=scope,
        assumptions=(
            "fixture preconditions close exceptions and downstream calls within this selected scope",
            "private export bindings are region outputs; output preservation remains a later obligation",
            "module loader and sys.modules behavior outside these body regions are not certified",
        ))
    engine = EffectClosureEngine(graph)
    engine.add_scope(ObservationScope(scope, "module-body-entry", "module-body-exit", "fixture-contract",
        ScopeMode.ALL_PATHS, "declared-order", closed=True, evidence=(declaration,)))
    coverage = tuple(EffectCoverage(scope, dimension, Completeness.COMPLETE,
        branches=Completeness.COMPLETE, calls=Completeness.COMPLETE, aliases=Completeness.COMPLETE,
        evidence=(declaration,)) for dimension in EffectDimension)
    policy = EffectPolicy("preserve-visible-effects", scope, (), declaration)

    # A declared closed pure body passes only this effects gate. The verdict
    # remains KEEP: value replacement, loader behavior and legality come later.
    engine.add_operation_effects(OperationEffects(pure_init, scope, coverage=coverage))
    pure = evaluate_removal(engine.boundary((pure_init,), scope), policy, graph)
    assert pure.removal_effects_satisfied and pure.ready_for_region_construction
    assert pure.disposition is Disposition.KEEP
    assert not pure.requests

    environment = EffectOccurrence("init:read-mode", effectful_init, EffectDimension.READS,
        EffectTarget(EffectTargetKind.ENVIRONMENT, "FIXTURE_MODE"), scope, 1, declaration,
        dependency_coverage=Completeness.COMPLETE, order_coverage=Completeness.COMPLETE)
    file_write = EffectOccurrence("init:write-file", effectful_init, EffectDimension.EXTERNAL,
        EffectTarget(EffectTargetKind.FILE, str(sentinel)), scope, 2, declaration,
        dependencies=(environment.id,), ordered_after=(environment.id,),
        dependency_coverage=Completeness.COMPLETE, order_coverage=Completeness.COMPLETE)
    engine.add_occurrence(environment)
    engine.add_occurrence(file_write)
    engine.add_operation_effects(OperationEffects(effectful_init, scope,
        (environment.id, file_write.id), coverage, inclusive=True))
    effectful = evaluate_removal(engine.boundary((effectful_init,), scope), policy, graph)
    assert effectful.disposition is Disposition.KEEP
    assert not effectful.removal_effects_satisfied
    assert effectful.required_effects == (file_write.id,)
    residual = engine.residual_slice(effectful.required_effects, scope)
    assert tuple(item.id for item in residual.occurrences) == (environment.id, file_write.id)
    assert environment.id in residual.dependencies
    assert (environment.id, file_write.id) in residual.order_edges
    assert not residual.requires_original_region

    # Merely resolving the module does not certify arbitrary __getattr__ work.
    engine.add_operation_effects(OperationEffects(lazy_access.id, scope,
        open_boundaries=("module __getattr__ dispatch and downstream effects lack a scoped contract",)))
    lazy = evaluate_removal(engine.boundary((lazy_access.id,), scope), policy, graph)
    assert lazy.disposition is Disposition.CONTRACT
    assert not lazy.ready_for_region_construction
    assert any("__getattr__" in request.missing_fact for request in lazy.requests)
    assert all(request.definitions == (lazy_access.id,) and request.sources
               and request.completion and request.required_fields for request in lazy.requests)
    assert all(request.rerun_argv is None for request in lazy.requests)
    assert all(source.path == str(application)
               for request in lazy.requests for source in request.sources)
    assert not sentinel.exists()
