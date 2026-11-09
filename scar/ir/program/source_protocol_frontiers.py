"""Original unresolved target fields, attached to existing program nodes."""
from dataclasses import dataclass

from .declared_contexts import DeclaredContext
from .providers import ProviderFactReference
from .source_value_flow import SourceBodyCall


@dataclass(frozen=True, slots=True)
class ProtocolCallFrontier:
    ordinal: int
    context: DeclaredContext
    call: SourceBodyCall | None
    evidence: ProviderFactReference
    reason: str
