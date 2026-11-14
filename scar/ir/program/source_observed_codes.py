"""Observed code templates corresponding to declared source code scopes."""
from dataclasses import dataclass
from enum import Enum
from .ids import ProviderID
from .providers import ProviderArtifact, ProviderFactReference
from .normal_targets import GlobalPort, Body
from .normal_links import CodeScopeWitness
from .call_edges import CodeCapture, CapturedCode, CallRecordAnchor
from .python_call_targets import PythonCallTarget, PythonEntryBinding
from .source_productions import EvaluationRequestEnvironment, ProductionStepID


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


class ObservedSourceRequestKind(str, Enum):
    FUNCTION_ANNOTATIONS = 'FUNCTION_ANNOTATIONS'
    CLASS_ANNOTATIONS = 'CLASS_ANNOTATIONS'
    MODULE_ANNOTATIONS = 'MODULE_ANNOTATIONS'


@dataclass(frozen=True, slots=True)
class ObservedSourceRequestCodeLink:
    """Code correspondence to a sealed request region, without a function fact.

    Declaration evidence addresses an original recipe, never a Fact table.
    Native ``format`` and creator/globals/cell bindings remain conditional.
    """
    id: ProviderID
    kind: ObservedSourceRequestKind
    declaration: ProviderFactReference
    declaration_step: ProductionStepID
    plan_sha256: str
    callable: GlobalPort
    body: Body
    scope: CodeScopeWitness
    environment: EvaluationRequestEnvironment
    captures: tuple[CodeCapture, ...]
    source: ProviderArtifact
    syntax: ProviderFactReference
    compiled_root: CapturedCode
    constant_path: tuple[int, ...]
    creator_constant_path: tuple[int, ...]
    load_offset: int
    make_offset: int
    installation_offset: int
    compile_flags: int
    frame_entries: tuple[CallRecordAnchor, ...]
    semantics: str = 'OBSERVED_CODE_TO_DEFERRED_REQUEST_NOT_FORMAT_CREATOR_OR_ENVIRONMENT_BINDING'

    def __post_init__(self):
        if (type(self.kind) is not ObservedSourceRequestKind or not self.captures
                or self.scope.owner.unit != self.body.unit or self.callable.unit != self.body.unit
                or (self.scope.template, self.scope.region) != (self.body.template, self.body.region)
                or self.environment.scope != self.scope.source_scope
                or len(self.plan_sha256) != 64 or any(c not in '0123456789abcdef' for c in self.plan_sha256)
                or any(type(path) is not tuple or any(type(v) is not int or v < 0 for v in path)
                    for path in (self.constant_path, self.creator_constant_path))
                or not self.constant_path or self.constant_path[:-1] != self.creator_constant_path
                or any(type(v) is not int or v < 0 for v in
                    (self.load_offset, self.make_offset, self.installation_offset, self.compile_flags))
                or not self.load_offset < self.make_offset < self.installation_offset):
            raise ValueError('request correspondence needs its sealed declaration/body and exact compiler creation')


ObservedSourceBodyLink = (ObservedSourceCodeLink | ObservedSourceScopeLink | ObservedSourceRequestCodeLink)
