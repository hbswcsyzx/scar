"""Selected callee-environment cell handles, never captured contents."""
from dataclasses import dataclass

from . import source_bindings as B, source_productions as P
from .dependencies import DependencyFrame
from .normal_targets import GlobalPort, Body
from .providers import ProviderArtifact, ProviderFactReference
from .source_state import BindingLocationTemplate


@dataclass(frozen=True, slots=True)
class CaptureRelaySelection:
    """Exactly one original C2 relay or sealed derived transport row."""
    reference: P.CaptureReference
    relay: B.ForwardHop | None
    transport: P.CaptureTransport | None


@dataclass(frozen=True, slots=True)
class FunctionCaptureBinding:
    function_fact: ProviderFactReference
    call: ProviderFactReference
    reference: ProviderFactReference
    function: GlobalPort
    body: Body
    frame: DependencyFrame
    environment: GlobalPort
    environment_source: GlobalPort
    capture: int
    relay: P.CaptureReference
    path: tuple[CaptureRelaySelection, ...]
    binding: int
    # Original C2 source-scope owner, not a CodeScopeRef ordinal or invocation.
    owner: int
    key: str
    location: BindingLocationTemplate
    materials: tuple[ProviderArtifact, ...]
    conditions: tuple[str, ...]
    semantics: str = 'CONDITIONAL_CALLEE_ENVIRONMENT_CELL_HANDLE_NOT_CREATOR_FRAME_ALIAS_OR_CONTENT_READ'
