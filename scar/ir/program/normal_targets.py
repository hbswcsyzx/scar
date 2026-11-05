"""Conditional source-call connections; no runtime dispatch is asserted."""
from dataclasses import dataclass
from enum import Enum

from .normal_graph import Port
from .source_template_links import SourceTemplateKey
from .source_productions import ProductionRegionID
from scar.ir.literals import PythonLiteral
from .normal_links import LanguageOperationKind,OperatorSelector,AttributeAction


@dataclass(frozen=True, slots=True)
class GlobalPort:
    unit: str
    port: Port


class ConstructionPortKind(str, Enum):
    NEW_RESULT = 'NEW_RESULT'
    NEW_WORLD = 'NEW_WORLD'


@dataclass(frozen=True, slots=True)
class ConstructionPort:
    """A language-protocol interface, never an invented source-production port.

    Both anchors reference original source ports. The role separates the
    result of allocation from the state after allocation and before init.
    """
    call: GlobalPort
    source_class: GlobalPort
    role: ConstructionPortKind

    @property
    def unit(self):
        return self.call.unit


Endpoint = GlobalPort | ConstructionPort


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
    CONDITIONAL_DEFAULT = 'CONDITIONAL_DEFAULT'
    PACK_POSITIONALS = 'PACK_POSITIONALS'
    PACK_KEYWORDS = 'PACK_KEYWORDS'
    FUNCTION_ENVIRONMENT = 'FUNCTION_ENVIRONMENT'
    CLASS_RECEIVER = 'CLASS_RECEIVER'
    STATE = 'STATE'


@dataclass(frozen=True, slots=True)
class Route:
    formal: GlobalPort
    kind: RouteKind
    actuals: tuple[Endpoint, ...]
    keyword_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ArgumentPacks:
    """Original pack objects; inference status is recorded on the connection.

    A receiver is prepended by method binding, never included in the pack.
    These are dependencies, not aliases between a pack and each parameter.
    """
    positional: GlobalPort | None
    keywords: GlobalPort | None = None
    receiver: Endpoint | None = None
    class_receiver: GlobalPort | None = None


class FunctionActivation(str,Enum):
    NORMAL='NORMAL'
    CREATE_DEFERRED_BODY='CREATE_DEFERRED_BODY'
    RESUME_BODY='RESUME_BODY'


class ArgumentBinding(str, Enum):
    NOT_MODELED = 'NOT_MODELED'
    DIRECT = 'DIRECT'
    CLOSED_PACK = 'CLOSED_PACK'
    SYMBOLIC_PACK = 'SYMBOLIC_PACK'


class ProjectionKind(str, Enum):
    POSITIONAL_ITEM = 'POSITIONAL_ITEM'
    KEYWORD_ITEM = 'KEYWORD_ITEM'
    POSITIONAL_TAIL = 'POSITIONAL_TAIL'
    KEYWORD_REMAINDER = 'KEYWORD_REMAINDER'


@dataclass(frozen=True, slots=True)
class ArgumentProjection:
    """Conditional content selection; the pack object is not the parameter.

    Shape/arity/key presence may remain unknown. Edges apply only where the
    original call's signature accepts its arguments and this source is selected.
    """
    formal: GlobalPort
    pack: GlobalPort
    kind: ProjectionKind
    index: int | None = None
    name: str | None = None
    excluded_names: tuple[str, ...] = ()
    conditions: tuple[str, ...] = ()

    def __post_init__(self):
        positional = self.kind in (ProjectionKind.POSITIONAL_ITEM, ProjectionKind.POSITIONAL_TAIL)
        if positional != (self.index is not None):
            raise ValueError('positional projection needs its original pack index')
        if self.index is not None and (type(self.index) is not int or self.index < 0):
            raise ValueError('projection index must be nonnegative')
        if (self.kind is ProjectionKind.KEYWORD_ITEM) != (self.name is not None):
            raise ValueError('keyword projection needs its parameter name')
        if self.excluded_names and self.kind is not ProjectionKind.KEYWORD_REMAINDER:
            raise ValueError('only keyword remainder excludes consumed names')


@dataclass(frozen=True,slots=True)
class FunctionConnection:
    """Conditional entry/exit wiring independent of the source operation kind."""
    source_callable: GlobalPort
    body: Body
    activation: FunctionActivation
    parameters: tuple[Route,...]
    returns: tuple[tuple[Endpoint,Endpoint],...]
    conditions: tuple[str,...]
    argument_packs: ArgumentPacks | None=None
    projections: tuple[ArgumentProjection, ...] = ()
    binding: ArgumentBinding = ArgumentBinding.DIRECT


