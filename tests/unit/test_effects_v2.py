from copy import deepcopy
from dataclasses import replace

import pytest

from scar.analysis.effects_v2 import (
    ClosureState, EffectClosureEngine, EffectCoverage, EffectDimension,
    EffectOccurrence, ObservationScope, OperationEffects, ScopeMode,
)
from scar.ir.v2 import (
    Completeness, EffectPresence, EffectTarget, EffectTargetKind, EvidenceClaim,
    EvidenceKind, OperationDefinition, OperationDefinitionID, OperationKind,
    SemanticGraph,
)


EVIDENCE = EvidenceClaim(EvidenceKind.DECLARED, ("fixture:explicit-scope-contract",))
STATE = EffectTarget(EffectTargetKind.OBJECT, "module:buffer")
VALUE = EffectTarget(EffectTargetKind.VALUE_VERSION, "lv:value@v0")


def fixture(closed=True, mode=ScopeMode.DYNAMIC_PATH):
    graph = SemanticGraph()
    parent, child, third = (OperationDefinitionID(name) for name in ("parent", "child", "third"))
    graph.add_definition(OperationDefinition(parent, OperationKind.FUNCTION, "parent"))
    graph.add_definition(OperationDefinition(child, OperationKind.FUNCTION, "child", parent_id=parent))
    graph.add_definition(OperationDefinition(third, OperationKind.FUNCTION, "third"))
    engine = EffectClosureEngine(graph)
    engine.add_scope(ObservationScope("scope", "enter", "exit" if closed else None, "run", mode,
        "logical-event-order", collectors=("fixture",), closed=closed, evidence=(EVIDENCE,)))
    return engine, parent, child, third


def covered(scope="scope", **overrides):
    return tuple(EffectCoverage(scope, dimension, overrides.get(dimension.value, Completeness.COMPLETE),
        branches=Completeness.COMPLETE, calls=Completeness.COMPLETE, aliases=Completeness.COMPLETE,
        evidence=(EVIDENCE,)) for dimension in EffectDimension)


def occurrence(engine, identity, definition, dimension, target=VALUE, position=0, **kwargs):
    kwargs.setdefault("dependency_coverage", Completeness.COMPLETE)
    kwargs.setdefault("order_coverage", Completeness.COMPLETE)
    item = EffectOccurrence(identity, definition, dimension, target, "scope", position, EVIDENCE, **kwargs)
    engine.add_occurrence(item)
    return item


def test_effect_presence_does_not_imply_complete_coverage():
    engine, parent, _, _ = fixture()
    occurrence(engine, "rng", parent, EffectDimension.RNG, EffectTarget(EffectTargetKind.RNG, "cpu:generator"))
    engine.add_operation_effects(OperationEffects(parent, "scope", ("rng",)))
    boundary = engine.boundary((parent,), "scope")
    assert boundary.effects.rng is EffectPresence.PRESENT
    assert not boundary.effects.is_complete
    assert not boundary.ready_for_region_construction
    assert any(gap.dimension is EffectDimension.RNG for gap in boundary.gaps)


def test_parent_inclusive_effect_not_double_counted():
    engine, parent, child, _ = fixture()
    occurrence(engine, "child-write", child, EffectDimension.WRITES, STATE)
    engine.add_operation_effects(OperationEffects(child, "scope", ("child-write",), covered()))
    engine.add_operation_effects(OperationEffects(parent, "scope", ("child-write",), covered(), (child,), inclusive=True))
    boundary = engine.boundary((parent,), "scope")
    assert tuple(item.id for item in boundary.occurrences) == ("child-write",)
    assert set(boundary.members) == {parent, child}
    assert boundary.outward_writes == (STATE,)
    assert boundary.ready_for_region_construction


def test_inclusive_occurrence_owner_requires_its_own_scoped_coverage():
    engine, parent, child, _ = fixture()
    occurrence(engine, "child-write", child, EffectDimension.WRITES, STATE)
    engine.add_operation_effects(OperationEffects(parent, "scope", ("child-write",), covered(), inclusive=True))
    boundary = engine.boundary((parent,), "scope")
    assert child in boundary.members
    assert not boundary.ready_for_region_construction
    assert any(gap.definition == child for gap in boundary.gaps)


