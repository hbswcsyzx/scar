"""Source content requests and symbolic state at world boundaries.

An address is an expression over reference occurrences, not an ObjectID or
physical slot. Projected state values can be equal; distinct IDs do not prove
a mutation or different LogicalVersions. Protocol side effects stay open.
"""
from dataclasses import dataclass
from enum import Enum

from .ids import LocationID, OperationID, UseID, ValueID
from .normal_targets import GlobalPort
from .normal_links import CodeScopeRef
from .source_address_paths import FieldSelector, ItemSelector


@dataclass(frozen=True, slots=True)
class SliceBoundsSelector:
    """Original bound references; no slice object or numeric bounds assumed."""
    lower: GlobalPort
    upper: GlobalPort


ContentSelector = FieldSelector | ItemSelector | SliceBoundsSelector


class ContentRequestKind(str, Enum):
    GET = 'GET'
    SET = 'SET'
    DELETE = 'DELETE'


class ContentInstanceParameter(str, Enum):
    ACTIVATION = 'ACTIVATION'
    OWNER_REFERENCE_OCCURRENCE = 'OWNER_REFERENCE_OCCURRENCE'
    SELECTOR_REFERENCE_OCCURRENCES = 'SELECTOR_REFERENCE_OCCURRENCES'


@dataclass(frozen=True, slots=True)
class ContentAddressTemplate:
    id: LocationID
    receiver: GlobalPort
    selector: ContentSelector
    instance_parameters: tuple[ContentInstanceParameter, ...]
    semantics: str = 'SOURCE_PROTOCOL_REQUEST_ADDRESS_NOT_PHYSICAL_SLOT'


@dataclass(frozen=True, slots=True)
class ContentStateProjection:
    """The abstract state project(world, selected address instance).

    This is a symbolic state variable, never a captured tensor, a write count,
    or an established LogicalVersion. A GET may run a mutating descriptor.
    """
    id: ValueID
    address: LocationID
    world: GlobalPort
    semantics: str = 'SYMBOLIC_CONTENT_AT_WORLD_NOT_LOGICAL_VERSION_EQUALITY'


@dataclass(frozen=True, slots=True)
class ContentAccessTemplate:
    operation: OperationID
    site: GlobalPort
    scope: CodeScopeRef
    kind: ContentRequestKind
    address: LocationID
    receiver_use: UseID
    payload: GlobalPort | None
    result: GlobalPort | None
    world_before: GlobalPort
    world_after: GlobalPort
    state_before: ValueID
    state_after: ValueID
    attribute_fact: int | None
    effects_closed: bool = False
