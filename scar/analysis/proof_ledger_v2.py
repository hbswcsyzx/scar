"""Fixed, recomputable proof obligations for report-only graph rewrites.

The ledger stores conclusions, never proof authority.  ``validate_proof_ledger``
and the JSON readers rebuild the obligation set and every status from the source,
semantic, region, effect, Q and delta models supplied by the caller.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from typing import Any

from scar.analysis.constants_v2 import (
    ConstantRuntimeRequirement,
    ConstantStatus,
    EvaluationBudget,
    evaluate_constants,
)
from scar.analysis.contracts_v2 import EffectPolicy, evaluate_removal
from scar.analysis.effects_v2 import (
    ClosureState, EffectCoverage,
    EffectClosureEngine,
    EffectDimension,
    ObservationScope,
    ScopeMode,
)
from scar.analysis.region_queries_v2 import MotionQuery, RegionQueries
from scar.analysis.regions_v2 import RegionInventory, RegionView
from scar.analysis.source_semantics_v2 import validate_source_semantics
from scar.ir import semantics_v2 as sm
from scar.ir.record_codec import decode, encode, loads
from scar.ir.v2 import (
    ContractID,
    EffectTarget,
    EffectTargetKind,
    EvidenceClaim,
    EvidenceKind,
    IRBundle,
    OperationDefinitionID,
    OperationInstanceID,
    OptimizationRegionID,
    ProofStatus,
    TransformDelta,
)
from scar.ir.v2._validation import cycle_errors, record_errors
from scar.ir.v2.optimization import StaticValueSubstitution


RULE_VERSION = "scar.proof-ledger.v2.1"
SCHEMA = "scar.proof-ledger.v2"
SCHEMA_VERSION = 1


class ProofFamily(str, Enum):
    CONSTANT = "CONSTANT"
    DEAD = "DEAD"
    REUSE = "REUSE"
    MOTION = "MOTION"


class ProofOutcome(str, Enum):
    CONDITIONALLY_LEGAL = "CONDITIONALLY_LEGAL"
    NEEDS_CONTRACT = "NEEDS_CONTRACT"
    ILLEGAL = "ILLEGAL"
    NOT_YET_SUPPORTED = "NOT_YET_SUPPORTED"


class QPredicate(str, Enum):
    """Closed set of conditional semantic predicates understood by this ledger."""

    SOURCE_PRECONDITION = "source_precondition"
    TARGET_RUNTIME_MATCH = "target_runtime_match"
    FLOATING_ENVIRONMENT_MATCH = "floating_environment_match"
    VALUE_CONTENT_ONLY = "value_content_only"
    VALUE_IDENTITY_UNOBSERVED = "value_identity_unobserved"
    RESOURCE_FAILURE_UNOBSERVED = "resource_failure_unobserved"
    EFFECT_COVERAGE_ACCEPTED = "effect_coverage_accepted"
    SCOPE_CLOSURE_ACCEPTED = "scope_closure_accepted"


@dataclass(frozen=True)
class QAssumption:
    """An explicit, scoped Q condition.  It remains DECLARED in every proof."""

    predicate: QPredicate
    subject: str
    evidence: EvidenceClaim

    def __post_init__(self):
        if not self.subject:
            raise ValueError("Q assumption needs a precise subject")
        if self.evidence.kind is not EvidenceKind.DECLARED or not self.evidence.references:
            raise ValueError("Q assumptions require auditable DECLARED evidence")
        if self.evidence.scope is None:
            raise ValueError("Q assumption evidence must name its scope")


@dataclass(frozen=True)
class ProofQ:
    """Behavioral contract and declared preconditions for one analysis scope."""

    scope: str
    assumptions: tuple[QAssumption, ...] = ()
    effect_policy: EffectPolicy | None = None
    contracts: tuple[ContractID, ...] = ()

    def __post_init__(self):
        if not self.scope:
            raise ValueError("Q requires a scope")
        keys = [(item.predicate, item.subject) for item in self.assumptions]
        if len(keys) != len(set(keys)):
            raise ValueError("Q assumptions must be unique by predicate and subject")
        if any(item.evidence.scope != self.scope for item in self.assumptions):
            raise ValueError("Q assumption scope must match Q")
        if len(self.contracts) != len(set(self.contracts)):
            raise ValueError("Q contract references must be unique")
        if self.effect_policy is not None and self.effect_policy.scope != self.scope:
            raise ValueError("Q effect policy scope must match Q")

    def assumption(self, predicate: QPredicate, subject: str) -> QAssumption | None:
        return next((item for item in self.assumptions
                     if item.predicate is predicate and item.subject == subject), None)


@dataclass(frozen=True)
class ReusePair:
    """A proposed earlier result and the invocation whose work is removed."""

    source: OperationInstanceID
    removed: OperationInstanceID

    def __post_init__(self):
        if self.source == self.removed:
            raise ValueError("reuse pair must name distinct invocations")


@dataclass(frozen=True)
class ProofRequest:
    """A typed rule request bound to the concrete Optimization TransformDelta."""

    family: ProofFamily
    region: OptimizationRegionID
    delta: TransformDelta
    reuse_pairs: tuple[ReusePair, ...] = ()
    motion_query: MotionQuery | None = None

    def __post_init__(self):
        if len(set(self.reuse_pairs)) != len(self.reuse_pairs):
            raise ValueError("reuse pairs must be unique")
        if self.family is ProofFamily.REUSE and not self.reuse_pairs:
            # Keep unsupported families representable while making the missing
            # positive witness explicit in their fixed obligation set.
            return
        if self.family is not ProofFamily.REUSE and self.reuse_pairs:
            raise ValueError("reuse pairs belong only to REUSE requests")
        if self.family is ProofFamily.MOTION and self.motion_query is None:
            return
        if self.family is not ProofFamily.MOTION and self.motion_query is not None:
            raise ValueError("motion query belongs only to MOTION requests")


@dataclass(frozen=True)
class ProofContext:
    """Caller-owned models required for independent proof recomputation.

    ``verification_budget`` is the verifier's resource ceiling.  It is not
    serialized in a ledger and cannot be raised by a document being checked.
    """

    bundle: IRBundle
    source_semantics: sm.SourceSemanticsGraph
    inventory: RegionInventory
    scope: str
    q: ProofQ
    effect_engine: EffectClosureEngine | None = None
    source_texts: dict[str, str] | None = None
    verification_budget: EvaluationBudget = EvaluationBudget()


@dataclass(frozen=True)
class ModelReference:
    kind: str
    identity: str
    digest: str


@dataclass(frozen=True)
class ProofObligation:
    id: str
    name: str
    subject: str
    status: ProofStatus
    dependencies: tuple[str, ...] = ()
    evidence: tuple[EvidenceClaim, ...] = ()
    model_references: tuple[ModelReference, ...] = ()
    conditions: tuple[QAssumption, ...] = ()
    reason: str = ""

    def __post_init__(self):
        if not self.id or not self.name or not self.subject:
            raise ValueError("proof obligation requires identity, name and subject")
        if self.status is ProofStatus.UNKNOWN and not self.reason:
            raise ValueError("unknown proof obligation requires a reason")


@dataclass(frozen=True)
class ProofLedger:
    family: ProofFamily
    outcome: ProofOutcome
    rule_version: str
    region: OptimizationRegionID
    scope: str
    delta: TransformDelta
    request_digest: str
    source_hash: str
    model_hash: str
    q_hash: str
    region_hash: str
    scope_hash: str
    obligations: tuple[ProofObligation, ...]
    selection_status: str = "NOT_SELECTED"
    cost_status: str = "PENDING"
    applied: bool = False

    def __post_init__(self):
        if not self.scope or not self.rule_version:
            raise ValueError("proof ledger needs scope and rule version")
        if self.selection_status != "NOT_SELECTED" or self.cost_status != "PENDING" or self.applied:
            raise ValueError("proof ledger is report-only and cannot select, cost or apply a rewrite")

    def to_dict(self) -> dict[str, Any]:
        return {"schema": SCHEMA, "schema_version": SCHEMA_VERSION,
                "ledger": encode(self)}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False)

    @classmethod
    def from_dict(cls, document, *, context: ProofContext,
                  request: ProofRequest) -> "ProofLedger":
        required = {"schema", "schema_version", "ledger"}
        if (type(document) is not dict or set(document) != required
                or document["schema"] != SCHEMA or type(document["schema_version"]) is not int
                or document["schema_version"] != SCHEMA_VERSION):
            raise ValueError("unsupported proof ledger schema or fields")
        record = decode(cls, document["ledger"])
        report = validate_proof_ledger(record, context, request)
        if not report["valid"]:
            raise ValueError("invalid proof ledger: " + "; ".join(report["errors"]))
        return record

    @classmethod
    def from_json(cls, payload: str, *, context: ProofContext,
                  request: ProofRequest) -> "ProofLedger":
        return cls.from_dict(loads(payload), context=context, request=request)


def _canonical(value: Any) -> str:
    return json.dumps(encode(value), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def target_runtime_q_subject(requirement: ConstantRuntimeRequirement, runtime) -> str:
    """Return the exact Q subject for a target-runtime precondition."""
    return requirement.value + ":" + _digest(runtime)


def dead_effect_coverage_q_subject(coverage: EffectCoverage) -> str:
    """Return the Q subject for accepting one exact effect-coverage record."""
    if type(coverage) is not EffectCoverage:
        raise TypeError("coverage must be EffectCoverage")
    return coverage.scope + ":" + coverage.dimension.value + ":" + _digest(coverage)


def dead_scope_closure_q_subject(scope: ObservationScope) -> str:
    """Return the Q subject for accepting one exact observation-scope record."""
    if type(scope) is not ObservationScope:
        raise TypeError("scope must be ObservationScope")
    return scope.id + ":" + _digest(scope)


def _ref(kind: str, identity: str, value: Any) -> ModelReference:
    return ModelReference(kind, identity, _digest(value))


def _assumption(context: ProofContext, predicate: QPredicate,
                subject: str) -> QAssumption | None:
    return context.q.assumption(predicate, subject)


def _obligation_id(family: ProofFamily, name: str, subject: str) -> str:
    # Stable and readable; subject is a typed wire ID or fixed rule key.
    return f"{family.value.lower()}:{name}:{subject}"


def _new_obligation(family, name, subject, status, *, dependencies=(), evidence=(),
                    model_references=(), conditions=(), reason=""):
    return ProofObligation(_obligation_id(family, name, subject), name, subject,
        status, tuple(dependencies), tuple(evidence), tuple(model_references),
        tuple(conditions), reason)


def _validate_context(context: ProofContext, request: ProofRequest) -> dict[str, str]:
    if type(context) is not ProofContext or type(request) is not ProofRequest:
        raise TypeError("proof derivation requires ProofContext and ProofRequest")
    if type(context.verification_budget) is not EvaluationBudget:
        raise TypeError("verification_budget must be EvaluationBudget")
    context.verification_budget.__post_init__()
    context_errors = record_errors(context.q, ProofQ, "proof_context.q")
    context_errors.extend(record_errors(request, ProofRequest, "proof_request"))
    if context_errors:
        raise ValueError("invalid proof context/request: " + "; ".join(context_errors))
    if context.source_texts is not None and (
        type(context.source_texts) is not dict
        or any(type(path) is not str or type(text) is not str
               for path, text in context.source_texts.items())
    ):
        raise ValueError("source_texts must map source paths to text")
    context.bundle.assert_valid()
    if context.source_semantics.validate(context.bundle.semantic)["valid"] is not True:
        raise ValueError("source semantics graph is invalid for this semantic graph")
    source_report = validate_source_semantics(context.source_semantics,
        context.bundle.semantic, sources=context.source_texts)
    if not source_report["valid"]:
        raise ValueError("source replay failed: " + "; ".join(source_report["errors"]))
    context.inventory.assert_valid()
    if context.inventory.bundle is not context.bundle:
        raise ValueError("region inventory must refer to the supplied IRBundle object")
    if context.bundle.source_semantics is None:
        raise ValueError("proof context bundle lacks its source semantics overlay")
    if context.bundle.source_semantics.to_dict() != context.source_semantics.to_dict():
        raise ValueError("proof context source semantics differs from the bundle overlay")
    if context.inventory.scope != context.scope or context.q.scope != context.scope:
        raise ValueError("proof context, region inventory and Q scopes must match")
    if request.region not in context.inventory.graph.regions:
        raise ValueError("proof request references an unknown region")
    if context.inventory.constructions[request.region].scope != context.scope:
        raise ValueError("proof region construction has a stale or mismatched scope")
    if context.effect_engine is not None:
        context.effect_engine.assert_valid()
        if context.effect_engine.semantic is not context.bundle.semantic:
            raise ValueError("effect engine must refer to the supplied semantic graph")
        if context.effect_engine.evidence is not None and context.effect_engine.evidence is not context.bundle.evidence:
            raise ValueError("effect engine must refer to the supplied evidence graph")
        if context.scope not in context.effect_engine.scopes:
            raise ValueError("effect engine lacks the requested scope")
        if context.inventory.effects is not context.effect_engine:
            raise ValueError("region inventory/effect engine mismatch")
    elif context.inventory.effects is not None:
        raise ValueError("proof context omitted the region inventory's effect engine")
    elif context.q.effect_policy is not None:
        # Policies can be hashed without an engine, but cannot create effect facts.
        if context.q.effect_policy.scope != context.scope:
            raise ValueError("Q policy scope mismatch")
    for contract_id in context.q.contracts:
        if context.bundle.semantic.contracts.get(contract_id) is None:
            raise ValueError("Q references a contract absent from the semantic graph")
    policy = context.q.effect_policy
    if policy is not None and policy.evidence.kind is not EvidenceKind.DECLARED:
        raise ValueError("Q effect policy must remain explicitly DECLARED")
    return _context_hashes(context, request)


def _context_hashes(context: ProofContext, request: ProofRequest) -> dict[str, str]:
    bundle = context.bundle
    source_value = {
        "semantic": bundle.semantic.to_dict(),
        "source_semantics": context.source_semantics.to_dict(),
        "source_texts": context.source_texts or {},
    }
    model_value = {
        "evidence": bundle.evidence.to_dict(),
        "values": bundle.values.to_dict(),
        "effects": context.effect_engine.to_dict() if context.effect_engine else None,
    }
    inventory = context.inventory
    region_value = {
        "region": inventory.graph.regions[request.region].as_dict(),
        "construction": encode(inventory.constructions[request.region]),
        "ports": {key: inventory.graph.ports[key].as_dict()
                  for key in inventory.graph.regions[request.region].ports},
    }
    scope_value = {
        "scope": encode(inventory.scopes[context.scope]),
        "scope_id": context.scope,
        "effect_scope": ({"operations": [encode(context.effect_engine.operations[key])
            for key in sorted(context.effect_engine.operations, key=lambda x: (x[1], x[0].wire))
            if key[1] == context.scope],
            "occurrences": [encode(context.effect_engine.occurrences[key])
                for key in sorted(context.effect_engine.occurrences)
                if context.effect_engine.occurrences[key].scope == context.scope]}
            if context.effect_engine else None),
    }
    return {
        "source_hash": _digest(source_value),
        "model_hash": _digest(model_value),
        "q_hash": _digest(context.q),
        "region_hash": _digest(region_value),
        "scope_hash": _digest(scope_value),
        "request_digest": _digest(request),
    }


def _region_members(context: ProofContext, region: OptimizationRegionID):
    return context.inventory.graph.regions[region]


def _validate_request_shape(context: ProofContext, request: ProofRequest) -> None:
    region = _region_members(context, request.region)
    delta = request.delta
    if request.family is ProofFamily.CONSTANT:
        if not delta.static_substitutions:
            raise ValueError("CONSTANT requires actual static_substitutions in TransformDelta")
        if any(item.static_value not in context.source_semantics.values
               for item in delta.static_substitutions):
            raise ValueError("CONSTANT delta references an unknown static value")
        keys = [item.static_value for item in delta.static_substitutions]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate static substitution in delta")
        if delta.removed_definitions or delta.removed_instances or delta.substitutions or delta.moves or delta.added_operations:
            raise ValueError("CONSTANT v2 accepts only static substitutions; compose removals as a separate DEAD proof")
        if context.inventory.view is not RegionView.SEMANTIC:
            raise ValueError("CONSTANT source substitutions require a semantic region")
        members = set(region.definitions)
        if any(item.operation not in members for item in delta.static_substitutions):
            raise ValueError("CONSTANT substitution operation is outside its region")
        for item in delta.static_substitutions:
            value = context.source_semantics.values[item.static_value]
            operation = context.source_semantics.operations.get(item.operation)
            if (value.external or value.producer != item.operation or value.source != item.source
                    or operation is None or operation.result != item.static_value
                    or operation.source != item.source):
                raise ValueError("CONSTANT substitution does not match the source semantics producer/span")
            if item.binding is not None:
                binding = context.source_semantics.bindings.get(item.binding)
                if (binding is None or binding.value != item.static_value
                        or binding.definition != item.operation or binding.source != item.source):
                    raise ValueError("CONSTANT substitution binding does not match the replaced definition/span")
            if operation.opcode is sm.Opcode.LITERAL:
                raise ValueError("CONSTANT literal-to-same-literal change is a NO-OP")
    elif request.family is ProofFamily.DEAD:
        if not (delta.removed_definitions or delta.removed_instances):
            raise ValueError("DEAD requires exact removed definitions or instances")
        if any((item not in set(region.definitions)) for item in delta.removed_definitions):
            raise ValueError("DEAD definition is outside its region")
        if any(item not in set(region.instances) for item in delta.removed_instances):
            raise ValueError("DEAD instance is outside its region")
        if delta.static_substitutions or delta.substitutions or delta.moves or delta.added_operations:
            raise ValueError("DEAD delta contains unrelated transform changes")
        if context.inventory.view is RegionView.SEMANTIC and delta.removed_instances:
            raise ValueError("semantic DEAD region requires removed definitions")
        if context.inventory.view is RegionView.EXECUTION and delta.removed_definitions:
            raise ValueError("execution DEAD region requires removed instances")
    elif request.family is ProofFamily.REUSE:
        if delta.static_substitutions or delta.substitutions or delta.moves or delta.added_operations:
            raise ValueError("REUSE delta contains unrelated transform changes")
        removed = set(delta.removed_instances)
        if not removed:
            raise ValueError("REUSE requires removed invocation identities in TransformDelta")
        if request.reuse_pairs and removed != {item.removed for item in request.reuse_pairs}:
            raise ValueError("REUSE pairs must exactly account for removed invocations")
        if any(item.source not in set(region.instances) or item.removed not in removed
               for item in request.reuse_pairs):
            raise ValueError("REUSE pair is not bound to region membership and delta")
    else:
        if delta.static_substitutions or delta.substitutions or delta.removed_definitions or delta.removed_instances or delta.added_operations:
            raise ValueError("MOTION delta contains unrelated transform changes")
        if not delta.moves:
            raise ValueError("MOTION requires actual region moves in TransformDelta")
        if any(item.region != request.region for item in delta.moves):
            raise ValueError("MOTION delta region does not match proof request")
        if any(item.from_control not in context.bundle.semantic.controls
               or item.to_control not in context.bundle.semantic.controls
               for item in delta.moves):
            raise ValueError("MOTION delta references an unknown control region")
        if request.motion_query is not None:
            if set(request.motion_query.members) != set(region.instances):
                raise ValueError("motion query members must exactly match execution region")
            if request.motion_query.scope != context.scope:
                raise ValueError("motion query scope mismatch")
    if delta.is_empty:
        raise ValueError("proof request delta is empty")
def _constant_obligations(context: ProofContext, request: ProofRequest):
    family = request.family
    graph = context.source_semantics
    substitutions = tuple(request.delta.static_substitutions)
    targets = tuple(item.static_value for item in substitutions)
    report = evaluate_constants(graph, targets=targets,
                                budget=context.verification_budget)
    report.assert_valid(graph, verification_budget=context.verification_budget)
    facts = report.facts
    proofs = report.proofs
    result = []
    source_replay_ref = _ref("source_semantics_replay", "source-replay", {
        "semantic": context.bundle.semantic.to_dict(),
        "source_semantics": graph.to_dict(),
        "source_texts": context.source_texts or {},
    })
    for item in substitutions:
        value = graph.values[item.static_value]
        operation = graph.operations.get(item.operation)
        subject = item.static_value.wire
        source_id = _obligation_id(family, "source_replay_matches", subject)
        result.append(_new_obligation(family, "source_replay_matches", subject,
            ProofStatus.PROVEN, model_references=(source_replay_ref,
                _ref("operation_semantics", item.operation.wire, operation),
                _ref("static_value", item.static_value.wire, value)),
            evidence=()))

        fact = facts[item.static_value]
        proof = proofs.get(fact.proof_id) if fact.proof_id else None
        proof_ref = (_ref("constant_proof", proof.id, proof) if proof else None)
        value_match = (fact.status is ConstantStatus.CONSTANT and fact.literal == item.literal
                       and value.producer == item.operation and value.source == item.source
                       and operation is not None and operation.result == item.static_value
                       and operation.source == item.source)
        name = "constant_value_matches_replacement"
        if fact.status is ConstantStatus.KNOWN_EXCEPTION:
            status, reason = ProofStatus.DISPROVEN, (
                "fixed builtin evaluation raises " + str(fact.exception)
                + "; replacing it with a value suppresses the exception")
        elif value_match:
            status, reason = ProofStatus.PROVEN, "fixed evaluator recomputed the exact typed literal"
        elif fact.status is ConstantStatus.CONSTANT:
            status, reason = ProofStatus.DISPROVEN, "replacement differs in exact Python literal type/content or producer/source"
        else:
            status, reason = ProofStatus.UNKNOWN, "; ".join(gap.reason for gap in fact.gaps) or fact.status.value
        result.append(_new_obligation(family, name, subject, status,
            dependencies=(source_id,),
            model_references=((proof_ref,) if proof_ref else ()) +
                (_ref("constant_fact", item.static_value.wire, fact),),
            reason=reason if status is not ProofStatus.PROVEN else ""))

        # A bounded content fact does not prove object identity.  The output
        # contract is conditional on the exact, scoped Q statement that identity
        # of this replacement result is not observed.
        q_conditions = (
            ("replacement_observation_is_value_content_only", QPredicate.VALUE_CONTENT_ONLY, subject,
             "Q does not declare value-content-only observation for this replacement"),
            ("replacement_identity_is_unobserved", QPredicate.VALUE_IDENTITY_UNOBSERVED, subject,
             "Q does not declare that identity of this replaced result is unobserved"),
            ("replacement_resource_failures_are_unobserved", QPredicate.RESOURCE_FAILURE_UNOBSERVED,
             item.operation.wire,
             "Q does not declare that allocation/resource failures at this operation are unobserved"),
        )
        for name, predicate, q_subject, missing_reason in q_conditions:
            assumption = _assumption(context, predicate, q_subject)
            status = ProofStatus.PROVEN if assumption else ProofStatus.UNKNOWN
            result.append(_new_obligation(family, name, subject, status,
                dependencies=(source_id,), evidence=(assumption.evidence,) if assumption else (),
                conditions=(assumption,) if assumption else (),
                model_references=(_ref("Q_assumption", q_subject, assumption),) if assumption else (),
                reason=missing_reason if assumption is None else ""))

        _proof_ids, binding_uses, runtime_requirements = _constant_proof_closure(
            report, proof.id if proof is not None else None)
        source_preconditions = set()
        for binding_use_id in binding_uses:
            binding_use = graph.uses[binding_use_id]
            scope_def = context.bundle.semantic.definitions.get(binding_use.scope)
            if scope_def is not None and scope_def.kind.value in {"function", "method"}:
                source_preconditions.add(sm.SourceExecutionPrecondition.STANDARD_FUNCTION_LOCALS)
            else:
                source_preconditions.add(sm.SourceExecutionPrecondition.FRESH_MODULE_NAMESPACE)
            source_preconditions.add(sm.SourceExecutionPrecondition.NO_EXTERNAL_NAMESPACE_MUTATION)
        required_preconditions = source_preconditions
        for precondition in sorted(required_preconditions, key=lambda item: item.value):
            assumption = _assumption(context, QPredicate.SOURCE_PRECONDITION, precondition.value)
            sub = subject + ":" + precondition.value
            result.append(_new_obligation(family, "source_precondition_in_Q", sub,
                ProofStatus.PROVEN if assumption else ProofStatus.UNKNOWN,
                dependencies=(source_id,), evidence=(assumption.evidence,) if assumption else (),
                conditions=(assumption,) if assumption else (),
                model_references=(_ref("Q_assumption", sub, assumption),) if assumption else (),
                reason=("required static binding precondition is absent from Q"
                        if assumption is None else "")))
        for requirement in sorted(runtime_requirements, key=lambda item: item.value):
            predicate = (QPredicate.TARGET_RUNTIME_MATCH if requirement is ConstantRuntimeRequirement.BUILTIN_RUNTIME_MATCH
                         else QPredicate.FLOATING_ENVIRONMENT_MATCH)
            runtime_subject = target_runtime_q_subject(requirement, report.runtime)
            sub = subject + ":" + runtime_subject
            assumption = _assumption(context, predicate, runtime_subject)
            result.append(_new_obligation(family, "runtime_requirement_in_Q", sub,
                ProofStatus.PROVEN if assumption else ProofStatus.UNKNOWN,
                dependencies=(source_id,), evidence=(assumption.evidence,) if assumption else (),
                conditions=(assumption,) if assumption else (),
                model_references=(_ref("Q_assumption", sub, assumption),) if assumption else (),
                reason=("runtime requirement is not explicitly declared in Q"
                        if assumption is None else "")))

        # Static import/attribute resolution facts are deliberately not inferred
        # from names or module text.  G7.2b/import resolver contracts may close
        # these paths; until then their normal constant obligation stays open.
        if operation is not None and operation.opcode in {sm.Opcode.IMPORT, sm.Opcode.ATTRIBUTE}:
            name = "import_resolution_contract"
            result.append(_new_obligation(family, name, subject, ProofStatus.UNKNOWN,
                dependencies=(source_id,),
                model_references=(_ref("operation_semantics", item.operation.wire, operation),),
                reason="loader/cache/re-export/lazy attribute resolution has no recomputable contract in this context"))
    return tuple(result)


def _constant_proof_closure(report, root_id):
    """Collect every premise proof, binding read and runtime precondition."""
    if root_id is None:
        return set(), set(), set()
    proof_index = report.proofs
    seen, pending = set(), [root_id]
    binding_uses, runtime_requirements = set(), set()
    while pending:
        identity = pending.pop()
        if identity in seen:
            continue
        proof = proof_index.get(identity)
        if proof is None:
            raise ValueError("constant proof DAG references a missing premise")
        seen.add(identity)
        binding_uses.update(proof.binding_uses)
        runtime_requirements.update(proof.runtime_requirements)
        pending.extend(proof.premises)
    return seen, binding_uses, runtime_requirements


def _removed_definitions(context: ProofContext, request: ProofRequest):
    if request.delta.removed_definitions:
        return tuple(request.delta.removed_definitions)
    if request.delta.removed_instances:
        return tuple(sorted({context.bundle.evidence.instances[item].definition
                             for item in request.delta.removed_instances}, key=lambda item: item.wire))
    return ()


def _within_lexical_scope(semantic, identity: OperationDefinitionID,
                          scope: OperationDefinitionID) -> bool:
    current = identity
    visited = set()
    while current is not None and current not in visited:
        if current == scope:
            return True
        visited.add(current)
        definition = semantic.definitions.get(current)
        current = definition.parent_id if definition is not None else None
    return False


def _binding_source_preconditions(semantic, scope_id):
    scope = semantic.definitions.get(scope_id)
    preconditions = {sm.SourceExecutionPrecondition.NO_EXTERNAL_NAMESPACE_MUTATION}
    if scope is not None and scope.kind.value in {"function", "method"}:
        preconditions.add(sm.SourceExecutionPrecondition.STANDARD_FUNCTION_LOCALS)
    else:
        preconditions.add(sm.SourceExecutionPrecondition.FRESH_MODULE_NAMESPACE)
    return preconditions


def _static_consumer_closure(context: ProofContext, value_id,
                             removed: set[OperationDefinitionID]):
    graph = context.source_semantics
    value = graph.values[value_id]
    producer = graph.operations.get(value.producer)
    if producer is None:
        return ProofStatus.UNKNOWN, (), "static producer has no source-semantics operation", ()
    bindings = {item.id for item in graph.bindings.values() if item.value == value_id}
    binding_slots = {graph.bindings[identity].slot for identity in bindings}
    preconditions = set()
    for identity in bindings:
        preconditions.update(_binding_source_preconditions(
            context.bundle.semantic, graph.bindings[identity].scope))
    if producer.opcode is sm.Opcode.READ and producer.binding_use in graph.uses:
        use = graph.uses[producer.binding_use]
        if use.status.name == "EXACT" and len(use.reaching) == 1:
            binding = graph.bindings[use.reaching[0]]
            preconditions.update(_binding_source_preconditions(
                context.bundle.semantic, binding.scope))
    dependencies = {}
    unresolved_reads = set()
    for operation in graph.operations.values():
        inputs = {item.value for item in operation.operands}
        if operation.opcode is sm.Opcode.READ and operation.binding_use in graph.uses:
            use = graph.uses[operation.binding_use]
            if use.status.name == "EXACT" and len(use.reaching) == 1:
                binding = graph.bindings[use.reaching[0]]
                inputs.add(binding.value)
                if binding.value == value_id or binding.id in bindings:
                    preconditions.update(_binding_source_preconditions(
                        context.bundle.semantic, binding.scope))
            elif use.scope == value.scope and use.slot in binding_slots:
                unresolved_reads.add(operation.operation)
        dependencies[operation.operation] = inputs
    consumers = {identity for identity, inputs in dependencies.items() if value_id in inputs}
    if bindings:
        for use in graph.uses.values():
            if use.slot not in binding_slots:
                continue
            if use.status.name == "EXACT" and bindings.intersection(use.reaching):
                consumers.add(use.operation)
                for identity in bindings.intersection(use.reaching):
                    preconditions.update(_binding_source_preconditions(
                        context.bundle.semantic, graph.bindings[identity].scope))
            elif use.status.name != "EXACT" and use.scope == value.scope:
                unresolved_reads.add(use.operation)
    outside = consumers - removed
    if outside:
        return ProofStatus.DISPROVEN, tuple(sorted(outside, key=lambda item: item.wire)), (
            "static value has source-model consumers outside the removed delta"), tuple(preconditions)
    hidden = unresolved_reads - removed
    if hidden:
        return ProofStatus.UNKNOWN, tuple(sorted(hidden, key=lambda item: item.wire)), (
            "same-scope read has unresolved reaching definitions"), tuple(preconditions)
    for operation in graph.operations.values():
        if (bindings and operation.scope == value.scope and operation.operation not in removed
                and operation.opcode in {sm.Opcode.CALL, sm.Opcode.OPAQUE, sm.Opcode.IMPORT}):
            # Opaque calls/import loaders may inspect the current namespace even
            # without a modeled value edge.  A local constant proof cannot close
            # that consumer by observing an empty operand list.
            return ProofStatus.UNKNOWN, (operation.operation,), (
                "same-scope opaque call/import may observe or consume the binding"), tuple(preconditions)
    for gap in graph.gaps:
        if gap.operation is None:
            return ProofStatus.UNKNOWN, (), (
                "unlocated source-semantics gap may affect lexical consumer closure"), tuple(preconditions)
        definition = (context.bundle.semantic.definitions.get(gap.operation)
                     if gap.operation is not None else None)
        if (gap.operation is not None and gap.operation not in removed
                # The MODULE node is a structural execution root, not a user
                # operation that independently consumes a static value.
                and not (definition is not None and definition.kind.value == "module")
                and _within_lexical_scope(context.bundle.semantic, gap.operation, value.scope)):
            return ProofStatus.UNKNOWN, (gap.operation,), (
                "source-semantics gap in the value's lexical scope leaves consumers open"), tuple(preconditions)
    for identity in graph.unmodeled_operations:
        definition = context.bundle.semantic.definitions.get(identity)
        if (identity not in removed
                and not (definition is not None and definition.kind.value == "module")
                and _within_lexical_scope(context.bundle.semantic, identity, value.scope)):
            return ProofStatus.UNKNOWN, (identity,), (
                "unmodeled operation in the value's lexical scope leaves consumers open"), tuple(preconditions)
    return (ProofStatus.PROVEN, tuple(sorted(consumers, key=lambda item: item.wire)),
            "", tuple(preconditions))


def _dead_obligations(context: ProofContext, request: ProofRequest):
    family = request.family
    region = _region_members(context, request.region)
    obligations = []
    if region.instances and request.delta.removed_instances:
        # Execution-instance effect closure is not compositional in the current
        # effect engine; keep fixed obligations and report that exact gap.
        for identity in sorted(request.delta.removed_instances, key=lambda item: item.wire):
            subject = identity.wire
            obligations.append(_new_obligation(family, "instance_consumers_closed", subject,
                ProofStatus.UNKNOWN,
                reason="instance-specific consumer/effect closure is not yet supported by EffectClosureEngine"))
        return tuple(obligations)
    definitions = _removed_definitions(context, request)
    removed = set(definitions)
    required_consumers = tuple(sorted(set(context.bundle.semantic.definitions) - removed,
                                       key=lambda item: item.wire))
    engine = context.effect_engine
    boundary = engine.boundary(definitions, context.scope) if engine and definitions else None
    effect_dependencies = []
    effect_conditions = []
    effect_references = []
    effect_evidence = []
    missing_effect_acceptances = []
    if boundary is None:
        effect_status, effect_reason = (
            ProofStatus.UNKNOWN, "no scoped effect closure was supplied")
    else:
        scope_record = engine.scopes[context.scope]
        effect_references.append(_ref("effect_boundary",
            "removed:" + ",".join(item.wire for item in definitions), boundary))
        effect_references.append(_ref("observation_scope", scope_record.id, scope_record))
        effect_evidence.extend(scope_record.evidence)
        for coverage in boundary.coverage:
            effect_evidence.extend(coverage.evidence)
            if (coverage.closed and "*" in coverage.target_domain
                    and (coverage.assumptions or any(
                        claim.kind is EvidenceKind.DECLARED for claim in coverage.evidence))):
                q_subject = dead_effect_coverage_q_subject(coverage)
                assumption = _assumption(context, QPredicate.EFFECT_COVERAGE_ACCEPTED,
                                         q_subject)
                q_obligation = _new_obligation(
                    family, "effect_coverage_declaration_in_Q", q_subject,
                    ProofStatus.PROVEN if assumption else ProofStatus.UNKNOWN,
                    evidence=coverage.evidence + ((assumption.evidence,) if assumption else ()),
                    model_references=(_ref("effect_coverage", q_subject, coverage),) +
                        ((_ref("Q_assumption", q_subject, assumption),) if assumption else ()),
                    conditions=(assumption,) if assumption else (),
                    reason=("declared effect coverage is not accepted by Q"
                            if assumption is None else ""))
                obligations.append(q_obligation)
                effect_dependencies.append(q_obligation.id)
                if assumption is None:
                    missing_effect_acceptances.append(q_subject)
                else:
                    effect_conditions.append(assumption)
                    effect_evidence.append(assumption.evidence)
                effect_references.append(_ref("effect_coverage", q_subject, coverage))
        if (scope_record.closed and any(claim.kind is EvidenceKind.DECLARED
                                        for claim in scope_record.evidence)):
            q_subject = dead_scope_closure_q_subject(scope_record)
            assumption = _assumption(context, QPredicate.SCOPE_CLOSURE_ACCEPTED,
                                     q_subject)
            q_obligation = _new_obligation(
                family, "scope_closure_declaration_in_Q", q_subject,
                ProofStatus.PROVEN if assumption else ProofStatus.UNKNOWN,
                evidence=scope_record.evidence + ((assumption.evidence,) if assumption else ()),
                model_references=(_ref("observation_scope", scope_record.id, scope_record),) +
                    ((_ref("Q_assumption", q_subject, assumption),) if assumption else ()),
                conditions=(assumption,) if assumption else (),
                reason=("declared observation-scope closure is not accepted by Q"
                        if assumption is None else ""))
            obligations.append(q_obligation)
            effect_dependencies.append(q_obligation.id)
            if assumption is None:
                missing_effect_acceptances.append(q_subject)
            else:
                effect_conditions.append(assumption)
                effect_evidence.append(assumption.evidence)
        if context.q.effect_policy is not None:
            effect_evidence.append(context.q.effect_policy.evidence)
            effect_references.append(_ref("effect_policy", context.q.effect_policy.id,
                                          context.q.effect_policy))
        policy = context.q.effect_policy
        if policy is None:
            policy = EffectPolicy("proof-default-preserve:" + context.scope,
                context.scope, (), EvidenceClaim(EvidenceKind.DECLARED,
                    ("scar:proof-ledger-default-preserve-unlisted-effects",),
                    scope=context.scope))
        assessment = evaluate_removal(boundary, policy, context.bundle.semantic,
            removed_effect_ids=tuple(item.id for item in boundary.occurrences),
            mode=ScopeMode.ALL_PATHS)
        if assessment.required_effects:
            effect_status, effect_reason = ProofStatus.DISPROVEN, (
                "Q preserves effects in the deleted delta: " + ", ".join(assessment.required_effects))
        elif boundary.mode is not ScopeMode.ALL_PATHS:
            effect_status, effect_reason = ProofStatus.UNKNOWN, "effect evidence is dynamic-path, not all-path"
        elif not boundary.ready_for_region_construction or not assessment.removal_effects_satisfied:
            effect_status, effect_reason = ProofStatus.UNKNOWN, "; ".join(
                tuple(item.reason for item in boundary.gaps) + assessment.reasons) or "effect closure is incomplete"
        else:
            effect_status, effect_reason = ProofStatus.PROVEN, "all-path effect closure and Q removal assessment recomputed"
        effect_references.append(_ref("removal_assessment",
            "removed:" + ",".join(item.wire for item in definitions), assessment))
        effect_evidence.extend(item.evidence for item in boundary.occurrences)
        if effect_status is ProofStatus.PROVEN and missing_effect_acceptances:
            effect_status = ProofStatus.UNKNOWN
            effect_reason = ("declared effect-closure prerequisites are absent from Q: "
                             + ", ".join(missing_effect_acceptances))
    effect_subject = "removed:" + ",".join(item.wire for item in definitions)
    effect_obligation_id = _obligation_id(family, "removed_effects_allowed_by_Q", effect_subject)
    obligations.append(_new_obligation(family, "removed_effects_allowed_by_Q", effect_subject,
        effect_status, dependencies=tuple(effect_dependencies),
        evidence=tuple(dict.fromkeys(effect_evidence)),
        model_references=tuple(dict.fromkeys(effect_references)),
        conditions=tuple(effect_conditions),
        reason=effect_reason if effect_status is not ProofStatus.PROVEN else ""))

    for definition_id in definitions:
        definition = context.bundle.semantic.definitions[definition_id]
        subject = definition_id.wire
        source_operation = context.source_semantics.operations.get(definition_id)
        if source_operation is not None and source_operation.result is not None:
            status, consumers, reason, preconditions = _static_consumer_closure(
                context, source_operation.result, removed)
            source_dependencies = []
            source_conditions = []
            source_evidence = []
            for precondition in sorted(preconditions, key=lambda item: item.value):
                precondition_subject = source_operation.result.wire + ":" + precondition.value
                assumption = _assumption(context, QPredicate.SOURCE_PRECONDITION,
                                         precondition.value)
                q_obligation = _new_obligation(
                    family, "source_precondition_in_Q", precondition_subject,
                    ProofStatus.PROVEN if assumption else ProofStatus.UNKNOWN,
                    evidence=(assumption.evidence,) if assumption else (),
                    model_references=(_ref("Q_assumption", precondition.value,
                                           assumption),) if assumption else (),
                    conditions=(assumption,) if assumption else (),
                    reason=("source binding consumer closure requires an explicit Q precondition"
                            if assumption is None else ""))
                obligations.append(q_obligation)
                source_dependencies.append(q_obligation.id)
                if assumption is None:
                    status = ProofStatus.UNKNOWN
                    reason = (reason + "; " if reason else "") + (
                        "source binding consumer fact is conditional on an unaccepted Q precondition")
                else:
                    source_conditions.append(assumption)
                    source_evidence.append(assumption.evidence)
            obligations.append(_new_obligation(family, "source_consumers_closed",
                source_operation.result.wire, status,
                dependencies=tuple(source_dependencies), evidence=tuple(source_evidence),
                conditions=tuple(source_conditions),
                model_references=(_ref("operation_semantics", definition_id.wire, source_operation),
                    *tuple(_ref("consumer_operation", item.wire,
                                context.source_semantics.operations.get(item) or
                                context.bundle.semantic.definitions[item])
                           for item in consumers),
                    *tuple(_ref("source_precondition", precondition.value, precondition)
                           for precondition in preconditions)),
                reason=reason if status is not ProofStatus.PROVEN else ""))
        for slot in definition.output_slots:
            slot_subject = subject + ":" + slot.wire
            if engine is None:
                closure = None
                status, reason = ProofStatus.UNKNOWN, "no scoped effect/consumer engine was supplied"
                refs = ()
            else:
                target = EffectTarget(EffectTargetKind.VALUE_SLOT, slot.wire)
                closure = engine.consumer_closure(target, context.scope,
                    members=definitions, required_consumers=required_consumers,
                    coverage=boundary.coverage if boundary else None,
                    scope_end_closed=True)
                status = (ProofStatus.PROVEN if closure.state is ClosureState.DEAD_IN_SCOPE
                          and engine.scopes[context.scope].mode is ScopeMode.ALL_PATHS
                          else ProofStatus.DISPROVEN if closure.state is ClosureState.LIVE
                          else ProofStatus.UNKNOWN)
                reason = ("output has a required consumer" if status is ProofStatus.DISPROVEN
                          else "consumer is dead only in a dynamic-path scope" if
                          closure.state is ClosureState.DEAD_IN_SCOPE and status is ProofStatus.UNKNOWN
                          else closure.reason if status is ProofStatus.UNKNOWN else "")
                refs = (_ref("consumer_closure", slot_subject, closure),)
            obligations.append(_new_obligation(family, "output_consumers_closed", slot_subject,
                status, model_references=refs, reason=reason))

        # Static import nodes may initialize modules, trigger loaders or
        # re-export hooks outside an effect trace; the source model does not
        # resolve that behavior yet.
        semantic_ops = [item for item in context.source_semantics.operations.values()
                        if item.operation == definition_id]
        if any(item.opcode is sm.Opcode.IMPORT for item in semantic_ops):
            obligations.append(_new_obligation(family, "import_initialization_and_loader_effects",
                subject, ProofStatus.UNKNOWN,
                dependencies=(effect_obligation_id,) + tuple(_obligation_id(family,
                    "output_consumers_closed", subject + ":" + slot.wire)
                    for slot in definition.output_slots),
                model_references=tuple(_ref("operation_semantics", item.operation.wire, item)
                    for item in semantic_ops),
                reason="import initialization/loader/cache effects require an import-resolution contract"))
    return tuple(obligations)


def _reuse_obligations(context: ProofContext, request: ProofRequest):
    family = request.family
    region = _region_members(context, request.region)
    obligations = []
    pairs = request.reuse_pairs
    if not pairs:
        pairs = (None,)
    for pair in pairs:
        subject = (pair.removed.wire if pair is not None else request.region.wire)
        matching = (pair is not None and pair.source in region.instances
                    and pair.removed in request.delta.removed_instances)
        source = context.bundle.evidence.instances.get(pair.source) if matching else None
        removed = context.bundle.evidence.instances.get(pair.removed) if matching else None
        refs = tuple(_ref("operation_instance", item.id.wire, item)
                     for item in (source, removed) if item is not None)
        previous = None
        for name, reason in (
            ("exact_inputs_and_hidden_state_match", "current graph lacks a recomputable complete input/state equality witness"),
            ("effects_rng_and_exception_equivalence", "a reuse pair does not prove effect, RNG, exception or ordering equivalence"),
            ("output_identity_alias_and_mutability", "current graph lacks a complete output ownership/identity proof"),
            ("autograd_hooks_callbacks_and_consumers", "current graph lacks complete autograd, hook, callback and consumer closure"),
        ):
            dependencies = (previous,) if previous else ()
            obligations.append(_new_obligation(family, name, subject, ProofStatus.UNKNOWN,
                dependencies=dependencies, model_references=refs,
                reason=(reason if matching else "reuse pair is missing or not bound to the concrete delta")))
            previous = obligations[-1].id
    return tuple(obligations)


def _motion_obligations(context: ProofContext, request: ProofRequest):
    family = request.family
    query = request.motion_query
    subject = request.region.wire
    valid = False
    refs = ()
    reason_prefix = "motion is not yet supported: "
    if query is None:
        reason_prefix += "no MotionQuery is supplied"
    else:
        if context.bundle.evidence.instances:
            query_report = RegionQueries(context.bundle).validate_result(query)
            valid = bool(query_report)
            refs = (_ref("motion_query", subject, query),)
            if query.scope != context.scope:
                valid = False
                reason_prefix += "query scope does not match Q"
            elif not query_report:
                reason_prefix += "query cannot be recomputed against supplied evidence graph"
        else:
            reason_prefix += "execution evidence graph has no operation instances"
    names = (
        "all_inputs_state_available_at_target",
        "control_dominance_and_zero_iteration",
        "effects_rng_exceptions_and_ordering",
        "alias_lifetime_readiness_autograd_hooks",
        "consumer_call_control_closure",
        "precise_insertion_point_and_delta",
    )
    obligations = []
    previous = None
    for name in names:
        dependencies = (previous,) if previous else ()
        obligations.append(_new_obligation(family, name, subject, ProofStatus.UNKNOWN,
            dependencies=dependencies, model_references=refs,
            reason=reason_prefix + name))
        previous = obligations[-1].id
    return tuple(obligations)


def _check_obligation_dag(obligations):
    ids = [item.id for item in obligations]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate proof obligation identity")
    known = set(ids)
    by_id = {item.id: item for item in obligations}
    edges = []
    for item in obligations:
        if len(item.dependencies) != len(set(item.dependencies)):
            raise ValueError("duplicate proof dependency")
        for parent in item.dependencies:
            if parent not in known:
                raise ValueError("proof obligation references a missing dependency")
            if item.status is ProofStatus.PROVEN and by_id[parent].status is not ProofStatus.PROVEN:
                raise ValueError("PROVEN proof obligation depends on a non-PROVEN premise")
            edges.append((parent, item.id))
    cycles = cycle_errors(edges, "proof obligation")
    if cycles:
        raise ValueError("cyclic proof premises: " + "; ".join(cycles))


def _outcome(family, obligations):
    statuses = {item.status for item in obligations}
    if family in {ProofFamily.REUSE, ProofFamily.MOTION}:
        return ProofOutcome.NOT_YET_SUPPORTED
    if ProofStatus.DISPROVEN in statuses:
        return ProofOutcome.ILLEGAL
    if ProofStatus.UNKNOWN in statuses:
        return ProofOutcome.NEEDS_CONTRACT
    return ProofOutcome.CONDITIONALLY_LEGAL


def derive_proof_ledger(context: ProofContext, request: ProofRequest) -> ProofLedger:
    """Derive the fixed obligation set and statuses from current typed models."""
    hashes = _validate_context(context, request)
    _validate_request_shape(context, request)
    if request.family is ProofFamily.CONSTANT:
        obligations = _constant_obligations(context, request)
    elif request.family is ProofFamily.DEAD:
        obligations = _dead_obligations(context, request)
    elif request.family is ProofFamily.REUSE:
        obligations = _reuse_obligations(context, request)
    else:
        obligations = _motion_obligations(context, request)
    _check_obligation_dag(obligations)
    return ProofLedger(request.family, _outcome(request.family, obligations),
        RULE_VERSION, request.region, context.scope, request.delta,
        hashes["request_digest"], hashes["source_hash"], hashes["model_hash"],
        hashes["q_hash"], hashes["region_hash"], hashes["scope_hash"], obligations)


def validate_proof_ledger(ledger: ProofLedger, context: ProofContext,
                          request: ProofRequest) -> dict[str, Any]:
    """Recompute every obligation; stored PROVEN values have no authority."""
    try:
        typed = record_errors(ledger, ProofLedger, "proof_ledger")
        if typed:
            return {"valid": False, "errors": typed}
        _check_obligation_dag(ledger.obligations)
        expected = derive_proof_ledger(context, request)
        if encode(ledger) != encode(expected):
            return {"valid": False,
                    "errors": ["proof ledger differs from fixed-rule recomputation"]}
        return {"valid": True, "errors": [], "outcome": ledger.outcome.value}
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        return {"valid": False, "errors": [str(error)]}


__all__ = [
    "ProofFamily", "ProofOutcome", "QPredicate", "QAssumption", "ProofQ",
    "ReusePair", "ProofRequest", "ProofContext", "ModelReference",
    "ProofObligation", "ProofLedger", "derive_proof_ledger",
    "validate_proof_ledger", "target_runtime_q_subject",
    "dead_effect_coverage_q_subject", "dead_scope_closure_q_subject",
]
