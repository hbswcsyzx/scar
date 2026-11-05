"""Bounded builtin values for original F5 language-operation interfaces.

This adapter invokes only the existing exact-builtin checker.  Results concern
conditional builtin content, not object identity, runtime dispatch, effects,
source authenticity, or execution of a target program.
"""
from dataclasses import dataclass

from scar.analysis.constants_v2 import (
    BuiltinRuntime, ConstantRuntimeRequirement, ConstantStatus, EvaluationBudget,
    EvaluationUsage, RULE_VERSION, _BINARY, _BudgetExceeded, _Unsupported,
    _builtin, _literal, _literal_size, _python_value, _reserve,
)
from scar.ir.literals import LiteralKind, PythonLiteral, require_legacy_literal
from scar.ir.program import normal_links as F


_UNARY_SELECTORS = {
    F.OperatorSelector.U_ADD: 'POS', F.OperatorSelector.U_SUB: 'NEG',
    F.OperatorSelector.INVERT: 'INVERT', F.OperatorSelector.NOT: 'NOT',
}
_BINARY_SELECTORS = {
    F.OperatorSelector.ADD: 'ADD', F.OperatorSelector.SUB: 'SUB',
    F.OperatorSelector.MULT: 'MUL', F.OperatorSelector.DIV: 'TRUE_DIV',
    F.OperatorSelector.FLOOR_DIV: 'FLOOR_DIV', F.OperatorSelector.MOD: 'MOD',
    F.OperatorSelector.POW: 'POW', F.OperatorSelector.L_SHIFT: 'LSHIFT',
    F.OperatorSelector.R_SHIFT: 'RSHIFT', F.OperatorSelector.BIT_AND: 'BIT_AND',
    F.OperatorSelector.BIT_OR: 'BIT_OR', F.OperatorSelector.BIT_XOR: 'BIT_XOR',
}


@dataclass(frozen=True, slots=True)
class BuiltinValueResult:
    status: ConstantStatus
    literal: PythonLiteral | None
    reason: str = ''
    exception: str | None = None
    requirements: tuple[ConstantRuntimeRequirement, ...] = ()

    def __post_init__(self):
        if type(self.status) is not ConstantStatus:
            raise TypeError('builtin result requires ConstantStatus')
        if self.status is ConstantStatus.CONSTANT:
            if type(self.literal) is not PythonLiteral:
                raise ValueError('a constant result requires a typed literal')
        elif self.literal is not None:
            raise ValueError('a failed evaluation cannot supply a constant literal')


