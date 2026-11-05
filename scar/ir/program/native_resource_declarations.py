"""Resource-relevant schema operands and declared dispatch alternatives.

Neither record is a ResourceUse, selected device, RNG effect, allocation,
transfer or executed kernel. Type projections describe types, not list items.
"""
from dataclasses import dataclass
from enum import Enum

from .ids import NativeBoundaryID
from .native import EntryPortRef
from .providers import ProviderFactReference


class ResourceOperandKind(str, Enum):
    TENSOR_ARGUMENT = 'TENSOR_ARGUMENT'
    DEVICE_ARGUMENT = 'DEVICE_ARGUMENT'
    GENERATOR_ARGUMENT = 'GENERATOR_ARGUMENT'


class TypeProjection(str, Enum):
    OPTIONAL_ELEMENT = 'OPTIONAL_ELEMENT'
    LIST_ELEMENT = 'LIST_ELEMENT'


@dataclass(frozen=True, slots=True)
class ResourceOperand:
    boundary: NativeBoundaryID
    port: EntryPortRef
    category: ResourceOperandKind
    schema_type: str
    type_path: tuple[TypeProjection, ...]
    evidence: ProviderFactReference


@dataclass(frozen=True, slots=True)
class DeclaredDispatchCandidate:
    boundary: NativeBoundaryID
    keys: tuple[str, ...]
    symbol: str
    evidence: ProviderFactReference
    conditions: tuple[str, ...] = ('DECLARED_IMPLEMENTATION', 'RUNTIME_DISPATCH_SELECTION_OPEN')
