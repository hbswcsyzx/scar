"""Sparse value/name/call facts referencing the existing normal graph ports."""
from dataclasses import dataclass
from enum import Enum

from . import source_productions as P
from .normal_graph import Port
from .source_template_links import SourceTemplateKey
from scar.ir.literals import PythonLiteral


class NamespaceKind(str, Enum):
    LEXICAL = 'LEXICAL'
    MODULE = 'MODULE'
    CLASS = 'CLASS'
    BUILTINS = 'BUILTINS'


@dataclass(frozen=True, slots=True)
class Namespace:
    kind: NamespaceKind
    owner: int
    name: str


@dataclass(frozen=True, slots=True)
class NameAccess:
    namespace: Namespace
    value: int
    write: bool


@dataclass(frozen=True, slots=True)
class Function:
    value: int
    template: SourceTemplateKey
    body: P.ProductionRegionID
    environment: P.DeferredEnvironment
    parameter_names: tuple[str, ...]
    formals: tuple[int, ...]
    defaults: tuple[int | None, ...]
    returns: int | None
    return_world: int | None


@dataclass(frozen=True, slots=True)
class Class:
    value: int
    template: SourceTemplateKey
    scope: int
    body: P.ProductionRegionID
    bases: tuple[int, ...]
    bases_pack: int | None = None


@dataclass(frozen=True, slots=True)
class Attribute:
    receiver: int
    name: str
    value: int
    write: bool


@dataclass(frozen=True, slots=True)
class Import:
    value: int
    module: str


@dataclass(frozen=True, slots=True)
class Constant:
    value: int
    literal: PythonLiteral


class ContainerKind(str, Enum):
    MAPPING = 'MAPPING'
    SEQUENCE = 'SEQUENCE'
    SET = 'SET'


@dataclass(frozen=True, slots=True)
class Container:
    value: int
    kind: ContainerKind
    elements: tuple[int, ...] = ()
    pairs: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True, slots=True)
class ItemAccess:
    receiver: int
    key: int | PythonLiteral
    value: int
    write: bool
    world: int
    result_world: int


@dataclass(frozen=True, slots=True)
class ContainerUpdate:
    target: int
    source: int
    append: bool


@dataclass(frozen=True, slots=True)
class Iteration:
    source: int
    value: int
    advance: bool


@dataclass(frozen=True, slots=True)
class Call:
    callee: int
    positional: tuple[int, ...]
    keywords: tuple[tuple[str, int], ...]
    result: int
    world: int
    result_world: int
    positional_pack: int | None = None
    keyword_pack: int | None = None


@dataclass(frozen=True, slots=True)
class UnitFacts:
    unit: str
    module: str
    ports: tuple[Port, ...]
    aliases: tuple[tuple[int, int], ...]
    names: tuple[NameAccess, ...]
    functions: tuple[Function, ...]
    classes: tuple[Class, ...]
    attributes: tuple[Attribute, ...]
    imports: tuple[Import, ...]
    constants: tuple[Constant, ...]
    calls: tuple[Call, ...]
    containers: tuple[Container, ...] = ()
    items: tuple[ItemAccess, ...] = ()
    updates: tuple[ContainerUpdate, ...] = ()
    iterations: tuple[Iteration, ...] = ()
