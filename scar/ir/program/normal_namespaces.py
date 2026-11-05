"""Namespace lookup relationships over original source ports.

An empty inferred value set is an open binding requirement, not an absent
member or an opaque operation. Native interface providers can attach here.
"""
from dataclasses import dataclass
from enum import Enum

from .normal_targets import GlobalPort


class NamespaceKind(str, Enum):
    MODULE = 'MODULE'
    EXTERNAL_SYMBOL = 'EXTERNAL_SYMBOL'


@dataclass(frozen=True, slots=True)
class NamespaceLookup:
    receiver: GlobalPort
    result: GlobalPort
    namespace: str
    member: str
    kind: NamespaceKind
    source_units: tuple[str, ...]
    inferred_source_values: int
    declared_import_candidate: bool
    conditions: tuple[str, ...] = ('POSSIBLE_NAMESPACE_REFERENCE', 'STANDARD_ATTRIBUTE_LOOKUP')
    binding_proven: bool = False

