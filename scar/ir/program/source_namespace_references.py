"""Conditional reference sources through declared namespace slots/imports."""
from dataclasses import dataclass
from enum import Enum

from .normal_targets import GlobalPort
from .providers import ProviderFactReference


class NamespaceEdgeKind(str, Enum):
    ALIAS = 'ALIAS'
    LEXICAL_WRITE = 'LEXICAL_WRITE'
    GLOBAL_WRITE = 'GLOBAL_WRITE'
    CLASS_WRITE = 'CLASS_WRITE'
    ATTRIBUTE_RECEIVER = 'ATTRIBUTE_RECEIVER'
    MODULE_EXPORT = 'MODULE_EXPORT'


class NamespaceOriginKind(str, Enum):
    CLASS_DEFINITION = 'CLASS_DEFINITION'
    FUNCTION_DEFINITION = 'FUNCTION_DEFINITION'
    SOURCE_LITERAL = 'SOURCE_LITERAL'
    MODULE_CANDIDATE = 'MODULE_CANDIDATE'


@dataclass(frozen=True, slots=True)
class NamespaceSelector:
    member: str
    import_from: bool
    access: ProviderFactReference


@dataclass(frozen=True, slots=True)
class NamespaceReferenceState:
    port: GlobalPort
    selectors: tuple[NamespaceSelector, ...] = ()


@dataclass(frozen=True, slots=True)
class NamespaceReferenceEdge:
    downstream: int
    upstream: int
    kind: NamespaceEdgeKind
    evidence: tuple[ProviderFactReference, ...]
    conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NamespaceReferenceOrigin:
    state: int
    kind: NamespaceOriginKind
    evidence: tuple[ProviderFactReference, ...]
    conditions: tuple[str, ...]
    symbol: str | None = None
    providers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NamespaceReferenceFrontier:
    state: int
    reason: str
    evidence: tuple[ProviderFactReference, ...] = ()


@dataclass(frozen=True, slots=True)
class NamespaceReferenceSlice:
    states: tuple[NamespaceReferenceState, ...]
    edges: tuple[NamespaceReferenceEdge, ...]
    origins: tuple[NamespaceReferenceOrigin, ...]
    frontiers: tuple[NamespaceReferenceFrontier, ...]
    semantics: str = 'DECLARED_NAMESPACE_SOURCE_ALTERNATIVES_NOT_CURRENT_SLOT_OR_OBJECT_IDENTITY'
