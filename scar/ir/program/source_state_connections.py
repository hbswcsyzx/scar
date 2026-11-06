"""Join declared state projections to admitted source-call interfaces."""
from dataclasses import dataclass

from .normal_targets import CallLink,Route,Endpoint
from .providers import ProviderFactReference


@dataclass(frozen=True,slots=True)
class SourceStateConnection:
    projection: ProviderFactReference
    call: ProviderFactReference
    connection: CallLink
    content_argument: Route
    state_argument: Route
    data_return: tuple[Endpoint,Endpoint]
    state_return: tuple[Endpoint,Endpoint]
    caller_activation: ProviderFactReference | None
    body_activation: ProviderFactReference | None
    aliases: tuple[ProviderFactReference,...]
    conditions: tuple[str,...]
    semantics: str = 'ADMITTED_CONDITIONAL_INTERFACE_NOT_CURRENT_CONTENT_OR_RUNTIME_DISPATCH'


@dataclass(frozen=True,slots=True)
class SourceStateConnectionObligation:
    projection: int
    code: str
    detail: str
