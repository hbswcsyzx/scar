"""Recomputable fixed-rule proof ledger tests."""
from dataclasses import replace
import json

import pytest

from scar.analysis.constants_v2 import (
    BuiltinRuntime, ConstantRuntimeRequirement,
)
from scar.analysis.effects_v2 import (
    EffectClosureEngine, EffectCoverage, EffectDimension, EffectOccurrence,
    ObservationScope, OperationEffects, ScopeMode,
)
from scar.analysis.proof_ledger_v2 import (
    ProofContext, ProofFamily, ProofLedger, ProofOutcome, ProofQ,
    ProofRequest, QAssumption, QPredicate, ReusePair,
    dead_effect_coverage_q_subject, dead_scope_closure_q_subject,
    derive_proof_ledger, target_runtime_q_subject, validate_proof_ledger,
)
from scar.analysis.regions_v2 import RegionInventory, RegionView
from scar.analysis.source_semantics_v2 import extract_source_semantics
from scar.ir.frontend_v2 import build_semantic
from scar.ir.literals import PythonLiteral
from scar.ir.semantics_v2 import Opcode, SourceExecutionPrecondition
from scar.ir.v2 import (
    Completeness, ControlRegionID, EffectTarget, EffectTargetKind,
    EvidenceClaim, EvidenceGraph, EvidenceKind, IRBundle,
    OperationInstance, OperationInstanceID, ProofStatus, RegionMove,
    StaticValueSubstitution, TransformDelta, ValueGraph,
)


def _evidence(scope, reference="test:declared-semantic-condition",
              kind=EvidenceKind.DECLARED):
    return EvidenceClaim(kind, (reference,), scope=scope)


def _assumptions(scope, result_id, operation_id, *, preconditions=()):
    evidence = _evidence(scope)
    assumptions = [
        QAssumption(QPredicate.VALUE_CONTENT_ONLY, result_id, evidence),
        QAssumption(QPredicate.VALUE_IDENTITY_UNOBSERVED, result_id, evidence),
        QAssumption(QPredicate.RESOURCE_FAILURE_UNOBSERVED, operation_id, evidence),
    ]
    for requirement in ConstantRuntimeRequirement:
        subject = target_runtime_q_subject(requirement, BuiltinRuntime.current())
        predicate = (QPredicate.TARGET_RUNTIME_MATCH
                     if requirement is ConstantRuntimeRequirement.BUILTIN_RUNTIME_MATCH
                     else QPredicate.FLOATING_ENVIRONMENT_MATCH)
        assumptions.append(QAssumption(predicate, subject, evidence))
    assumptions.extend(QAssumption(QPredicate.SOURCE_PRECONDITION, item.value, evidence)
                       for item in preconditions)
    return tuple(assumptions)


def _base(tmp_path, text, *, effect_engine=None, view=RegionView.SEMANTIC,
          evidence_graph=None):
    source = tmp_path / "program.py"
    source.write_text(text)
    semantic = build_semantic(source).graph
    source_model = extract_source_semantics(semantic)
    evidence_graph = evidence_graph or EvidenceGraph()
    bundle = IRBundle(semantic, evidence_graph, ValueGraph(),
                      source_semantics=source_model)
    inventory = RegionInventory(bundle, view=view, effects=effect_engine,
                                scope=(next(iter(effect_engine.scopes))
                                       if effect_engine is not None else None))
    members = (tuple(source_model.operations) if view is RegionView.SEMANTIC
               else tuple(evidence_graph.instances))
    region = inventory.region(members)
    return source, bundle, source_model, inventory, region


def _operation(model, opcode, line):
    matches = [item for item in model.operations.values()
               if item.opcode is opcode and item.source.start_line == line]
    assert len(matches) == 1
    return matches[0]


def _constant_case(tmp_path, text, opcode, line, literal, *, preconditions=()):
    _, bundle, model, inventory, region = _base(tmp_path, text)
    operation = _operation(model, opcode, line)
    assert operation.result is not None
    q = ProofQ(inventory.scope, _assumptions(inventory.scope,
        operation.result.wire, operation.operation.wire,
        preconditions=preconditions))
    context = ProofContext(bundle, model, inventory, inventory.scope, q)
    request = ProofRequest(ProofFamily.CONSTANT, region,
        TransformDelta(static_substitutions=(StaticValueSubstitution(
            operation.result, operation.operation, operation.source,
            PythonLiteral.from_python(literal)),)))
    return context, request, operation


