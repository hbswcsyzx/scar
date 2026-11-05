"""Conditional scalar content fields over existing source ports."""
from dataclasses import dataclass
from enum import Enum

from scar.ir.literals import PythonLiteral
from . import normal_targets as T


class ScalarEvaluationStatus(str, Enum):
    """Field outcomes, independent of the legacy evaluator implementation."""
    CONSTANT = 'CONSTANT'
    NOT_CONSTANT = 'NOT_CONSTANT'
    NEEDS_CONTRACT = 'NEEDS_CONTRACT'
    KNOWN_EXCEPTION = 'KNOWN_EXCEPTION'
    BUDGET_EXCEEDED = 'BUDGET_EXCEEDED'


class ScalarRuntimeRequirement(str, Enum):
    BUILTIN_RUNTIME_MATCH = 'builtin_runtime_match'
    FLOATING_ENVIRONMENT_MATCH = 'floating_environment_match'


@dataclass(frozen=True, slots=True)
class ScalarPremise:
    port: T.GlobalPort
    literal: PythonLiteral
    requirements: tuple[ScalarRuntimeRequirement, ...] = ()


@dataclass(frozen=True, slots=True)
class ScalarLiteralSource:
    port: T.GlobalPort
    literal: PythonLiteral
    semantics: str = 'SOURCE_LITERAL_MAY_CONTENT_NOT_OBJECT_IDENTITY'


@dataclass(frozen=True, slots=True)
class ScalarReferenceFlow:
    source: T.GlobalPort
    target: T.GlobalPort
    semantics: str = 'MAY_CONTENT_FLOW_NOT_OBJECT_IDENTITY'


@dataclass(frozen=True, slots=True)
class ScalarTransferGroup:
    """A relation factored through an existing source-query table row.

    The group is an analysis relation, not a new program operation or value.
    Original table/row/role retain its applicability and provenance.
    """
    source_table: str
    source_ordinal: int
    role: str
    sources: tuple[T.GlobalPort, ...]
    targets: tuple[T.GlobalPort, ...]
    conditions: tuple[str, ...] = ()
    semantics: str = 'CONDITIONAL_MAY_SCALAR_CONTENT_NOT_VALUE_IDENTITY'


@dataclass(frozen=True, slots=True)
class ScalarDerivation:
    site: T.LanguageOperationSite
    premises: tuple[ScalarPremise, ...]
    result: ScalarPremise
    requirements: tuple[ScalarRuntimeRequirement, ...]
    semantics: str = 'CONDITIONAL_BUILTIN_CONTENT'
    conditions: tuple[str, ...] = (
        'OPERAND_LITERAL_ALTERNATIVES_SELECTED',
        'EXACT_IMMUTABLE_BUILTIN_SIGNATURE',
        'SOURCE_CODE_SCOPE_ADMISSION_REQUIRED',
        'ORIGINAL_NORMAL_COMPLETION_SELECTED',
        'NO_UNIQUE_VALUE_OR_IDENTITY_CLAIM',
    )


class ScalarObligationKind(str, Enum):
    SOURCE_OPEN = 'SOURCE_OPEN'
    UPSTREAM_OPEN = 'UPSTREAM_OPEN'
    OPERAND_OPEN = 'OPERAND_OPEN'
    INPUT_LITERAL_ABSENT = 'INPUT_LITERAL_ABSENT'
    LITERAL_LIMIT = 'LITERAL_LIMIT'
    UNSUPPORTED_OPERATOR = 'UNSUPPORTED_OPERATOR'
    EVALUATION_FAILURE = 'EVALUATION_FAILURE'


@dataclass(frozen=True, slots=True)
class ScalarObligation:
    port: T.GlobalPort
    kind: ScalarObligationKind
    reason: str
    site: T.LanguageOperationSite | None = None
    inputs: tuple[T.GlobalPort, ...] = ()
    premises: tuple[ScalarPremise, ...] = ()
    status: ScalarEvaluationStatus | None = None
    exception: str | None = None
    requirements: tuple[ScalarRuntimeRequirement, ...] = ()


@dataclass(frozen=True, slots=True)
class ScalarSnapshot:
    port: T.GlobalPort
    literals: tuple[PythonLiteral, ...] = ()
    builtin_types: tuple[str, ...] = ()
    content_open: bool = False
    widened: bool = False
    complete: bool = False
    semantics: str = 'CONDITIONAL_BUILTIN_CONTENT'
