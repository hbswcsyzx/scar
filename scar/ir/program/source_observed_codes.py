"""Observed code templates corresponding to declared source code scopes."""
from dataclasses import dataclass
from enum import Enum
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


class ObservedSourceScopeKind(str, Enum):
    CODE_ROOT = 'CODE_ROOT'
    CLASS_BODY = 'CLASS_BODY'


@dataclass(frozen=True, slots=True)
class ObservedSourceScopeLink:
    """A code region, without a Python-function value or argument binder.

    Class execution and exec/eval roots have their own namespace protocols.
    Their matching code cannot be treated as a fresh function invocation.
    """
    id: ProviderID
    kind: ObservedSourceScopeKind
    source_fact: ProviderFactReference
    body: Body
    scope: CodeScopeWitness
    captures: tuple[CodeCapture, ...]
    source: ProviderArtifact
    syntax: ProviderFactReference
    compiled_root: CapturedCode
    constant_path: tuple[int, ...]
    compile_flags: int
    frame_entries: tuple[CallRecordAnchor, ...]
    semantics: str = 'OBSERVED_CODE_TO_SCOPE_NOT_EXECUTION_NAMESPACE_OR_CREATION_IDENTITY'

    def __post_init__(self):
        if (type(self.kind) is not ObservedSourceScopeKind or not self.captures
                or self.scope.owner.unit != self.body.unit
                or (self.scope.template, self.scope.region) != (self.body.template, self.body.region)
                or type(self.constant_path) is not tuple
                or any(type(v) is not int or v < 0 for v in self.constant_path)
                or type(self.compile_flags) is not int or self.compile_flags < 0):
            raise ValueError('code-scope correspondence needs its original body, captures and compiler path')
