"""Sparse value/name/call facts referencing the existing normal graph ports."""
from dataclasses import dataclass
from enum import Enum

from . import source_productions as P
from .normal_graph import Port
from .source_template_links import SourceTemplateKey
from scar.ir.literals import PythonLiteral


@dataclass(frozen=True, slots=True)
class CodeScopeRef:
    unit: str
    ordinal: int

    def __post_init__(self):
        if type(self.unit) is not str or not self.unit or type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError('code scope needs its original unit and nonnegative source ordinal')


@dataclass(frozen=True, slots=True)
class CodeScopeWitness:
    owner: CodeScopeRef
    template: SourceTemplateKey
    region: P.ProductionRegionID
    source_scope: int


class FactTable(str, Enum):
    ALIASES='aliases'
    NAMES='names'
    FUNCTIONS='functions'
    CLASSES='classes'
    ATTRIBUTES='attributes'
    IMPORTS='imports'
    CONSTANTS='constants'
    CALLS='calls'
    CONTAINERS='containers'
    ITEMS='items'
    UPDATES='updates'
    ITERATIONS='iterations'
    OPERATIONS='operations'
    ACTIVATIONS='activations'


@dataclass(frozen=True, slots=True)
class FactRange:
    table: FactTable
    start: int
    stop: int

    def __post_init__(self):
        if type(self.table) is not FactTable or type(self.start) is not int or type(self.stop) is not int or not 0 <= self.start <= self.stop:
            raise ValueError('fact range needs a typed table and nonnegative half-open bounds')


@dataclass(frozen=True, slots=True)
class FactScopeGroup:
    owner: CodeScopeRef
    tables: tuple[FactRange, ...]


@dataclass(frozen=True, slots=True)
class ScopeActivation:
    source: CodeScopeRef
    target: CodeScopeWitness
    kind: P.CompilationEdgeKind
    step: P.ProductionStepID
    path: tuple[P.CompilationPathPart, ...]


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
    body_scope: CodeScopeWitness | None = None


@dataclass(frozen=True, slots=True)
class Class:
    value: int
    template: SourceTemplateKey
    scope: int
    body: P.ProductionRegionID
    bases: tuple[int, ...]
    bases_pack: int | None = None
    body_scope: CodeScopeWitness | None = None


class AttributeAction(str,Enum):
    GET='GET'
    SET='SET'
    DELETE='DELETE'
    IMPORT_MEMBER='IMPORT_MEMBER'


@dataclass(frozen=True, slots=True)
class Attribute:
    receiver: int
    name: str
    value: int | None
    action: AttributeAction
    world: int
    result_world: int

    def __post_init__(self):
        if type(self.action) is not AttributeAction:raise ValueError('attribute action needs an exact kind')
        if (self.value is None)!=(self.action is AttributeAction.DELETE):raise ValueError('only attribute DELETE has no value port')


@dataclass(frozen=True, slots=True)
class Import:
    value: int
    module: str
    requested_module: str | None = None


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


class LanguageOperationKind(str, Enum):
    UNARY = 'UNARY'
    BINARY = 'BINARY'
    INPLACE_BINARY = 'INPLACE_BINARY'
    COMPARE = 'COMPARE'


class OperatorSelector(str, Enum):
    ADD = 'Add'
    SUB = 'Sub'
    MULT = 'Mult'
    MAT_MULT = 'MatMult'
    DIV = 'Div'
    FLOOR_DIV = 'FloorDiv'
    MOD = 'Mod'
    POW = 'Pow'
    L_SHIFT = 'LShift'
    R_SHIFT = 'RShift'
    BIT_OR = 'BitOr'
    BIT_XOR = 'BitXor'
    BIT_AND = 'BitAnd'
    U_ADD = 'UAdd'
    U_SUB = 'USub'
    INVERT = 'Invert'
    NOT = 'Not'
    EQ = 'Eq'
    NOT_EQ = 'NotEq'
    LT = 'Lt'
    LT_E = 'LtE'
    GT = 'Gt'
    GT_E = 'GtE'
    IS = 'Is'
    IS_NOT = 'IsNot'
    IN = 'In'
    NOT_IN = 'NotIn'


@dataclass(frozen=True, slots=True)
class LanguageOperation:
    action: LanguageOperationKind
    selector: OperatorSelector
    operands: tuple[int, ...]
    result: int
    world: int
    result_world: int


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
    operations: tuple[LanguageOperation, ...] = ()
    root_scope: CodeScopeWitness | None = None
    scope_groups: tuple[FactScopeGroup, ...] = ()
    activations: tuple[ScopeActivation, ...] = ()
