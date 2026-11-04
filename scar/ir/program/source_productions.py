"""Finite structured recipe vocabulary targeting the existing program IR.

A recipe is a source-bound plan, not a second executable program or a proof
of Python semantics. References to syntax, source namespace ports and planned
values stay separate. CFG/SSA emission belongs to the later lowering layer.
"""
from dataclasses import dataclass
from enum import Enum

from scar.ir.program.control import LanguageCompletionKind
from scar.ir.program.source_contexts import ContextState
from scar.ir.program.source_roles import SlotRef
from scar.ir.program.signature_patterns import (GroundType, Bindings, CountBinding,
    ChoiceBinding, TypeBinding, TypesBinding)
from scar.ir.program.structured import PythonProtocolKind
from scar.ir.program.protocol_signatures import ExceptionABI
from scar.ir.literals import PythonLiteral
from scar.ir.v2.ids import Identifier


class ProductionRegionID(Identifier):
    prefix = 'source_production_region'


class ProductionStepID(Identifier):
    prefix = 'source_production_step'


class ProductionPurpose(str, Enum):
    VALUE = 'VALUE'
    STATEMENT = 'STATEMENT'
    STORE = 'STORE'
    DELETE = 'DELETE'
    ADDRESS = 'ADDRESS'
    PATTERN = 'PATTERN'
    DESCRIPTOR = 'DESCRIPTOR'
    GRAMMAR = 'GRAMMAR'


class ProductionRegionKind(str, Enum):
    EXECUTION = 'EXECUTION'
    DEFERRED = 'DEFERRED'
    ALTERNATIVE = 'ALTERNATIVE'
    LOOP = 'LOOP'
    LOOP_CONDITION = 'LOOP_CONDITION'
    LOOP_BODY = 'LOOP_BODY'
    HANDLER = 'HANDLER'
    CLEANUP = 'CLEANUP'
    RESUME = 'RESUME'
    TARGET = 'TARGET'
    PATTERN = 'PATTERN'
    COMPREHENSION = 'COMPREHENSION'


class ProductionDispositionKind(str, Enum):
    EVALUATED_CHILD = 'EVALUATED_CHILD'
    TARGET_ADDRESS = 'TARGET_ADDRESS'
    ROLE_PORT = 'ROLE_PORT'
    DEFERRED_CHILD = 'DEFERRED_CHILD'
    MARKER = 'MARKER'
    METADATA = 'METADATA'
    SUPPRESSED = 'SUPPRESSED'


class LanguageActionKind(str, Enum):
    UNARY = 'UNARY'
    BINARY = 'BINARY'
    COMPARE = 'COMPARE'
    CALL = 'CALL'
    ATTRIBUTE_GET = 'ATTRIBUTE_GET'
    ATTRIBUTE_SET = 'ATTRIBUTE_SET'
    ATTRIBUTE_DELETE = 'ATTRIBUTE_DELETE'
    ITEM_GET = 'ITEM_GET'
    ITEM_SET = 'ITEM_SET'
    ITEM_DELETE = 'ITEM_DELETE'
    TRUTH = 'TRUTH'
    ITERATOR = 'ITERATOR'
    NEXT = 'NEXT'
    IMPORT = 'IMPORT'
    UNPACK = 'UNPACK'
    FORMAT = 'FORMAT'
    TYPE_TEST = 'TYPE_TEST'
    EXCEPTION_NORMALIZE = 'EXCEPTION_NORMALIZE'
    MATCH_PROTOCOL = 'MATCH_PROTOCOL'
    WITH_ENTER = 'WITH_ENTER'
    WITH_EXIT = 'WITH_EXIT'
    AWAIT_PROTOCOL = 'AWAIT_PROTOCOL'
    TARGET_READ = 'TARGET_READ'
    TARGET_WRITE = 'TARGET_WRITE'
    TARGET_DELETE = 'TARGET_DELETE'
    SET_INSERT = 'SET_INSERT'
    SET_UPDATE = 'SET_UPDATE'
    UNPACK_EXTENDED = 'UNPACK_EXTENDED'
    STRING_JOIN = 'STRING_JOIN'


