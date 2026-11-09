"""Conditional descriptor alternatives with original ordered base witnesses."""
from dataclasses import dataclass

from .declared_contexts import DescriptorReference
from .normal_targets import GlobalPort
from .source_class_bases import ClassBaseGraph


@dataclass(frozen=True, slots=True)
class BasePathStep:
    """query/slot index an unchanged base_queries graph and its slots table.

    Exactly one address_path or namespace_origin selects the source witness.
    namespace_edges indexes a complete root-to-origin path in that slot's
    NamespaceReferenceSlice. Base order remains the original slot.ordinal.
    """
    query: int
    slot: int
    source_class: GlobalPort
    target_class: GlobalPort
    address_path: int | None = None
    namespace_origin: int | None = None
    namespace_edges: tuple[int, ...] = ()
    conditions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class InheritedDescriptor:
    """An empty path is a direct declaration on receiver_class."""
    receiver_class: GlobalPort
    member: str
    owner_class: GlobalPort
    path: tuple[BasePathStep, ...]
    descriptor: DescriptorReference


@dataclass(frozen=True, slots=True)
class InheritedMemberFrontier:
    source_class: GlobalPort
    member: str
    reason: str


@dataclass(frozen=True, slots=True)
class InheritedMemberGraph:
    base_queries: tuple[ClassBaseGraph, ...]
    descriptors: tuple[InheritedDescriptor, ...]
    frontiers: tuple[InheritedMemberFrontier, ...]
    semantics: str = 'CONDITIONAL_SOURCE_BASE_PATHS_NOT_C3_RUNTIME_MRO_OR_DISPATCH'
