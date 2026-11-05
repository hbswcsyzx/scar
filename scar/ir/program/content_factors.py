"""Lossless factors of existing may-content links, not source operations."""
from dataclasses import dataclass

from scar.ir.literals import PythonLiteral
from . import normal_targets as T


@dataclass(frozen=True, slots=True)
class ContentFactor:
    id: str
    container: T.Endpoint
    key: PythonLiteral | None
    sources: tuple[T.Endpoint, ...]
    targets: tuple[T.Endpoint, ...]
    semantics: str = 'FLOW_INSENSITIVE_MAY_CONTENT'


@dataclass(frozen=True, slots=True)
class ContentIndexCycle:
    container: T.Endpoint
    source: T.Endpoint
    start: int
    stride: int
    path: tuple[T.Endpoint, ...]
    abstract_position: str = 'UNKNOWN_POSITION'
    semantics: str = 'DESCENDING_CYCLE_CONSTRAINT_WITH_MAY_POSITION_WIDENING'