def _all_coverage(scope, evidence_kind=EvidenceKind.DECLARED):
    claim = _evidence(scope, "test:all-path-effect-coverage", evidence_kind)
    return tuple(EffectCoverage(scope, dimension, Completeness.COMPLETE,
        branches=Completeness.COMPLETE, calls=Completeness.COMPLETE,
        aliases=Completeness.COMPLETE, evidence=(claim,))
        for dimension in EffectDimension)


def _dead_case(tmp_path, text, *, closed=True, mode=ScopeMode.ALL_PATHS,
               effect_dimension=None, accept_effect_q=False,
               source_preconditions=(), evidence_kind=EvidenceKind.DECLARED):
    source = tmp_path / "program.py"
    source.write_text(text)
    semantic = build_semantic(source).graph
    model = extract_source_semantics(semantic)
    scope = "dead-test-scope"
    engine = EffectClosureEngine(semantic)
    closure_evidence = _evidence(scope, "test:closed-effect-endpoint", evidence_kind)
    engine.add_scope(ObservationScope(scope, "entry", "exit" if closed else None,
        "run", mode, "test-clock", closed=closed,
        evidence=(closure_evidence,) if closed else ()))
    selected = next(item for item in model.operations.values()
                    if item.opcode is Opcode.ADD)
    line = selected.source.start_line
    removed = tuple(identity for identity, definition in semantic.definitions.items()
        if any(semantic.source_atoms[atom].reference.start_line == line
               for atom in definition.source_atoms)
        and definition.kind.value != "module")
    occurrences = ()
    if effect_dimension is not None:
        occurrence = EffectOccurrence("known-effect", selected.operation,
            effect_dimension, EffectTarget(EffectTargetKind.LOG, "test-log"),
            scope, 0, closure_evidence)
        engine.add_occurrence(occurrence)
        occurrences = (occurrence.id,)
    for identity in removed:
        engine.add_operation_effects(OperationEffects(identity, scope,
            occurrences if identity == selected.operation else (),
            _all_coverage(scope, evidence_kind)))
    bundle = IRBundle(semantic, EvidenceGraph(), ValueGraph(),
                      source_semantics=model)
    inventory = RegionInventory(bundle, effects=engine, scope=scope)
    region = inventory.region(tuple(semantic.definitions))
    assumptions = []
    q_evidence = _evidence(scope, "test:accepted-effect-closure-q")
    if accept_effect_q:
        boundary = engine.boundary(removed, scope)
        for coverage in boundary.coverage:
            if (coverage.closed and "*" in coverage.target_domain
                    and (coverage.assumptions or any(
                        claim.kind is EvidenceKind.DECLARED for claim in coverage.evidence))):
                assumptions.append(QAssumption(QPredicate.EFFECT_COVERAGE_ACCEPTED,
                    dead_effect_coverage_q_subject(coverage), q_evidence))
        scope_record = engine.scopes[scope]
        if (scope_record.closed and any(claim.kind is EvidenceKind.DECLARED
                                        for claim in scope_record.evidence)):
            assumptions.append(QAssumption(QPredicate.SCOPE_CLOSURE_ACCEPTED,
                dead_scope_closure_q_subject(scope_record), q_evidence))
    assumptions.extend(QAssumption(QPredicate.SOURCE_PRECONDITION, item.value, q_evidence)
                       for item in source_preconditions)
    context = ProofContext(bundle, model, inventory, scope,
                           ProofQ(scope, tuple(assumptions)), engine)
    request = ProofRequest(ProofFamily.DEAD, region,
        TransformDelta(removed_definitions=removed))
    return context, request, selected


