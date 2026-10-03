"""Source-replayed certificates for a narrow, straight-line Python body.

These records describe statement structure and exact local-value flow. They do
not establish that moving a statement is legal: runtime, resource, scheduling,
frame-observation and reference-count conditions remain explicit inputs to the
caller. In particular, a constant result alone never certifies a statement.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import tokenize
from typing import Any

from scar.analysis.constants_v2 import (
    ConstantRuntimeRequirement, ConstantStatus, EvaluationBudget,
    EvaluationUsage, evaluate_constants,
)
from scar.analysis.control_flow_v2 import validate_source_control_flow
from scar.analysis.source_semantics_v2 import validate_source_semantics
from scar.ir import semantics_v2 as sm
from scar.ir.control_flow_v2 import (
    ControlFlowBudget, ControlFlowSuiteID, NodeKind, SourceControlFlowGraph,
    SourceVersion, SuiteKind,
)
from scar.ir.record_codec import decode, encode, loads
from scar.ir.v2 import (
    OperationDefinitionID, SemanticGraph, SemanticNodeKind, SemanticRelation,
    SourceReference, StaticBindingID, StaticValueID, ValueSlotID,
)
from scar.ir.v2._validation import record_errors


RULE_VERSION = "scar.local-statement-semantics.v2.1"
SCHEMA = "scar.local-statement-semantics.v2"
SCHEMA_VERSION = 1


class StatementKind(str, Enum):
    ASSIGN_LITERAL = "ASSIGN_LITERAL"
    ASSIGN_CONSTANT = "ASSIGN_CONSTANT"
    ASSIGN_ALIAS = "ASSIGN_ALIAS"
    RETURN_LITERAL = "RETURN_LITERAL"
    RETURN_LOCAL = "RETURN_LOCAL"
    PASS = "PASS"


class StatementFact(str, Enum):
    SOURCE_AND_CFG_REPLAYED = "source_and_cfg_replayed"
    STRAIGHT_LINE_FUNCTION_BODY = "straight_line_function_body"
    EXACT_READ_BINDINGS = "exact_read_bindings"
    FIRST_LOCAL_BINDING = "first_local_binding"
    IMMUTABLE_BUILTIN_VALUE = "immutable_builtin_value"
    NO_USER_DISPATCH = "no_user_dispatch"
    NO_MUTABLE_VALUE = "no_mutable_value"
    NO_RNG_OR_AUTOGRAD = "no_rng_or_autograd"
    NO_EXTERNAL_OR_ORDERED_EFFECT = "no_external_or_ordered_effect"
    ALIAS_IDENTITY_PRESERVED = "alias_identity_preserved"
    RETURN_SLOT_CONNECTED = "return_slot_connected"


class RequiredCondition(str, Enum):
    """Conditions that must remain visible to the consuming proof ledger."""

    TARGET_PYTHON_RUNTIME_MATCH = "target_python_runtime_match"
    RESOURCE_FAILURE_UNOBSERVED = "resource_failure_unobserved"
    ASYNC_INTERRUPT_UNOBSERVED = "async_interrupt_unobserved"
    FRAME_AND_BINDING_TIMING_UNOBSERVED = "frame_and_binding_timing_unobserved"
    REFCOUNT_AND_FINALIZER_OBSERVATION_UNOBSERVED = "refcount_and_finalizer_observation_unobserved"


class Coverage(str, Enum):
    SUPPORTED = "SUPPORTED"
    INCOMPLETE = "INCOMPLETE"


class GapKind(str, Enum):
    WRONG_SUITE = "wrong_suite"
    FUNCTION_JOIN = "function_join"
    UNSUPPORTED_FUNCTION = "unsupported_function"
    UNSUPPORTED_STATEMENT = "unsupported_statement"
    UNSUPPORTED_EXPRESSION = "unsupported_expression"
    CONTROL_FLOW_GAP = "control_flow_gap"
    SOURCE_SEMANTICS_GAP = "source_semantics_gap"
    AMBIGUOUS_OPERATION = "ambiguous_operation"
    AMBIGUOUS_BINDING = "ambiguous_binding"
    NONLOCAL_OR_PARAMETER = "nonlocal_or_parameter"
    REBOUND_LOCAL = "rebound_local"
    UNRESOLVED_READ = "unresolved_read"
    EXTERNAL_OR_CLOSURE_READ = "external_or_closure_read"
    NONCONSTANT_VALUE = "nonconstant_value"
    KNOWN_EXCEPTION = "known_exception"
    MUTABLE_VALUE = "mutable_value"
    SEMANTIC_EDGE_MISMATCH = "semantic_edge_mismatch"
    UNUSED_OR_UNMODELED_SYNTAX = "unmodeled_syntax"


@dataclass(frozen=True, slots=True)
class StatementRead:
    use: sm.BindingUseID
    binding: StaticBindingID


@dataclass(frozen=True, slots=True)
class StatementCertificate:
    id: str
    scope: OperationDefinitionID
    suite: ControlFlowSuiteID
    source: SourceReference
    statement: OperationDefinitionID
    kind: StatementKind
    ordered_reads: tuple[StatementRead, ...] = ()
    written_binding: StaticBindingID | None = None
    written_slot: ValueSlotID | None = None
    expression_value: StaticValueID | None = None
    result_value: StaticValueID | None = None
    alias_source_binding: StaticBindingID | None = None
    immutable_type: str | None = None
    constant_proofs: tuple[str, ...] = ()
    facts: tuple[StatementFact, ...] = ()
    required_conditions: tuple[RequiredCondition, ...] = ()
    required_source_preconditions: tuple[sm.SourceExecutionPrecondition, ...] = ()

    def __post_init__(self) -> None:
        if not self.id or not self.source.fingerprint:
            raise ValueError("statement certificate requires identity and source version")
        if self.written_binding is not None and self.written_slot is None:
            raise ValueError("written binding requires its destination slot")
        if self.kind in {StatementKind.ASSIGN_LITERAL, StatementKind.ASSIGN_CONSTANT,
                         StatementKind.ASSIGN_ALIAS} and self.written_binding is None:
            raise ValueError("assignment certificate requires its first local binding")
        if self.kind in {StatementKind.RETURN_LITERAL, StatementKind.RETURN_LOCAL} and self.written_slot is None:
            raise ValueError("return certificate requires its function return slot")
        if self.kind is not StatementKind.PASS and not self.constant_proofs:
            raise ValueError("value-producing certificate requires constant proof lineage")
        if self.kind is not StatementKind.PASS and self.immutable_type is None:
            raise ValueError("value-producing certificate requires an immutable builtin type")
        if self.kind in {StatementKind.ASSIGN_LITERAL, StatementKind.ASSIGN_CONSTANT,
                         StatementKind.ASSIGN_ALIAS} and (
                self.expression_value is None or self.result_value is None):
            raise ValueError("assignment certificate requires expression and result values")
        if self.kind in {StatementKind.RETURN_LITERAL, StatementKind.RETURN_LOCAL} and (
                self.expression_value is None or self.result_value is None):
            raise ValueError("return certificate requires an expression and result value")
        if self.kind in {StatementKind.ASSIGN_ALIAS, StatementKind.RETURN_LOCAL} and self.alias_source_binding is None:
            raise ValueError("local alias/return requires its exact source binding")
        if self.kind not in {StatementKind.ASSIGN_ALIAS, StatementKind.RETURN_LOCAL} and self.alias_source_binding is not None:
            raise ValueError("only local alias/return has a source binding")
        if self.kind in {StatementKind.ASSIGN_ALIAS, StatementKind.RETURN_LOCAL} and len(self.ordered_reads) != 1:
            raise ValueError("local alias/return requires exactly one ordered read")
        if self.kind not in {StatementKind.ASSIGN_ALIAS, StatementKind.RETURN_LOCAL} and self.ordered_reads:
            raise ValueError("only direct local alias/return can contain a source read")
        if self.required_conditions != _condition_set():
            raise ValueError("statement certificate must retain the fixed Q condition set")
        if self.required_source_preconditions != _source_precondition_set():
            raise ValueError("statement certificate must retain the fixed source preconditions")
        if len(set(self.ordered_reads)) != len(self.ordered_reads):
            raise ValueError("duplicate ordered read in statement certificate")
        if len(set(self.constant_proofs)) != len(self.constant_proofs):
            raise ValueError("duplicate constant proof reference")
        if len(set(self.facts)) != len(self.facts):
            raise ValueError("duplicate statement fact")
        if len(set(self.required_conditions)) != len(self.required_conditions):
            raise ValueError("duplicate required statement condition")

    @property
    def read_bindings(self) -> tuple[StaticBindingID, ...]:
        return tuple(item.binding for item in self.ordered_reads)


@dataclass(frozen=True, slots=True)
class StatementGap:
    kind: GapKind
    scope: OperationDefinitionID
    suite: ControlFlowSuiteID
    source: SourceReference | None
    statement: OperationDefinitionID | None
    reason: str

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("statement gap requires a reason")


@dataclass(frozen=True, slots=True)
class LocalStatementUsage:
    ast_nodes: int
    statements: int
    source_operations: int
    constant_usage: EvaluationUsage
    work: int


@dataclass(frozen=True, slots=True)
class _ReportRecord:
    schema: str
    schema_version: int
    rule_version: str
    scope: OperationDefinitionID
    suite: ControlFlowSuiteID
    source_version: SourceVersion
    semantic_digest: str
    source_semantics_digest: str
    control_flow_digest: str
    model_digest: str
    budget: EvaluationBudget
    control_budget: ControlFlowBudget
    usage: LocalStatementUsage
    coverage: Coverage
    certificates: tuple[StatementCertificate, ...]
    gaps: tuple[StatementGap, ...]
    required_conditions: tuple[RequiredCondition, ...]
    required_source_preconditions: tuple[sm.SourceExecutionPrecondition, ...]


def _digest(value: Any) -> str:
    payload = json.dumps(encode(value), sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _source_digest(value: Any) -> str:
    return _digest(value.to_dict())


def _span(node: ast.AST) -> tuple[str, int | None, int | None, int | None, int | None]:
    return (type(node).__name__, getattr(node, "lineno", None),
            getattr(node, "end_lineno", None), getattr(node, "col_offset", None),
            getattr(node, "end_col_offset", None))


def _reference_key(reference: SourceReference) -> tuple[str, int, int, int, int | None]:
    return (reference.path, reference.start_line, reference.end_line,
            reference.start_column, reference.end_column)


def _source_atom_key(path: str, node: ast.AST) -> tuple[str, str, int | None, int | None, int | None, int | None]:
    return (path, type(node).__name__, *_span(node)[1:])


def _reference_atom_key(reference: SourceReference, kind: str) -> tuple:
    return (reference.path, kind, reference.start_line, reference.end_line,
            reference.start_column, reference.end_column)


class _Meter:
    def __init__(self, budget: ControlFlowBudget):
        self.budget = budget
        self.work = 0
        self.ast_nodes = 0

    def step(self, amount: int = 1) -> None:
        self.work += amount
        if self.work > self.budget.max_build_work:
            raise ValueError("local statement analysis work budget exceeded")

    def node(self) -> None:
        self.ast_nodes += 1
        self.step()
        if self.ast_nodes > self.budget.max_ast_nodes:
            raise ValueError("local statement AST-node budget exceeded")


class _ExpressionNames(ast.NodeVisitor):
    def __init__(self, meter: _Meter):
        self.meter = meter
        self.names: list[ast.Name] = []

    def visit(self, node):
        pending = [node]
        while pending:
            current = pending.pop()
            self.meter.node()
            if isinstance(current, ast.Name) and isinstance(current.ctx, ast.Load):
                self.names.append(current)
            children = list(ast.iter_child_nodes(current))
            self.meter.step(len(children))
            pending.extend(reversed(children))


_BINARY_EXPR_TYPES = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod,
                      ast.Pow, ast.LShift, ast.RShift, ast.BitAnd, ast.BitOr,
                      ast.BitXor)
_UNARY_EXPR_TYPES = (ast.UAdd, ast.USub, ast.Invert)


def _expression_children(node: ast.AST, *, allow_arithmetic: bool):
    if isinstance(node, ast.Constant):
        try:
            sm.PythonLiteral.from_python(node.value)
        except (ValueError, TypeError):
            return None
        return ()
    if isinstance(node, ast.Tuple):
        return tuple(node.elts)
    if allow_arithmetic and isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_EXPR_TYPES:
        return (node.operand,)
    if allow_arithmetic and isinstance(node, ast.BinOp) and type(node.op) in _BINARY_EXPR_TYPES:
        return (node.left, node.right)
    return None


def _is_immutable_constant_expression(node: ast.AST, meter: _Meter) -> bool:
    pending = [node]
    while pending:
        current = pending.pop()
        meter.node()
        children = _expression_children(current, allow_arithmetic=True)
        if children is None:
            return False
        meter.step(len(children))
        pending.extend(reversed(children))
    return True


def _is_literal_expression(node: ast.AST, meter: _Meter) -> bool:
    pending = [node]
    while pending:
        current = pending.pop()
        meter.node()
        children = _expression_children(current, allow_arithmetic=False)
        if children is None:
            return False
        meter.step(len(children))
        pending.extend(reversed(children))
    return True


def _expression_shape(node: ast.expr, meter: _Meter, *, allow_name_alias: bool) -> str | None:
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
        return "alias" if allow_name_alias else None
    if _is_literal_expression(node, meter):
        return "literal"
    if _is_immutable_constant_expression(node, meter):
        return "closed"
    return None


def _literal_type(literal: sm.PythonLiteral | None) -> str | None:
    if literal is None:
        return None
    if literal.kind is sm.LiteralKind.TUPLE:
        if not all(_literal_type(item) is not None for item in literal.items):
            return None
    return literal.kind.value


def _condition_set() -> tuple[RequiredCondition, ...]:
    return tuple(RequiredCondition)


def _source_precondition_set() -> tuple[sm.SourceExecutionPrecondition, ...]:
    return (sm.SourceExecutionPrecondition.STANDARD_FUNCTION_LOCALS,
            sm.SourceExecutionPrecondition.NO_EXTERNAL_NAMESPACE_MUTATION)


def _gap(kind, scope, suite, reason, *, source=None, statement=None):
    return StatementGap(kind, scope, suite, source, statement, reason)


def _semantic_edges(semantic: SemanticGraph, meter: _Meter):
    reads: dict[OperationDefinitionID, list[ValueSlotID]] = defaultdict(list)
    writes: dict[OperationDefinitionID, list[ValueSlotID]] = defaultdict(list)
    produces: dict[OperationDefinitionID, list[ValueSlotID]] = defaultdict(list)
    for edge in semantic.edges.values():
        meter.step()
        if edge.relation not in (SemanticRelation.READS_SLOT,
                                 SemanticRelation.WRITES_SLOT,
                                 SemanticRelation.PRODUCES):
            continue
        if edge.source.kind is not SemanticNodeKind.OPERATION or edge.target.kind is not SemanticNodeKind.VALUE_SLOT:
            continue
        target = edge.target.id
        if not isinstance(target, ValueSlotID):
            continue
        table = (reads if edge.relation is SemanticRelation.READS_SLOT else
                 writes if edge.relation is SemanticRelation.WRITES_SLOT else produces)
        table[edge.source.id].append(target)
    for table in (reads, writes, produces):
        for key in table:
            table[key].sort(key=lambda item: item.wire)
    return reads, writes, produces


def _expression_operations(node: ast.AST, path: str, operations_by_span, scope,
                           meter: _Meter) -> tuple[sm.OperationSemantics, ...] | None:
    """Return every supported expression operation in source evaluation order."""
    values: dict[int, tuple[sm.OperationSemantics, ...]] = {}
    stack: list[tuple[ast.AST, bool, tuple[ast.AST, ...]]] = [(node, False, ())]
    while stack:
        current, finished, children = stack.pop()
        if not finished:
            meter.node()
            if isinstance(current, ast.Constant) or isinstance(current, ast.Name):
                children = ()
            elif isinstance(current, ast.Tuple):
                children = tuple(current.elts)
            elif isinstance(current, ast.UnaryOp) and type(current.op) in _UNARY_EXPR_TYPES:
                children = (current.operand,)
            elif isinstance(current, ast.BinOp) and type(current.op) in _BINARY_EXPR_TYPES:
                children = (current.left, current.right)
            else:
                return None
            meter.step(len(children))
            stack.append((current, True, children))
            stack.extend((child, False, ()) for child in reversed(children))
            continue

        candidates = [item for item in operations_by_span.get(_source_atom_key(path, current), ())
                      if item.scope == scope]
        if len(candidates) != 1:
            return None
        operation = candidates[0]
        if operation.result is None or operation.dispatch is not sm.DispatchKind.BUILTIN:
            return None
        if isinstance(current, ast.Name):
            if operation.opcode is not sm.Opcode.READ:
                return None
        elif isinstance(current, ast.Constant):
            if operation.opcode is not sm.Opcode.LITERAL:
                return None
        elif isinstance(current, ast.Tuple):
            if operation.opcode is not sm.Opcode.BUILD_TUPLE:
                return None
        elif isinstance(current, ast.UnaryOp):
            if operation.opcode not in {sm.Opcode.POS, sm.Opcode.NEG, sm.Opcode.INVERT}:
                return None
        elif isinstance(current, ast.BinOp):
            if operation.opcode not in {sm.Opcode.ADD, sm.Opcode.SUB, sm.Opcode.MUL,
                    sm.Opcode.TRUE_DIV, sm.Opcode.FLOOR_DIV, sm.Opcode.MOD,
                    sm.Opcode.POW, sm.Opcode.LSHIFT, sm.Opcode.RSHIFT,
                    sm.Opcode.BIT_AND, sm.Opcode.BIT_OR, sm.Opcode.BIT_XOR}:
                return None
        nested = []
        for child in children:
            nested.extend(values[id(child)])
        values[id(current)] = tuple(nested) + (operation,)
    return values.get(id(node))


def _proof_lineage(report, fact, by_id=None) -> tuple[str, ...]:
    if fact is None or fact.proof_id is None:
        return ()
    # The root proof record owns its premise IDs. Keeping only this root avoids
    # serializing an O(n^2) transitive closure for long alias chains; the fixed
    # constant checker and source digest let the caller recompute every premise.
    if by_id is not None and fact.proof_id not in by_id:
        return ()
    return (fact.proof_id,)


def _has_floating_runtime_requirement(report, proof_ids, by_id=None,
                                      cache=None, meter: _Meter | None = None) -> bool:
    required = ConstantRuntimeRequirement.FLOATING_ENVIRONMENT_MATCH
    by_id = ({proof.id: proof for proof in report.proofs.values()}
             if by_id is None else by_id)
    cache = {} if cache is None else cache
    for root in proof_ids:
        if root in cache:
            if cache[root]:
                return True
            continue
        pending = [(root, False)]
        queued = {root}
        while pending:
            identity, finished = pending.pop()
            if identity in cache:
                continue
            if meter is not None:
                meter.step()
            proof = by_id.get(identity)
            if proof is None:
                cache[identity] = False
                continue
            if required in proof.runtime_requirements:
                cache[identity] = True
                continue
            if not finished:
                pending.append((identity, True))
                for premise in reversed(proof.premises):
                    if premise not in cache and premise not in queued:
                        queued.add(premise)
                        pending.append((premise, False))
            else:
                cache[identity] = any(cache.get(item, False)
                                      for item in proof.premises)
        if cache.get(root, False):
            return True
    return False


def _contains_known_exception(source_semantics, constant_report, value_id,
                              meter: _Meter, cache: dict[StaticValueID, bool]) -> bool:
    pending = [(value_id, False)]
    queued = {value_id}
    while pending:
        current, finished = pending.pop()
        if current in cache:
            continue
        meter.step()
        fact = constant_report.facts.get(current)
        if fact is not None and fact.status is ConstantStatus.KNOWN_EXCEPTION:
            cache[current] = True
            continue
        value = source_semantics.values.get(current)
        operation = (source_semantics.operations.get(value.producer)
                     if value is not None and value.producer is not None else None)
        if operation is None:
            cache[current] = False
            continue
        dependencies = [item.value for item in operation.operands]
        if operation.opcode is sm.Opcode.READ:
            use = source_semantics.uses.get(operation.binding_use)
            if use is not None and use.status is sm.BindingStatus.EXACT and len(use.reaching) == 1:
                binding = source_semantics.bindings.get(use.reaching[0])
                if binding is not None:
                    dependencies.append(binding.value)
        if not finished:
            pending.append((current, True))
            for dependency in reversed(dependencies):
                if dependency not in cache and dependency not in queued:
                    queued.add(dependency)
                    pending.append((dependency, False))
        else:
            cache[current] = any(cache.get(item, False) for item in dependencies)
    return cache.get(value_id, False)


def _verify_budget(stored: EvaluationBudget, ceiling: EvaluationBudget) -> None:
    if type(stored) is not EvaluationBudget or type(ceiling) is not EvaluationBudget:
        raise TypeError("verification budgets must be EvaluationBudget")
    stored.__post_init__()
    ceiling.__post_init__()
    excess = [name for name in stored.__dataclass_fields__
              if getattr(stored, name) > getattr(ceiling, name)]
    if excess:
        raise ValueError("stored local statement evaluation budget exceeds caller ceiling: "
                         + ", ".join(excess))


def _verify_control_budget(stored: ControlFlowBudget, ceiling: ControlFlowBudget) -> None:
    if type(stored) is not ControlFlowBudget or type(ceiling) is not ControlFlowBudget:
        raise TypeError("control-flow budgets must be ControlFlowBudget")
    stored.__post_init__()
    ceiling.__post_init__()
    excess = [name for name in stored.__dataclass_fields__
              if getattr(stored, name) > getattr(ceiling, name)]
    if excess:
        raise ValueError("stored local statement control budget exceeds caller ceiling: "
                         + ", ".join(excess))


class LocalStatementSemanticsReport:
    """Recomputable report; graph references are inputs, never stored authority."""

    def __init__(self, record: _ReportRecord, *, semantic: SemanticGraph,
                 source_semantics: sm.SourceSemanticsGraph,
                 control_flow: SourceControlFlowGraph,
                 source_texts: dict[str, str] | None):
        self._record_value = record
        self._semantic = semantic
        self._source_semantics = source_semantics
        self._control_flow = control_flow
        self._source_texts = source_texts

    def __getattr__(self, name):
        try:
            return getattr(self._record_value, name)
        except AttributeError:
            raise AttributeError(name) from None

    def _recompute(self, *, verification_budget=EvaluationBudget(),
                   control_budget: ControlFlowBudget | None = None):
        _verify_budget(self._record_value.budget, verification_budget)
        ceiling = ControlFlowBudget() if control_budget is None else control_budget
        _verify_control_budget(self._record_value.control_budget, ceiling)
        expected = derive_local_statement_semantics(
            self._semantic, self._source_semantics, self._control_flow,
            self._record_value.suite, source_texts=self._source_texts,
            budget=self._record_value.budget,
            control_budget=self._record_value.control_budget)
        return expected._record_value

    def validate(self, *, verification_budget=EvaluationBudget(),
                 control_budget: ControlFlowBudget | None = None) -> dict[str, Any]:
        try:
            errors = record_errors(self._record_value, _ReportRecord,
                                   "local_statement_semantics")
            if errors:
                return {"valid": False, "errors": sorted(set(errors))}
            expected = self._recompute(verification_budget=verification_budget,
                                       control_budget=control_budget)
            if encode(self._record_value) != encode(expected):
                return {"valid": False,
                        "errors": ["statement certificates differ from fixed-rule source replay"]}
            return {"valid": True, "errors": []}
        except (ValueError, TypeError, KeyError, AttributeError, OSError,
                SyntaxError, RecursionError) as exc:
            return {"valid": False, "errors": [str(exc)]}

    def assert_valid(self, **kwargs):
        result = self.validate(**kwargs)
        if not result["valid"]:
            raise ValueError("invalid local statement semantics: " + "; ".join(result["errors"]))
        return result

    def to_dict(self, *, verification_budget=EvaluationBudget(),
                control_budget: ControlFlowBudget | None = None) -> dict[str, Any]:
        self.assert_valid(verification_budget=verification_budget,
                          control_budget=control_budget)
        return {"schema": SCHEMA, "schema_version": SCHEMA_VERSION,
                "report": encode(self._record_value)}

    def to_json(self, *, verification_budget=EvaluationBudget(),
                control_budget: ControlFlowBudget | None = None) -> str:
        return json.dumps(self.to_dict(verification_budget=verification_budget,
                                      control_budget=control_budget),
                          sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False)

    @classmethod
    def from_dict(cls, document, *, semantic: SemanticGraph,
                  source_semantics: sm.SourceSemanticsGraph,
                  control_flow: SourceControlFlowGraph, suite: ControlFlowSuiteID,
                  source_texts: dict[str, str] | None = None,
                  verification_budget: EvaluationBudget = EvaluationBudget(),
                  control_budget: ControlFlowBudget = ControlFlowBudget()):
        if (type(document) is not dict or set(document) != {"schema", "schema_version", "report"}
                or document["schema"] != SCHEMA or type(document["schema_version"]) is not int
                or document["schema_version"] != SCHEMA_VERSION):
            raise ValueError("unsupported local statement semantics schema")
        record = decode(_ReportRecord, document["report"])
        if record.suite != suite:
            raise ValueError("serialized statement report names a different suite")
        _verify_budget(record.budget, verification_budget)
        _verify_control_budget(record.control_budget, control_budget)
        report = derive_local_statement_semantics(
            semantic, source_semantics, control_flow, suite,
            source_texts=source_texts, budget=record.budget,
            control_budget=record.control_budget)
        if encode(record) != encode(report._record_value):
            raise ValueError("serialized statement report differs from fixed-rule source replay")
        return report

    @classmethod
    def from_json(cls, payload, **kwargs):
        return cls.from_dict(loads(payload), **kwargs)


def _read_text(path: str, supplied: dict[str, str] | None, budget: ControlFlowBudget) -> str:
    if supplied is not None:
        if type(supplied) is not dict or any(type(key) is not str or type(value) is not str
                                              for key, value in supplied.items()):
            raise ValueError("source_texts must map paths to decoded source text")
        try:
            return supplied[path]
        except KeyError as exc:
            raise ValueError("source_texts lacks suite source path") from exc
    try:
        with tokenize.open(path) as stream:
            text = stream.read(budget.max_source_bytes + 1)
    except (OSError, UnicodeError, LookupError) as exc:
        raise ValueError("cannot read suite source snapshot: " + str(exc)) from exc
    if len(text.encode("utf-8")) > budget.max_source_bytes:
        raise ValueError("local statement source-byte budget exceeded")
    return text


def _ast_source_function(tree: ast.Module, source: SourceReference, meter: _Meter):
    matches = []
    stack = [tree]
    while stack:
        node = stack.pop()
        meter.node()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _span(node)[1:] == (
                source.start_line, source.end_line, source.start_column, source.end_column):
            matches.append(node)
        children = list(ast.iter_child_nodes(node))
        meter.step(len(children))
        stack.extend(reversed(children))
    return matches


def _record_digest_context(semantic, source_semantics, control_flow, suite,
                           semantic_digest, source_semantics_digest,
                           control_flow_digest, certificates, gaps, usage,
                           coverage, budget, control_budget):
    return _digest({
        "rule_version": RULE_VERSION,
        "scope": control_flow.suites[suite].scope,
        "suite": suite,
        "source_version": control_flow.suites[suite].version,
        "semantic_digest": semantic_digest,
        "source_semantics_digest": source_semantics_digest,
        "control_flow_digest": control_flow_digest,
        "budget": budget,
        "control_budget": control_budget,
        "usage": usage,
        "coverage": coverage,
        "certificates": certificates,
        "gaps": gaps,
        "required_conditions": _condition_set(),
        "required_source_preconditions": _source_precondition_set(),
    })


def _derive_records(semantic: SemanticGraph, source_semantics: sm.SourceSemanticsGraph,
                    control_flow: SourceControlFlowGraph, suite_id: ControlFlowSuiteID,
                    *, source_texts: dict[str, str] | None, budget: EvaluationBudget,
                    control_budget: ControlFlowBudget):
    semantic.assert_valid()
    source_semantics.assert_valid(semantic)
    control_flow.assert_valid(semantic, source_semantics)
    source_validation = validate_source_semantics(source_semantics, semantic,
                                                  sources=source_texts)
    if not source_validation["valid"]:
        raise ValueError("source semantics replay failed: " + "; ".join(source_validation["errors"]))
    cfg_validation = validate_source_control_flow(
        control_flow, semantic, source_semantics, sources=source_texts,
        verification_budget=control_budget)
    if not cfg_validation["valid"]:
        raise ValueError("control-flow replay failed: " + "; ".join(cfg_validation["errors"]))
    if type(suite_id) is not ControlFlowSuiteID or suite_id not in control_flow.suites:
        raise ValueError("suite must reference a known ControlFlowSuiteID")
    suite = control_flow.suites[suite_id]
    scope = suite.scope
    meter = _Meter(control_budget)
    gaps: list[StatementGap] = []
    certificates: list[StatementCertificate] = []
    constant_targets: list[StaticValueID] = []
    pending: list[dict[str, Any]] = []

    semantic_digest = _source_digest(semantic)
    source_semantics_digest = _source_digest(source_semantics)
    control_flow_digest = _source_digest(control_flow)
    if suite.kind is not SuiteKind.FUNCTION:
        gaps.append(_gap(GapKind.WRONG_SUITE, scope, suite_id,
                         "Only a lexical synchronous-function suite can be certified."))
    if not suite.complete:
        gaps.append(_gap(GapKind.CONTROL_FLOW_GAP, scope, suite_id,
                         "Control-flow suite is incomplete."))
    if not isinstance(semantic.definitions.get(scope), type(next(iter(semantic.definitions.values()), None))):
        # The reference check below emits a useful gap; this avoids trusting only
        # a serialized scope ID and keeps malformed model types out of the walk.
        gaps.append(_gap(GapKind.FUNCTION_JOIN, scope, suite_id,
                         "Function scope has no SemanticGraph definition."))
    scope_definition = semantic.definitions.get(scope)
    if scope_definition is None or scope_definition.kind.value != "function":
        gaps.append(_gap(GapKind.FUNCTION_JOIN, scope, suite_id,
                         "Suite scope does not identify a plain function definition."))

    text = _read_text(suite.version.path, source_texts, control_budget)
    fingerprint = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    if fingerprint != suite.version.fingerprint:
        raise ValueError("suite source fingerprint mismatch")
    try:
        tree = ast.parse(text, filename=suite.version.path, type_comments=True)
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise ValueError("cannot parse suite source snapshot: " + str(exc)) from exc
    function_nodes = _ast_source_function(tree, suite.source, meter) if suite.source is not None else []
    if len(function_nodes) != 1 or not isinstance(function_nodes[0], ast.FunctionDef):
        gaps.append(_gap(GapKind.FUNCTION_JOIN, scope, suite_id,
                         "Suite does not join uniquely to a synchronous FunctionDef source node.",
                         source=suite.source))
        function_node = None
    else:
        function_node = function_nodes[0]
    for control_gap in control_flow.gaps:
        if control_gap.suite == suite_id:
            gaps.append(_gap(GapKind.CONTROL_FLOW_GAP, scope, suite_id,
                             control_gap.reason, source=control_gap.source,
                             statement=control_gap.operation))

    if function_node is not None:
        if (function_node.decorator_list or function_node.returns is not None
                or any(arg.annotation is not None for arg in
                       function_node.args.posonlyargs + function_node.args.args
                       + function_node.args.kwonlyargs)
                or function_node.args.defaults
                or any(item is not None for item in function_node.args.kw_defaults)):
            gaps.append(_gap(GapKind.UNSUPPORTED_FUNCTION, scope, suite_id,
                             "Decorators, defaults and annotations are outside the first local-body subset.",
                             source=suite.source))
        if any((function_node.args.vararg, function_node.args.kwarg)):
            gaps.append(_gap(GapKind.UNSUPPORTED_FUNCTION, scope, suite_id,
                             "Variadic parameters are outside the first local-body subset.",
                             source=suite.source))
        if (function_node.args.posonlyargs or function_node.args.args
                or function_node.args.kwonlyargs):
            argument_names = [item.arg for item in function_node.args.posonlyargs
                              + function_node.args.args + function_node.args.kwonlyargs]
            if len(argument_names) != len(set(argument_names)):
                gaps.append(_gap(GapKind.UNSUPPORTED_FUNCTION, scope, suite_id,
                                 "Duplicate parameter names prevent a precise slot join.",
                                 source=suite.source))

    atom_by_span = defaultdict(list)
    for atom in semantic.source_atoms.values():
        meter.step()
        atom_by_span[_reference_atom_key(atom.reference, atom.kind)].append(atom)
    operations_by_span: dict[tuple, list[sm.OperationSemantics]] = defaultdict(list)
    for operation in source_semantics.operations.values():
        meter.step()
        atom = semantic.source_atoms.get(operation.source.atom_id)
        if atom is not None:
            operations_by_span[_reference_atom_key(operation.source, atom.kind)].append(operation)
    # Build one-pass indexes for source reads/writes and SG statement edges.
    bindings_by_source: dict[tuple, list[sm.StaticBinding]] = defaultdict(list)
    history_by_slot_scope: dict[tuple, list[sm.StaticBinding]] = defaultdict(list)
    for binding in source_semantics.bindings.values():
        meter.step()
        bindings_by_source[_reference_key(binding.source)].append(binding)
        history_by_slot_scope[(binding.slot, binding.scope)].append(binding)
    uses_by_operation: dict[OperationDefinitionID, list[sm.BindingUse]] = defaultdict(list)
    for use in source_semantics.uses.values():
        meter.step()
        uses_by_operation[use.operation].append(use)
    reads, writes, produces = _semantic_edges(semantic, meter)

    if function_node is not None and suite.source is not None:
        statement_nodes = [node for node in control_flow.nodes.values()
                           if node.suite == suite_id and node.kind in
                           {NodeKind.STATEMENT, NodeKind.GAP, NodeKind.BRANCH_TEST,
                            NodeKind.LOOP_TEST}]
        meter.step(len(control_flow.nodes))
        node_by_source = defaultdict(list)
        for node in statement_nodes:
            if node.source is not None:
                node_by_source[_reference_key(node.source)].append(node)
        ast_statement_keys = []
        for statement in function_node.body:
            meter.node()
            candidates = atom_by_span.get(_source_atom_key(suite.version.path, statement), ())
            if len(candidates) != 1:
                gaps.append(_gap(GapKind.AMBIGUOUS_OPERATION, scope, suite_id,
                                 "Function-body statement has no unique source atom.",
                                 statement=None))
                ast_statement_keys.append(None)
                continue
            reference = candidates[0].reference
            ast_statement_keys.append(_reference_key(reference))
            cfg_nodes = node_by_source.get(_reference_key(reference), ())
            if len(cfg_nodes) != 1:
                gaps.append(_gap(GapKind.CONTROL_FLOW_GAP, scope, suite_id,
                                 "Function-body statement does not map to exactly one CFG statement node.",
                                 source=reference))
                pending.append({"statement": statement, "source": reference,
                                "node": None, "reason": "missing CFG node"})
                continue
            pending.append({"statement": statement, "source": reference,
                            "node": cfg_nodes[0], "reason": ""})
        represented = {key for key in ast_statement_keys if key is not None}
        if represented != set(node_by_source):
            gaps.append(_gap(GapKind.CONTROL_FLOW_GAP, scope, suite_id,
                             "CFG suite contains a source statement outside the joined function body."))
        if not function_node.body:
            gaps.append(_gap(GapKind.UNSUPPORTED_FUNCTION, scope, suite_id,
                             "Empty function bodies are outside the first certificate subset.",
                             source=suite.source))
        if (not function_node.body or not isinstance(function_node.body[-1], ast.Return)
                or sum(isinstance(item, ast.Return) for item in function_node.body) != 1):
            gaps.append(_gap(GapKind.UNSUPPORTED_FUNCTION, scope, suite_id,
                             "The subset requires exactly one final Return statement.",
                             source=suite.source))
        if any(isinstance(item, (ast.Global, ast.Nonlocal, ast.AsyncFunctionDef,
                                 ast.ClassDef, ast.If, ast.For, ast.AsyncFor,
                                 ast.While, ast.Try, getattr(ast, "TryStar", ast.Try),
                                 ast.With, ast.AsyncWith, ast.Break, ast.Continue,
                                 ast.Raise, ast.Delete, ast.AugAssign, ast.AnnAssign))
               for item in function_node.body):
            gaps.append(_gap(GapKind.UNSUPPORTED_FUNCTION, scope, suite_id,
                             "Function body contains control, namespace or mutation syntax outside the subset.",
                             source=suite.source))

    body_local_writes: dict[ValueSlotID, list[tuple[ast.stmt, sm.StaticBinding]]] = defaultdict(list)
    bindings_by_statement: dict[int, list[sm.StaticBinding]] = defaultdict(list)
    expected_use_ids: set[sm.BindingUseID] = set()
    all_load_nodes: list[ast.Name] = []
    if function_node is not None:
        for record in pending:
            statement = record["statement"]
            if isinstance(statement, ast.Assign):
                if len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name):
                    gaps.append(_gap(GapKind.UNSUPPORTED_STATEMENT, scope, suite_id,
                                     "Assign requires exactly one Name target.", source=record["source"],
                                     statement=(record["node"].operations[0]
                                                if record["node"] and len(record["node"].operations) == 1 else None)))
                    continue
                target = statement.targets[0]
                target_atoms = atom_by_span.get(_source_atom_key(suite.version.path, target), ())
                if len(target_atoms) != 1:
                    gaps.append(_gap(GapKind.AMBIGUOUS_BINDING, scope, suite_id,
                                     "Assignment target has no unique source reference.",
                                     source=record["source"]))
                else:
                    matches = bindings_by_source.get(_reference_key(target_atoms[0].reference), ())
                    matches = [item for item in matches if item.scope == scope]
                    if len(matches) != 1:
                        gaps.append(_gap(GapKind.AMBIGUOUS_BINDING, scope, suite_id,
                                         "Assignment target does not define exactly one source binding.",
                                         source=target_atoms[0].reference))
                    else:
                        body_local_writes[matches[0].slot].append((statement, matches[0]))
                        bindings_by_statement[id(statement)].append(matches[0])
            elif isinstance(statement, ast.Pass):
                pass
            elif isinstance(statement, ast.Return):
                pass
            else:
                gaps.append(_gap(GapKind.UNSUPPORTED_STATEMENT, scope, suite_id,
                                 "Only Assign, Return and Pass statements are supported.",
                                 source=record["source"],
                                 statement=(record["node"].operations[0]
                                            if record["node"] and len(record["node"].operations) == 1 else None)))
        # Compare source-level local writes and uses across the full body, not
        # only the bindings that happened to have epoch zero.
        parameter_slots = set(scope_definition.input_slots) if scope_definition else set()
        for slot_id, writes_for_slot in body_local_writes.items():
            slot = semantic.slots.get(slot_id)
            if (slot is None or slot.owner != scope or slot_id in parameter_slots
                    or slot.direction == "input"):
                gaps.append(_gap(GapKind.NONLOCAL_OR_PARAMETER, scope, suite_id,
                                 "Assignment target is a parameter, outer slot or nonlocal binding.",
                                 source=writes_for_slot[0][1].source))
            if len(writes_for_slot) != 1:
                gaps.append(_gap(GapKind.REBOUND_LOCAL, scope, suite_id,
                                 "A local slot is assigned more than once.",
                                 source=writes_for_slot[-1][1].source))
            all_history = history_by_slot_scope.get((slot_id, scope), ())
            if len(all_history) != 1 or (all_history and all_history[0].id != writes_for_slot[0][1].id):
                gaps.append(_gap(GapKind.REBOUND_LOCAL, scope, suite_id,
                                 "The source model has an earlier or additional binding for this local slot.",
                                 source=writes_for_slot[0][1].source))
        for record in pending:
            node = record["statement"]
            if isinstance(node, (ast.Assign, ast.Return)):
                expression = node.value
                if expression is not None:
                    visitor = _ExpressionNames(meter)
                    visitor.visit(expression)
                    all_load_nodes.extend(visitor.names)
        for name_node in all_load_nodes:
            candidates = atom_by_span.get(_source_atom_key(suite.version.path, name_node), ())
            if len(candidates) != 1:
                gaps.append(_gap(GapKind.AMBIGUOUS_BINDING, scope, suite_id,
                                 "Name read has no unique source atom."))
                continue
            ref = candidates[0].reference
            operations = [item for item in operations_by_span.get(
                _source_atom_key(suite.version.path, name_node), ())
                if item.scope == scope and item.opcode is sm.Opcode.READ]
            if len(operations) != 1:
                gaps.append(_gap(GapKind.AMBIGUOUS_BINDING, scope, suite_id,
                                 "Name read has no unique static READ operation.", source=ref))
                continue
            operation = operations[0]
            use = source_semantics.uses.get(operation.binding_use)
            if use is None or use.status is not sm.BindingStatus.EXACT or len(use.reaching) != 1:
                gaps.append(_gap(GapKind.UNRESOLVED_READ, scope, suite_id,
                                 "Name read lacks one EXACT local binding.", source=ref,
                                 statement=operation.operation))
                continue
            binding = source_semantics.bindings.get(use.reaching[0])
            if binding is None or binding.scope != scope:
                gaps.append(_gap(GapKind.EXTERNAL_OR_CLOSURE_READ, scope, suite_id,
                                 "Name read resolves outside the current function scope.", source=ref,
                                 statement=operation.operation))
                continue
            if binding.slot not in body_local_writes:
                gaps.append(_gap(GapKind.EXTERNAL_OR_CLOSURE_READ, scope, suite_id,
                                 "Name read does not resolve to a first local binding in this body.",
                                 source=ref, statement=operation.operation))
                continue
            expected_use_ids.add(use.id)
        actual_use_ids = {use.id for use in source_semantics.uses.values()
                          if use.scope == scope}
        if actual_use_ids != expected_use_ids:
            missing = actual_use_ids - expected_use_ids
            if missing:
                gaps.append(_gap(GapKind.SOURCE_SEMANTICS_GAP, scope, suite_id,
                                 "Function scope contains an unjoined or hidden local read."))

    # Only allow the source extractor's terminal-return barrier; all earlier
    # barriers make later EXACT local facts conditional or open-ended.
    terminal_boundaries = [item for item in source_semantics.boundaries if item.scope == scope]
    if terminal_boundaries:
        accepted = (function_node is not None and function_node.body
                    and isinstance(function_node.body[-1], ast.Return)
                    and len(terminal_boundaries) == 1
                    and terminal_boundaries[0].reason == "Following source is not proved reachable after return."
                    and all(item.position > max((op.position for op in source_semantics.operations.values()
                                                 if op.scope == scope), default=-1)
                            for item in terminal_boundaries))
        if not accepted:
            gaps.append(_gap(GapKind.SOURCE_SEMANTICS_GAP, scope, suite_id,
                             "Function scope has a nonterminal source-semantic boundary."))
    elif function_node is not None and function_node.body and isinstance(function_node.body[-1], ast.Return):
        gaps.append(_gap(GapKind.SOURCE_SEMANTICS_GAP, scope, suite_id,
                         "Terminal Return barrier is missing from source semantics."))

    # One constant evaluation shares dependency memoization over every candidate
    # assigned/returned value. Its result is value evidence only, never a purity
    # or whole-statement certificate.
    for slot_writes in body_local_writes.values():
        for _, binding in slot_writes:
            constant_targets.append(binding.value)
    if function_node is not None:
        for record in pending:
            statement = record["statement"]
            expr = statement.value if isinstance(statement, (ast.Assign, ast.Return)) else None
            if expr is None:
                continue
            operations = _expression_operations(expr, suite.version.path,
                                                operations_by_span, scope, meter)
            if operations:
                constant_targets.extend(item.result for item in operations
                                        if item.result is not None)
    constant_report = evaluate_constants(
        source_semantics, targets=tuple(dict.fromkeys(constant_targets)), budget=budget)
    constant_proof_by_id = {proof.id: proof for proof in constant_report.proofs.values()}
    floating_requirement_cache: dict[str, bool] = {}
    known_exception_cache: dict[StaticValueID, bool] = {}

    if function_node is not None:
        # Find the result return slot once, then reuse the maps for each source
        # statement. No per-statement graph scan is performed below.
        return_slots = tuple(scope_definition.output_slots) if scope_definition else ()
        if len(return_slots) != 1 or return_slots[0] not in semantic.slots:
            return_slot = None
        else:
            return_slot = return_slots[0]
        operation_reads, operation_writes, operation_produces = reads, writes, produces
        binding_by_id = source_semantics.bindings
        for record in pending:
            statement_node = record["statement"]
            source = record["source"]
            cfg_node = record["node"]
            if cfg_node is None or len(cfg_node.operations) != 1:
                continue
            statement_id = cfg_node.operations[0]
            stmt_def = semantic.definitions.get(statement_id)
            expected_label = ("return" if isinstance(statement_node, ast.Return)
                              else type(statement_node).__name__)
            if stmt_def is None or stmt_def.parent_id != scope or stmt_def.label != expected_label:
                gaps.append(_gap(GapKind.AMBIGUOUS_OPERATION, scope, suite_id,
                                 "CFG statement operation does not uniquely belong to this function AST statement.",
                                 source=source, statement=statement_id))
                continue
            if isinstance(statement_node, ast.Pass):
                if operation_reads.get(statement_id) or operation_writes.get(statement_id):
                    gaps.append(_gap(GapKind.SEMANTIC_EDGE_MISMATCH, scope, suite_id,
                                     "Pass unexpectedly reads or writes a semantic slot.",
                                     source=source, statement=statement_id))
                    continue
                kind = StatementKind.PASS
                expression_value = result_value = None
                written_binding = written_slot = alias_source_binding = None
                immutable_type = None
                proof_ids = ()
                ordered_reads = ()
            elif isinstance(statement_node, ast.Assign):
                if len(statement_node.targets) != 1 or not isinstance(statement_node.targets[0], ast.Name):
                    continue
                rhs = statement_node.value
                shape = _expression_shape(rhs, meter, allow_name_alias=True)
                if shape is None:
                    gaps.append(_gap(GapKind.UNSUPPORTED_EXPRESSION, scope, suite_id,
                                     "Assign RHS is outside immutable literals, closed builtins or exact local aliases.",
                                     source=source, statement=statement_id))
                    continue
                expression_ops = _expression_operations(rhs, suite.version.path,
                                                       operations_by_span, scope, meter)
                if not expression_ops:
                    gaps.append(_gap(GapKind.AMBIGUOUS_OPERATION, scope, suite_id,
                                     "Assignment RHS has no unique source-semantics operation tree.",
                                     source=source, statement=statement_id))
                    continue
                expression_value = expression_ops[-1].result
                target_candidates = bindings_by_statement.get(id(statement_node), ())
                if len(target_candidates) != 1:
                    continue
                target_binding = target_candidates[0]
                written_binding, written_slot = target_binding.id, target_binding.slot
                expression_definition = semantic.definitions.get(
                    source_semantics.values[expression_value].producer)
                if (expression_definition is None or len(expression_definition.output_slots) != 1
                        or operation_reads.get(statement_id, ()) != [expression_definition.output_slots[0]]):
                    gaps.append(_gap(GapKind.SEMANTIC_EDGE_MISMATCH, scope, suite_id,
                                     "Assign does not read exactly its source expression result slot.",
                                     source=source, statement=statement_id))
                    continue
                assigned_value = source_semantics.values.get(target_binding.value)
                binding_operation = source_semantics.operations.get(target_binding.definition)
                binding_definition = semantic.definitions.get(target_binding.definition)
                if (assigned_value is None or binding_operation is None
                        or binding_definition is None or binding_definition.parent_id != statement_id
                        or operation_writes.get(target_binding.definition, ()) != [written_slot]
                        or operation_reads.get(target_binding.definition, ()) != [expression_definition.output_slots[0]]
                        or binding_operation.opcode is not sm.Opcode.ALIAS
                        or binding_operation.dispatch is not sm.DispatchKind.BUILTIN
                        or len(binding_operation.operands) != 1
                        or binding_operation.operands[0].value != expression_value):
                    gaps.append(_gap(GapKind.SEMANTIC_EDGE_MISMATCH, scope, suite_id,
                                     "Written binding is not the exact alias of the source RHS value.",
                                     source=target_binding.source, statement=statement_id))
                    continue
                read_records, read_gap = _reads_for_expression(
                    rhs, suite.version.path, scope, source_semantics,
                    operations_by_span, binding_by_id, body_local_writes, meter)
                if read_gap:
                    gaps.append(_gap(read_gap[0], scope, suite_id, read_gap[1],
                                     source=source, statement=statement_id))
                    continue
                ordered_reads = read_records
                alias_source_binding = (ordered_reads[0].binding if shape == "alias" else None)
                result_value = target_binding.value
                fact = constant_report.facts.get(result_value)
                if fact is None or fact.status is not ConstantStatus.CONSTANT or fact.literal is None:
                    kind_gap = (GapKind.KNOWN_EXCEPTION if _contains_known_exception(
                                    source_semantics, constant_report, result_value, meter,
                                    known_exception_cache)
                                else GapKind.NONCONSTANT_VALUE)
                    gaps.append(_gap(kind_gap, scope, suite_id,
                                     "Assignment result lacks a successful immutable builtin constant derivation.",
                                     source=source, statement=statement_id))
                    continue
                proof_ids = _proof_lineage(constant_report, fact, constant_proof_by_id)
                if not proof_ids:
                    gaps.append(_gap(GapKind.NONCONSTANT_VALUE, scope, suite_id,
                                     "Assignment has no replayable constant proof lineage.",
                                     source=source, statement=statement_id))
                    continue
                if _has_floating_runtime_requirement(constant_report, proof_ids,
                                                     constant_proof_by_id,
                                                     floating_requirement_cache, meter):
                    gaps.append(_gap(GapKind.UNSUPPORTED_EXPRESSION, scope, suite_id,
                                     "Floating arithmetic requires a target floating-environment Q path not supported here.",
                                     source=source, statement=statement_id))
                    continue
                immutable_type = _literal_type(fact.literal)
                if immutable_type is None:
                    gaps.append(_gap(GapKind.MUTABLE_VALUE, scope, suite_id,
                                     "Assignment result is not an immutable builtin value.",
                                     source=source, statement=statement_id))
                    continue
                if shape == "alias":
                    kind = StatementKind.ASSIGN_ALIAS
                    # The exact StaticBinding link, rather than content equality,
                    # is the identity-preservation witness.
                    alias_binding = binding_by_id.get(alias_source_binding)
                    read_use = source_semantics.uses.get(ordered_reads[0].use) if ordered_reads else None
                    if (alias_binding is None or read_use is None
                            or read_use.reaching != (alias_binding.id,)
                            or binding_operation.operands[0].value != expression_value):
                        gaps.append(_gap(GapKind.SEMANTIC_EDGE_MISMATCH, scope, suite_id,
                                         "Alias identity does not follow the exact read binding.",
                                         source=source, statement=statement_id))
                        continue
                elif shape == "literal":
                    kind = StatementKind.ASSIGN_LITERAL
                else:
                    kind = StatementKind.ASSIGN_CONSTANT
            elif isinstance(statement_node, ast.Return):
                if statement_node.value is None:
                    gaps.append(_gap(GapKind.UNSUPPORTED_STATEMENT, scope, suite_id,
                                     "Bare return is outside the explicit immutable-value subset.",
                                     source=source, statement=statement_id))
                    continue
                shape = _expression_shape(statement_node.value, meter, allow_name_alias=True)
                if shape not in {"alias", "literal"}:
                    gaps.append(_gap(GapKind.UNSUPPORTED_EXPRESSION, scope, suite_id,
                                     "Return accepts only an exact local Name or immutable literal.",
                                     source=source, statement=statement_id))
                    continue
                expression_ops = _expression_operations(
                    statement_node.value, suite.version.path, operations_by_span, scope, meter)
                if not expression_ops:
                    gaps.append(_gap(GapKind.AMBIGUOUS_OPERATION, scope, suite_id,
                                     "Return expression has no unique source-semantics operation.",
                                     source=source, statement=statement_id))
                    continue
                expression_value = result_value = expression_ops[-1].result
                if (return_slot is None or operation_produces.get(statement_id, ()) != [return_slot]
                        or len(operation_reads.get(statement_id, ())) != 1):
                    gaps.append(_gap(GapKind.SEMANTIC_EDGE_MISMATCH, scope, suite_id,
                                     "Return operation is not connected to one expression and the function return slot.",
                                     source=source, statement=statement_id))
                    continue
                expression_definition = semantic.definitions.get(
                    source_semantics.values[expression_value].producer)
                if (expression_definition is None or len(expression_definition.output_slots) != 1
                        or operation_reads.get(statement_id, ()) != [expression_definition.output_slots[0]]):
                    gaps.append(_gap(GapKind.SEMANTIC_EDGE_MISMATCH, scope, suite_id,
                                     "Return operation reads a different or ambiguous expression slot.",
                                     source=source, statement=statement_id))
                    continue
                read_records, read_gap = _reads_for_expression(
                    statement_node.value, suite.version.path, scope,
                    source_semantics, operations_by_span, binding_by_id,
                    body_local_writes, meter)
                if read_gap:
                    gaps.append(_gap(read_gap[0], scope, suite_id, read_gap[1],
                                     source=source, statement=statement_id))
                    continue
                ordered_reads = read_records
                alias_source_binding = ordered_reads[0].binding if shape == "alias" else None
                fact = constant_report.facts.get(expression_value)
                if fact is None or fact.status is not ConstantStatus.CONSTANT or fact.literal is None:
                    kind_gap = (GapKind.KNOWN_EXCEPTION if _contains_known_exception(
                                    source_semantics, constant_report, expression_value, meter,
                                    known_exception_cache)
                                else GapKind.NONCONSTANT_VALUE)
                    gaps.append(_gap(kind_gap, scope, suite_id,
                                     "Returned value lacks a successful immutable builtin constant derivation.",
                                     source=source, statement=statement_id))
                    continue
                proof_ids = _proof_lineage(constant_report, fact, constant_proof_by_id)
                if not proof_ids:
                    gaps.append(_gap(GapKind.NONCONSTANT_VALUE, scope, suite_id,
                                     "Return has no replayable constant proof lineage.",
                                     source=source, statement=statement_id))
                    continue
                if _has_floating_runtime_requirement(constant_report, proof_ids,
                                                     constant_proof_by_id,
                                                     floating_requirement_cache, meter):
                    gaps.append(_gap(GapKind.UNSUPPORTED_EXPRESSION, scope, suite_id,
                                     "Floating arithmetic requires a target floating-environment Q path not supported here.",
                                     source=source, statement=statement_id))
                    continue
                immutable_type = _literal_type(fact.literal)
                if immutable_type is None:
                    gaps.append(_gap(GapKind.MUTABLE_VALUE, scope, suite_id,
                                     "Returned value is not immutable.", source=source,
                                     statement=statement_id))
                    continue
                kind = StatementKind.RETURN_LOCAL if shape == "alias" else StatementKind.RETURN_LITERAL
                if shape == "alias":
                    alias_binding = binding_by_id.get(alias_source_binding)
                    read_use = source_semantics.uses.get(ordered_reads[0].use) if ordered_reads else None
                    if (alias_binding is None or read_use is None
                            or read_use.reaching != (alias_binding.id,)):
                        gaps.append(_gap(GapKind.SEMANTIC_EDGE_MISMATCH, scope, suite_id,
                                         "Return local is not connected to its exact binding.",
                                         source=source, statement=statement_id))
                        continue
                written_slot = return_slot
                written_binding = None
            else:
                continue

            facts = [StatementFact.SOURCE_AND_CFG_REPLAYED,
                     StatementFact.STRAIGHT_LINE_FUNCTION_BODY,
                     StatementFact.EXACT_READ_BINDINGS,
                     StatementFact.NO_USER_DISPATCH,
                     StatementFact.NO_MUTABLE_VALUE,
                     StatementFact.NO_RNG_OR_AUTOGRAD,
                     StatementFact.NO_EXTERNAL_OR_ORDERED_EFFECT]
            if written_binding is not None:
                facts.append(StatementFact.FIRST_LOCAL_BINDING)
            if alias_source_binding is not None:
                facts.append(StatementFact.ALIAS_IDENTITY_PRESERVED)
            if isinstance(statement_node, ast.Return):
                facts.append(StatementFact.RETURN_SLOT_CONNECTED)
            conditions = _condition_set()
            source_preconditions = _source_precondition_set()
            cert_id = _digest((RULE_VERSION, scope, suite_id, source, statement_id,
                               kind, ordered_reads, written_binding, written_slot,
                               expression_value, result_value, alias_source_binding,
                               immutable_type, proof_ids, tuple(facts), conditions,
                               source_preconditions))
            certificates.append(StatementCertificate(
                cert_id, scope, suite_id, source, statement_id, kind,
                tuple(ordered_reads), written_binding, written_slot,
                expression_value, result_value, alias_source_binding,
                immutable_type, tuple(proof_ids), tuple(facts), conditions,
                source_preconditions))

    certificates.sort(key=lambda item: (item.source.start_line,
                                        item.source.start_column,
                                        item.statement.wire))
    gaps = sorted(set(gaps), key=lambda item: (
        item.source.path if item.source else "",
        item.source.start_line if item.source else 0,
        item.source.start_column if item.source else 0,
        item.kind.value, item.statement.wire if item.statement else "", item.reason))
    # A suite is complete only when every direct source statement has its fixed
    # certificate and no structural/read-closure gap remains.
    expected_statement_count = len(function_node.body) if function_node is not None else 0
    coverage = (Coverage.SUPPORTED if not gaps and len(certificates) == expected_statement_count
                else Coverage.INCOMPLETE)
    usage = LocalStatementUsage(meter.ast_nodes, len(pending),
        len(source_semantics.operations), constant_report.usage, meter.work)
    model_digest = _record_digest_context(
        semantic, source_semantics, control_flow, suite_id,
        semantic_digest, source_semantics_digest, control_flow_digest,
        tuple(certificates), tuple(gaps), usage, coverage, budget, control_budget)
    record = _ReportRecord(SCHEMA, SCHEMA_VERSION, RULE_VERSION, scope,
        suite_id, suite.version, semantic_digest, source_semantics_digest,
        control_flow_digest, model_digest, budget, control_budget, usage,
        coverage, tuple(certificates), tuple(gaps), _condition_set(),
        _source_precondition_set())
    errors = record_errors(record, _ReportRecord, "local_statement_semantics")
    if errors:
        raise ValueError("derived local statement report is malformed: " + "; ".join(errors))
    return record


def _reads_for_expression(node: ast.expr, path: str, scope,
                          source_semantics: sm.SourceSemanticsGraph,
                          operations_by_span, binding_by_id,
                          body_local_writes, meter: _Meter):
    visitor = _ExpressionNames(meter)
    visitor.visit(node)
    result = []
    for name in visitor.names:
        operations = [item for item in operations_by_span.get(_source_atom_key(path, name), ())
                      if item.scope == scope and item.opcode is sm.Opcode.READ]
        if len(operations) != 1:
            return (), (GapKind.AMBIGUOUS_BINDING,
                        "Expression Name read has no unique source READ operation.")
        use = source_semantics.uses.get(operations[0].binding_use)
        if use is None or use.status is not sm.BindingStatus.EXACT or len(use.reaching) != 1:
            return (), (GapKind.UNRESOLVED_READ,
                        "Expression Name read lacks one EXACT local reaching binding.")
        binding = binding_by_id.get(use.reaching[0])
        if binding is None or binding.scope != scope or binding.slot not in body_local_writes:
            return (), (GapKind.EXTERNAL_OR_CLOSURE_READ,
                        "Expression Name read does not resolve to a first local binding.")
        result.append(StatementRead(use.id, binding.id))
    return tuple(result), None


def derive_local_statement_semantics(
        semantic: SemanticGraph,
        source_semantics: sm.SourceSemanticsGraph,
        control_flow: SourceControlFlowGraph,
        suite: ControlFlowSuiteID,
        *, source_texts: dict[str, str] | None = None,
        budget: EvaluationBudget = EvaluationBudget(),
        control_budget: ControlFlowBudget = ControlFlowBudget()) -> LocalStatementSemanticsReport:
    """Derive a source-replayed certificate for one entire function suite.

    Unsupported syntax is retained as a gap and makes report coverage
    incomplete. The function never executes target code and never treats a
    constant fact as a statement-effect proof.
    """
    if type(budget) is not EvaluationBudget or type(control_budget) is not ControlFlowBudget:
        raise TypeError("budget arguments must be EvaluationBudget and ControlFlowBudget")
    budget.__post_init__()
    control_budget.__post_init__()
    record = _derive_records(semantic, source_semantics, control_flow, suite,
        source_texts=source_texts, budget=budget, control_budget=control_budget)
    return LocalStatementSemanticsReport(record, semantic=semantic,
        source_semantics=source_semantics, control_flow=control_flow,
        source_texts=source_texts)


def validate_local_statement_semantics(
        report: LocalStatementSemanticsReport,
        semantic: SemanticGraph,
        source_semantics: sm.SourceSemanticsGraph,
        control_flow: SourceControlFlowGraph,
        suite: ControlFlowSuiteID,
        *, source_texts: dict[str, str] | None = None,
        verification_budget: EvaluationBudget = EvaluationBudget(),
        control_budget: ControlFlowBudget = ControlFlowBudget()) -> dict[str, Any]:
    """Independently rebuild the report from caller-owned source and graph inputs."""
    try:
        if type(report) is not LocalStatementSemanticsReport:
            raise TypeError("report must be LocalStatementSemanticsReport")
        _verify_budget(report.budget, verification_budget)
        _verify_control_budget(report.control_budget, control_budget)
        expected = derive_local_statement_semantics(
            semantic, source_semantics, control_flow, suite,
            source_texts=source_texts, budget=report.budget,
            control_budget=report.control_budget)
        if encode(report._record_value) != encode(expected._record_value):
            return {"valid": False,
                    "errors": ["statement certificates differ from fixed-rule source replay"]}
        return {"valid": True, "errors": []}
    except (ValueError, TypeError, KeyError, AttributeError, OSError,
            SyntaxError, RecursionError) as exc:
        return {"valid": False, "errors": [str(exc)]}


__all__ = [
    "Coverage", "GapKind", "LocalStatementSemanticsReport", "LocalStatementUsage",
    "RequiredCondition", "RULE_VERSION", "SCHEMA", "SCHEMA_VERSION",
    "StatementCertificate", "StatementFact", "StatementGap", "StatementKind",
    "StatementRead", "derive_local_statement_semantics",
    "validate_local_statement_semantics",
]
