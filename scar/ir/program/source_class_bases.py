"""Ordered source class-build operands, not resolved runtime bases or MRO."""
from dataclasses import dataclass

from .normal_links import CodeScopeRef
from .normal_targets import GlobalPort
from .providers import ProviderFactReference
from .source_address_paths import AddressPath
from .source_namespace_references import NamespaceReferenceSlice


@dataclass(frozen=True, slots=True)
class ClassBaseDeclaration:
    source_class: GlobalPort
    fact: ProviderFactReference
    creator_scope: CodeScopeRef
    bases: tuple[GlobalPort, ...]
    bases_pack: GlobalPort | None
    bases_pack_paths: tuple[AddressPath, ...]
    no_explicit_bases: bool
    conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ClassBaseSlot:
    owner: int
    ordinal: int
    expression: GlobalPort
    paths: tuple[AddressPath, ...]
    source_classes: tuple[GlobalPort, ...]
    conditions: tuple[str, ...]
    namespace: NamespaceReferenceSlice | None = None


@dataclass(frozen=True, slots=True)
class ClassBaseFrontier:
    """owner indexes declarations; slot indexes slots, or None for the declaration."""
    owner: int
    slot: int | None
    reason: str


@dataclass(frozen=True, slots=True)
class ClassBaseGraph:
    declarations: tuple[ClassBaseDeclaration, ...]
    slots: tuple[ClassBaseSlot, ...]
    frontiers: tuple[ClassBaseFrontier, ...]
    semantics: str = 'ORDERED_SOURCE_BASE_EXPRESSIONS_NOT_RESOLVED_RUNTIME_BASES_OR_MRO'
