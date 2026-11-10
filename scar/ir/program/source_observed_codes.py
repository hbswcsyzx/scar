"""Observed code templates corresponding to original source function bodies."""
from dataclasses import dataclass
from .ids import ProviderID
from .providers import ProviderArtifact, ProviderFactReference
from .normal_targets import GlobalPort, Body
from .normal_links import CodeScopeWitness
from .call_edges import CodeCapture, CapturedCode, CallRecordAnchor
from .python_call_targets import PythonCallTarget, PythonEntryBinding


@dataclass(frozen=True, slots=True)
class ObservedSourceCodeLink:
    id: ProviderID
    function_fact: ProviderFactReference
    function: GlobalPort
    body: Body
    scope: CodeScopeWitness
    captures: tuple[CodeCapture, ...]
    targets: tuple[tuple[CallRecordAnchor, PythonCallTarget], ...]
    entries: tuple[tuple[CallRecordAnchor, PythonEntryBinding], ...]
    source: ProviderArtifact
    syntax: ProviderFactReference
    compiled_root: CapturedCode
    constant_path: tuple[int, ...]
    compile_flags: int
    semantics: str = 'OBSERVED_CODE_TO_DECLARED_BODY_NOT_CREATOR_GLOBALS_OR_CALLSITE_SELECTION'
