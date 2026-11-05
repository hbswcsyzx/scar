"""Conditional standard-builtin boundaries over original source call ports."""
from dataclasses import dataclass
from enum import Enum

from scar.ir.literals import PythonLiteral
from . import normal_links as F, normal_targets as T, source_productions as P
from .python_bindings import SourceCallSite


class SourceBuiltin(str, Enum):
    COMPILE = 'compile'
    EXEC = 'exec'


class BuiltinArgumentOrigin(str, Enum):
    SOURCE_VALUE = 'SOURCE_VALUE'
    SOURCE_LITERAL = 'SOURCE_LITERAL'
    LANGUAGE_DEFAULT = 'LANGUAGE_DEFAULT'
    OPEN_PACK = 'OPEN_PACK'


@dataclass(frozen=True, slots=True)
class BuiltinArgument:
    name: str
    origin: BuiltinArgumentOrigin
    source: T.GlobalPort | None
    literal: PythonLiteral | None = None
    literal_occurrence: P.ProductionOccurrence | None = None


@dataclass(frozen=True, slots=True)
class PackConstructionDependency:
    source: T.GlobalPort
    kind: F.ContainerKind


@dataclass(frozen=True, slots=True)
class SourceBuiltinInvocation:
    builtin: SourceBuiltin
    site: SourceCallSite
    owner: F.CodeScopeRef
    parameters: tuple[BuiltinArgument, ...]
    binding: T.ArgumentBinding
    pack_dependencies: tuple[PackConstructionDependency, ...]
    signature: str
    binding_note: str = ''
    normal_result: PythonLiteral | None = None
    conditions: tuple[str, ...] = (
        'SOURCE_SCOPE_AND_NORMAL_COMPLETION_SELECTED',
        'STANDARD_BUILTIN_REFERENCE_SELECTED',
        'CURRENT_CODE_AND_NAMESPACE_VERSIONS_SELECTED',
        'CALL_SIGNATURE_AND_VALUE_TYPE_ACCEPTANCE',
        'SOURCE_PACK_CONSTRUCTION_DEPENDENCIES_NOT_INVALIDATED',
    )


@dataclass(frozen=True, slots=True)
class SourceCompilationRequest:
    invocation_result: T.GlobalPort
    caller: F.CodeScopeRef
    requested_flags: int | None
    dont_inherit: bool | None
    requested_optimize: int | None
    process_optimize: int | None
    inherited_future_flags: int | None
    effective_optimize: int | None
    result_kind: str
    source_future_flags: int | None = None
    effective_flags: int | None = None
    obligations: tuple[str, ...] = (
        'SOURCE_PAYLOAD_VALUE_AND_TEXT_INTERPRETATION_NOT_RESOLVED',
        'COMPILED_CONTEXT_HAS_NO_MATCHED_F4_BODY_VARIANT',
    )


@dataclass(frozen=True, slots=True)
class CompiledCodeUse:
    producer: T.GlobalPort
    consumer: T.GlobalPort
    exec_result: T.GlobalPort
    semantics: str = 'CONDITIONAL_MAY_CODE_REFERENCE_FLOW'
    namespace_rule: str = 'STANDARD_EXEC_GLOBALS_LOCALS_AND_CALLER_FRAME_RULES'
    conditions: tuple[str, ...] = (
        'STANDARD_BUILTIN_REFERENCE_SELECTED',
        'SOURCE_NAMESPACE_READ_VERSION_SELECTED',
        'CODE_OBJECT_TYPE_ACCEPTANCE',
        'NO_SOURCE_BODY_ACTIVATION_OR_REFERENCE_IDENTITY_PROOF',
    )
