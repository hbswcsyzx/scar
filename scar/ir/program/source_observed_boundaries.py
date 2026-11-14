"""Shared source CALL interfaces and separate recorded dispatch occurrences.

An interface describes original Python-side ports. It is neither a callee
body nor a native signature, constructor stage, completion or effect proof.
"""
from dataclasses import dataclass
from enum import Enum

from scar.ir.effects import Knowledge
from .ids import ProviderID
from .normal_links import CodeScopeWitness
from .normal_targets import GlobalPort, Body
from .providers import ProviderFactReference
from .call_edges import CallRecordAnchor, CapturedCode, InvocationKey
from .python_call_targets import PythonCallTarget, PythonTargetKind
from .native_callables import NativeCallableFact


@dataclass(frozen=True, slots=True)
class SourceObservedBoundary:
    id: ProviderID
    unit: str
    query: int
    call: ProviderFactReference
    owner: CodeScopeWitness
    target_kind: PythonTargetKind
    callee: GlobalPort
    positional: tuple[GlobalPort, ...]
    keywords: tuple[tuple[str, GlobalPort], ...]
    positional_pack: GlobalPort | None
    keyword_pack: GlobalPort | None
    world: GlobalPort
    result: GlobalPort
    result_world: GlobalPort
    effects: Knowledge = Knowledge.UNKNOWN


@dataclass(frozen=True, slots=True)
class SourceObservedProtocolBoundary:
    """Original protocol ports and shared body; never a Python-formal ABI."""
    id: ProviderID
    unit: str
    kind: str
    definition: ProviderFactReference
    operation: GlobalPort
    arguments: tuple[GlobalPort, ...]
    result: GlobalPort
    world: GlobalPort
    result_world: GlobalPort
    body: Body
    owner: CodeScopeWitness
    effects: Knowledge = Knowledge.UNKNOWN

    def __post_init__(self):
        if (self.kind not in ('CREATE_GENEXPR', 'BUILD_CLASS')
                or self.owner.owner.unit != self.unit or self.body.unit != self.unit
                or any(port.unit != self.unit for port in
                    (self.operation, *self.arguments, self.result, self.world, self.result_world))):
            raise ValueError('protocol boundary needs its original unit, operation and body')


@dataclass(frozen=True, slots=True)
class SourceBoundaryObservation:
    boundary: ProviderID
    source_observation: ProviderID
    attempt: CallRecordAnchor
    target: PythonCallTarget
    target_anchor: CallRecordAnchor
    profile_alternatives: tuple[ProviderFactReference, ...]
    native: NativeCallableFact | None = None
    native_anchor: CallRecordAnchor | None = None


class SourceCallbackBodyKind(str, Enum):
    NO_SOURCE = 'NO_SOURCE'
    FUNCTION = 'FUNCTION'
    EVALUATION_REQUEST = 'EVALUATION_REQUEST'


@dataclass(frozen=True, slots=True)
class SourceBoundaryCallback:
    """One shared callback code/interface, not one frame per iteration.

    A suspending code does not identify its generator instance or resume
    position. Missing source-body correspondence never erases the known code.
    For EVALUATION_REQUEST, ``formals`` are the original region's environment,
    format and world inputs, not a Python-function parameter binder.
    """
    id: ProviderID
    boundary: ProviderID
    code: CapturedCode
    suspending: bool
    body_kind: SourceCallbackBodyKind
    body: Body | None
    definition: ProviderFactReference | None
    scope: CodeScopeWitness | None
    formals: tuple[GlobalPort, ...]
    result: GlobalPort | None
    result_world: GlobalPort | None

    def __post_init__(self):
        if type(self.body_kind) is not SourceCallbackBodyKind or type(self.suspending) is not bool:
            raise ValueError('callback needs an explicit body protocol and suspension state')
        if self.body_kind is SourceCallbackBodyKind.NO_SOURCE:
            if (any(value is not None for value in (self.body, self.definition, self.scope,
                    self.result, self.result_world)) or self.formals):
                raise ValueError('source-free callback cannot carry a source ABI')
            return
        if (self.body is None or self.definition is None or self.scope is None
                or self.scope.owner.unit != self.body.unit
                or (self.scope.template, self.scope.region) != (self.body.template, self.body.region)
                or any(port.unit != self.body.unit for port in
                    (*self.formals, *((self.result,) if self.result is not None else ()),
                        *((self.result_world,) if self.result_world is not None else ())))):
            raise ValueError('callback source ABI must retain its original body and scope')
        if self.body_kind is SourceCallbackBodyKind.EVALUATION_REQUEST and (
                self.suspending or len(self.formals) != 3
                or self.result is None or self.result_world is None):
            raise ValueError('evaluation-request callback needs its three inputs and two return ports')


@dataclass(frozen=True, slots=True)
class SourceCallbackObservation:
    callback: ProviderID
    source_observation: ProviderID
    invocation: InvocationKey
    entry: CallRecordAnchor
    exit: CallRecordAnchor | None
    code_capture: CallRecordAnchor
