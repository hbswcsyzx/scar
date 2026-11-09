"""Shared source body entrances with selected outer caller interfaces."""
from dataclasses import dataclass
from enum import Enum

from .providers import ProviderFactReference


class EntranceKind(str, Enum):
    NAMESPACE_FUNCTION = 'NAMESPACE_FUNCTION'
    CONSTRUCTOR = 'CONSTRUCTOR'
    DECLARED_MEMBER = 'DECLARED_MEMBER'


@dataclass(frozen=True, slots=True)
class ConnectedBodyRoot:
    body: int
    incoming: int
    outer: tuple[int, ...]
    evidence: ProviderFactReference
    kind: EntranceKind
    parent_query: int | None = None
    declared_context: int | None = None
    predecessor: int | None = None


@dataclass(frozen=True, slots=True)
class ConnectedBodyFrontier:
    evidence: ProviderFactReference
    reason: str
    root: int | None = None


@dataclass(frozen=True, slots=True)
class ContextualInterfaceScope:
    incoming: int
    caller_interfaces: tuple[int, ...]
