"""Ordered namespace accesses over shared source graphs, not module aliases."""
from dataclasses import dataclass
from scar.ir.literals import PythonLiteral

from . import normal_links as F, normal_targets as T, normal_graph as G
from . import source_bindings as B, source_productions as P
from .source_exec_roots import ExecEndpoint


@dataclass(frozen=True, slots=True)
class NamespaceInterfaceRef:
    unit: str
    index: int


@dataclass(frozen=True, slots=True)
class NamespaceLookupStep:
    """Step n is attempted only after all earlier steps report a miss."""
    ordinal: int
    interface: NamespaceInterfaceRef
    on_hit: str
    on_miss: str
    on_exception: str


@dataclass(frozen=True, slots=True)
class NamespaceAccess:
    site: T.GlobalPort
    owner: F.CodeScopeWitness
    binding_port: int
    action: P.BindingActionKind
    name: B.NameRef
    key: str
    read_plan: int | None
    lookup: tuple[NamespaceLookupStep, ...]
    missing_outcome: str | None
    target: NamespaceInterfaceRef | None
    value: T.GlobalPort | None
    world_in: T.GlobalPort
    world_out: T.GlobalPort


@dataclass(frozen=True, slots=True)
class NamespaceInterfaceBinding:
    """A branch binds templates to handles; it does not prove their contents."""
    connection: str
    interface: NamespaceInterfaceRef
    descriptor: B.EnvironmentInterface
    origin: str
    actual: ExecEndpoint | None
    root_formal: T.GlobalPort | None
    conditions: tuple[str, ...]
    capturing_function: T.GlobalPort | None = None


@dataclass(frozen=True, slots=True)
class GlobalsEnvironmentReference:
    site: T.GlobalPort
    owner: F.CodeScopeWitness
    globals_scope: int
    result: T.GlobalPort
    world_in: T.GlobalPort
    world_out: T.GlobalPort


@dataclass(frozen=True, slots=True)
class FunctionGlobalsCapture:
    """Retain the actual globals argument, separately from code and closure."""
    site: T.GlobalPort
    owner: F.CodeScopeWitness
    function: T.GlobalPort
    code: T.GlobalPort
    globals: T.GlobalPort
    body: F.CodeScopeWitness
    globals_scope: int
    world_in: T.GlobalPort
    world_out: T.GlobalPort
    builtins_policy: str = 'SELECT_FROM_GLOBALS_OR_CURRENT_FRAME_AT_FUNCTION_CREATION'


@dataclass(frozen=True, slots=True)
class GlobalsReferenceBinding:
    connection: str
    reference: T.GlobalPort
    actual: ExecEndpoint
    owner: F.CodeScopeWitness
    conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NamespaceReferenceHop:
    source: T.GlobalPort
    target: T.GlobalPort
    table: F.FactTable
    rows: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class NamespaceContentLink:
    """Conditional reaching definition, never a constant or equality proof."""
    connection: str
    interface: NamespaceInterfaceRef
    lookup_ordinal: int
    read: T.GlobalPort
    read_world: T.GlobalPort
    mapping: T.GlobalPort
    assigned: T.GlobalPort
    write_world: T.GlobalPort
    write_result_world: T.GlobalPort
    item_row: int
    source_table: F.FactTable
    member_ordinal: int | None
    key: str
    key_source: T.GlobalPort | PythonLiteral
    key_literal_source: T.GlobalPort | None
    key_reference_path: tuple[NamespaceReferenceHop, ...]
    reference_path: tuple[NamespaceReferenceHop, ...]
    conditions: tuple[str, ...]
    capturing_function: T.GlobalPort | None = None
    globals_reference: T.GlobalPort | None = None
    relation: str = 'MAY_REACHING_NAMESPACE_CONTENT'


@dataclass(frozen=True, slots=True)
class NamespaceGraphObligation:
    site: T.GlobalPort
    reason: str


@dataclass(frozen=True, slots=True)
class ExplicitNamespaceAction:
    site: T.GlobalPort
    owner: F.CodeScopeWitness
    kind: P.NamespaceActionKind
    arguments: tuple[T.GlobalPort, ...]
    world_in: T.GlobalPort
    world_out: T.GlobalPort
