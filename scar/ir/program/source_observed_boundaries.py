"""Shared source CALL interfaces and separate recorded dispatch occurrences.

An interface describes original Python-side ports. It is neither a callee
body nor a native signature, constructor stage, completion or effect proof.
"""
from dataclasses import dataclass

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


@dataclass(frozen=True, slots=True)
class SourceBoundaryCallback:
    """One shared callback code/interface, not one frame per iteration.

    A suspending code does not identify its generator instance or resume
    position. Missing source-body correspondence never erases the known code.
    """
    id: ProviderID
    boundary: ProviderID
    code: CapturedCode
    suspending: bool
    body: Body | None
    definition: ProviderFactReference | None
    scope: CodeScopeWitness | None
    formals: tuple[GlobalPort, ...]
    result: GlobalPort | None
    result_world: GlobalPort | None


@dataclass(frozen=True, slots=True)
class SourceCallbackObservation:
    callback: ProviderID
    source_observation: ProviderID
    invocation: InvocationKey
    entry: CallRecordAnchor
    exit: CallRecordAnchor | None
    code_capture: CallRecordAnchor
