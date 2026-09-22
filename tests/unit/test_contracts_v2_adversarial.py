"""Independent contract-boundary counterexamples; no optimizer execution."""
from dataclasses import replace

import pytest

from scar.analysis.contracts_v2 import (
    CollectorCapability, ContractAssessment, Disposition, EffectPolicy,
    EffectPolicyRule, PolicyAction, RunManifest, evaluate_removal,
)
from scar.analysis.effects_v2 import (
    EffectClosureEngine, EffectCoverage, EffectDimension, EffectOccurrence,
    ObservationScope, OperationEffects, ScopeMode,
)
from scar.ir.frontend_v2 import build_semantic
from scar.ir.record_codec import loads
from scar.ir.v2 import (
    Completeness, EffectTarget, EffectTargetKind, EvidenceClaim, EvidenceKind,
    OperationDefinitionID,
)


def _fixture(tmp_path, *, mode=ScopeMode.ALL_PATHS, complete=True, specs=()):
    path = tmp_path / "program.py"
    path.write_text("def compute(x):\n    return x + 1\n")
    semantic = build_semantic(path).graph
    definition = next(item.id for item in semantic.definitions.values()
                      if item.metadata.get("phase") == "call_time")
    claim = EvidenceClaim(EvidenceKind.DECLARED, ("fixture:scoped-contract",), scope="scope")
    engine = EffectClosureEngine(semantic)
    engine.add_scope(ObservationScope("scope", "enter", "exit", "run", mode,
                                      "semantic", closed=True, evidence=(claim,)))
    occurrences = []
    for index, (dimension, kind, reference) in enumerate(specs):
        occurrence = EffectOccurrence(f"effect:{index}", definition, dimension,
                                      EffectTarget(kind, reference), "scope", index, claim)
        engine.add_occurrence(occurrence)
        occurrences.append(occurrence.id)
    completeness = Completeness.COMPLETE if complete else Completeness.PARTIAL
    coverage = tuple(EffectCoverage("scope", dimension, completeness,
                                    branches=completeness, calls=completeness,
                                    aliases=completeness, evidence=(claim,))
                     for dimension in EffectDimension)
    engine.add_operation_effects(OperationEffects(definition, "scope", tuple(occurrences), coverage))
    return semantic, engine.boundary((definition,), "scope"), claim


def _policy(claim, *rules):
    return EffectPolicy("policy", "scope", tuple(rules), claim)


def _assert_uncertified(callback):
    try:
        result = callback()
    except ValueError:
        return  # Explicit rejection is an acceptable response to conflicting evidence.
    assert not result.removal_effects_satisfied
    assert result.requests or result.required_effects


def test_complete_dynamic_path_cannot_certify_requested_all_paths(tmp_path):
    semantic, boundary, claim = _fixture(tmp_path, mode=ScopeMode.DYNAMIC_PATH)
    assert boundary.ready_for_region_construction
    _assert_uncertified(lambda: evaluate_removal(boundary, _policy(claim), semantic,
                                               mode=ScopeMode.ALL_PATHS))


def test_restricted_target_coverage_cannot_be_upgraded_by_boundary_ready_flag(tmp_path):
    semantic, boundary, claim = _fixture(tmp_path)
    narrowed = tuple(replace(item, target_domain=("log:stdout",)) for item in boundary.coverage)
    boundary = replace(boundary, coverage=narrowed, gaps=(), ready_for_region_construction=True)
    _assert_uncertified(lambda: evaluate_removal(boundary, _policy(claim), semantic))


def test_duplicate_occurrence_identity_cannot_replace_file_effect_with_ignored_log(tmp_path):
    semantic, boundary, claim = _fixture(tmp_path, specs=(
        (EffectDimension.EXTERNAL, EffectTargetKind.FILE, "/output.bin"),
        (EffectDimension.EXTERNAL, EffectTargetKind.LOG, "stdout"),
    ))
    collision = replace(boundary.occurrences[1], id=boundary.occurrences[0].id)
    boundary = replace(boundary, occurrences=(boundary.occurrences[0], collision))
    ignore_log = EffectPolicyRule(EffectDimension.EXTERNAL, EffectTargetKind.LOG, "*", PolicyAction.IGNORE)
    _assert_uncertified(lambda: evaluate_removal(boundary, _policy(claim, ignore_log), semantic))


def test_present_summary_effect_cannot_disappear_with_deleted_occurrence(tmp_path):
    semantic, boundary, claim = _fixture(tmp_path, specs=(
        (EffectDimension.EXTERNAL, EffectTargetKind.FILE, "/output.bin"),))
    boundary = replace(boundary, occurrences=())
    _assert_uncertified(lambda: evaluate_removal(boundary, _policy(claim), semantic))


