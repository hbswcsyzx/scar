"""Locations read or written at original world boundaries, with open effects."""
from dataclasses import dataclass

from .normal_targets import GlobalPort
from .providers import ProviderFactReference
from .source_address_paths import AddressPath


@dataclass(frozen=True, slots=True)
class CallAddressInput:
    role: str
    ordinal: int
    keyword: str | None
    value: GlobalPort
    paths: tuple[AddressPath, ...]


@dataclass(frozen=True, slots=True)
class AddressedAccess:
    access_ordinal: int
    fact: ProviderFactReference
    table: str
    action: str
    world_before: GlobalPort
    world_after: GlobalPort
    locations: tuple[AddressPath, ...]
    call_inputs: tuple[CallAddressInput, ...]
    effect_frontier: str
    semantics: str = 'SYMBOLIC_LOCATION_AT_WORLD_NOT_SELECTED_OBJECT_OR_CONTENT_VERSION'


@dataclass(frozen=True, slots=True)
class AddressedWorld:
    query_ordinal: int
    unit: str
    anchor: GlobalPort
    normal_exit: GlobalPort
    accesses: tuple[AddressedAccess, ...]
