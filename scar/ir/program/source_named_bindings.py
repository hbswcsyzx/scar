"""Full namespace requests linked to conditional generated binding interfaces."""
from dataclasses import dataclass

from .providers import ProviderFactReference
from .python_bindings import NativeCallCandidate


@dataclass(frozen=True, slots=True)
class NamedBindingMatch:
    request: ProviderFactReference
    call: ProviderFactReference
    declaration: ProviderFactReference
    symbol: str
    candidate: NativeCallCandidate


@dataclass(frozen=True, slots=True)
class NamedBindingFrontier:
    request: ProviderFactReference
    symbol: str
    reason: str
