"""Demand graph for declared reference flow; never tensor/content equality."""
from dataclasses import dataclass
from enum import Enum

from .normal_targets import Endpoint, GlobalPort, AttributeSite, FunctionConnection
from .providers import ProviderFactReference


class ReferenceTransitionKind(str, Enum):
    DECLARED_ALIAS = 'DECLARED_ALIAS'
    LEXICAL_MAY_BINDING = 'LEXICAL_MAY_BINDING'
    ARGUMENT = 'ARGUMENT'
    INITIAL_DEFAULT = 'INITIAL_DEFAULT'
    DATA_RETURN_ENTER_CALL = 'DATA_RETURN_ENTER_CALL'
    CONSTRUCTOR_DATA_FROM_NEW_RESULT = 'CONSTRUCTOR_DATA_FROM_NEW_RESULT'


class ReferenceOriginKind(str, Enum):
    ALLOCATION_SITE_CANDIDATE = 'ALLOCATION_SITE_CANDIDATE'
    SOURCE_LITERAL = 'SOURCE_LITERAL'
    FUNCTION_DEFINITION = 'FUNCTION_DEFINITION'
    CLASS_DEFINITION = 'CLASS_DEFINITION'


@dataclass(frozen=True, slots=True)
class ReferenceState:
    port: Endpoint
    calls: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class ReferenceTransition:
    downstream: int
    upstream: int
    kind: ReferenceTransitionKind
    evidence: tuple[ProviderFactReference, ...]
    conditions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReferenceOrigin:
    state: int
    kind: ReferenceOriginKind
    source_class: GlobalPort | None
    evidence: tuple[ProviderFactReference, ...]
    conditions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReferenceFrontier:
    state: int
    reason: str


@dataclass(frozen=True, slots=True)
class ReferenceSlice:
    states: tuple[ReferenceState, ...]
    transitions: tuple[ReferenceTransition, ...]
    origins: tuple[ReferenceOrigin, ...]
    frontiers: tuple[ReferenceFrontier, ...]
    semantics: str = 'CONDITIONAL_DECLARED_REFERENCE_FLOW_NOT_CONTENT_OR_RUNTIME_IDENTITY'


@dataclass(frozen=True, slots=True)
class ConditionalFieldFlow:
    write: ProviderFactReference
    read: ProviderFactReference
    write_site: AttributeSite
    read_site: AttributeSite
    shared_allocation_candidate: Endpoint
    receiver_class: GlobalPort
    write_slice: int
    read_slice: int
    write_origin: int
    read_origin: int
    conditions: tuple[str, ...]
    semantics: str = 'MAY_REACHING_FIELD_STORE_NOT_SELECTED_STATE_VERSION'


@dataclass(frozen=True, slots=True)
class DeclaredMethodInterface:
    call: ProviderFactReference
    attribute: ProviderFactReference
    class_binding: ProviderFactReference
    field_flow: int
    value_slice: int
    value_origin: int
    member_slice: int
    member_origin: int
    source_class: GlobalPort
    connection: FunctionConnection
    conditions: tuple[str, ...]
    semantics: str = 'CONDITIONAL_DECLARED_INTERFACE_NOT_ENTRY_ADMISSION_OR_RUNTIME_DISPATCH'


@dataclass(frozen=True, slots=True)
class FieldInterfaceQuery:
    unit: str
    call_ordinal: int
    method_attribute_ordinal: int
    field_attribute_ordinal: int
    slices: tuple[ReferenceSlice, ...]
    flows: tuple[ConditionalFieldFlow, ...]
    methods: tuple[DeclaredMethodInterface, ...]
    writer_units: tuple[str, ...]
    obligations: tuple[str, ...]
