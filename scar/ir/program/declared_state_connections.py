"""Conditional state projections through shared declared body interfaces."""
from dataclasses import dataclass

from .normal_targets import Endpoint, FunctionConnection, Route
from .providers import ProviderFactReference


SEMANTICS = 'GUARDED_DECLARED_STATE_INTERFACE_NOT_CURRENT_CONTENT_OR_SCOPE_ADMISSION'


@dataclass(frozen=True, slots=True)
class DeclaredStateConnection:
    projection: ProviderFactReference
    edge: ProviderFactReference
    connection: FunctionConnection
    content_route: Route
    state_route: Route
    data_return: tuple[Endpoint, Endpoint]
    state_return: tuple[Endpoint, Endpoint]
    conditions: tuple[str, ...]
    semantics: str = SEMANTICS


@dataclass(frozen=True, slots=True)
class DeclaredStateObligation:
    projection: int
    code: str
    detail: str
