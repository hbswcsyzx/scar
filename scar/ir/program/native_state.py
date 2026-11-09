"""Local native state declarations; no dispatch or physical alias proof."""
from dataclasses import dataclass
from enum import Enum

from .ids import LocationID, NativeBoundaryID, OperationID, ValueID
from .native import EntryPortRef, ExitPortRef
from .native_resource_declarations import TypeProjection
from .providers import ProviderFactReference


class NativeStateCategory(str, Enum):
    TENSOR = 'TENSOR'
    GENERATOR = 'GENERATOR'


class NativePortDirection(str, Enum):
    INPUT = 'INPUT'
    OUTPUT = 'OUTPUT'


class NativeStateParameter(str, Enum):
    INVOCATION = 'INVOCATION'
    PORT_VALUE_INSTANCE = 'PORT_VALUE_INSTANCE'
    OPTIONAL_LEAF_PRESENT = 'OPTIONAL_LEAF_PRESENT'
    LIST_ELEMENT_SELECTIONS = 'LIST_ELEMENT_SELECTIONS'


class AliasAnnotationPhase(str, Enum):
    # These name original annotation fields, not execution time. A return's
    # annotation.before can share a label with an input's annotation.before.
    BEFORE = 'BEFORE'
    EXPLICIT_AFTER = 'EXPLICIT_AFTER'


@dataclass(frozen=True, slots=True)
class NativeStateAddress:
    id: LocationID
    boundary: NativeBoundaryID
    slot: EntryPortRef | ExitPortRef
    direction: NativePortDirection
    position: int
    reference: ValueID
    category: NativeStateCategory
    schema_type: str
    type_path: tuple[TypeProjection, ...]
    type_evidence: ProviderFactReference
    alias_before: tuple[str, ...] | None
    declared_may_write: bool | None
    alias_after: tuple[str, ...] | None
    parameters: tuple[NativeStateParameter, ...]
    semantics: str = 'DECLARED_NATIVE_LEAF_FAMILY_NOT_PHYSICAL_TENSOR_OR_STORAGE'


@dataclass(frozen=True, slots=True)
class NativeStateProjection:
    id: ValueID
    address: LocationID
    world: ValueID
    semantics: str = 'SYMBOLIC_NATIVE_STATE_AT_WORLD_NOT_OBSERVED_CONTENT_VERSION'


@dataclass(frozen=True, slots=True)
class NativeStateAccess:
    operation: OperationID
    address: LocationID
    world_before: ValueID | None
    world_normal: ValueID
    world_raised: ValueID | None
    state_before: ValueID | None
    state_normal: ValueID
    state_raised: ValueID | None
    effects_closed: bool = False


@dataclass(frozen=True, slots=True)
class NativeAliasGroup:
    """Factored declaration relation, not a program node or StorageID.

    No explicit after labels means an unspecified annotation field, never an
    established empty post-alias set. Wildcards retain an open alias frontier.
    """
    boundary: NativeBoundaryID
    declaration: ProviderFactReference
    phase: AliasAnnotationPhase
    label: str
    members: tuple[LocationID, ...]
    wildcard: bool
