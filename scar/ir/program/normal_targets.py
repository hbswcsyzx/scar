"""Conditional source-call connections; no runtime dispatch is asserted."""
from dataclasses import dataclass
from enum import Enum

from .normal_graph import Port
from .source_template_links import SourceTemplateKey
from .source_productions import ProductionRegionID
from scar.ir.literals import PythonLiteral
from .normal_links import LanguageOperationKind,OperatorSelector


@dataclass(frozen=True, slots=True)
class GlobalPort:
    unit: str
    port: Port


@dataclass(frozen=True, slots=True)
class LanguageOperationSite:
    action: LanguageOperationKind
    selector: OperatorSelector
    operands: tuple[GlobalPort,...]
    result: GlobalPort
    world: GlobalPort
    result_world: GlobalPort


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
class ArgumentPacks:
    """Source pack objects; their contents/arity have not been established.

    A receiver is prepended by method binding, never included in the pack.
    These are dependencies, not aliases between a pack and each parameter.
    """
    positional: GlobalPort
    keywords: GlobalPort | None = None
    receiver: GlobalPort | None = None
    class_receiver: GlobalPort | None = None


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
    argument_packs: ArgumentPacks | None = None


@dataclass(frozen=True, slots=True)
class ContentLink:
    """Possible reference content, never a concrete content version proof."""
    source: GlobalPort
    target: GlobalPort
    container: GlobalPort
    key: PythonLiteral | None = None
    semantics: str = 'FLOW_INSENSITIVE_MAY_CONTENT'