def test_policy_evidence_from_another_scope_cannot_authorize_ignoring(tmp_path):
    semantic, boundary, claim = _fixture(tmp_path, specs=(
        (EffectDimension.EXTERNAL, EffectTargetKind.LOG, "stdout"),))
    other_claim = replace(claim, scope="another-run-and-region")
    ignore_log = EffectPolicyRule(EffectDimension.EXTERNAL, EffectTargetKind.LOG, "*", PolicyAction.IGNORE)
    _assert_uncertified(lambda: evaluate_removal(boundary, _policy(other_claim, ignore_log), semantic))


def test_unlisted_dimension_kind_and_reference_all_remain_preserved(tmp_path):
    semantic, boundary, claim = _fixture(tmp_path, specs=(
        (EffectDimension.EXTERNAL, EffectTargetKind.LOG, "stdout"),
        (EffectDimension.WRITES, EffectTargetKind.LOG, "stdout"),
        (EffectDimension.EXTERNAL, EffectTargetKind.FILE, "stdout"),
        (EffectDimension.EXTERNAL, EffectTargetKind.LOG, "audit"),
    ))
    rule = EffectPolicyRule(EffectDimension.EXTERNAL, EffectTargetKind.LOG, "stdout", PolicyAction.IGNORE)
    result = evaluate_removal(boundary, _policy(claim, rule), semantic)
    assert result.ignored_effects == ("effect:0",)
    assert result.required_effects == ("effect:1", "effect:2", "effect:3")
    assert not result.removal_effects_satisfied


def test_partial_coverage_yields_concrete_requests_even_when_policy_ignores_logs(tmp_path):
    semantic, boundary, claim = _fixture(tmp_path, complete=False, specs=(
        (EffectDimension.EXTERNAL, EffectTargetKind.LOG, "stdout"),))
    rule = EffectPolicyRule(EffectDimension.EXTERNAL, EffectTargetKind.LOG, "*", PolicyAction.IGNORE)
    result = evaluate_removal(boundary, _policy(claim, rule), semantic)
    assert result.disposition is Disposition.CONTRACT
    assert not result.removal_effects_satisfied
    assert {request.dimension for request in result.requests} == set(EffectDimension)
    assert all(request.definitions and request.sources and request.missing_fact
               and request.completion and request.invalidation for request in result.requests)
    assert all(request.rerun_argv is None for request in result.requests)


def test_empty_collector_executable_cannot_be_an_instrument_request(tmp_path):
    semantic, boundary, claim = _fixture(tmp_path, complete=False)
    try:
        capability = CollectorCapability("bad-command", ScopeMode.ALL_PATHS,
            tuple(EffectDimension), ("effects",), ("",), "fixture:collector")
        result = evaluate_removal(boundary, _policy(claim), semantic,
            mode=ScopeMode.ALL_PATHS, collectors=(capability,),
            run_manifest=RunManifest(("python", "program.py"), str(tmp_path), "env"))
    except ValueError:
        return
    assert all(request.disposition is not Disposition.INSTRUMENT for request in result.requests)


def test_assessment_wire_cannot_assert_satisfied_without_ready_boundary(tmp_path):
    semantic, boundary, claim = _fixture(tmp_path)
    document = evaluate_removal(boundary, _policy(claim), semantic).to_dict()
    document["assessment"].update(removal_effects_satisfied=True, ready_for_region_construction=False)
    with pytest.raises(ValueError):
        ContractAssessment.from_dict(document)


def test_assessment_wire_cannot_assert_satisfied_with_required_effects(tmp_path):
    semantic, boundary, claim = _fixture(tmp_path, specs=(
        (EffectDimension.EXTERNAL, EffectTargetKind.FILE, "/output.bin"),))
    document = evaluate_removal(boundary, _policy(claim), semantic).to_dict()
    document["assessment"]["removal_effects_satisfied"] = True
    with pytest.raises(ValueError):
        ContractAssessment.from_dict(document)


def test_json_numeric_overflow_is_rejected_at_load_boundary():
    with pytest.raises(ValueError):
        loads('{"confidence":1e999}')


@pytest.mark.parametrize("members", [(), (OperationDefinitionID("not-in-semantic-graph"),)])
def test_ready_boundary_must_name_existing_semantic_region_members(tmp_path, members):
    semantic, boundary, claim = _fixture(tmp_path)
    boundary = replace(boundary, members=members)
    _assert_uncertified(lambda: evaluate_removal(boundary, _policy(claim), semantic))