class BindingActionKind(str, Enum):
    READ = 'READ'
    WRITE = 'WRITE'
    DELETE = 'DELETE'


class ConstructionKind(str, Enum):
    LITERAL = 'LITERAL'
    CONTAINER = 'CONTAINER'
    SLICE = 'SLICE'
    FUNCTION = 'FUNCTION'
    CLASS = 'CLASS'
    TYPE_ALIAS = 'TYPE_ALIAS'
    FORMATTED_STRING = 'FORMATTED_STRING'
    TEMPLATE_STRING = 'TEMPLATE_STRING'
    EXCEPTION = 'EXCEPTION'
    CONTROL_PACKET = 'CONTROL_PACKET'
    TUPLE = 'TUPLE'
    INTERPOLATION = 'INTERPOLATION'


class SuspensionKind(str, Enum):
    YIELD = 'YIELD'
    ASYNC_YIELD = 'ASYNC_YIELD'
    YIELD_FROM = 'YIELD_FROM'
    AWAIT = 'AWAIT'


class DelegationProtocolKind(str, Enum):
    YIELD_FROM_ITER = 'YIELD_FROM_ITER'
    AWAITABLE_ITER = 'AWAITABLE_ITER'
    SEND = 'SEND'
    STOP_ITERATION_VALUE = 'STOP_ITERATION_VALUE'
    GET_ASYNC_ITERATOR = 'GET_ASYNC_ITERATOR'
    GET_ASYNC_NEXT = 'GET_ASYNC_NEXT'
    MATCH_STOP_ASYNC_ITERATION = 'MATCH_STOP_ASYNC_ITERATION'


class DeferredBodyKind(str, Enum):
    FUNCTION = 'FUNCTION'
    GENERATOR = 'GENERATOR'
    COROUTINE = 'COROUTINE'
    ASYNC_GENERATOR = 'ASYNC_GENERATOR'


class DeferredParameterKind(str, Enum):
    POSITIONAL_ONLY = 'POSITIONAL_ONLY'
    POSITIONAL_OR_KEYWORD = 'POSITIONAL_OR_KEYWORD'
    VAR_POSITIONAL = 'VAR_POSITIONAL'
    KEYWORD_ONLY = 'KEYWORD_ONLY'
    VAR_KEYWORD = 'VAR_KEYWORD'
    INITIAL_ITERATOR = 'INITIAL_ITERATOR'


@dataclass(frozen=True, slots=True)
class ProductionInput:
    path: str
    namespace_root: str
    f2_sha256: str
    roles_sha256: str
    contexts_sha256: str
    declarations_sha256: str
    bindings_sha256: str


@dataclass(frozen=True, slots=True)
class ProductionOccurrence:
    occurrence: int


ProductionSource = ProductionOccurrence | SlotRef


@dataclass(frozen=True, slots=True)
class ProductionCompletion:
    kind: LanguageCompletionKind
    types: tuple[GroundType, ...]
    target: ProductionRegionID | None = None


@dataclass(frozen=True, slots=True)
class ProductionParameter:
    region: ProductionRegionID
    index: int


@dataclass(frozen=True, slots=True)
class ProductionResult:
    """A FALLTHROUGH result; exceptional values enter handler parameters."""
    step: ProductionStepID
    index: int


ProductionValue = ProductionParameter | ProductionResult


@dataclass(frozen=True, slots=True)
class ProductionRegionCall:
    region: ProductionRegionID
    arguments: tuple[ProductionValue, ...]


@dataclass(frozen=True, slots=True)
class EvaluateChild:
    field: SlotRef
    purpose: ProductionPurpose


@dataclass(frozen=True, slots=True)
class ApplyLanguageAction:
    action: LanguageActionKind
    selectors: tuple[SlotRef, ...] = ()


@dataclass(frozen=True, slots=True)
class ApplyPythonProtocol:
    """Reuse the existing protocol/signature domain with explicit bindings."""
    protocol: PythonProtocolKind
    bindings: Bindings
    selectors: tuple[SlotRef, ...] = ()


