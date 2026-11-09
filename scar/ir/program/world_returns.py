"""Cross-function state returns and separately guarded reference transport."""
from dataclasses import dataclass

from .normal_targets import GlobalPort, FunctionConnection
from .providers import ProviderFactReference
from .source_address_paths import AddressPath
from .source_world_flow import SourceWorldFlow


@dataclass(frozen=True, slots=True)
class WorldReturnNode:
    source_function: GlobalPort
    declared_context: int | None
    tracked_reference: GlobalPort | None
    flow: SourceWorldFlow


@dataclass(frozen=True, slots=True)
class WorldReturnEdge:
    callee: int
    caller: int
    call: ProviderFactReference
    interface: ProviderFactReference
    connection: FunctionConnection
    state_return: tuple[GlobalPort, GlobalPort]
    data_return: tuple[GlobalPort, GlobalPort] | None
    reference_paths: tuple[AddressPath, ...]
    reference_forwarded: bool
    conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WorldReturnFrontier:
    node: int
    reason: str


@dataclass(frozen=True, slots=True)
class WorldReturnGraph:
    roots: tuple[int, ...]
    nodes: tuple[WorldReturnNode, ...]
    edges: tuple[WorldReturnEdge, ...]
    frontiers: tuple[WorldReturnFrontier, ...]
    semantics: str = 'GUARDED_WORLD_RETURN_AND_REFERENCE_PATHS_NOT_CONTENT_PRESERVATION'
