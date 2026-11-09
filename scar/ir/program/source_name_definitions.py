"""Conditional reaching binding definitions over a shared source control view."""
from dataclasses import dataclass
from enum import Enum

from . import normal_graph as G
from .normal_links import CodeScopeRef, Namespace
from .normal_targets import Body, GlobalPort
from .providers import ProviderFactReference
from .source_name_access_anchors import NameAccessAnchorGraph
from .source_value_flow import SourceOperation


class NameDefinitionKind(str, Enum):
    ENTRY_OPEN = 'ENTRY_OPEN'
    FORMAL = 'FORMAL'
    WRITE = 'WRITE'
    DELETE = 'DELETE'
    OPAQUE_EFFECT = 'OPAQUE_EFFECT'


@dataclass(frozen=True, slots=True)
class NameDefinition:
    """None value means no known reference operand, never Python None.

    access/formal index the input anchor graph; operation indexes operations.
    """
    kind: NameDefinitionKind
    site: G.Port
    value: GlobalPort | None
    access: int | None
    formal: int | None
    operation: int | None
    evidence: tuple[ProviderFactReference, ...]
    conditions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NameDefinitionState:
    port: G.Port
    stack: tuple[G.CallSite, ...]
    incoming: tuple[int, ...]
    outgoing: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class NameDefinitionTransition:
    """edge indexes the unchanged control_edges table."""
    source: int
    target: int
    edge: int


@dataclass(frozen=True, slots=True)
class NameDefinitionRead:
    """Definitions observed at one READ ENTER and its recipe caller stack."""
    state: int
    access: int
    anchors: tuple[int, ...]
    definitions: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class NameDefinitionFrontier:
    state: int | None
    edge: int | None
    access: int | None
    reason: str
    evidence: tuple[ProviderFactReference, ...] = ()


@dataclass(frozen=True, slots=True)
class NameDefinitionGraph:
    source_function: GlobalPort
    function: ProviderFactReference
    body: Body
    scope: CodeScopeRef
    namespace: Namespace
    anchor_graph: NameAccessAnchorGraph
    control_edges: tuple[G.Edge, ...]
    operations: tuple[SourceOperation, ...]
    definitions: tuple[NameDefinition, ...]
    states: tuple[NameDefinitionState, ...]
    transitions: tuple[NameDefinitionTransition, ...]
    reads: tuple[NameDefinitionRead, ...]
    frontiers: tuple[NameDefinitionFrontier, ...]
    traversal_complete: bool
    dataflow_complete: bool
    conditions: tuple[str, ...] = (
        'SOURCE_FUNCTION_BODY_AND_SAME_LEXICAL_FRAME_BINDING_CONTEXT_SELECTED',
        'STRUCTURAL_RECIPE_CALL_RETURN_SITES_MATCHED',
        'BRANCH_GUARDS_RETAINED_WITHOUT_RUNTIME_PATH_SELECTION',
        'APPLICATION_EXCEPTION_AND_RESUME_PATHS_REMAIN_OPEN',
        'OPAQUE_CALLBACK_AND_CAPTURE_IDENTITY_EFFECTS_REMAIN_OPEN',
        'TRACKED_MAY_REACHING_BINDING_DEFINITIONS_NOT_TENSOR_CONTENT_VERSIONS',
        'NO_CURRENT_REFERENCE_RUNTIME_ENTRY_OR_EXTERNAL_WRITER_ABSENCE_PROOF',
    )
    loops_unrolled: bool = False
    semantics: str = 'CONDITIONAL_TRACKED_MAY_REACHING_BINDING_DEFINITIONS'