def test_constant_positive_requires_exact_runtime_and_typed_conditional_q(tmp_path):
    context, request, operation = _constant_case(
        tmp_path, "answer = 2 + 3\n", Opcode.ADD, 1, 5)

    ledger = derive_proof_ledger(context, request)

    assert ledger.outcome is ProofOutcome.CONDITIONALLY_LEGAL
    assert all(item.status is ProofStatus.PROVEN for item in ledger.obligations)
    runtime = next(item for item in ledger.obligations
                   if item.name == "runtime_requirement_in_Q")
    assert runtime.conditions[0].predicate is QPredicate.TARGET_RUNTIME_MATCH
    assert runtime.conditions[0].subject == target_runtime_q_subject(
        ConstantRuntimeRequirement.BUILTIN_RUNTIME_MATCH, BuiltinRuntime.current())
    q_backed = [item for item in ledger.obligations if item.conditions]
    assert q_backed and all(claim.kind is EvidenceKind.DECLARED
                            for item in q_backed for claim in item.evidence)
    assert ledger.delta.static_substitutions[0].operation == operation.operation
    assert validate_proof_ledger(ledger, context, request)["valid"]
    assert ProofLedger.from_json(ledger.to_json(), context=context,
                                 request=request) == ledger


def test_constant_positive_rechecks_transitive_binding_preconditions(tmp_path):
    required = tuple(SourceExecutionPrecondition)
    context, request, _ = _constant_case(tmp_path,
        "base = 40\nanswer = base + 2\n", Opcode.ADD, 2, 42,
        preconditions=required)

    ledger = derive_proof_ledger(context, request)

    preconditions = [item for item in ledger.obligations
                     if item.name == "source_precondition_in_Q"]
    assert {item.subject.rsplit(":", 1)[-1] for item in preconditions} == {
        SourceExecutionPrecondition.FRESH_MODULE_NAMESPACE.value,
        SourceExecutionPrecondition.NO_EXTERNAL_NAMESPACE_MUTATION.value,
    }
    assert all(item.status is ProofStatus.PROVEN for item in preconditions)
    assert ledger.outcome is ProofOutcome.CONDITIONALLY_LEGAL


def test_missing_content_condition_stays_declared_and_needs_contract(tmp_path):
    context, request, operation = _constant_case(
        tmp_path, "answer = 2 + 3\n", Opcode.ADD, 1, 5)
    assumptions = tuple(item for item in context.q.assumptions
                        if item.predicate is not QPredicate.VALUE_CONTENT_ONLY)
    context = replace(context, q=replace(context.q, assumptions=assumptions))

    ledger = derive_proof_ledger(context, request)

    content = next(item for item in ledger.obligations
                   if item.name == "replacement_observation_is_value_content_only")
    assert content.status is ProofStatus.UNKNOWN
    assert "value-content-only" in content.reason
    assert ledger.outcome is ProofOutcome.NEEDS_CONTRACT
    assert not any(item.status is ProofStatus.PROVEN and item.name.endswith("_in_Q")
                   and operation.operation.wire in item.subject for item in ledger.obligations)


def test_known_exception_cannot_be_replaced_with_a_literal(tmp_path):
    context, request, _ = _constant_case(
        tmp_path, "answer = 1 // 0\n", Opcode.FLOOR_DIV, 1, 0)

    ledger = derive_proof_ledger(context, request)

    exact_value = next(item for item in ledger.obligations
                       if item.name == "constant_value_matches_replacement")
    assert exact_value.status is ProofStatus.DISPROVEN
    assert "raises" in exact_value.reason
    assert ledger.outcome is ProofOutcome.ILLEGAL


def test_dead_positive_needs_closed_all_path_consumers_and_effects(tmp_path):
    context, request, selected = _dead_case(tmp_path, "1 + 2\n",
                                             accept_effect_q=True)

    ledger = derive_proof_ledger(context, request)

    assert ledger.outcome is ProofOutcome.CONDITIONALLY_LEGAL
    assert next(item for item in ledger.obligations
                if item.name == "source_consumers_closed").status is ProofStatus.PROVEN
    assert next(item for item in ledger.obligations
                if item.name == "removed_effects_allowed_by_Q").status is ProofStatus.PROVEN
    accepted = [item for item in ledger.obligations
                if item.name in {"effect_coverage_declaration_in_Q",
                                 "scope_closure_declaration_in_Q"}]
    assert accepted and all(item.status is ProofStatus.PROVEN for item in accepted)
    assert all(claim.kind is EvidenceKind.DECLARED
               for item in accepted for claim in item.evidence)
    assert selected.operation in request.delta.removed_definitions


