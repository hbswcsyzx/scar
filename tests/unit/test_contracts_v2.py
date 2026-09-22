from dataclasses import replace
import json

import pytest

from scar.analysis.contracts_v2 import (
    CollectorCapability, ContractAssessment, Disposition, EffectPolicy, EffectPolicyRule,
    PolicyAction, RunManifest, evaluate_removal,
)
from scar.analysis.effects_v2 import (
    EffectClosureEngine, EffectCoverage, EffectDimension, EffectOccurrence,
    ObservationScope, OperationEffects, ScopeMode,
)
from scar.ir.frontend_v2 import build_semantic
from scar.ir.v2 import Completeness, EffectTarget, EffectTargetKind, EvidenceClaim, EvidenceKind


def fixture(tmp_path, *, complete=True, targets=(EffectTargetKind.LOG,)):
    source = tmp_path / "program.py"
    source.write_text("def initialize():\n    return 7\n")
    semantic = build_semantic(source).graph
    definition = next(item.id for item in semantic.definitions.values() if item.source_atoms)
    evidence = EvidenceClaim(EvidenceKind.DECLARED, ("fixture:reviewed-effect-contract",), scope="fixture")
    engine = EffectClosureEngine(semantic)
    engine.add_scope(ObservationScope("fixture", "entry", "exit", "run", ScopeMode.ALL_PATHS,
                                      "semantic", closed=True, evidence=(evidence,)))
    effects = []
    for index, kind in enumerate(targets):
        effect = EffectOccurrence(f"effect:{index}", definition, EffectDimension.EXTERNAL,
            EffectTarget(kind, "channel"), "fixture", index, evidence)
        engine.add_occurrence(effect)
        effects.append(effect.id)
    coverages = tuple(EffectCoverage("fixture", dimension,
        Completeness.COMPLETE if complete else Completeness.UNKNOWN,
        branches=Completeness.COMPLETE if complete else Completeness.UNKNOWN,
        calls=Completeness.COMPLETE if complete else Completeness.UNKNOWN,
        aliases=Completeness.COMPLETE if complete else Completeness.UNKNOWN,
        evidence=(evidence,) if complete else ()) for dimension in EffectDimension)
    engine.add_operation_effects(OperationEffects(definition, "fixture", tuple(effects), coverages))
    return semantic, engine.boundary((definition,), "fixture"), evidence


def test_q_profiles_explain_different_required_effects(tmp_path):
    semantic, boundary, evidence = fixture(tmp_path)
    strict = EffectPolicy("strict", "fixture", (), evidence)
    relaxed = EffectPolicy("ignore-log", "fixture", (EffectPolicyRule(
        EffectDimension.EXTERNAL, EffectTargetKind.LOG, "*", PolicyAction.IGNORE),), evidence)
    before = evaluate_removal(boundary, strict, semantic)
    after = evaluate_removal(boundary, relaxed, semantic)
    assert before.disposition is Disposition.KEEP and not before.removal_effects_satisfied
    assert before.required_effects == ("effect:0",)
    assert after.removal_effects_satisfied and after.ignored_effects == ("effect:0",)
    assert after.disposition is Disposition.KEEP  # This gate never selects a rewrite.


def test_logging_ignore_does_not_ignore_environment_or_file_write(tmp_path):
    semantic, boundary, evidence = fixture(tmp_path, targets=(
        EffectTargetKind.LOG, EffectTargetKind.ENVIRONMENT, EffectTargetKind.FILE))
    policy = EffectPolicy("ignore-log", "fixture", (EffectPolicyRule(
        EffectDimension.EXTERNAL, EffectTargetKind.LOG, "*", PolicyAction.IGNORE),), evidence)
    result = evaluate_removal(boundary, policy, semantic)
    assert result.required_effects == ("effect:1", "effect:2")
    assert result.ignored_effects == ("effect:0",)


def test_unknown_facets_default_to_preserve_and_specific_rule_wins(tmp_path):
    semantic, boundary, evidence = fixture(tmp_path)
    rules = (EffectPolicyRule(EffectDimension.EXTERNAL, EffectTargetKind.LOG, "*", PolicyAction.IGNORE),
             EffectPolicyRule(EffectDimension.EXTERNAL, EffectTargetKind.LOG, "channel", PolicyAction.PRESERVE))
    result = evaluate_removal(boundary, EffectPolicy("specific", "fixture", rules, evidence), semantic)
    assert result.required_effects == ("effect:0",)
    with pytest.raises(ValueError, match="duplicate"):
        EffectPolicy("duplicate", "fixture", (rules[0], rules[0]), evidence)


