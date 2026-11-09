"""Logical argument-binding state; no CPython struct or tensor snapshots."""
from dataclasses import dataclass
from enum import Enum

from .ids import LocationID,ValueID,OperationID
from .normal_targets import GlobalPort,RouteKind
from .source_productions import DeferredParameter


class DefaultInstanceParameter(str,Enum):
    CALLER_ACTIVATION='CALLER_ACTIVATION'
    CALLABLE_REFERENCE_OCCURRENCE='CALLABLE_REFERENCE_OCCURRENCE'
    WORLD_OCCURRENCE='WORLD_OCCURRENCE'


@dataclass(frozen=True,slots=True)
class FunctionDefaultSlot:
    id: LocationID
    callable: GlobalPort
    definition: GlobalPort
    parameter_index: int
    parameter_name: str
    parameter: DeferredParameter
    instance_parameters: tuple[DefaultInstanceParameter,...] = (
        DefaultInstanceParameter.CALLER_ACTIVATION,
        DefaultInstanceParameter.CALLABLE_REFERENCE_OCCURRENCE)
    semantics: str = 'SELECTED_SOURCE_FUNCTION_DEFAULT_SLOT_NOT_OBJECT_CONTENT'


@dataclass(frozen=True,slots=True)
class FunctionDefaultState:
    id: ValueID
    address: LocationID
    world: GlobalPort
    instance_parameters: tuple[DefaultInstanceParameter,...] = (
        DefaultInstanceParameter.CALLER_ACTIVATION,DefaultInstanceParameter.WORLD_OCCURRENCE)
    semantics: str = 'SYMBOLIC_CURRENT_SLOT_AT_WORLD_NOT_CREATION_VALUE_EQUALITY'


@dataclass(frozen=True,slots=True)
class FunctionDefaultRead:
    operation: OperationID
    address: LocationID
    state: ValueID
    formal: GlobalPort
    initial_source: GlobalPort
    route: RouteKind
    semantics: str = 'INITIAL_SOURCE_REQUIRES_SELECTED_CREATION_AND_UNCHANGED_DEFAULT_STATE'
