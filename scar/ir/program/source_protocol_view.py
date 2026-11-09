"""Symbolic Python protocol interfaces, without physical object identities."""
from dataclasses import dataclass

from .ids import LocationID, ValueID
from .normal_targets import ConstructionPort, Endpoint, GlobalPort
from .providers import ProviderFactReference


@dataclass(frozen=True, slots=True)
class ConstructionInterfaceValue:
    id: ValueID
    endpoint: ConstructionPort
    instance_parameters: tuple[str, ...] = ('CALLER_ACTIVATION', 'CONSTRUCTION_OCCURRENCE')


@dataclass(frozen=True, slots=True)
class ProtocolCallableSelection:
    id: ValueID
    callee: GlobalPort
    definition: GlobalPort
    lookup_world: Endpoint
    selection: ProviderFactReference
    protocol: str
    instance_parameters: tuple[str, ...] = ('CALLER_ACTIVATION', 'LOOKUP_OCCURRENCE', 'CURRENT_DESCRIPTOR_VERSION')


@dataclass(frozen=True, slots=True)
class ProtocolDefaultSlot:
    id: LocationID
    callable: ValueID
    definition: GlobalPort
    parameter_index: int
    parameter_name: str
    initial_source: GlobalPort


@dataclass(frozen=True, slots=True)
class ProtocolDefaultState:
    id: ValueID
    address: LocationID
    world: Endpoint
    instance_parameters: tuple[str, ...] = ('CALLER_ACTIVATION', 'LOOKUP_OCCURRENCE', 'DEFAULT_MUTATION_HISTORY')
