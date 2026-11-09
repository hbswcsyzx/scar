"""Guarded class inputs from original constructor parameter interfaces."""
from dataclasses import dataclass

from .declared_contexts import DeclaredContext


@dataclass(frozen=True, slots=True)
class ConstructorClassInputRoot:
    """entry indexes the unchanged parent ConstructorInterfaceGraph.entries."""
    entry: int
    context: DeclaredContext
    conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConstructorClassInputFrontier:
    entry: int
    reason: str


@dataclass(frozen=True, slots=True)
class ConstructorClassInputGraph:
    roots: tuple[ConstructorClassInputRoot, ...]
    frontiers: tuple[ConstructorClassInputFrontier, ...]
    semantics: str = 'GUARDED_CONSTRUCTOR_CLASS_COMPATIBILITY_NOT_EXACT_CLASS_ALLOCATION_OR_RUNTIME_INVOCATION'
