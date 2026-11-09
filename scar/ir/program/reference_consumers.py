"""Original argument uses and conditional source parameter consumers."""
from dataclasses import dataclass
from enum import Enum

from .normal_targets import GlobalPort, Body, Endpoint, Route, FunctionActivation
from .providers import ProviderFactReference
from .source_address_paths import AddressPath
from .source_world_flow import SourceWorldFlow


class ArgumentRole(str, Enum):
    CALLEE = 'CALLEE'
    ATTRIBUTE_RECEIVER = 'ATTRIBUTE_RECEIVER'
    POSITIONAL = 'POSITIONAL'
    KEYWORD = 'KEYWORD'
    POSITIONAL_PACK = 'POSITIONAL_PACK'
    KEYWORD_PACK = 'KEYWORD_PACK'


@dataclass(frozen=True, slots=True)
class ReferenceArgumentUse:
    node: int
    call: ProviderFactReference
    role: ArgumentRole
    ordinal: int
    keyword: str | None
    actual: GlobalPort
    paths: tuple[AddressPath, ...]
    direct_reference: bool
    world_before: GlobalPort
    world_after: GlobalPort
    conditions: tuple[str, ...]
    attribute: ProviderFactReference | None = None


@dataclass(frozen=True, slots=True)
class SourceConsumerBinding:
    use: int
    interface: ProviderFactReference
    source_callable: GlobalPort
    body: Body
    activation: FunctionActivation
    argument: Route
    state: Route
    data_return: tuple[Endpoint, Endpoint] | None
    state_return: tuple[Endpoint, Endpoint] | None
    conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConsumerFrontier:
    node: int
    use: int | None
    actual: GlobalPort | None
    interface: ProviderFactReference | None
    reason: str


@dataclass(frozen=True, slots=True)
class ConsumerBody:
    source_function: GlobalPort
    flow: SourceWorldFlow


@dataclass(frozen=True, slots=True)
class ConsumerBodyEntry:
    binding: int
    body: int
    formal: GlobalPort
    conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReferenceConsumerGraph:
    uses: tuple[ReferenceArgumentUse, ...]
    bindings: tuple[SourceConsumerBinding, ...]
    frontiers: tuple[ConsumerFrontier, ...]
    bodies: tuple[ConsumerBody, ...] = ()
    entries: tuple[ConsumerBodyEntry, ...] = ()
    semantics: str = 'CONDITIONAL_ARGUMENT_DEPENDENCIES_NOT_SELECTED_DISPATCH_ESCAPE_OR_CONTENT_IDENTITY'