def test_read_before_write_remains_boundary_input():
    engine, parent, _, _ = fixture()
    occurrence(engine, "read", parent, EffectDimension.READS, STATE, 1)
    occurrence(engine, "write", parent, EffectDimension.WRITES, STATE, 2, dependencies=("read",))
    engine.add_operation_effects(OperationEffects(parent, "scope", ("read", "write"), covered()))
    boundary = engine.boundary((parent,), "scope")
    assert STATE in boundary.entry_reads
    assert STATE in boundary.outward_writes


def test_hidden_module_state_and_rng_keep_parent_open():
    engine, parent, child, _ = fixture()
    occurrence(engine, "state", child, EffectDimension.WRITES, STATE)
    occurrence(engine, "rng", child, EffectDimension.RNG, EffectTarget(EffectTargetKind.RNG, "cuda:generator"), 1)
    engine.add_operation_effects(OperationEffects(child, "scope", ("state", "rng"),
        covered(writes=Completeness.PARTIAL, rng=Completeness.UNKNOWN), open_boundaries=("custom module state unobserved",)))
    engine.add_operation_effects(OperationEffects(parent, "scope", coverage=covered(), children=(child,)))
    boundary = engine.boundary((parent,), "scope")
    assert not boundary.ready_for_region_construction
    assert boundary.effects.rng is EffectPresence.PRESENT
    assert boundary.effects.writes.completeness is not Completeness.COMPLETE
    assert any(gap.definition == child and "custom" in gap.reason for gap in boundary.gaps)


def test_uncaptured_exception_branch_blocks_all_paths_closure():
    engine, parent, _, _ = fixture(mode=ScopeMode.DYNAMIC_PATH)
    engine.add_operation_effects(OperationEffects(parent, "scope", coverage=covered()))
    assert engine.boundary((parent,), "scope").ready_for_region_construction
    engine.add_scope(ObservationScope("all", "entry", "all-exits", "program", ScopeMode.ALL_PATHS,
        "static-control", closed=True, evidence=(EVIDENCE,)))
    boundary = engine.boundary((parent,), "all")
    assert boundary.mode is ScopeMode.ALL_PATHS
    assert engine.boundary((parent,), "scope").mode is ScopeMode.DYNAMIC_PATH
    assert not boundary.ready_for_region_construction
    assert boundary.effects.may_raise is EffectPresence.UNKNOWN
    with pytest.raises(ValueError, match="coverage scope"):
        engine.add_operation_effects(OperationEffects(parent, "all", coverage=covered()))


def test_absent_consumer_in_open_scope_is_not_dead():
    engine, parent, _, _ = fixture(closed=False)
    engine.add_operation_effects(OperationEffects(parent, "scope", coverage=covered()))
    closure = engine.consumer_closure(VALUE, "scope", members=(parent,))
    assert closure.state is ClosureState.OPEN
    assert closure.visited_consumers == ()
    assert closure.open_boundaries


def test_complete_closed_scope_can_prove_only_scoped_deadness():
    engine, parent, _, _ = fixture()
    engine.add_operation_effects(OperationEffects(parent, "scope", coverage=covered()))
    closure = engine.consumer_closure(VALUE, "scope", members=(parent,))
    assert closure.state is ClosureState.DEAD_IN_SCOPE
    assert closure.endpoint == "exit"
    assert closure.scope == "scope"


def test_callback_escape_keeps_future_consumer_open():
    engine, parent, _, _ = fixture()
    occurrence(engine, "escape", parent, EffectDimension.ESCAPES)
    engine.add_operation_effects(OperationEffects(parent, "scope", ("escape",), covered(),
        open_boundaries=("callback may consume value after function returns",)))
    closure = engine.consumer_closure(VALUE, "scope", members=(parent,), required_consumers=())
    assert closure.state is ClosureState.OPEN
    assert "callback" in " ".join(closure.open_boundaries)


def test_required_consumer_is_live_and_alias_edges_are_traversed_both_directions():
    engine, parent, child, _ = fixture()
    alias = EffectTarget(EffectTargetKind.VALUE_VERSION, "lv:view@v0")
    occurrence(engine, "alias", parent, EffectDimension.ALIASES, VALUE, related_targets=(alias,))
    occurrence(engine, "read", child, EffectDimension.READS, VALUE, 1)
    engine.add_operation_effects(OperationEffects(parent, "scope", ("alias",), covered(), (child,)))
    engine.add_operation_effects(OperationEffects(child, "scope", ("read",), covered()))
    closure = engine.consumer_closure(alias, "scope", members=(parent,), required_consumers=(child,))
    assert closure.state is ClosureState.LIVE
    assert child in closure.visited_consumers