def test_dead_live_binding_consumer_without_source_q_is_unknown(tmp_path):
    context, request, _ = _dead_case(tmp_path,
        "answer = 1 + 2\nprint(answer)\n", accept_effect_q=True)

    ledger = derive_proof_ledger(context, request)

    source_consumers = [item for item in ledger.obligations
                        if item.name == "source_consumers_closed"]
    source_preconditions = [item for item in ledger.obligations
                            if item.name == "source_precondition_in_Q"]
    assert source_preconditions
    assert all(item.status is ProofStatus.UNKNOWN for item in source_preconditions)
    assert all(item.status is not ProofStatus.DISPROVEN for item in source_consumers)
    assert ledger.outcome is ProofOutcome.NEEDS_CONTRACT


def test_dead_live_binding_consumer_is_disproven_after_source_q_acceptance(tmp_path):
    required = (SourceExecutionPrecondition.FRESH_MODULE_NAMESPACE,
                SourceExecutionPrecondition.NO_EXTERNAL_NAMESPACE_MUTATION)
    context, request, _ = _dead_case(tmp_path,
        "answer = 1 + 2\nprint(answer)\n", accept_effect_q=True,
        source_preconditions=required)

    ledger = derive_proof_ledger(context, request)

    source_consumers = [item for item in ledger.obligations
                        if item.name == "source_consumers_closed"]
    assert any(item.status is ProofStatus.DISPROVEN for item in source_consumers)
    assert all(item.status is ProofStatus.PROVEN for item in ledger.obligations
               if item.name == "source_precondition_in_Q")
    assert ledger.outcome is ProofOutcome.ILLEGAL


def test_dead_open_consumer_scope_stays_unknown(tmp_path):
    context, request, _ = _dead_case(tmp_path, "1 + 2\n", closed=False,
                                     accept_effect_q=True)

    ledger = derive_proof_ledger(context, request)

    consumers = next(item for item in ledger.obligations
                     if item.name == "output_consumers_closed")
    assert consumers.status is ProofStatus.UNKNOWN
    assert ledger.outcome is ProofOutcome.NEEDS_CONTRACT


def test_dead_effect_preserved_by_default_q_is_illegal(tmp_path):
    context, request, _ = _dead_case(tmp_path, "1 + 2\n",
                                     effect_dimension=EffectDimension.EXTERNAL,
                                     accept_effect_q=True)

    ledger = derive_proof_ledger(context, request)

    effects = next(item for item in ledger.obligations
                   if item.name == "removed_effects_allowed_by_Q")
    assert effects.status is ProofStatus.DISPROVEN
    assert ledger.outcome is ProofOutcome.ILLEGAL


def test_dead_declared_empty_effect_closure_requires_q_and_keeps_provenance(tmp_path):
    context, request, _ = _dead_case(tmp_path, "1 + 2\n")

    ledger = derive_proof_ledger(context, request)

    effect = next(item for item in ledger.obligations
                  if item.name == "removed_effects_allowed_by_Q")
    accepted = [item for item in ledger.obligations
                if item.name in {"effect_coverage_declaration_in_Q",
                                 "scope_closure_declaration_in_Q"}]
    assert effect.status is ProofStatus.UNKNOWN
    assert ledger.outcome is ProofOutcome.NEEDS_CONTRACT
    assert len(accepted) == len(EffectDimension) + 1
    assert all(item.status is ProofStatus.UNKNOWN for item in accepted)
    assert all(claim.kind is EvidenceKind.DECLARED
               for item in accepted for claim in item.evidence)
    assert any(claim.kind is EvidenceKind.DECLARED for claim in effect.evidence)


def test_dead_observed_effect_closure_is_not_upgraded_to_declared_or_q(tmp_path):
    context, request, _ = _dead_case(tmp_path, "1 + 2\n",
        evidence_kind=EvidenceKind.OBSERVED)

    ledger = derive_proof_ledger(context, request)

    effect = next(item for item in ledger.obligations
                  if item.name == "removed_effects_allowed_by_Q")
    assert effect.status is ProofStatus.PROVEN
    assert not any(item.name in {"effect_coverage_declaration_in_Q",
                                 "scope_closure_declaration_in_Q"}
                   for item in ledger.obligations)
    assert effect.evidence
    assert all(claim.kind is EvidenceKind.OBSERVED for claim in effect.evidence)


