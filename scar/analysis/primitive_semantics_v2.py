"""Fixed source-replayed semantics for Python identity comparison primitives.

Certificates describe one ``is``/``is not`` operation only. They do not claim
that evaluating either operand, the surrounding expression, or its function is
pure, effect-free, or safe to replace.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import sys
from typing import Iterable
from itertools import islice

from scar.analysis.constants_v2 import EvaluationBudget
from scar.analysis.source_semantics_v2 import validate_source_semantics
from scar.ir import semantics_v2 as sm
from scar.ir.record_codec import decode, encode, loads
from scar.ir.v2 import OperationDefinitionID, SemanticGraph
from scar.ir.v2._validation import record_errors


RULE_ID = "python.identity_comparison"
RULE_VERSION = "scar.primitive-semantics.v1"


class PrimitiveGapKind(str, Enum):
    NOT_IDENTITY_COMPARISON = "NOT_IDENTITY_COMPARISON"
    BLOCKED_COMPARISON = "BLOCKED_COMPARISON"
    MISSING_OPERATION = "MISSING_OPERATION"


class PrimitiveEffect(str, Enum):
    NO_USER_DISPATCH = "NO_USER_DISPATCH"
    NO_RNG_ACCESS = "NO_RNG_ACCESS"
    NO_WRITES = "NO_WRITES"
    NO_AUTOGRAD_EDGE = "NO_AUTOGRAD_EDGE"


class PrimitiveInputBehavior(str, Enum):
    IDENTITY_ONLY = "IDENTITY_ONLY"
    OPERAND_CONTENT_NOT_READ = "OPERAND_CONTENT_NOT_READ"


class PrimitiveOutputType(str, Enum):
    BOOL = "BOOL"


class PrimitiveOutputIdentity(str, Enum):
    BOOL_SINGLETON = "BOOL_SINGLETON"


class PrimitiveCoverage(str, Enum):
    OPERATOR_ONLY = "OPERATOR_ONLY"


class PrimitiveExcludedRegion(str, Enum):
    OPERAND_EVALUATION = "OPERAND_EVALUATION"
    ENCLOSING_EXPRESSION_AND_FUNCTION = "ENCLOSING_EXPRESSION_AND_FUNCTION"


class PrimitiveObservationBoundary(str, Enum):
    DEBUGGER_TRACING = "DEBUGGER_TRACING"
    FRAME_TRACING = "FRAME_TRACING"
    RESOURCE_OBSERVATION = "RESOURCE_OBSERVATION"
    EXCEPTION_OBSERVATION = "EXCEPTION_OBSERVATION"


class PrimitiveRuntimeRequirement(str, Enum):
    TARGET_PYTHON_IDENTITY_SEMANTICS_MATCH = "TARGET_PYTHON_IDENTITY_SEMANTICS_MATCH"


class SourceReplayStatus(str, Enum):
    VALID = "VALID"


@dataclass(frozen=True, slots=True)
class PrimitiveRuntimeScope:
    implementation: str
    version: tuple[int, int, int]

    def __post_init__(self) -> None:
        if not self.implementation or len(self.version) != 3:
            raise ValueError("primitive runtime scope requires implementation and 3-part version")
        if any(type(item) is not int or item < 0 for item in self.version):
            raise ValueError("primitive runtime version components must be non-negative integers")

    @classmethod
    def current(cls) -> "PrimitiveRuntimeScope":
        return cls(sys.implementation.name, tuple(sys.version_info[:3]))


@dataclass(frozen=True, slots=True)
class PrimitiveScope:
    """Caller-scoped preconditions and observations, never accepted legality."""

    runtime: PrimitiveRuntimeScope
    runtime_requirements: tuple[PrimitiveRuntimeRequirement, ...]
    source_preconditions: tuple[sm.SourceExecutionPrecondition, ...]
    observation_boundaries: tuple[PrimitiveObservationBoundary, ...]


@dataclass(frozen=True, slots=True)
class PrimitiveSemanticsCertificate:
    rule_id: str
    rule_version: str
    operation: OperationDefinitionID
    source: sm.SourceReference
    opcode: sm.Opcode
    inputs: tuple[sm.OperandUse, ...]
    result: sm.StaticValueID
    input_behavior: tuple[PrimitiveInputBehavior, ...]
    effects: tuple[PrimitiveEffect, ...]
    output_type: PrimitiveOutputType
    output_identity: PrimitiveOutputIdentity
    coverage: PrimitiveCoverage
    excluded_regions: tuple[PrimitiveExcludedRegion, ...]
    scope: PrimitiveScope

    def __post_init__(self) -> None:
        if self.rule_id != RULE_ID or self.rule_version != RULE_VERSION:
            raise ValueError("unsupported primitive semantic rule identity/version")
        if self.opcode not in {sm.Opcode.IS, sm.Opcode.IS_NOT}:
            raise ValueError("identity certificate must name IS or IS_NOT")
        if len(self.inputs) != 2:
            raise ValueError("identity certificate requires two ordered inputs")
        if tuple((item.role, item.index) for item in self.inputs) != (("left", 0), ("right", 1)):
            raise ValueError("identity certificate inputs must be ordered left/right operands")
        if set(self.effects) != set(PrimitiveEffect):
            raise ValueError("identity certificate must enumerate the complete fixed effect behavior")
        if set(self.input_behavior) != set(PrimitiveInputBehavior):
            raise ValueError("identity certificate must state identity-only input behavior")
        if set(self.excluded_regions) != set(PrimitiveExcludedRegion):
            raise ValueError("identity certificate must exclude operand and enclosing evaluation")
        if self.output_type is not PrimitiveOutputType.BOOL:
            raise ValueError("identity comparison output type must be bool")
        if self.output_identity is not PrimitiveOutputIdentity.BOOL_SINGLETON:
            raise ValueError("identity comparison output must be a bool singleton")
        if self.coverage is not PrimitiveCoverage.OPERATOR_ONLY:
            raise ValueError("identity certificate only covers the operator itself")


@dataclass(frozen=True, slots=True)
class PrimitiveGap:
    operation: OperationDefinitionID
    kind: PrimitiveGapKind
    source: sm.SourceReference | None
    reason: str
    required_fact: str

    def __post_init__(self) -> None:
        if not self.reason or not self.required_fact:
            raise ValueError("primitive gap requires a concrete reason and required fact")


@dataclass(frozen=True, slots=True)
class PrimitiveEvaluationUsage:
    nodes: int
    steps: int
    work: int
    output_bytes: int


@dataclass(frozen=True, slots=True)
class _ReportRecord:
    schema: str
    schema_version: int
    rule_id: str
    rule_version: str
    semantic_digest: str
    source_semantics_digest: str
    budget: EvaluationBudget
    targets: tuple[OperationDefinitionID, ...]
    certificates: tuple[PrimitiveSemanticsCertificate, ...]
    gaps: tuple[PrimitiveGap, ...]
    runtime_scope: PrimitiveRuntimeScope
    source_preconditions: tuple[sm.SourceExecutionPrecondition, ...]
    observation_boundaries: tuple[PrimitiveObservationBoundary, ...]
    source_replay: SourceReplayStatus
    usage: PrimitiveEvaluationUsage


def _canonical(value) -> str:
    return json.dumps(encode(value), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def _digest(value) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _check_verification_budget(stored: EvaluationBudget, ceiling: EvaluationBudget) -> None:
    if type(stored) is not EvaluationBudget or type(ceiling) is not EvaluationBudget:
        raise TypeError("budgets must be EvaluationBudget")
    stored.__post_init__()
    ceiling.__post_init__()
    if any(getattr(stored, name) > getattr(ceiling, name)
           for name in stored.__dataclass_fields__):
        raise ValueError("report budget exceeds verification budget")


_OBSERVATION_BOUNDARIES = tuple(PrimitiveObservationBoundary)
_SOURCE_PRECONDITIONS = tuple(sm.SourceExecutionPrecondition)
_RUNTIME_REQUIREMENTS = (PrimitiveRuntimeRequirement.TARGET_PYTHON_IDENTITY_SEMANTICS_MATCH,)


def _comparison_boundary_by_operation(graph: sm.SourceSemanticsGraph, targets=None):
    comparison_kinds = {sm.BoundaryKind.COMPARISON_DISPATCH,
                        sm.BoundaryKind.COMPARISON_SHORT_CIRCUIT}
    selected = None if targets is None else set(targets)
    return {boundary.operation: boundary for boundary in graph.boundaries
            if boundary.operation is not None and boundary.kind in comparison_kinds
            and (selected is None or boundary.operation in selected)}


def _normalize_targets(graph, operations, *, max_nodes):
    if operations is None:
        selected = set()
        for item in graph.operations.values():
            if item.opcode in {sm.Opcode.IS, sm.Opcode.IS_NOT}:
                selected.add(item.operation)
                if len(selected) > max_nodes:
                    raise ValueError("primitive target count exceeds max_nodes")
        comparison_kinds = {sm.BoundaryKind.COMPARISON_DISPATCH,
                            sm.BoundaryKind.COMPARISON_SHORT_CIRCUIT}
        for boundary in graph.boundaries:
            if boundary.operation is not None and boundary.kind in comparison_kinds:
                selected.add(boundary.operation)
                if len(selected) > max_nodes:
                    raise ValueError("primitive target count exceeds max_nodes")
        return tuple(sorted(selected, key=lambda item: item.wire))
    if isinstance(operations, OperationDefinitionID):
        values = (operations,)
    else:
        if isinstance(operations, (str, bytes)):
            raise TypeError("operations must be operation IDs")
        values = tuple(islice(iter(operations), max_nodes + 1))
        if len(values) > max_nodes:
            raise ValueError("primitive target count exceeds max_nodes")
    if any(type(item) is not OperationDefinitionID for item in values):
        raise TypeError("operations must contain OperationDefinitionID records")
    if len(values) != len(set(values)):
        raise ValueError("primitive target operations must be unique")
    return tuple(sorted(values, key=lambda item: item.wire))


def _scope(runtime, preconditions):
    ordered_preconditions = tuple(sorted(preconditions, key=lambda item: item.value))
    return PrimitiveScope(runtime, _RUNTIME_REQUIREMENTS, ordered_preconditions,
                          _OBSERVATION_BOUNDARIES)


def _evaluate(semantic, source_semantics, *, targets, budget, source_texts):
    if type(semantic) is not SemanticGraph or type(source_semantics) is not sm.SourceSemanticsGraph:
        raise TypeError("semantic graph and source semantics graph are required")
    budget.__post_init__()
    if not semantic.validate()["valid"]:
        raise ValueError("semantic graph is invalid")
    if not source_semantics.validate(semantic)["valid"]:
        raise ValueError("source semantics graph is invalid")
    if len(targets) > budget.max_nodes:
        raise ValueError("primitive target count exceeds max_nodes")

    # Replay the extractor once for the whole batch. This authenticates the
    # modeled operator and ordered operands against the current caller sources.
    replay = validate_source_semantics(source_semantics, semantic, sources=source_texts)
    if not replay["valid"]:
        raise ValueError("source replay failed: " + "; ".join(replay["errors"]))

    runtime = PrimitiveRuntimeScope.current()
    scope = _scope(runtime, source_semantics.required_preconditions)
    comparison_boundaries = _comparison_boundary_by_operation(source_semantics, targets)
    certificates = []
    gaps = []
    steps = work = 0
    for identity in targets:
        operation = source_semantics.operations.get(identity)
        work += 1
        steps += 1
        if operation is None:
            gaps.append(PrimitiveGap(identity, PrimitiveGapKind.MISSING_OPERATION, None,
                "The requested operation is absent from the source semantics overlay.",
                "Rebuild the semantic overlay from the same source snapshot."))
            continue
        if operation.opcode in {sm.Opcode.IS, sm.Opcode.IS_NOT}:
            if operation.result is None:
                gaps.append(PrimitiveGap(identity, PrimitiveGapKind.NOT_IDENTITY_COMPARISON,
                    operation.source, "Identity comparison has no modeled result value.",
                    "Preserve a result value linked to the source comparison operation."))
                continue
            # The source replay above has established this precise opcode and
            # operand order. Input producer semantics remain outside the rule.
            certificates.append(PrimitiveSemanticsCertificate(
                RULE_ID, RULE_VERSION, identity, operation.source, operation.opcode,
                operation.operands, operation.result,
                tuple(PrimitiveInputBehavior), tuple(PrimitiveEffect),
                PrimitiveOutputType.BOOL, PrimitiveOutputIdentity.BOOL_SINGLETON,
                PrimitiveCoverage.OPERATOR_ONLY, tuple(PrimitiveExcludedRegion), scope))
            steps += len(operation.operands)
            work += len(operation.operands)
            continue
        if identity in comparison_boundaries:
            boundary = comparison_boundaries[identity]
            if boundary.kind is sm.BoundaryKind.COMPARISON_SHORT_CIRCUIT:
                reason = boundary.reason
                required_fact = (
                    "Model short-circuit behavior and conditionally evaluate every chained operand.")
            else:
                reason = boundary.reason
                required_fact = (
                    "Model comparison dispatch and its exact result semantics without executing user code.")
            gaps.append(PrimitiveGap(identity, PrimitiveGapKind.BLOCKED_COMPARISON,
                operation.source, reason, required_fact))
        else:
            gaps.append(PrimitiveGap(identity, PrimitiveGapKind.NOT_IDENTITY_COMPARISON,
                operation.source,
                "The selected source operation is not a supported identity comparison.",
                "Select a source-replayed IS or IS_NOT operation."))
    if steps > budget.max_steps:
        raise ValueError("primitive report exceeds max_steps")
    if work > budget.max_work:
        raise ValueError("primitive report exceeds max_work")

    certificates = tuple(sorted(certificates, key=lambda item: item.operation.wire))
    gaps = tuple(sorted(gaps, key=lambda item: item.operation.wire))
    semantic_digest = _digest(semantic.to_dict())
    source_digest = _digest(source_semantics.to_dict())
    usage = PrimitiveEvaluationUsage(len(targets), steps, work, 0)
    record = _ReportRecord(PrimitiveSemanticsReport.SCHEMA,
        PrimitiveSemanticsReport.SCHEMA_VERSION, RULE_ID, RULE_VERSION,
        semantic_digest, source_digest, budget, targets, certificates, gaps,
        runtime, tuple(sorted(source_semantics.required_preconditions,
                              key=lambda item: item.value)),
        _OBSERVATION_BOUNDARIES, SourceReplayStatus.VALID, usage)
    for _ in range(8):
        byte_count = len(_canonical(record).encode("utf-8"))
        if byte_count == record.usage.output_bytes:
            break
        usage = PrimitiveEvaluationUsage(len(targets), steps, work, byte_count)
        record = _ReportRecord(record.schema, record.schema_version, record.rule_id,
            record.rule_version, record.semantic_digest, record.source_semantics_digest,
            record.budget, record.targets, record.certificates, record.gaps,
            record.runtime_scope, record.source_preconditions, record.observation_boundaries,
            record.source_replay, usage)
    else:
        raise ValueError("primitive report size accounting did not stabilize")
    if record.usage.output_bytes > budget.max_total_output_bytes:
        raise ValueError("primitive report exceeds max_total_output_bytes")
    return PrimitiveSemanticsReport(semantic, source_semantics, record)


class PrimitiveSemanticsReport:
    """Strict, independently rederived primitive-rule descriptions."""

    SCHEMA = "scar.primitive-semantics"
    SCHEMA_VERSION = 1

    def __init__(self, semantic, source_semantics, record: _ReportRecord):
        self.semantic = semantic
        self.source_semantics = source_semantics
        self.rule_id = record.rule_id
        self.rule_version = record.rule_version
        self.semantic_digest = record.semantic_digest
        self.source_semantics_digest = record.source_semantics_digest
        self.budget = record.budget
        self.targets = record.targets
        self.certificates = {item.operation: item for item in record.certificates}
        self.gaps = {item.operation: item for item in record.gaps}
        self.runtime_scope = record.runtime_scope
        self.source_preconditions = record.source_preconditions
        self.observation_boundaries = record.observation_boundaries
        self.source_replay = record.source_replay
        self.usage = record.usage

    def _record(self) -> _ReportRecord:
        return _ReportRecord(self.SCHEMA, self.SCHEMA_VERSION, self.rule_id,
            self.rule_version, self.semantic_digest, self.source_semantics_digest,
            self.budget, self.targets,
            tuple(self.certificates[key] for key in sorted(self.certificates, key=lambda item: item.wire)),
            tuple(self.gaps[key] for key in sorted(self.gaps, key=lambda item: item.wire)),
            self.runtime_scope, self.source_preconditions, self.observation_boundaries,
            self.source_replay, self.usage)

    def validate(self, semantic=None, source_semantics=None, *, source_texts=None,
                 verification_budget=EvaluationBudget()):
        semantic = self.semantic if semantic is None else semantic
        source_semantics = self.source_semantics if source_semantics is None else source_semantics
        try:
            _check_verification_budget(self.budget, verification_budget)
            record = self._record()
            errors = record_errors(record, _ReportRecord, "primitive_semantics_report")
            if errors:
                return {"valid": False, "errors": errors}
            if self.semantic_digest != _digest(semantic.to_dict()):
                return {"valid": False, "errors": ["semantic graph digest differs"]}
            if self.source_semantics_digest != _digest(source_semantics.to_dict()):
                return {"valid": False, "errors": ["source semantics graph digest differs"]}
            expected = _evaluate(semantic, source_semantics, targets=self.targets,
                budget=self.budget, source_texts=source_texts)
            if encode(record) != encode(expected._record()):
                return {"valid": False, "errors": ["primitive certificates/gaps differ from fixed-rule source rederivation"]}
            return {"valid": True, "errors": []}
        except (ValueError, TypeError, KeyError, AttributeError, OSError, SyntaxError) as error:
            return {"valid": False, "errors": [str(error)]}

    def assert_valid(self, semantic=None, source_semantics=None, *, source_texts=None,
                     verification_budget=EvaluationBudget()):
        result = self.validate(semantic, source_semantics, source_texts=source_texts,
                               verification_budget=verification_budget)
        if not result["valid"]:
            raise ValueError("invalid primitive semantics report: " + "; ".join(result["errors"]))
        return result

    def to_dict(self, *, source_texts=None, verification_budget=EvaluationBudget()):
        self.assert_valid(source_texts=source_texts, verification_budget=verification_budget)
        return encode(self._record())

    def to_json(self, *, source_texts=None, verification_budget=EvaluationBudget()):
        return json.dumps(self.to_dict(source_texts=source_texts,
            verification_budget=verification_budget), sort_keys=True,
            separators=(",", ":"), ensure_ascii=True, allow_nan=False)

    @classmethod
    def from_dict(cls, document, *, semantic, source_semantics, source_texts=None,
                  verification_budget=EvaluationBudget()):
        record = decode(_ReportRecord, document)
        if record.schema != cls.SCHEMA or record.schema_version != cls.SCHEMA_VERSION:
            raise ValueError("unsupported primitive semantics report schema/version")
        _check_verification_budget(record.budget, verification_budget)
        expected = _evaluate(semantic, source_semantics, targets=record.targets,
            budget=record.budget, source_texts=source_texts)
        if encode(record) != encode(expected._record()):
            raise ValueError("primitive semantics report differs from fixed-rule rederivation")
        return expected

    @classmethod
    def from_json(cls, payload, *, semantic, source_semantics, source_texts=None,
                  verification_budget=EvaluationBudget()):
        return cls.from_dict(loads(payload), semantic=semantic,
            source_semantics=source_semantics, source_texts=source_texts,
            verification_budget=verification_budget)

    def summary(self):
        return {
            "schema": self.SCHEMA,
            "schema_version": self.SCHEMA_VERSION,
            "rule_id": self.rule_id,
            "rule_version": self.rule_version,
            "source_replay": self.source_replay.value,
            "semantic_digest": self.semantic_digest,
            "source_semantics_digest": self.source_semantics_digest,
            "target_count": len(self.targets),
            "certificate_count": len(self.certificates),
            "gap_count": len(self.gaps),
            "certificates": [{
                "operation": item.operation.wire,
                "opcode": item.opcode.value,
                "inputs": [{"role": operand.role, "index": operand.index,
                            "value": operand.value.wire} for operand in item.inputs],
                "output_type": item.output_type.value,
                "coverage": item.coverage.value,
                "effects": sorted(effect.value for effect in item.effects),
                "source": item.source.as_dict(),
            } for item in self.certificates.values()],
            "gaps": [{"operation": item.operation.wire,
                      "kind": item.kind.value, "reason": item.reason,
                      "required_fact": item.required_fact}
                     for item in self.gaps.values()],
            "source_preconditions": sorted(item.value for item in self.source_preconditions),
            "runtime_scope": encode(self.runtime_scope),
            "runtime_requirements": [item.value for item in _RUNTIME_REQUIREMENTS],
            "observation_boundaries": [item.value for item in self.observation_boundaries],
            "usage": encode(self.usage),
        }


def derive_primitive_semantics(semantic: SemanticGraph,
                              source_semantics: sm.SourceSemanticsGraph,
                              operations: OperationDefinitionID | Iterable[OperationDefinitionID] | None = None,
                              *, source_texts=None,
                              budget=EvaluationBudget()) -> PrimitiveSemanticsReport:
    """Re-derive identity operator certificates and explicit unsupported gaps.

    ``source_texts`` are caller-provided decoded snapshots keyed by source path;
    when omitted the fixed source extractor validates against current files.
    Passing a batch replays the complete overlay once, then derives all items.
    """
    if type(budget) is not EvaluationBudget:
        raise TypeError("budget must be EvaluationBudget")
    targets = _normalize_targets(source_semantics, operations, max_nodes=budget.max_nodes)
    return _evaluate(semantic, source_semantics, targets=targets,
                     budget=budget, source_texts=source_texts)


__all__ = [
    "RULE_ID", "RULE_VERSION", "PrimitiveGapKind", "PrimitiveEffect",
    "PrimitiveInputBehavior", "PrimitiveOutputType", "PrimitiveOutputIdentity",
    "PrimitiveCoverage", "PrimitiveExcludedRegion", "PrimitiveObservationBoundary",
    "PrimitiveRuntimeRequirement", "PrimitiveRuntimeScope", "PrimitiveScope",
    "PrimitiveSemanticsCertificate", "PrimitiveGap", "PrimitiveEvaluationUsage",
    "PrimitiveSemanticsReport", "derive_primitive_semantics",
]