class BuiltinValueEvaluator:
    """Memoized primitive evaluations under one cumulative budget.

    A cache miss charges one step and one logical value node for each operand
    root plus the result.  Literal trees also obey the existing size/depth/item
    checks.  Cached outcomes do not repeat evaluation or consume budget again;
    terminal budget refusals are not inserted as unbounded new cache entries.
    These resource limits do not replace the caller's finite-height value
    domain or establish that any original operation executes.
    """

    def __init__(self, budget=EvaluationBudget()):
        if type(budget) is not EvaluationBudget:
            raise TypeError('budget must be EvaluationBudget')
        budget.__post_init__()
        self.budget = budget
        self.runtime = BuiltinRuntime.current()
        self.rule_version = RULE_VERSION
        self._state = dict(nodes=0, steps=0, work=0, output_bytes=0)
        self._cache = {}
        self._calls = self._hits = self._misses = 0
        self._statuses = {}

    @property
    def usage(self):
        return EvaluationUsage(**self._state)

    @property
    def stats(self):
        return dict(calls=self._calls, cache_hits=self._hits,
            cache_misses=self._misses, cache_entries=len(self._cache),
            usage=dict(self._state), statuses=dict(self._statuses))

    @staticmethod
    def opcode_for(action, selector):
        if type(action) is not F.LanguageOperationKind or type(selector) is not F.OperatorSelector:
            raise TypeError('original language-operation enums required')
        if action is F.LanguageOperationKind.UNARY:
            return _UNARY_SELECTORS.get(selector)
        if action in (F.LanguageOperationKind.BINARY, F.LanguageOperationKind.INPLACE_BINARY):
            return _BINARY_SELECTORS.get(selector)
        return None

    def _return(self, result):
        key = result.status.value
        self._statuses[key] = self._statuses.get(key, 0) + 1
        return result

    def evaluate(self, action, selector, ordered_literals):
        """Return a typed outcome without executing arbitrary Python values."""
        opcode = self.opcode_for(action, selector)
        if (type(ordered_literals) is not tuple
                or any(type(item) is not PythonLiteral for item in ordered_literals)):
            raise TypeError('ordered_literals must be a tuple of exact PythonLiteral records')
        self._calls += 1
        if opcode is None:
            return self._return(BuiltinValueResult(ConstantStatus.NOT_CONSTANT, None,
                'no fixed builtin checker for ' + action.value + '/' + selector.value))
        arity = 1 if action is F.LanguageOperationKind.UNARY else 2
        if len(ordered_literals) != arity:
            return self._return(BuiltinValueResult(ConstantStatus.NOT_CONSTANT, None,
                'builtin opcode requires ' + str(arity) + ' ordered operands'))
        # Shared literal grammar validates before recursive dataclass hashing;
        # exact-only kinds are rejected, never silently coerced to legacy data.
        try:
            for item in ordered_literals:
                require_legacy_literal(item)
        except (ValueError, TypeError) as error:
            return self._return(BuiltinValueResult(ConstantStatus.NOT_CONSTANT, None, str(error)))
        key = opcode, ordered_literals
        if key in self._cache:
            self._hits += 1
            return self._return(self._cache[key])
        self._misses += 1
        if self._state['steps'] >= self.budget.max_steps:
            return self._return(BuiltinValueResult(ConstantStatus.BUDGET_EXCEEDED, None,
                'constant step budget exceeded'))
        nodes = len(ordered_literals) + 1
        if nodes > self.budget.max_nodes - self._state['nodes']:
            return self._return(BuiltinValueResult(ConstantStatus.BUDGET_EXCEEDED, None,
                'constant value-node budget exceeded'))
        self._state['nodes'] += nodes
        self._state['steps'] += 1
        requirements = [ConstantRuntimeRequirement.BUILTIN_RUNTIME_MATCH]
        if ((opcode in _BINARY or opcode in ('POS', 'NEG'))
                and (opcode == 'TRUE_DIV' or any(item.kind is LiteralKind.FLOAT64 for item in ordered_literals))):
            requirements.append(ConstantRuntimeRequirement.FLOATING_ENVIRONMENT_MATCH)
        requirements = tuple(requirements)
        try:
            sizes = tuple(_literal_size(item, self.budget) for item in ordered_literals)
            values = tuple(_python_value(item) for item in ordered_literals)
            value = _builtin(opcode, values, sizes, self.budget, self._state, ordered_literals)
            literal = _literal(value)
            size = _literal_size(literal, self.budget)
            _reserve(size, self._state, self.budget)
            self._state['output_bytes'] += size.bytes
            result = BuiltinValueResult(ConstantStatus.CONSTANT, literal,
                requirements=requirements)
        except _BudgetExceeded as error:
            result = BuiltinValueResult(ConstantStatus.BUDGET_EXCEEDED, None, str(error))
        except _Unsupported as error:
            result = BuiltinValueResult(ConstantStatus.NOT_CONSTANT, None, str(error))
        except (ArithmeticError, IndexError, ValueError) as error:
            result = BuiltinValueResult(ConstantStatus.KNOWN_EXCEPTION, None,
                'fixed builtin operation raises ' + type(error).__name__,
                exception=type(error).__name__, requirements=requirements)
        self._cache[key] = result
        return self._return(result)


__all__ = ['BuiltinValueEvaluator', 'BuiltinValueResult']