@dataclass(frozen=True, slots=True)
class ApplyDelegationProtocol:
    """A declared compiler/runtime boundary; not an expanded native call graph."""
    protocol: DelegationProtocolKind
    bindings: Bindings


@dataclass(frozen=True, slots=True)
class AccessBinding:
    action: BindingActionKind
    port: int


@dataclass(frozen=True, slots=True)
class ConstructValue:
    construction: ConstructionKind
    payload: tuple[SlotRef, ...] = ()


@dataclass(frozen=True, slots=True)
class DefineLiteral:
    """An exact implicit value; no object identity or allocation assertion."""
    value: PythonLiteral


@dataclass(frozen=True, slots=True)
class ApplyRegion:
    invocation: ProductionRegionCall


@dataclass(frozen=True, slots=True)
class BranchControl:
    on_true: ProductionRegionCall
    on_false: ProductionRegionCall


@dataclass(frozen=True, slots=True)
class IterationCondition:
    """Advance, classify exhaustion, then deliver the item only to the body.

    world_parameter is a carried loop port replaced by the advance's current
    world on both success and exhaustion. Other exceptions propagate unchanged.
    """
    advance: ProductionRegionCall
    exhausted: ProductionRegionID
    world_parameter: int


@dataclass(frozen=True, slots=True)
class RepeatCondition:
    """Unconditional backedge until an explicit body completion exits.

    This is control structure, not an invented evaluation of literal True.
    """


@dataclass(frozen=True, slots=True)
class LoopControl:
    """One loop template, with invariant prefix and carried suffix input ports.

    Condition/body receive both groups. Only carried values return along the
    backedge; invariants stay connected to the original loop inputs.
    """
    condition: ProductionRegionID | IterationCondition | RepeatCondition
    body: ProductionRegionID
    otherwise: ProductionRegionID | None = None
    invariant_count: int = 0


@dataclass(frozen=True, slots=True)
class DeferredParameter:
    """Source-order logical admission port, not a native frame ordinal."""
    kind: DeferredParameterKind
    source: SlotRef
    binding_port: int | None
    # Initial default's original creation-time expression; later mutation of
    # function.__defaults__/__kwdefaults__ is not ruled out by this relation.
    default_source: SlotRef | None = None


@dataclass(frozen=True, slots=True)
class DeferredEnvironment:
    scope: int
    globals_scope: int
    parameters: tuple[DeferredParameter, ...]
    # Original active C2b ForwardHop ordinals, including transitive forwarding.
    # These are cell handles, not values or a native co_freevars ordering.
    captures: tuple[int, ...]
    kind: DeferredBodyKind
    world: GroundType
    exception_abi: ExceptionABI


@dataclass(frozen=True, slots=True)
class GlobalsEnvironment:
    scope: int


@dataclass(frozen=True, slots=True)
class ClosureEnvironment:
    relay: int


@dataclass(frozen=True, slots=True)
class ReferenceEnvironment:
    """Retain a namespace/cell handle without reading the cell's contents."""
    source: GlobalsEnvironment | ClosureEnvironment


@dataclass(frozen=True, slots=True)
class EnterDeferredBody:
    """Bind an admitted environment and parameter values into a fresh activation.

    Input ports are (function environment reference, source-order parameters,
    current world). Caller argument admission and actual cell/frame layout
    are distinct obligations; no old world is captured at definition time.
    """
    environment: DeferredEnvironment


@dataclass(frozen=True, slots=True)
class DeferRegion:
    """Declare a code reference with a typed later-entry interface, no execution."""
    body: ProductionRegionID
    environment: DeferredEnvironment


@dataclass(frozen=True, slots=True)
class CleanupControl:
    protected: ProductionRegionCall
    cleanup: ProductionRegionID


@dataclass(frozen=True, slots=True)
class CompletionRoute:
    """Completion payload then explicit captures form the handler inputs."""
    kind: LanguageCompletionKind
    target: ProductionRegionID | None
    handler: ProductionRegionID
    captures: tuple[ProductionValue, ...] = ()


