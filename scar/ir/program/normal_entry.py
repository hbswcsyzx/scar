"""Static entry/activation evidence, distinct from runtime invocations."""
from dataclasses import dataclass
from enum import Enum

from .normal_links import CodeScopeRef,CodeScopeWitness
from .normal_targets import GlobalPort, Endpoint


class EntryReason(str,Enum):
    PROGRAM_ENTRY='PROGRAM_ENTRY'
    MODULE_REFERENCE='MODULE_REFERENCE'
    REQUESTED_MODULE='REQUESTED_MODULE'
    SOURCE_FUNCTION_CALL='SOURCE_FUNCTION_CALL'
    CLASS_BUILD='CLASS_BUILD'
    EAGER_REGION='EAGER_REGION'
    GENERATOR_ADVANCE='GENERATOR_ADVANCE'


@dataclass(frozen=True,slots=True)
class ScopeActivationEvidence:
    target: CodeScopeRef
    cause: Endpoint | CodeScopeRef | None
    reason: EntryReason
    conditions: tuple[str,...]=('STATIC_MAY_ACTIVATION','CODE_SCOPE_ACTIVE_NOT_PATH_SELECTED')


@dataclass(frozen=True,slots=True)
class ModuleEntryDemand:
    module: str
    producer: Endpoint | None
    conditions: tuple[str,...]=('NO_DECLARED_PYTHON_UNIT','SOURCE_OR_NATIVE_PROVIDER_CLASSIFICATION_PENDING')


class BodyDemandKind(str,Enum):
    ARGUMENT_PACK_BINDING_OPEN='ARGUMENT_PACK_BINDING_OPEN'
    DEFERRED_BODY_RESUME_OPEN='DEFERRED_BODY_RESUME_OPEN'


@dataclass(frozen=True,slots=True)
class BodyEntryDemand:
    target: CodeScopeWitness
    producer: GlobalPort
    kind: BodyDemandKind


@dataclass(frozen=True,slots=True)
class CallEntryDemand:
    callee: GlobalPort
    result: GlobalPort
    symbol: str | None
    conditions: tuple[str,...]=('CALLABLE_TARGET_OR_EXTERNAL_PROVIDER_OPEN',)