def test_ledger_validation_recomputes_fixed_obligation_set_and_q_hash(tmp_path):
    context, request, _ = _constant_case(
        tmp_path, "answer = 2 + 3\n", Opcode.ADD, 1, 5)
    ledger = derive_proof_ledger(context, request)
    assert not validate_proof_ledger(replace(ledger,
        obligations=ledger.obligations[:-1]), context, request)["valid"]
    assumptions = tuple(item for item in context.q.assumptions
                        if item.predicate is not QPredicate.VALUE_IDENTITY_UNOBSERVED)
    stale_q = replace(context, q=replace(context.q, assumptions=assumptions))
    assert not validate_proof_ledger(ledger, stale_q, request)["valid"]
    ledger_with_unknown = derive_proof_ledger(stale_q, request)
    unknown = next(index for index, item in enumerate(ledger_with_unknown.obligations)
                   if item.status is ProofStatus.UNKNOWN)
    forged_items = list(ledger_with_unknown.obligations)
    forged_items[unknown] = replace(forged_items[unknown],
                                    status=ProofStatus.PROVEN, reason="")
    assert not validate_proof_ledger(replace(ledger_with_unknown,
        obligations=tuple(forged_items)), stale_q, request)["valid"]
    stale_scope = replace(context, scope=context.scope + ":stale")
    assert not validate_proof_ledger(ledger, stale_scope, request)["valid"]


def test_reuse_reports_fixed_missing_positive_obligations_without_false_proofs(tmp_path):
    source = tmp_path / "program.py"
    source.write_text("value = 1\n")
    semantic = build_semantic(source).graph
    source_model = extract_source_semantics(semantic)
    definition = next(iter(semantic.definitions))
    evidence = EvidenceGraph()
    source_instance, removed_instance = (OperationInstanceID("call:source"),
                                         OperationInstanceID("call:removed"))
    evidence.add_instance(OperationInstance(source_instance, definition, 1, 1))
    evidence.add_instance(OperationInstance(removed_instance, definition, 1, 1))
    bundle = IRBundle(semantic, evidence, ValueGraph(), source_semantics=source_model)
    inventory = RegionInventory(bundle, view=RegionView.EXECUTION)
    region = inventory.region((source_instance, removed_instance))
    context = ProofContext(bundle, source_model, inventory, inventory.scope,
                           ProofQ(inventory.scope))
    request = ProofRequest(ProofFamily.REUSE, region,
        TransformDelta(removed_instances=(removed_instance,)),
        (ReusePair(source_instance, removed_instance),))

    ledger = derive_proof_ledger(context, request)

    assert ledger.outcome is ProofOutcome.NOT_YET_SUPPORTED
    assert {item.name for item in ledger.obligations} == {
        "exact_inputs_and_hidden_state_match", "effects_rng_and_exception_equivalence",
        "output_identity_alias_and_mutability", "autograd_hooks_callbacks_and_consumers",
    }
    assert all(item.status is ProofStatus.UNKNOWN and item.reason
               for item in ledger.obligations)
    cycle = list(ledger.obligations)
    cycle[0] = replace(cycle[0], dependencies=(cycle[1].id,))
    assert not validate_proof_ledger(replace(ledger, obligations=tuple(cycle)),
                                     context, request)["valid"]
    with pytest.raises(ValueError, match="exactly account"):
        derive_proof_ledger(context, replace(request,
            reuse_pairs=(ReusePair(source_instance, removed_instance),),
            delta=TransformDelta(removed_instances=(source_instance,))))


def test_motion_requires_real_control_delta_and_reports_unsupported(tmp_path):
    _, bundle, source_model, inventory, region = _base(
        tmp_path, "if True:\n    value = 1\n")
    controls = tuple(bundle.semantic.controls)
    assert len(controls) >= 2
    request = ProofRequest(ProofFamily.MOTION, region,
        TransformDelta(moves=(RegionMove(region, controls[0], controls[1]),)))
    context = ProofContext(bundle, source_model, inventory, inventory.scope,
                           ProofQ(inventory.scope))

    ledger = derive_proof_ledger(context, request)

    assert ledger.outcome is ProofOutcome.NOT_YET_SUPPORTED
    assert len(ledger.obligations) == 6
    assert all(item.status is ProofStatus.UNKNOWN and
               "not yet supported" in item.reason for item in ledger.obligations)
    bad_move = RegionMove(region, controls[0], ControlRegionID("control:unknown"))
    with pytest.raises(ValueError, match="unknown control region"):
        derive_proof_ledger(context, replace(request,
            delta=TransformDelta(moves=(bad_move,))))
