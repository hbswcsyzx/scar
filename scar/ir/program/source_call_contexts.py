"""Matched static incoming interfaces, distinct from runtime invocations."""
from dataclasses import dataclass

from .normal_targets import CallLink, Endpoint, GlobalPort, FunctionConnection
from .providers import ProviderFactReference
from .source_reference_slices import ReferenceTransition, ReferenceOrigin, ReferenceFrontier


@dataclass(frozen=True, slots=True)
class CallInterfaceRecord:
    evidence: ProviderFactReference
    link: CallLink


@dataclass(frozen=True, slots=True)
class ContextReferenceState:
    port: Endpoint
    interfaces: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class ContextReferenceSlice:
    states: tuple[ContextReferenceState, ...]
    edges: tuple[ReferenceTransition, ...]
    origins: tuple[ReferenceOrigin, ...]
    frontiers: tuple[ReferenceFrontier, ...]
    semantics: str = 'SELECTED_INCOMING_INTERFACE_REFERENCE_PATHS_NOT_CONTENT_OR_RUNTIME_IDENTITY'


@dataclass(frozen=True, slots=True)
class CallContextQuery:
    incoming: int
    call: ProviderFactReference
    callee: GlobalPort
    reference: ContextReferenceSlice
    root: int = 0


@dataclass(frozen=True, slots=True)
class CallContextRoot:
    body: int
    incoming: int
    entries: tuple[ProviderFactReference, ...]


@dataclass(frozen=True, slots=True)
class ContextFunctionConnection:
    query: int
    origin: int
    connection: FunctionConnection


@dataclass(frozen=True, slots=True)
class ContextTargetEvidence:
    query: int
    candidate: int
    relation: str
    conditions: tuple[str, ...] = (
        'SOURCE_OWNING_SCOPES_AND_RECORDED_REFERENCE_PATH_CONDITIONS_SELECTED',
        'HISTORICAL_CANDIDATES_RETAINED_NOT_RUNTIME_DISPATCH',
        'NO_EFFECT_CONTENT_VERSION_OR_TRANSFORMATION_AUTHORITY',
    )
