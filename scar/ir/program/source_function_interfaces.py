"""Original source-function candidates connected to conditional call ABIs."""
from dataclasses import dataclass

from .normal_links import CodeScopeRef
from .normal_targets import CallLink, FunctionActivation
from .providers import ProviderFactReference


@dataclass(frozen=True, slots=True)
class SourceFunctionInterface:
    query: int
    origin: int
    call: ProviderFactReference
    definition: ProviderFactReference
    reference: ProviderFactReference
    activation: FunctionActivation
    link: CallLink


@dataclass(frozen=True, slots=True)
class SourceFunctionInterfaceFrontier:
    query: int
    origin: int | None
    reference: ProviderFactReference
    reason: str


@dataclass(frozen=True, slots=True)
class SourceFunctionInterfaceQuery:
    """Indexes original declarations, including calls with no function target.

    ``declared`` and ``reference`` identify complete parent query records.
    Frontier ordinals index their respective NamespaceReferenceSlice.frontiers;
    interface ordinals index this unit's interfaces table. Owners are source
    code scopes, never evidence of their activation or of a caller frame.
    """
    query: int
    call: ProviderFactReference
    declared: ProviderFactReference
    reference: ProviderFactReference
    owners: tuple[CodeScopeRef, ...]
    function_origins: tuple[int, ...]
    interfaces: tuple[int, ...]
    declared_frontiers: tuple[int, ...]
    reference_frontiers: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class SourceFunctionInterfaceUnit:
    unit: str
    calls: int
    function_origins: int
    controlled_queries: tuple[int, ...]
    interfaces: tuple[SourceFunctionInterface, ...]
    frontiers: tuple[SourceFunctionInterfaceFrontier, ...]
    queries: tuple[SourceFunctionInterfaceQuery, ...] = ()
    semantics: str = 'DECLARED_SOURCE_FUNCTION_PARAMETER_AND_RETURN_INTERFACES_NOT_SCOPE_ADMISSION'