class AttributeOrigin(str,Enum):
    ATTRIBUTE='ATTRIBUTE'
    IMPORT_MEMBER='IMPORT_MEMBER'
    BUILTIN_GETATTR='BUILTIN_GETATTR'


@dataclass(frozen=True,slots=True)
class AttributeSite:
    origin: AttributeOrigin
    action: AttributeAction
    receiver: GlobalPort
    member: str
    result: GlobalPort | None
    assigned: GlobalPort | None
    world: GlobalPort
    result_world: GlobalPort
    dynamic_member: GlobalPort | None=None


@dataclass(frozen=True,slots=True)
class PropertyAccess:
    site: AttributeSite
    descriptor: GlobalPort
    receiver_class: GlobalPort
    accessor: GlobalPort | None
    connection: FunctionConnection | None
    conditions: tuple[str,...]
    state: 'PropertyAccessState'


class PropertyAccessState(str,Enum):
    CONNECTED='CONNECTED'
    ACCESSOR_ABSENT='ACCESSOR_ABSENT'
    ACCESSOR_NOT_CALLABLE='ACCESSOR_NOT_CALLABLE'
    ACCESSOR_TARGET_OPEN='ACCESSOR_TARGET_OPEN'
    ACCESSOR_ARGUMENT_PACK_OPEN='ACCESSOR_ARGUMENT_PACK_OPEN'
    SIGNATURE_INAPPLICABLE='SIGNATURE_INAPPLICABLE'


class AttributeStorageKind(str,Enum):
    INSTANCE_FIELDS='INSTANCE_FIELDS'
    CLASS_NAMESPACE='CLASS_NAMESPACE'
    MODULE_NAMESPACE='MODULE_NAMESPACE'


@dataclass(frozen=True,slots=True)
class AttributeStorageAccess:
    site: AttributeSite
    kind: AttributeStorageKind
    owner: Endpoint
    namespace_unit: str | None
    conditions: tuple[str,...]


@dataclass(frozen=True, slots=True)
class CallLink:
    result: GlobalPort
    callee: GlobalPort
    source_callable: GlobalPort | None
    body: Body | None
    mode: str
    external_symbol: str | None
    parameters: tuple[Route, ...] = ()
    returns: tuple[tuple[Endpoint, Endpoint], ...] = ()
    conditions: tuple[str, ...] = ('SOURCE_STATIC_CANDIDATE', 'CURRENT_CALLABLE_DESCRIPTOR')
    runtime_dispatch_verified: bool = False
    argument_packs: ArgumentPacks | None = None
    projections: tuple[ArgumentProjection, ...] = ()
    binding: ArgumentBinding = ArgumentBinding.NOT_MODELED


@dataclass(frozen=True, slots=True)
class ContentLink:
    """Possible reference content, never a concrete content version proof."""
    source: Endpoint
    target: Endpoint
    container: Endpoint
    key: PythonLiteral | None = None
    semantics: str = 'FLOW_INSENSITIVE_MAY_CONTENT'


class ConstructionStage(str, Enum):
    NEW_LOOKUP_PENDING = 'NEW_LOOKUP_PENDING'
    SOURCE_NEW = 'SOURCE_NEW'
    OBJECT_NEW = 'OBJECT_NEW'
    EXPLICIT_OBJECT_NEW = 'EXPLICIT_OBJECT_NEW'
    INIT_LOOKUP_PENDING = 'INIT_LOOKUP_PENDING'
    SOURCE_INIT = 'SOURCE_INIT'
    OBJECT_INIT = 'OBJECT_INIT'
    RETURN_FOREIGN = 'RETURN_FOREIGN'
    RESULT_TYPE_OPEN = 'RESULT_TYPE_OPEN'


@dataclass(frozen=True, slots=True)
class ConstructionLink:
    """One conditional step of a class call or explicit object allocation.

    Outputs declare interfaces even when the target is still pending; they
    do not prove that an allocation/initialization occurred or produced data.
    """
    result: GlobalPort
    callee: GlobalPort
    source_class: GlobalPort
    stage: ConstructionStage
    inputs: tuple[Endpoint, ...]
    outputs: tuple[Endpoint, ...]
    connection: FunctionConnection | None
    conditions: tuple[str, ...]