def test_unknown_coverage_becomes_concrete_source_contract_requests(tmp_path):
    semantic, boundary, evidence = fixture(tmp_path, complete=False, targets=())
    result = evaluate_removal(boundary, EffectPolicy("strict", "fixture", (), evidence), semantic)
    assert result.disposition is Disposition.CONTRACT
    assert not result.ready_for_region_construction
    assert result.requests
    for request in result.requests:
        assert request.sources and request.sources[0].fingerprint
        assert request.missing_fact and request.completion and request.scope == "fixture"
        assert request.rerun_argv is None  # Missing execution context is never invented.


def test_supported_request_contains_source_scope_fields_and_argv(tmp_path):
    semantic, boundary, evidence = fixture(tmp_path, complete=False, targets=())
    capability = CollectorCapability("fixture-collector", ScopeMode.ALL_PATHS, tuple(EffectDimension),
        ("reads", "writes", "branch/call/alias coverage"),
        ("python", "collector.py"), "fixture:test-collector-contract")
    manifest = RunManifest(("python", "program.py", "literal $(unsafe)"), str(tmp_path), "fixture-env")
    result = evaluate_removal(boundary, EffectPolicy("strict", "fixture", (), evidence), semantic,
        mode=ScopeMode.ALL_PATHS, collectors=(capability,), run_manifest=manifest)
    assert result.disposition is Disposition.INSTRUMENT
    assert all(request.rerun_argv == capability.command_prefix + ("--",) + manifest.argv
               for request in result.requests)
    assert all(request.environment_identity == "fixture-env" for request in result.requests)


def test_dynamic_collector_cannot_certify_all_paths(tmp_path):
    semantic, boundary, evidence = fixture(tmp_path, complete=False, targets=())
    capability = CollectorCapability("observed-path", ScopeMode.DYNAMIC_PATH, tuple(EffectDimension),
        ("runtime events",), ("scar", "trace"), "fixture:dynamic-only")
    result = evaluate_removal(boundary, EffectPolicy("strict", "fixture", (), evidence), semantic,
        mode=ScopeMode.ALL_PATHS, collectors=(capability,),
        run_manifest=RunManifest(("python", "program.py"), str(tmp_path), "fixture-env"))
    assert result.disposition is Disposition.CONTRACT


def test_known_required_effect_keeps_region_while_retaining_other_gaps(tmp_path):
    semantic, boundary, evidence = fixture(tmp_path, complete=False)
    result = evaluate_removal(boundary, EffectPolicy("strict", "fixture", (), evidence), semantic)
    assert result.disposition is Disposition.KEEP
    assert result.required_effects and result.requests


def test_assessment_and_policy_roundtrip_are_strict_and_deterministic(tmp_path):
    semantic, boundary, evidence = fixture(tmp_path, complete=False)
    policy = EffectPolicy("strict", "fixture", (), evidence)
    result = evaluate_removal(boundary, policy, semantic)
    encoded = json.dumps(result.to_dict(), sort_keys=True)
    assert ContractAssessment.from_json(encoded).to_dict() == result.to_dict()
    assert EffectPolicy.from_dict(policy.to_dict()) == policy
    assert evaluate_removal(boundary, policy, semantic).to_dict() == result.to_dict()
    with pytest.raises(ValueError, match="duplicate JSON"):
        ContractAssessment.from_json('{"schema":"x","schema":"y"}')
    document = policy.to_dict()
    document["schema_version"] = True
    with pytest.raises(ValueError):
        EffectPolicy.from_dict(document)


def test_inconsistent_scope_and_unknown_removed_effect_are_rejected(tmp_path):
    semantic, boundary, evidence = fixture(tmp_path)
    with pytest.raises(ValueError, match="scopes differ"):
        evaluate_removal(boundary, EffectPolicy("other", "elsewhere", (), replace(evidence, scope="elsewhere")), semantic)
    with pytest.raises(ValueError, match="unknown effect"):
        evaluate_removal(boundary, EffectPolicy("strict", "fixture", (), evidence), semantic,
                         removed_effect_ids=("absent",))


def test_incomplete_coverage_cannot_hide_behind_an_empty_gap_list(tmp_path):
    semantic, boundary, evidence = fixture(tmp_path, complete=False, targets=())
    forged = replace(boundary, gaps=(), ready_for_region_construction=True)
    result = evaluate_removal(forged, EffectPolicy("strict", "fixture", (), evidence), semantic)
    assert not result.removal_effects_satisfied
    assert result.requests