@dataclass(frozen=True, slots=True)
class HandleCompletions:
    protected: ProductionRegionCall
    routes: tuple[CompletionRoute, ...]


@dataclass(frozen=True, slots=True)
class TransferCompletion:
    kind: LanguageCompletionKind
    target: ProductionRegionID | None = None


@dataclass(frozen=True, slots=True)
class ProductionResumeRoute:
    """Normalized delivery, followed by the suspension's explicit saved values.

    FALLTHROUGH delivers (sent reference, current world); RAISE delivers the
    chosen exception ABI. NEXT is SEND(None); admitted close/cancellation
    delivers an exception. Driver admission/normalization is not proved here.
    """
    kind: LanguageCompletionKind
    region: ProductionRegionID


@dataclass(frozen=True, slots=True)
class SuspendExecution:
    """Export (reference, world), then eventually complete through a route.

    Current-world inputs arrive afresh at a later temporal ingress; they must
    never be saved across the handoff. Saved references preserve identities,
    not snapshots of mutable referents. Steps after this control execute only
    if a later normal resumption completes. No eventual resumption is assumed.
    """
    suspension: SuspensionKind
    exception_abi: ExceptionABI
    routes: tuple[ProductionResumeRoute, ...]
    saved: tuple[ProductionValue, ...] = ()
    # A delegated suspension is processed by its driver before a normalized
    # result/error is delivered to these routes. It is not an ordinary yield.
    delegate: ProductionValue | None = None


ProductionInstruction = (EvaluateChild | ApplyLanguageAction | ApplyPythonProtocol | ApplyDelegationProtocol | AccessBinding | ConstructValue | DefineLiteral
    | ApplyRegion | BranchControl | LoopControl | DeferRegion | ReferenceEnvironment | EnterDeferredBody | CleanupControl
    | HandleCompletions | TransferCompletion | SuspendExecution)


@dataclass(frozen=True, slots=True)
class ProductionStep:
    id: ProductionStepID
    region: ProductionRegionID
    source: ProductionSource
    instruction: ProductionInstruction
    arguments: tuple[ProductionValue, ...]
    completions: tuple[ProductionCompletion, ...]


@dataclass(frozen=True, slots=True)
class ProductionRegion:
    id: ProductionRegionID
    parent: ProductionRegionID | None
    kind: ProductionRegionKind
    source: ProductionSource
    context: ContextState
    parameters: tuple[GroundType, ...]
    completions: tuple[ProductionCompletion, ...]
    steps: tuple[ProductionStepID, ...]


@dataclass(frozen=True, slots=True)
class ProductionSlotDisposition:
    field: SlotRef
    disposition: ProductionDispositionKind


@dataclass(frozen=True, slots=True)
class SourceProductionPlan:
    input: ProductionInput
    source: ProductionSource
    purpose: ProductionPurpose
    root: ProductionRegionID
    regions: tuple[ProductionRegion, ...]
    steps: tuple[ProductionStep, ...]
    slots: tuple[ProductionSlotDisposition, ...]
    schema: str = 'scar.source-production-plan'
    schema_version: int = 5
    authority: str = 'SOURCE_RECIPE_SHAPE_ONLY'


PRODUCTION_RECORD_TAGS = {cls: ('record_kind', cls.__name__) for cls in (
    ProductionOccurrence, SlotRef, ProductionParameter, ProductionResult,
    EvaluateChild, ApplyLanguageAction, ApplyPythonProtocol, ApplyDelegationProtocol, AccessBinding, ConstructValue, DefineLiteral, ApplyRegion,
    BranchControl, LoopControl, DeferRegion, ReferenceEnvironment, EnterDeferredBody, CleanupControl, HandleCompletions,
    GlobalsEnvironment, ClosureEnvironment,
    TransferCompletion, SuspendExecution, ProductionResumeRoute, IterationCondition, RepeatCondition,
    CountBinding, ChoiceBinding, TypeBinding, TypesBinding)}