def test_local_temporary_requires_alias_and_lifetime_closure():
    engine, parent, _, _ = fixture()
    engine.add_operation_effects(OperationEffects(parent, "scope", coverage=covered(frees=Completeness.UNKNOWN)))
    closure = engine.consumer_closure(STATE, "scope", members=(parent,))
    assert closure.state is ClosureState.OPEN
    assert any("frees" in reason for reason in closure.open_boundaries)


def test_residual_effect_keeps_dependencies_and_order():
    engine, parent, _, _ = fixture()
    occurrence(engine, "read-env", parent, EffectDimension.READS,
               EffectTarget(EffectTargetKind.ENVIRONMENT, "MODE"), 1)
    occurrence(engine, "log", parent, EffectDimension.EXTERNAL,
               EffectTarget(EffectTargetKind.LOG, "configuration"), 2, dependencies=("read-env",))
    occurrence(engine, "file", parent, EffectDimension.EXTERNAL,
               EffectTarget(EffectTargetKind.FILE, "result.log"), 3, ordered_after=("log",))
    engine.add_operation_effects(OperationEffects(parent, "scope", ("read-env", "log", "file"), covered()))
    residual = engine.residual_slice(("file",), "scope")
    assert tuple(item.id for item in residual.occurrences) == ("read-env", "log", "file")
    assert "read-env" in residual.dependencies
    assert ("log", "file") in residual.order_edges
    assert not residual.requires_original_region


def test_inseparable_residual_requires_original_region():
    engine, parent, _, _ = fixture()
    occurrence(engine, "log", parent, EffectDimension.EXTERNAL,
               EffectTarget(EffectTargetKind.LOG, "channel"), position=None)
    engine.add_operation_effects(OperationEffects(parent, "scope", ("log",),
        open_boundaries=("log payload depends on opaque value computation",)))
    residual = engine.residual_slice(("log",), "scope")
    assert residual.requires_original_region
    assert residual.open_boundaries


def test_residual_dependency_list_is_not_itself_a_completeness_proof():
    engine, parent, _, _ = fixture()
    occurrence(engine, "log", parent, EffectDimension.EXTERNAL,
               EffectTarget(EffectTargetKind.LOG, "channel"),
               dependency_coverage=Completeness.UNKNOWN, order_coverage=Completeness.UNKNOWN)
    engine.add_operation_effects(OperationEffects(parent, "scope", ("log",), covered()))
    residual = engine.residual_slice(("log",), "scope")
    assert residual.requires_original_region
    assert any("dependency edges" in reason for reason in residual.open_boundaries)


def test_recursive_definition_decomposition_reaches_monotone_fixed_point():
    engine, parent, child, _ = fixture()
    occurrence(engine, "read", child, EffectDimension.READS)
    engine.add_operation_effects(OperationEffects(parent, "scope", coverage=covered(), children=(child,)))
    engine.add_operation_effects(OperationEffects(child, "scope", ("read",), covered(), (parent,)))
    boundary = engine.boundary((parent,), "scope")
    assert set(boundary.members) == {parent, child}
    assert len(boundary.occurrences) == 1


def test_lexical_child_is_not_assumed_to_execute_dynamically():
    engine, parent, child, _ = fixture()
    engine.add_operation_effects(OperationEffects(parent, "scope", coverage=covered()))
    boundary = engine.boundary((parent,), "scope")
    assert boundary.members == (parent,)
    assert child not in boundary.members


def test_narrow_target_coverage_cannot_fill_another_members_missing_domain():
    engine, parent, child, _ = fixture()
    engine.add_operation_effects(OperationEffects(parent, "scope", coverage=covered(), children=(child,)))
    narrowed = tuple(replace(item, target_domain=("object:buffer",)) for item in covered())
    engine.add_operation_effects(OperationEffects(child, "scope", coverage=narrowed))
    boundary = engine.boundary((parent,), "scope")
    assert not boundary.effects.is_complete
    assert not boundary.ready_for_region_construction
    assert all("*" not in item.target_domain for item in boundary.coverage)


