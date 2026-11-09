"""Guarded function-body contexts, separate from runtime invocations."""
from dataclasses import dataclass
from enum import Enum

from .normal_targets import GlobalPort, Body, FunctionConnection
from .providers import ProviderFactReference


class ClassValueKind(str, Enum):
    INSTANCE = 'INSTANCE'
    CLASS_OBJECT = 'CLASS_OBJECT'


class DescriptorKind(str, Enum):
    FUNCTION = 'FUNCTION'
    STATICMETHOD = 'STATICMETHOD'
    CLASSMETHOD = 'CLASSMETHOD'


@dataclass(frozen=True, slots=True)
class ClassInput:
    formal: GlobalPort
    source_class: GlobalPort
    kind: ClassValueKind


@dataclass(frozen=True, slots=True)
class DeclaredContext:
    source_callable: GlobalPort
    body: Body
    class_inputs: tuple[ClassInput, ...]


class CopyKind(str, Enum):
    ALIAS = 'ALIAS'
    LEXICAL_BINDING = 'LEXICAL_BINDING'
    MODULE_DECLARATION = 'MODULE_DECLARATION'


@dataclass(frozen=True, slots=True)
class CopyStep:
    source: GlobalPort
    target: GlobalPort
    kind: CopyKind
    evidence: tuple[ProviderFactReference, ...]
    conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ClassReference:
    point: GlobalPort
    origin: GlobalPort
    source_class: GlobalPort
    kind: ClassValueKind
    input_ordinal: int | None
    path: tuple[CopyStep, ...]
    conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DescriptorReference:
    class_binding: ProviderFactReference
    function: GlobalPort
    kind: DescriptorKind
    value_path: tuple[CopyStep, ...]
    wrapper_call: ProviderFactReference | None
    builtin_read: ProviderFactReference | None
    wrapper_callee_path: tuple[CopyStep, ...]
    function_path: tuple[CopyStep, ...]
    conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DeclaredContextEdge:
    caller: int
    target: int
    call: ProviderFactReference
    attribute: ProviderFactReference
    callee_path: tuple[CopyStep, ...]
    receiver: ClassReference
    descriptor: DescriptorReference
    connection: FunctionConnection
    inputs: tuple[ClassReference, ...]
    conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DeclaredContextEntry:
    target: int
    parent: ProviderFactReference
    connection: FunctionConnection


@dataclass(frozen=True, slots=True)
class ContextFrontier:
    context: int
    call: ProviderFactReference | None
    reason: str


@dataclass(frozen=True, slots=True)
class DeclaredContextGraph:
    contexts: tuple[DeclaredContext, ...]
    entries: tuple[DeclaredContextEntry, ...]
    edges: tuple[DeclaredContextEdge, ...]
    frontiers: tuple[ContextFrontier, ...]
    semantics: str = 'GUARDED_DECLARED_BODY_CONNECTIONS_NOT_RUNTIME_OR_CURRENT_STATE'
