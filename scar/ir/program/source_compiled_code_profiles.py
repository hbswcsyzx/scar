"""Receipt-bound compiler inputs; matching a root never selects an exec branch."""
from dataclasses import dataclass

from .call_edges import CapturedCode, CodeCapture
from .normal_links import CodeScopeWitness
from .providers import ProviderFactReference
from .source_compiled_values import CompiledSourceCandidate
from .source_execution import SourceBuiltinInvocation, SourceCompilationRequest
from .source_exec_roots import ExecRootConnection
from .source_references import SourceArtifactLocator
from .source_text import SourceTextCandidate


@dataclass(frozen=True, slots=True)
class CompiledExecAlternative:
    evidence: ProviderFactReference
    connection: ExecRootConnection


@dataclass(frozen=True, slots=True)
class CompiledCodeProfile:
    unit: str
    original_source_unit: str
    root_scope: CodeScopeWitness
    root_fact: ProviderFactReference
    candidate_fact: ProviderFactReference
    candidate: CompiledSourceCandidate
    request_fact: ProviderFactReference
    request: SourceCompilationRequest
    compile_boundary_fact: ProviderFactReference
    compile_boundary: SourceBuiltinInvocation
    compile_call: ProviderFactReference
    text_fact: ProviderFactReference
    text: SourceTextCandidate
    context_fact: ProviderFactReference
    syntax: SourceArtifactLocator
    compiled_root: CapturedCode
    branches: tuple[CompiledExecAlternative, ...]


@dataclass(frozen=True, slots=True)
class CompiledRootCodeMatch:
    profile: int
    capture: CodeCapture
    conditions: tuple[str, ...] = (
        'OBSERVED_CODE_EQUALS_RECORDED_COMPILER_PROFILE_ROOT_TEMPLATE',
        'EXEC_BRANCH_AND_NAMESPACE_SELECTION_NOT_ESTABLISHED_BY_CODE_MATCH',
        'CALLER_CREATOR_AND_CELL_CONTENT_IDENTITIES_NOT_ESTABLISHED',
    )
