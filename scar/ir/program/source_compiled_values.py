"""Compiler inputs and code-value candidates, distinct from source bodies."""
from dataclasses import dataclass

from . import normal_links as F, normal_targets as T
from .source_bytes import SourceBytesProfile
from .source_references import SourceArtifactLocator
from .python_bindings import SourceCallSite


@dataclass(frozen=True, slots=True)
class CompileFilenameCandidate:
    compile_result: T.GlobalPort
    filename: str
    source: T.GlobalPort
    path_source: T.GlobalPort | None = None
    conversion: SourceCallSite | None = None
    conditions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EffectiveCompileContext:
    filename: str
    mode: str
    requested_flags: int
    caller_dont_inherit: bool
    inherited_future_flags: int
    compiler_input_flags: int
    compiled_future_flags: int
    compiled_code_flags: int
    optimize: int
    runtime: SourceBytesProfile
    lowering: str = 'EXPLICIT_RECORDED_FLAGS_DONT_INHERIT_TRUE'


@dataclass(frozen=True, slots=True)
class CompiledSourceCandidate:
    id: str
    compile_result: T.GlobalPort
    read_result: T.GlobalPort
    builtin_boundary_ordinal: int
    text_candidate_ordinal: int
    source_unit: str
    source: SourceArtifactLocator
    text_utf8_sha256: str
    context: EffectiveCompileContext
    code_digest: str
    captured_root_reference: F.CodeScopeWitness | None
    source_only_control_digest: str | None
    code_matches_source_only_control: bool | None
    conditions: tuple[str, ...]
    obligations: tuple[str, ...]
    matched_body: T.Body | None = None
    semantics: str = 'CONDITIONAL_COMPILED_CODE_VALUES_NOT_OBJECT_IDENTITY_OR_F4_BODY'


@dataclass(frozen=True, slots=True)
class SourceCompileObligation:
    port: T.GlobalPort
    reason: str


@dataclass(frozen=True, slots=True)
class CompiledSourceOverlay:
    unit: str
    filenames: tuple[CompileFilenameCandidate, ...]
    candidates: tuple[CompiledSourceCandidate, ...]
    obligations: tuple[SourceCompileObligation, ...]