def test_same_input_produces_deterministic_closure_report():
    engine, parent, child, _ = fixture()
    occurrence(engine, "child-write", child, EffectDimension.WRITES, STATE)
    engine.add_operation_effects(OperationEffects(child, "scope", ("child-write",), covered()))
    engine.add_operation_effects(OperationEffects(parent, "scope", coverage=covered(), children=(child,)))
    encoded = engine.to_json()
    restored = EffectClosureEngine.from_json(encoded, engine.semantic)
    assert restored.to_json() == encoded
    assert restored.boundary((parent,), "scope").as_dict() == engine.boundary((parent,), "scope").as_dict()


@pytest.mark.parametrize("mode", [ScopeMode.DYNAMIC_PATH, ScopeMode.ALL_PATHS])
def test_boundary_scope_mode_is_preserved_by_engine_serialization(mode):
    engine, parent, _, _ = fixture(mode=mode)
    engine.add_operation_effects(OperationEffects(parent, "scope", coverage=covered()))
    restored = EffectClosureEngine.from_json(engine.to_json(), engine.semantic)
    boundary = restored.boundary((parent,), "scope")
    assert boundary.mode is mode
    assert boundary.as_dict()["mode"] == mode.value


@pytest.mark.parametrize("corruption", ["unknown-member", "unknown-occurrence", "wrong-scope", "duplicate",
                                        "new-field", "false-position", "empty-closure-evidence"])
def test_effect_codec_rejects_invalid_references_scopes_and_records(corruption):
    engine, parent, _, _ = fixture()
    occurrence(engine, "read", parent, EffectDimension.READS)
    engine.add_operation_effects(OperationEffects(parent, "scope", ("read",), covered()))
    document = deepcopy(engine.to_dict())
    if corruption == "unknown-member":
        document["operations"][0]["definition"] = OperationDefinitionID("missing").as_dict()
    elif corruption == "unknown-occurrence":
        document["operations"][0]["occurrences"] = ["missing"]
    elif corruption == "wrong-scope":
        document["occurrences"][0]["scope"] = "unknown"
    elif corruption == "duplicate":
        document["occurrences"].append(deepcopy(document["occurrences"][0]))
    elif corruption == "new-field":
        document["occurrences"][0]["pure"] = True
    elif corruption == "false-position":
        document["occurrences"][0]["position"] = True
    elif corruption == "empty-closure-evidence":
        document["scopes"][0]["evidence"] = []
    with pytest.raises(ValueError):
        EffectClosureEngine.from_dict(document, engine.semantic)


def test_effect_order_and_direct_ownership_violations_are_rejected():
    engine, parent, child, _ = fixture()
    occurrence(engine, "first", parent, EffectDimension.READS, position=1)
    occurrence(engine, "second", child, EffectDimension.WRITES, position=0, ordered_after=("first",))
    with pytest.raises(ValueError, match="another definition"):
        engine.add_operation_effects(OperationEffects(parent, "scope", ("second",)))
    with pytest.raises(ValueError, match="contradicts"):
        engine.assert_valid()


def test_missing_dependency_and_mutated_registry_records_fail_validation():
    engine, parent, _, _ = fixture()
    occurrence(engine, "read", parent, EffectDimension.READS, dependencies=("missing",))
    assert not engine.validate()["valid"]
    engine.occurrences["read"] = "bad record"
    assert not engine.validate()["valid"]


def test_boundary_batch_validates_once_and_matches_individual_queries(monkeypatch):
    engine, parent, child, third = fixture()
    occurrence(engine, "read", parent, EffectDimension.READS)
    occurrence(engine, "write", child, EffectDimension.WRITES, STATE)
    engine.add_operation_effects(OperationEffects(parent, "scope", ("read",), covered(), children=(child,)))
    engine.add_operation_effects(OperationEffects(child, "scope", ("write",), covered()))
    requests = [((definition,), "scope") for definition in (parent, child, third)]
    individual = [engine.boundary(members, scope).as_dict() for members, scope in requests]
    validations = []
    original = engine.assert_valid

    def counted():
        validations.append(1)
        return original()

    monkeypatch.setattr(engine, "assert_valid", counted)
    batch = engine.boundaries(requests)
    assert len(validations) == 1
    assert [summary.as_dict() for summary in batch] == individual
    # Batch validation is not a sticky 'validated' flag on mutable registries.
    engine.occurrences["read"] = "corrupt-after-first-batch"
    with pytest.raises(ValueError):
        engine.boundaries(requests)
