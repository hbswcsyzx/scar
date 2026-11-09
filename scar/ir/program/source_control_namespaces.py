"""Control-qualified name sources; the original declaration graph stays shared."""
from dataclasses import dataclass

from .normal_links import CodeScopeRef, Namespace
from .normal_targets import GlobalPort, Body
from .providers import ProviderFactReference
from .source_name_access_anchors import NameAccessAnchorGraph
from .source_name_definitions import (NameDefinitionGraph, NameDefinitionKind, NameDefinition,
    NameDefinitionState, NameDefinitionTransition, NameDefinitionRead, NameDefinitionFrontier)
from .source_namespace_references import NamespaceReferenceSlice
from .source_value_flow import SourceOperation
from .normal_graph import Edge


NORMAL_VIEW = (
    'RECORDED_NORMAL_RECIPE_CONTROL_PATH_AND_SAME_FRAME_SELECTED',
    'ALL_RETAINED_RECIPE_CONTEXTS_AND_BRANCH_ALTERNATIVES_JOINED_AS_MAY',
    'APPLICATION_EXCEPTION_AND_RESUME_PATHS_REQUIRE_SEPARATE_SOURCE_BRANCH',
    'OPAQUE_REFERENCE_SOURCES_REMAIN_OPEN_NOT_CONNECTED_TO_ARBITRARY_WRITERS',
    'NO_CURRENT_BINDING_CONTENT_TENSOR_VERSION_OR_RUNTIME_DISPATCH_PROOF',
)


@dataclass(frozen=True, slots=True)
class NameReadFilter:
    read: ProviderFactReference
    scope: CodeScopeRef | None
    track: int | None
    accesses: tuple[int, ...]
    read_states: tuple[int, ...]
    writers: tuple[ProviderFactReference, ...]
    open_kinds: tuple[NameDefinitionKind, ...]
    applied: bool
    reason: str
    conditions: tuple[str, ...] = NORMAL_VIEW


@dataclass(frozen=True, slots=True)
class ExcludedNameWriter:
    downstream: int
    writer: ProviderFactReference
    read: ProviderFactReference
    filter: int
    conditions: tuple[str, ...] = NORMAL_VIEW


@dataclass(frozen=True, slots=True)
class ControlNamespaceQuery:
    query: int
    callee: GlobalPort
    reference: NamespaceReferenceSlice
    filters: tuple[int, ...]
    excluded: tuple[ExcludedNameWriter, ...]
    conditions: tuple[str, ...] = NORMAL_VIEW


@dataclass(frozen=True, slots=True)
class NameControlBody:
    source_function: GlobalPort
    function: ProviderFactReference
    body: Body
    scope: CodeScopeRef
    control_edges: tuple[Edge, ...]
    operations: tuple[SourceOperation, ...]


@dataclass(frozen=True, slots=True)
class StoredNameDefinitionTrack:
    """Per-slot propagation references shared body and anchor tables."""
    anchor: int
    body: int
    namespace: Namespace
    definitions: tuple[NameDefinition, ...]
    states: tuple[NameDefinitionState, ...]
    transitions: tuple[NameDefinitionTransition, ...]
    reads: tuple[NameDefinitionRead, ...]
    frontiers: tuple[NameDefinitionFrontier, ...]
    traversal_complete: bool
    dataflow_complete: bool
    conditions: tuple[str, ...]
    loops_unrolled: bool
    semantics: str


@dataclass(frozen=True, slots=True)
class ControlNamespaceUnit:
    unit: str
    anchors: tuple[NameAccessAnchorGraph, ...]
    bodies: tuple[NameControlBody, ...]
    tracks: tuple[NameDefinitionGraph, ...]
    filters: tuple[NameReadFilter, ...]
    queries: tuple[ControlNamespaceQuery, ...]
    semantics: str = 'NORMAL_CONTROL_QUALIFIED_EXPLICIT_NAME_SOURCES_WITH_OPEN_EFFECT_FRONTIERS'
