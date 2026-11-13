"""Shared source CALL interfaces and separate recorded dispatch occurrences.

An interface describes original Python-side ports. It is neither a callee
body nor a native signature, constructor stage, completion or effect proof.
"""
from dataclasses import dataclass

from scar.ir.effects import Knowledge
from .ids import ProviderID
from .normal_links import CodeScopeWitness
from .normal_targets import GlobalPort
from .providers import ProviderFactReference
from .call_edges import CallRecordAnchor
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
class SourceBoundaryObservation:
    boundary: ProviderID
    source_observation: ProviderID
    attempt: CallRecordAnchor
    target: PythonCallTarget
    target_anchor: CallRecordAnchor
    profile_alternatives: tuple[ProviderFactReference, ...]
    native: NativeCallableFact | None = None
    native_anchor: CallRecordAnchor | None = None
