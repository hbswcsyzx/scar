"""Bounded builtin constant reasoning over typed source semantics.

Facts establish exact builtin type/content (including float bits), never object
identity, source authenticity, import deletion, effect freedom or profitability.
Only the fixed checker below evaluates operations; target code is not executed.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import math
import operator
import struct
import sys

from scar.ir import semantics_v2 as sm
from scar.ir.record_codec import decode, encode, loads
from scar.ir.v2 import OperationDefinitionID, SourceReference
from scar.ir.v2._validation import record_errors


RULE_VERSION = "scar.builtin.constants.v1"


class ConstantStatus(str, Enum):
    CONSTANT = "CONSTANT"
    NOT_CONSTANT = "NOT_CONSTANT"
    NEEDS_CONTRACT = "NEEDS_CONTRACT"
    KNOWN_EXCEPTION = "KNOWN_EXCEPTION"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"


class SourceValidation(str, Enum):
    NOT_CHECKED = "NOT_CHECKED"


class ContractAcceptance(str, Enum):
    REQUIRED_CONTRACT = "REQUIRED_CONTRACT"


class RuntimeValidation(str, Enum):
    NOT_CHECKED = "NOT_CHECKED"


class ConstantRuntimeRequirement(str, Enum):
    BUILTIN_RUNTIME_MATCH = "builtin_runtime_match"
    FLOATING_ENVIRONMENT_MATCH = "floating_environment_match"


class ConstantRule(str, Enum):
    LITERAL = "literal"
    BINDING = "binding"
    TUPLE = "tuple"
    BUILTIN = "builtin"


class ConstantGapKind(str, Enum):
    UNSUPPORTED = "unsupported"
    BINDING = "binding"
    DISPATCH = "dispatch"
    IMPORT = "import"
    DEPENDENCY = "dependency"
    CYCLE = "cycle"
    BUDGET = "budget"


@dataclass(frozen=True)
class EvaluationBudget:
    max_nodes: int = 10000
    max_steps: int = 10000
    max_work: int = 10000000
    max_int_bits: int = 4096
    max_sequence_items: int = 4096
    max_bytes: int = 1048576
    max_total_output_bytes: int = 8388608
    max_literal_depth: int = 64

    def __post_init__(self):
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError("evaluation budgets must be positive integers")


@dataclass(frozen=True)
class EvaluationUsage:
    nodes: int
    steps: int
    work: int
    output_bytes: int


@dataclass(frozen=True)
class BuiltinRuntime:
    implementation: str
    version: tuple[int, int, int]
    float_mantissa: int
    float_max_exp: int

    @classmethod
    def current(cls):
        return cls(sys.implementation.name, tuple(sys.version_info[:3]),
                   sys.float_info.mant_dig, sys.float_info.max_exp)


@dataclass(frozen=True)
class ConstantGap:
    kind: ConstantGapKind
    reason: str
    operation: OperationDefinitionID | None = None
    reference: str | None = None


@dataclass(frozen=True)
class ConstantFact:
    value: sm.StaticValueID
    status: ConstantStatus
    literal: sm.PythonLiteral | None = None
    proof_id: str | None = None
    gaps: tuple[ConstantGap, ...] = ()
    exception: str | None = None


@dataclass(frozen=True)
class ConstantProof:
    id: str
    rule: ConstantRule
    operation: OperationDefinitionID
    source: SourceReference
    value: sm.StaticValueID
    premises: tuple[str, ...]
    binding_uses: tuple[sm.BindingUseID, ...]
    result_digest: str
    runtime_requirements: tuple[ConstantRuntimeRequirement, ...] = ()


@dataclass(frozen=True)
class _ReportRecord:
    schema: str
    schema_version: int
    model_digest: str
    rule_version: str
    runtime: BuiltinRuntime
    budget: EvaluationBudget
    targets: tuple[sm.StaticValueID, ...]
    facts: tuple[ConstantFact, ...]
    proofs: tuple[ConstantProof, ...]
    usage: EvaluationUsage
    source_validation: SourceValidation
    required_preconditions: tuple[sm.SourceExecutionPrecondition, ...]
    preconditions_status: ContractAcceptance
    runtime_requirements: tuple[ConstantRuntimeRequirement, ...]
    runtime_validation: RuntimeValidation


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode()).hexdigest()


class ConstantReport:
    SCHEMA = "scar.constants"
    SCHEMA_VERSION = 1

    def __init__(self, graph, *, model_digest, budget, targets, facts, proofs, usage):
        self.graph = graph
        self.model_digest = model_digest
        self.rule_version = RULE_VERSION
        self.runtime = BuiltinRuntime.current()
        self.budget, self.targets = budget, targets
        self.facts, self.proofs, self.usage = facts, proofs, usage
        self.source_validation = SourceValidation.NOT_CHECKED
        self.required_preconditions = graph.required_preconditions
        self.preconditions_status = ContractAcceptance.REQUIRED_CONTRACT
        self.runtime_requirements = tuple(sorted({item for proof in proofs.values()
                                                 for item in proof.runtime_requirements}, key=lambda item: item.value))
        self.runtime_validation = RuntimeValidation.NOT_CHECKED

    def _record(self):
        return _ReportRecord(self.SCHEMA, self.SCHEMA_VERSION, self.model_digest,
            self.rule_version, self.runtime, self.budget, self.targets,
            tuple(self.facts[key] for key in sorted(self.facts, key=lambda item: item.wire)),
            tuple(self.proofs[key] for key in sorted(self.proofs)), self.usage, self.source_validation,
            self.required_preconditions, self.preconditions_status, self.runtime_requirements,
            self.runtime_validation)

    def validate(self, graph=None, *, verification_budget=EvaluationBudget()):
        graph = self.graph if graph is None else graph
        try:
            _check_verification_budget(self.budget, verification_budget)
            typed = record_errors(self._record(), _ReportRecord, "constant_report")
            if typed:
                return {"valid": False, "errors": typed}
            own = encode(self._record())
            expected = evaluate_constants(graph, targets=self.targets, budget=self.budget)
            if own != encode(expected._record()):
                return {"valid": False, "errors": ["constant facts/proofs differ from fixed-rule recomputation"]}
            if set(self.facts) != {item.value for item in self.facts.values()} or set(self.proofs) != {item.id for item in self.proofs.values()}:
                return {"valid": False, "errors": ["constant registry key identity mismatch"]}
            return {"valid": True, "errors": []}
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            return {"valid": False, "errors": [str(error)]}

    def assert_valid(self, graph=None, *, verification_budget=EvaluationBudget()):
        report = self.validate(graph, verification_budget=verification_budget)
        if not report["valid"]:
            raise ValueError("invalid constant report: " + "; ".join(report["errors"]))
        return report

    def to_dict(self, *, verification_budget=EvaluationBudget()):
        self.assert_valid(verification_budget=verification_budget)
        return encode(self._record())

    def to_json(self, *, verification_budget=EvaluationBudget()):
        return json.dumps(self.to_dict(verification_budget=verification_budget), sort_keys=True,
                          separators=(",", ":"), ensure_ascii=True, allow_nan=False)

    @classmethod
    def from_dict(cls, document, *, graph, verification_budget=EvaluationBudget()):
        record = decode(_ReportRecord, document)
        if record.schema != cls.SCHEMA or record.schema_version != cls.SCHEMA_VERSION:
            raise ValueError("unsupported constant report schema")
        if len({item.value for item in record.facts}) != len(record.facts) or len({item.id for item in record.proofs}) != len(record.proofs):
            raise ValueError("duplicate constant fact or proof identity")
        _check_verification_budget(record.budget, verification_budget)
        expected = evaluate_constants(graph, targets=record.targets, budget=record.budget)
        if record != expected._record():
            raise ValueError("constant report does not match fixed-rule recomputation")
        return expected

    @classmethod
    def from_json(cls, payload, *, graph, verification_budget=EvaluationBudget()):
        return cls.from_dict(loads(payload), graph=graph, verification_budget=verification_budget)


def _check_verification_budget(stored, ceiling):
    """Serialized limits are requests, never authority to allocate resources."""
    if type(stored) is not EvaluationBudget or type(ceiling) is not EvaluationBudget:
        raise ValueError("stored and caller verification budgets must be EvaluationBudget")
    stored.__post_init__()
    ceiling.__post_init__()
    excess = [name for name in stored.__dataclass_fields__ if getattr(stored, name) > getattr(ceiling, name)]
    if excess:
        raise ValueError("stored evaluation budget exceeds caller verification ceiling: " + ", ".join(excess))


class _BudgetExceeded(Exception):
    pass


class _Unsupported(Exception):
    pass


@dataclass(frozen=True)
class _Size:
    bytes: int
    items: int
    depth: int
    bits: int = 0


def _literal_size(literal, budget):
    """Check payload envelopes before converting decimal/hex/container values."""
    total, items, depth, integer_bits = 0, 0, 0, 0
    stack = [(literal, 1)]
    while stack:
        item, level = stack.pop()
        depth = max(depth, level)
        if level > budget.max_literal_depth:
            raise _BudgetExceeded("literal nesting budget exceeded")
        kind, payload = item.kind.name.lower(), item.payload
        if kind == "tuple":
            items += len(item.items)
            if items > budget.max_sequence_items:
                raise _BudgetExceeded("literal item budget exceeded")
            total += 8 * len(item.items)
            stack.extend((child, level + 1) for child in item.items)
        elif kind == "int":
            digits = len(payload.lstrip("-"))
            conversion_limit = sys.get_int_max_str_digits()
            if conversion_limit and digits > conversion_limit:
                raise _BudgetExceeded("interpreter integer conversion limit exceeded")
            if digits > (budget.max_int_bits * 30103 // 100000) + 2:
                raise _BudgetExceeded("integer digit budget exceeded before conversion")
            bits = abs(int(payload)).bit_length()
            if bits > budget.max_int_bits:
                raise _BudgetExceeded("integer bit budget exceeded")
            integer_bits = max(integer_bits, bits)
            total += max(1, (bits + 7) // 8)
        elif kind == "bytes":
            if len(payload) > budget.max_bytes * 2:
                raise _BudgetExceeded("byte literal budget exceeded")
            total += len(payload) // 2
        elif kind == "str":
            if len(payload) > budget.max_bytes:
                raise _BudgetExceeded("string literal budget exceeded")
            total += len(payload.encode("utf-8", errors="surrogatepass"))
        else:
            total += 8
        if total > budget.max_bytes:
            raise _BudgetExceeded("literal payload budget exceeded")
    return _Size(total, items, depth, integer_bits)


def _python_value(literal):
    kind, payload = literal.kind.name.lower(), literal.payload
    if kind == "none":
        return None
    if kind == "ellipsis":
        return Ellipsis
    if kind == "bool":
        return payload
    if kind == "int":
        return int(payload)
    if kind == "float64":
        return struct.unpack(">d", bytes.fromhex(payload))[0]
    if kind == "str":
        return payload
    if kind == "bytes":
        return bytes.fromhex(payload)
    if kind == "tuple":
        return tuple(_python_value(child) for child in literal.items)
    raise _Unsupported("unsupported literal type")


def _literal(value):
    kind = {type(None): sm.LiteralKind.NONE, bool: sm.LiteralKind.BOOL,
            int: sm.LiteralKind.INT, float: sm.LiteralKind.FLOAT64,
            str: sm.LiteralKind.STR, bytes: sm.LiteralKind.BYTES,
            tuple: sm.LiteralKind.TUPLE, type(Ellipsis): sm.LiteralKind.ELLIPSIS}.get(type(value))
    if kind is None:
        raise _Unsupported("builtin result has unsupported literal type")
    if type(value) is int:
        return sm.PythonLiteral(kind, str(value))
    if type(value) is float:
        return sm.PythonLiteral(kind, struct.pack(">d", value).hex())
    if type(value) is bytes:
        return sm.PythonLiteral(kind, value.hex())
    if type(value) is tuple:
        return sm.PythonLiteral(kind, items=tuple(_literal(item) for item in value))
    return sm.PythonLiteral(kind, value if value is not Ellipsis else None)


def _reserve(size, state, budget):
    if size.bytes > budget.max_bytes or state["output_bytes"] + size.bytes > budget.max_total_output_bytes:
        raise _BudgetExceeded("cumulative output budget exceeded before result allocation")
    if size.items > budget.max_sequence_items or size.depth > budget.max_literal_depth:
        raise _BudgetExceeded("result container/depth budget exceeded before allocation")
    if size.bits > budget.max_int_bits:
        raise _BudgetExceeded("result integer budget exceeded before allocation")
    conversion_limit = sys.get_int_max_str_digits()
    if conversion_limit and size.bits > conversion_limit * 3:
        raise _BudgetExceeded("conservative integer serialization budget exceeded before allocation")


def _work(units, state, budget):
    if units > budget.max_work - state["work"]:
        raise _BudgetExceeded("builtin operation work budget exceeded")
    state["work"] += units


_UNARY = {"POS": operator.pos, "NEG": operator.neg, "INVERT": operator.invert, "NOT": operator.not_}
_BINARY = {"ADD": operator.add, "SUB": operator.sub, "MUL": operator.mul,
           "TRUE_DIV": operator.truediv, "FLOOR_DIV": operator.floordiv,
           "MOD": operator.mod, "POW": operator.pow, "LSHIFT": operator.lshift,
           "RSHIFT": operator.rshift, "BIT_AND": operator.and_,
           "BIT_OR": operator.or_, "BIT_XOR": operator.xor}


def _builtin(opcode, values, sizes, budget, state, literals):
    """Check a closed exact-builtin signature before invoking operator helpers."""
    if opcode in _UNARY:
        if len(values) != 1:
            raise _Unsupported("unary opcode requires one ordered operand")
        value, size = values[0], sizes[0]
        if opcode == "NOT":
            estimate = _Size(8, 0, 1)
        elif type(value) is int:
            bits = size.bits + (opcode == "INVERT")
            estimate = _Size(max(1, (bits + 7) // 8), 0, 1, bits)
        elif type(value) is float and opcode in {"POS", "NEG"} and math.isfinite(value):
            estimate = _Size(8, 0, 1)
        else:
            raise _Unsupported("unary operation has no exact builtin type rule")
        _reserve(estimate, state, budget)
        _work(max(1, size.bits), state, budget)
        return _UNARY[opcode](value)
    if opcode == "INDEX":
        if len(values) != 2 or type(values[0]) not in (tuple, str, bytes) or type(values[1]) is not int:
            raise _Unsupported("index requires immutable tuple/string/bytes and exact int")
        sequence, index = values
        _work(1, state, budget)
        if index < -len(sequence) or index >= len(sequence):
            raise IndexError("constant sequence index out of range")
        # The selected element is already an accepted immutable value. Indexing
        # does not allocate an unbounded user object or invoke __index__.
        if type(sequence) is str:
            estimate = _Size(4, 0, 1)
        elif type(sequence) is bytes:
            estimate = _Size(1, 0, 1, 8)
        else:
            estimate = _literal_size(literals[0].items[index], budget)
        _reserve(estimate, state, budget)
        return operator.getitem(sequence, index)
    if opcode not in _BINARY or len(values) != 2:
        raise _Unsupported("opcode is not in the fixed builtin checker")
    left, right = values
    a, b = sizes
    if opcode == "ADD" and type(left) is type(right) and type(left) in (str, bytes, tuple):
        estimate = _Size(a.bytes + b.bytes, a.items + b.items, max(a.depth, b.depth))
        _reserve(estimate, state, budget)
        _work(max(1, a.bytes + b.bytes), state, budget)
    elif opcode == "MUL" and (
        (type(left) in (str, bytes, tuple) and type(right) is int) or
        (type(right) in (str, bytes, tuple) and type(left) is int)
    ):
        sequence, count, size = (left, right, a) if type(right) is int else (right, left, b)
        count = max(0, count)
        # Multiplication of bounded size estimates is itself bounded by input
        # integer bits; no sequence allocation happens until these checks pass.
        estimate = _Size(size.bytes * count, size.items * count, size.depth)
        _reserve(estimate, state, budget)
        _work(max(1, size.bytes * count), state, budget)
    elif type(left) is int and type(right) is int:
        bits = max(a.bits, b.bits) + 1
        work = max(1, a.bits + b.bits)
        if opcode == "MUL":
            bits, work = a.bits + b.bits, max(1, a.bits * b.bits)
        elif opcode in {"FLOOR_DIV", "MOD"}:
            bits, work = max(a.bits, b.bits), max(1, a.bits * b.bits)
        elif opcode == "TRUE_DIV":
            bits, work = 0, max(1, a.bits * b.bits)
        elif opcode in {"LSHIFT", "RSHIFT"}:
            if right < 0:
                raise ValueError("negative shift count")
            bits = a.bits + right if opcode == "LSHIFT" else max(1, a.bits)
            work = max(1, bits)
        elif opcode == "POW":
            if right < 0:
                raise _Unsupported("negative integer power is outside the builtin rule")
            bits = 1 if left in (-1, 0, 1) else max(1, a.bits) * right
            work = max(1, bits * bits * max(1, right.bit_length()))
        elif opcode in {"BIT_AND", "BIT_OR", "BIT_XOR"}:
            bits = max(a.bits, b.bits) + 1
        estimate = _Size(8 if opcode == "TRUE_DIV" else max(1, (bits + 7) // 8), 0, 1, bits)
        _reserve(estimate, state, budget)
        _work(work, state, budget)
    elif type(left) is float and type(right) is float and opcode in {"ADD", "SUB", "MUL", "TRUE_DIV"}:
        if not math.isfinite(left) or not math.isfinite(right):
            raise _Unsupported("nonfinite float arithmetic has no portable bit-result rule")
        _reserve(_Size(8, 0, 1), state, budget)
        _work(1, state, budget)
    else:
        raise _Unsupported("operator requires an allowed exact builtin type signature")
    return _BINARY[opcode](left, right)


def _dependencies(graph, operation):
    values = tuple(item.value for item in operation.operands)
    if operation.opcode.name != "READ":
        return values
    use = graph.uses.get(operation.binding_use)
    if use is None or use.status.name != "EXACT" or len(use.reaching) != 1:
        return values
    binding = graph.bindings[use.reaching[0]]
    return values + ((binding.value,) if binding.value is not None else ())


def _failure(value, status, kind, reason, operation=None, reference=None, exception=None):
    return ConstantFact(value, status, gaps=(ConstantGap(kind, reason, operation, reference),), exception=exception)


def evaluate_constants(graph, *, targets=None, budget=EvaluationBudget()):
    """Derive bounded content facts, with source authenticity kept unverified.

    Budgets cover constant evaluation, not parsing or schema validation of the
    supplied graph. Node limits bound evaluated nodes; requested targets whose
    dependency traversal exceeds that limit receive explicit budget outcomes.
    """
    if type(budget) is not EvaluationBudget:
        raise TypeError("budget must be EvaluationBudget")
    budget.__post_init__()
    if type(graph) is not sm.SourceSemanticsGraph:
        raise TypeError("graph must be SourceSemanticsGraph")
    model_digest = _digest(graph.to_dict())
    selected = tuple(graph.values) if targets is None else tuple(targets)
    if any(type(item) is not sm.StaticValueID or item not in graph.values for item in selected):
        raise ValueError("constant targets must reference known static values")
    selected = tuple(sorted(set(selected), key=lambda item: item.wire))
    state = {"nodes": 0, "steps": 0, "work": 0, "output_bytes": 0}
    facts, proofs, active, scheduled = {}, {}, set(), {}
    for target in selected:
        pending = [(target, False)]
        while pending:
            value_id, finish = pending.pop()
            if value_id in facts:
                continue
            value = graph.values[value_id]
            operation = graph.operations.get(value.producer)
            if not finish:
                if value_id in active:
                    facts[value_id] = _failure(value_id, ConstantStatus.NOT_CONSTANT,
                        ConstantGapKind.CYCLE, "cyclic static value dependencies", value.producer)
                    continue
                if state["nodes"] >= budget.max_nodes:
                    facts[value_id] = _failure(value_id, ConstantStatus.BUDGET_EXCEEDED,
                        ConstantGapKind.BUDGET, "constant dependency node budget exceeded", value.producer)
                    continue
                state["nodes"] += 1
                if operation is None or value.external:
                    facts[value_id] = _failure(value_id, ConstantStatus.NOT_CONSTANT,
                        ConstantGapKind.DEPENDENCY, "external value has no local constant producer", value.producer)
                    continue
                active.add(value_id)
                dependencies = _dependencies(graph, operation)
                scheduled[value_id] = dependencies
                pending.append((value_id, True))
                pending.extend((dependency, False) for dependency in reversed(dependencies) if dependency not in facts)
                continue
            active.discard(value_id)
            dependencies = scheduled[value_id]
            if state["steps"] >= budget.max_steps:
                facts[value_id] = _failure(value_id, ConstantStatus.BUDGET_EXCEEDED,
                    ConstantGapKind.BUDGET, "constant step budget exceeded", operation.operation)
                continue
            state["steps"] += 1
            opcode = operation.opcode.name
            rule, binding_uses = ConstantRule.BUILTIN, ()
            try:
                if opcode in {"IMPORT", "ATTRIBUTE"}:
                    facts[value_id] = _failure(value_id, ConstantStatus.NEEDS_CONTRACT,
                        ConstantGapKind.IMPORT, "module resolution/loader/lazy attribute contract is not supplied",
                        operation.operation)
                    continue
                if opcode in {"CALL", "OPAQUE", "BUILD_LIST", "BUILD_DICT", "BUILD_SET", "MATMUL"}:
                    raise _Unsupported("opaque/user calls and mutable construction recipes are not immutable constants")
                if operation.dispatch.name == "USER_DEFINED":
                    raise _Unsupported("user-defined dispatch cannot use builtin constant rules")
                if opcode == "READ":
                    use = graph.uses.get(operation.binding_use)
                    if use is None or use.status.name != "EXACT" or len(use.reaching) != 1:
                        facts[value_id] = _failure(value_id, ConstantStatus.NOT_CONSTANT,
                            ConstantGapKind.BINDING, "read lacks a unique exact reaching definition", operation.operation)
                        continue
                    binding = graph.bindings[use.reaching[0]]
                    if (binding.scope != use.scope or binding.block != use.block or
                            binding.position >= use.position or use.operation != operation.operation or
                            use.scope != operation.scope or use.block != operation.block or binding.value is None):
                        facts[value_id] = _failure(value_id, ConstantStatus.NOT_CONSTANT,
                            ConstantGapKind.BINDING, "binding use is outside its exact preceding local scope/block",
                            operation.operation, use.id.wire)
                        continue
                    rule, binding_uses = ConstantRule.BINDING, (use.id,)
                if any(facts[item].status is not ConstantStatus.CONSTANT for item in dependencies):
                    budget_failure = any(facts[item].status is ConstantStatus.BUDGET_EXCEEDED for item in dependencies)
                    facts[value_id] = _failure(value_id,
                        ConstantStatus.BUDGET_EXCEEDED if budget_failure else ConstantStatus.NOT_CONSTANT,
                        ConstantGapKind.BUDGET if budget_failure else ConstantGapKind.DEPENDENCY,
                        "ordered input lacks a constant proof", operation.operation)
                    continue
                literals = tuple(facts[item].literal for item in dependencies)
                if opcode == "LITERAL":
                    if literals or operation.literal is None:
                        raise _Unsupported("literal opcode requires one literal payload and no operands")
                    literal, rule = operation.literal, ConstantRule.LITERAL
                    size = _literal_size(literal, budget)
                    _reserve(size, state, budget)
                    _work(max(1, size.bytes), state, budget)
                elif opcode in {"READ", "ALIAS", "RETURN"}:
                    if len(literals) != 1:
                        raise _Unsupported("binding/alias/return requires one proved value")
                    literal = literals[0]
                    if opcode != "READ":
                        rule = ConstantRule.BINDING
                    size = _literal_size(literal, budget)
                    _reserve(size, state, budget)
                    _work(1, state, budget)
                elif opcode == "BUILD_TUPLE":
                    sizes = tuple(_literal_size(item, budget) for item in literals)
                    size = _Size(8 * len(literals) + sum(item.bytes for item in sizes),
                                 len(literals) + sum(item.items for item in sizes),
                                 1 + max((item.depth for item in sizes), default=0))
                    _reserve(size, state, budget)
                    _work(max(1, len(literals)), state, budget)
                    literal, rule = sm.PythonLiteral(sm.LiteralKind.TUPLE, items=literals), ConstantRule.TUPLE
                else:
                    sizes = tuple(_literal_size(item, budget) for item in literals)
                    values = tuple(_python_value(item) for item in literals)
                    result = _builtin(opcode, values, sizes, budget, state, literals)
                    literal = _literal(result)
                    size = _literal_size(literal, budget)
                    _reserve(size, state, budget)
                state["output_bytes"] += size.bytes
                premises = tuple(facts[item].proof_id for item in dependencies)
                runtime_requirements = {requirement for premise in premises
                                        for requirement in proofs[premise].runtime_requirements}
                if rule is ConstantRule.BUILTIN:
                    runtime_requirements.add(ConstantRuntimeRequirement.BUILTIN_RUNTIME_MATCH)
                if ((opcode in _BINARY or opcode in {"POS", "NEG"}) and
                        (opcode == "TRUE_DIV" or any(item.kind is sm.LiteralKind.FLOAT64 for item in literals))):
                    runtime_requirements.add(ConstantRuntimeRequirement.FLOATING_ENVIRONMENT_MATCH)
                runtime_requirements = tuple(sorted(runtime_requirements, key=lambda item: item.value))
                digest = _digest(encode(literal))
                proof_id = "constant-proof:" + _digest((model_digest, RULE_VERSION, operation.operation.wire,
                    rule.value, premises, tuple(item.wire for item in binding_uses), digest,
                    tuple(item.value for item in runtime_requirements)))
                proof = ConstantProof(proof_id, rule, operation.operation, operation.source, value_id,
                                      premises, binding_uses, digest, runtime_requirements)
                proofs[proof_id] = proof
                facts[value_id] = ConstantFact(value_id, ConstantStatus.CONSTANT, literal, proof_id)
            except _BudgetExceeded as error:
                facts[value_id] = _failure(value_id, ConstantStatus.BUDGET_EXCEEDED,
                    ConstantGapKind.BUDGET, str(error), operation.operation)
            except _Unsupported as error:
                facts[value_id] = _failure(value_id, ConstantStatus.NOT_CONSTANT,
                    ConstantGapKind.UNSUPPORTED, str(error), operation.operation)
            except (ArithmeticError, IndexError, ValueError) as error:
                facts[value_id] = _failure(value_id, ConstantStatus.KNOWN_EXCEPTION,
                    ConstantGapKind.UNSUPPORTED, "fixed builtin operation raises " + type(error).__name__,
                    operation.operation, exception=type(error).__name__)
    return ConstantReport(graph, model_digest=model_digest, budget=budget, targets=selected,
                          facts=facts, proofs=proofs, usage=EvaluationUsage(**state))


__all__ = ["EvaluationBudget", "EvaluationUsage", "ConstantStatus", "SourceValidation", "ContractAcceptance",
           "RuntimeValidation", "ConstantRuntimeRequirement", "ConstantGap", "ConstantFact", "ConstantProof",
           "ConstantReport", "evaluate_constants"]
