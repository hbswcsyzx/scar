"""Conditional source-call connections; no runtime dispatch is asserted."""
from dataclasses import dataclass
from enum import Enum

from .normal_graph import Port
from .source_template_links import SourceTemplateKey
from .source_productions import ProductionRegionID


@dataclass(frozen=True, slots=True)
class GlobalPort:
    unit: str
    port: Port


@dataclass(frozen=True, slots=True)
class Body:
    unit: str
    template: SourceTemplateKey
    region: ProductionRegionID


class RouteKind(str, Enum):
    ARGUMENT = 'ARGUMENT'
    INITIAL_DEFAULT = 'INITIAL_DEFAULT'
    PACK_POSITIONALS = 'PACK_POSITIONALS'
    PACK_KEYWORDS = 'PACK_KEYWORDS'
    FUNCTION_ENVIRONMENT = 'FUNCTION_ENVIRONMENT'
    CLASS_RECEIVER = 'CLASS_RECEIVER'
    STATE = 'STATE'


@dataclass(frozen=True, slots=True)
class Route:
    formal: GlobalPort
    kind: RouteKind
    actuals: tuple[GlobalPort, ...]
    keyword_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CallLink:
    result: GlobalPort
    callee: GlobalPort
    source_callable: GlobalPort | None
    body: Body | None
    mode: str
    external_symbol: str | None
    parameters: tuple[Route, ...] = ()
    returns: tuple[tuple[GlobalPort, GlobalPort], ...] = ()
    conditions: tuple[str, ...] = ('SOURCE_STATIC_CANDIDATE', 'CURRENT_CALLABLE_DESCRIPTOR')
    runtime_dispatch_verified: bool = False
