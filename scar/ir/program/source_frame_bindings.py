"""Frame namespace provenance, independent of source-module object identity."""
from dataclasses import dataclass
from scar.ir.literals import PythonLiteral

from . import normal_links as F,normal_targets as T
from .source_exec_roots import ExecEndpoint
from .source_namespaces import FunctionGlobalsCapture
from .suspension_interfaces import StepWitness


@dataclass(frozen=True,slots=True)
class StaticInputPort:
    """A declared input field; never a fabricated original source-code port."""
    root: F.CodeScopeWitness
    contract_sha256: str
    path: tuple[str | int,...]

    @property
    def unit(self):
        return self.root.owner.unit


@dataclass(frozen=True,slots=True)
class StaticInputBinding:
    port: StaticInputPort
    literal: PythonLiteral
    semantics: str = 'DECLARED_INITIAL_FIELD_VERSION_NOT_IMMUTABLE_CURRENT_CONTENT'


ContextEndpoint = T.Endpoint | StaticInputPort


@dataclass(frozen=True,slots=True)
class ContextContentFactor:
    id: str
    container: ContextEndpoint
    key: PythonLiteral | None
    sources: tuple[ContextEndpoint,...]
    targets: tuple[ContextEndpoint,...]
    semantics: str = 'FLOW_INSENSITIVE_MAY_CONTENT'


@dataclass(frozen=True,slots=True)
class ContextContentIndexCycle:
    container: ContextEndpoint
    source: ContextEndpoint
    start: int
    stride: int
    path: tuple[ContextEndpoint,...]
    abstract_position: str = 'UNKNOWN_POSITION'
    semantics: str = 'DESCENDING_CYCLE_CONSTRAINT_WITH_MAY_POSITION_WIDENING'


@dataclass(frozen=True,slots=True)
class RootNamespaceBinding:
    root: F.CodeScopeWitness
    globals: T.GlobalPort
    locals: T.GlobalPort
    initialization: str
    conditions: tuple[str,...]
    entry_contract_sha256: str | None = None


@dataclass(frozen=True,slots=True)
class FunctionFrameSource:
    source_callable: T.GlobalPort
    callee: T.Endpoint
    body: F.CodeScopeWitness
    environment_formal: T.GlobalPort
    capture: FunctionGlobalsCapture
    capture_witness: StepWitness
    conditions: tuple[str,...]


@dataclass(frozen=True,slots=True)
class FrameGlobalsBinding:
    connection: str
    caller: F.CodeScopeRef
    protocol_reference: ExecEndpoint
    source: T.GlobalPort
    target: T.GlobalPort
    read_world: T.GlobalPort
    function: FunctionFrameSource | None
    conditions: tuple[str,...]


@dataclass(frozen=True,slots=True)
class FrameGlobalsRead:
    caller: F.CodeScopeRef
    result: T.GlobalPort
    source: T.GlobalPort
    read_world: T.GlobalPort
    function: FunctionFrameSource | None
    conditions: tuple[str,...]


@dataclass(frozen=True,slots=True)
class FrameGlobalsObligation:
    caller: F.CodeScopeRef
    result: T.GlobalPort
    reason: str
