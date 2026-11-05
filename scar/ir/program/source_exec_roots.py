"""Standard exec protocol regions, linked to original caller/root ports."""
from dataclasses import dataclass
from enum import Enum

from scar.ir.effects import ActionLabel,Knowledge
from scar.ir.literals import PythonLiteral
from . import normal_links as F,normal_targets as T,normal_graph as G
from .python_bindings import SourceCallSite
from .source_execution import CompiledCodeUse


class ExecNamespaceKind(str,Enum):
    EXPLICIT_VALUE='EXPLICIT_VALUE'
    CALLER_GLOBALS='CALLER_GLOBALS'
    CALLER_LOCALS='CALLER_LOCALS'


class ExecPhase(str,Enum):
    NAMESPACE_SELECTION='NAMESPACE_SELECTION'
    ENSURE_BUILTINS='ENSURE_BUILTINS'
    CHECK_CLOSURE='CHECK_CLOSURE'
    AUDIT='AUDIT'
    BODY='BODY'
    DISCARD_AND_RELEASE='DISCARD_AND_RELEASE'


@dataclass(frozen=True,slots=True)
class ExecPredicate:
    rule: str
    source: T.GlobalPort | None = None


@dataclass(frozen=True,slots=True)
class ExecProtocolValue:
    """A protocol result, never a fabricated original source port."""
    site: T.GlobalPort
    branch: str
    role: str
    owner: F.CodeScopeRef


ExecEndpoint = T.GlobalPort | ExecProtocolValue


@dataclass(frozen=True,slots=True)
class ExecNamespaceSelection:
    kind: ExecNamespaceKind
    value: ExecEndpoint
    frame_owner: F.CodeScopeRef | None
    frame_kind: str | None
    representation: str
    conditions: tuple[ExecPredicate,...] = ()


@dataclass(frozen=True,slots=True)
class ExecProtocolAction:
    phase: ExecPhase
    world_in: ExecEndpoint
    world_out: ExecEndpoint
    control_in: ExecEndpoint
    control_out: ExecEndpoint
    labels: tuple[ActionLabel,...]
    known_reads: tuple[str,...]
    known_writes: tuple[str,...] = ()
    inputs: tuple[ExecEndpoint,...] = ()
    outputs: tuple[ExecEndpoint,...] = ()
    completeness: Knowledge = Knowledge.UNKNOWN
    allocations: Knowledge = Knowledge.UNKNOWN
    frees: Knowledge = Knowledge.UNKNOWN
    rng: Knowledge = Knowledge.UNKNOWN
    may_raise: Knowledge = Knowledge.KNOWN
    external: Knowledge = Knowledge.UNKNOWN
    conditions: tuple[ExecPredicate,...] = ()


@dataclass(frozen=True,slots=True)
class ExecGraphEdge:
    source: ExecEndpoint
    target: ExecEndpoint
    kind: G.EdgeKind
    transition: G.Transition
    conditions: tuple[ExecPredicate,...] = ()


@dataclass(frozen=True,slots=True)
class ExecRootConnection:
    id: str
    site: SourceCallSite
    owner: F.CodeScopeRef
    compiled_candidate: str
    root: F.CodeScopeWitness
    globals: ExecNamespaceSelection
    locals: ExecNamespaceSelection
    predicates: tuple[ExecPredicate,...]
    actions: tuple[ExecProtocolAction,...]
    edges: tuple[ExecGraphEdge,...]
    normal_result: PythonLiteral
    free_variables: tuple[str,...]
    conditions: tuple[str,...]
    discharged: tuple[str,...] = (
        'COMPILED_CONTEXT_HAS_NO_MATCHED_F4_BODY_VARIANT',
        'CONTEXT_QUALIFIED_F3_F4_VARIANT_NOT_BUILT',
        'CONTEXT_QUALIFIED_F4_BODY_NOT_BUILT',
    )
    obligations: tuple[str,...] = (
        'EXEC_NAMESPACE_CONTENTS_NOT_PROPAGATED_INTO_ROOT_CONSTRAINT_SOLVER',
        'EXEC_BOUNDARY_EFFECTS_NOT_PROVEN_PURE',
    )
    semantics: str = 'CONDITIONAL_STANDARD_EXEC_GRAPH_CONNECTION_NOT_RUNTIME_OBSERVATION'
    code_use: CompiledCodeUse | None = None
    profile: str = 'NORMAL_SUCCESS'


@dataclass(frozen=True,slots=True)
class ExecRootObligation:
    site: T.GlobalPort
    reason: str
