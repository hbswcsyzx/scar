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
    CONDITION = 'CONDITION'
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
    TYPE_PARAMETERS = 'TYPE_PARAMETERS'
    SHARED = 'SHARED'


class ProductionDispositionKind(str, Enum):
    EVALUATED_CHILD = 'EVALUATED_CHILD'
    TARGET_ADDRESS = 'TARGET_ADDRESS'
    ROLE_PORT = 'ROLE_PORT'
    DEFERRED_CHILD = 'DEFERRED_CHILD'
    MARKER = 'MARKER'
    METADATA = 'METADATA'
    SUPPRESSED = 'SUPPRESSED'
    NO_NORMAL_PREDECESSOR = 'NO_NORMAL_PREDECESSOR'
    DELEGATED_VALUE_RULE = 'DELEGATED_VALUE_RULE'


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


class TypeParameterKind(str, Enum):
    TYPE_VAR = 'TYPE_VAR'
    TYPE_VAR_TUPLE = 'TYPE_VAR_TUPLE'
    PARAM_SPEC = 'PARAM_SPEC'


class ContextMethodKind(str, Enum):
    ENTER = 'ENTER'
    EXIT = 'EXIT'
    ASYNC_ENTER = 'ASYNC_ENTER'
    ASYNC_EXIT = 'ASYNC_EXIT'


class CompilationOption(str, Enum):
    ASSERTIONS_ENABLED = 'ASSERTIONS_ENABLED'


class AnnotationPublicationKind(str, Enum):
    STRINGIZED = 'STRINGIZED'
    DEFERRED = 'DEFERRED'


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
class SourceLoopTarget:
    """An original F2 loop, including one outside this local recipe.

    Composition consumes this port at that loop's shared template. It is
    neither an unresolved name nor a fabricated local ancestor region.
    """
    occurrence: int


ProductionControlTarget = ProductionRegionID | SourceLoopTarget


@dataclass(frozen=True, slots=True)
class ProductionCompletion:
    kind: LanguageCompletionKind
    types: tuple[GroundType, ...]
    target: ProductionControlTarget | None = None


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
class ReadCompilationOption:
    """A symbolic target compilation fact, not an analyzer/runtime probe."""
    option: CompilationOption


@dataclass(frozen=True, slots=True)
class ApplyInplaceOperator:
    operator: SlotRef
    exception_abi: ExceptionABI


@dataclass(frozen=True, slots=True)
class PublishAnnotation:
    """Retain a source annotation without eagerly evaluating its expression.

    A deferred entry belongs to the original C1 annotation scope. Registering
    an unconditional class annotation is compile metadata; conditional class
    and all module annotations also record that this declaration was reached.
    Stringized publication instead writes the compiled string immediately.
    These are logical publication operations, not expanded native helpers.
    """
    annotation: SlotRef
    name: SlotRef
    publication: AnnotationPublicationKind
    conditional_registration: bool
    exception_abi: ExceptionABI


@dataclass(frozen=True, slots=True)
class ImportRequest:
    """Logical IMPORT_NAME request in an original source namespace.

    Source selectors retain the compiler/private-name context. No fromlist
    means ordinary import, distinct from a tuple of imported member names.
    Namespace capabilities, importer dispatch, registry tests and module
    initialization are not falsely replaced by a pure constant lookup.
    """
    module: SlotRef
    fromlist: tuple[SlotRef, ...] | None
    level: SlotRef | None
    environment: int
    exception_abi: ExceptionABI
    requested_name: str
    from_names: tuple[str, ...] | None
    relative_level: int


@dataclass(frozen=True, slots=True)
class ImportMember:
    """IMPORT_FROM, including its import-registry fallback, not plain getattr.

    None selects a from-import member under its compiler name projection.
    A positive component selects an unmangled dotted-asname path segment.
    """
    name: SlotRef
    component: int | None
    exception_abi: ExceptionABI
    member_name: str


@dataclass(frozen=True, slots=True)
class ImportStar:
    """Dynamic namespace mutation; never invent static binders for its names."""
    specifier: SlotRef
    environment: int
    exception_abi: ExceptionABI


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
    source_loop: SourceLoopTarget | None = None


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
class FunctionAnnotationEntry:
    parameter: SlotRef | None
    name: str
    value: SlotRef


@dataclass(frozen=True, slots=True)
class FunctionAnnotationInterface:
    scope: int
    captures: tuple[int, ...]
    entries: tuple[FunctionAnnotationEntry, ...]
    stringized: bool


@dataclass(frozen=True, slots=True)
class BuildFunctionAnnotations:
    """Create the later annotation-request callable, without evaluating values."""
    annotations: FunctionAnnotationInterface
    exception_abi: ExceptionABI


@dataclass(frozen=True, slots=True)
class BuildFunction:
    """Code/globals, defaults, source captures, optional annotate callable, world.

    Source-order formal/default metadata is not a physical MAKE_FUNCTION ABI.
    A docstring source is compile metadata, conditional on target compilation.
    """
    environment: DeferredEnvironment
    annotations: FunctionAnnotationInterface | None
    docstring: SlotRef | None


@dataclass(frozen=True, slots=True)
class ApplyDecorator:
    source: SlotRef
    exception_abi: ExceptionABI


@dataclass(frozen=True, slots=True)
class TranslateEscapingException:
    """Compiler generator/coroutine wrapper, after user cleanup/handlers."""
    kind: DeferredBodyKind
    exception_abi: ExceptionABI


@dataclass(frozen=True, slots=True)
class LazyExpressionInterface:
    source: SlotRef
    scope: int
    captures: tuple[int, ...]
    unpack_starred: bool
    format_default: int = 1


@dataclass(frozen=True, slots=True)
class TypeParameterSpec:
    name: SlotRef
    kind: TypeParameterKind
    binding_port: int
    bound: LazyExpressionInterface | None
    default: LazyExpressionInterface | None
    constraints: bool


@dataclass(frozen=True, slots=True)
class TypeParameterEnvironment:
    """Logical source inputs, not synthetic compiler defaults-tuple/dict ABI."""
    scope: int
    captures: tuple[int, ...]
    parameters: tuple[TypeParameterSpec, ...]
    inputs: tuple[SlotRef, ...]
    world: GroundType
    exception_abi: ExceptionABI


@dataclass(frozen=True, slots=True)
class EnterTypeParameters:
    environment: TypeParameterEnvironment


@dataclass(frozen=True, slots=True)
class InvokeTypeParameterFactory:
    invocation: ProductionRegionCall
    environment: TypeParameterEnvironment


@dataclass(frozen=True, slots=True)
class BuildLazyExpression:
    expression: LazyExpressionInterface
    exception_abi: ExceptionABI


@dataclass(frozen=True, slots=True)
class CreateTypeParameter:
    parameter: TypeParameterSpec
    exception_abi: ExceptionABI


@dataclass(frozen=True, slots=True)
class SetTypeParameterDefault:
    """Write the default evaluator; retain the original parameter reference."""
    parameter: TypeParameterSpec
    exception_abi: ExceptionABI


@dataclass(frozen=True, slots=True)
class BindTypeParameter:
    """Initialize the original TYPE_PARAMETER_INTERFACE, not a guessed Store."""
    parameter: TypeParameterSpec
    exception_abi: ExceptionABI


@dataclass(frozen=True, slots=True)
class AttachTypeParameters:
    """Associate the tuple with the existing object; no new object identity."""
    source: SlotRef
    exception_abi: ExceptionABI


@dataclass(frozen=True, slots=True)
class ClassBodyInterface:
    scope: int
    globals_scope: int
    captures: tuple[int, ...]
    protocol_bindings: tuple[int, ...]
    docstring: SlotRef | None
    type_parameters: SlotRef | None
    world: GroundType
    exception_abi: ExceptionABI


@dataclass(frozen=True, slots=True)
class DeferClassBody:
    body: ProductionRegionID
    interface: ClassBodyInterface


@dataclass(frozen=True, slots=True)
class EnterClassBody:
    """Admit closure environment and the namespace supplied by the builder."""
    interface: ClassBodyInterface


@dataclass(frozen=True, slots=True)
class InitializeClassNamespace:
    """Compiler prelude: namespace reads/writes, protocol cells and docstring.

    Namespace may be a custom mapping. No pure/dict-only effect is asserted.
    Compiler metadata derives from the original class source and profile.
    """
    interface: ClassBodyInterface


@dataclass(frozen=True, slots=True)
class FinalizeClassNamespace:
    """Deferred annotations, static attributes and class-cell publication."""
    interface: ClassBodyInterface


@dataclass(frozen=True, slots=True)
class ReadBuildClass:
    exception_abi: ExceptionABI


@dataclass(frozen=True, slots=True)
class BuildClassBody:
    interface: ClassBodyInterface


@dataclass(frozen=True, slots=True)
class BuildGenericBase:
    exception_abi: ExceptionABI


@dataclass(frozen=True, slots=True)
class BuildTypeAlias:
    name: SlotRef
    expression: LazyExpressionInterface
    type_parameters: SlotRef | None
    exception_abi: ExceptionABI


@dataclass(frozen=True, slots=True)
class ReadContextMethod:
    """Type-special lookup, retaining a logical callable/receiver handle.

    This does not assert allocation of a Python bound-method object.
    """
    source: SlotRef
    method: ContextMethodKind
    exception_abi: ExceptionABI


@dataclass(frozen=True, slots=True)
class InvokeContextMethod:
    source: SlotRef
    method: ContextMethodKind
    exception_abi: ExceptionABI


@dataclass(frozen=True, slots=True)
class ContextAwaitable:
    """GET_AWAITABLE qualified for async enter/exit error context."""
    source: SlotRef
    method: ContextMethodKind
    exception_abi: ExceptionABI


@dataclass(frozen=True, slots=True)
class EnterHandledException:
    """Install the delivered exception; return the previous handled value."""
    exception_abi: ExceptionABI


@dataclass(frozen=True, slots=True)
class RestoreHandledException:
    """Restore a retained handled-exception value, threading current world."""
    pass


@dataclass(frozen=True, slots=True)
class ContextExceptionArguments:
    """Read type/value/current traceback; ABI sidecar is not an attribute read."""
    exception_abi: ExceptionABI


@dataclass(frozen=True, slots=True)
class PrepareReraise:
    """Propagate a saved exception with current traceback, without a new raise site.

    Inputs are the exception reference and current world, not an old traceback.
    Native frame/lasti mapping is a separate obligation.
    """
    exception_abi: ExceptionABI


@dataclass(frozen=True, slots=True)
class MatchExceptionType:
    """CHECK_EXC_MATCH, including validation of the evaluated catch type."""
    source: SlotRef
    exception_abi: ExceptionABI


@dataclass(frozen=True, slots=True)
class DeleteExceptionBinding:
    """Compiler cleanup deletion authorized by CLEAR_ON_HANDLER_EXIT.

    The original name port supplies the target; no source Del port is invented.
    Its preceding None assignment is a separate binding write.
    """
    port: int
    exception_abi: ExceptionABI


@dataclass(frozen=True, slots=True)
class ReferenceIsNone:
    """Identity predicate, without truth conversion or a world transition."""
    pass


@dataclass(frozen=True, slots=True)
class InvertCondition:
    """Invert an admitted control boolean without truth-testing an object."""
    pass


@dataclass(frozen=True, slots=True)
class SplitExceptionGroup:
    """CHECK_EG_MATCH: validate type, split, install non-None matched group.

    None remainder still validates the evaluated type. Group split may invoke
    user code, wrap a naked exception, allocate or fail.
    """
    source: SlotRef
    exception_abi: ExceptionABI


@dataclass(frozen=True, slots=True)
class MergeExceptionGroup:
    """Recompose original/reraised/new exceptions using current metadata."""
    source: SlotRef
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
class CompletionRoute:
    """Completion payload then explicit captures form the handler inputs."""
    kind: LanguageCompletionKind
    target: ProductionControlTarget | None
    handler: ProductionRegionID
    captures: tuple[ProductionValue, ...] = ()


@dataclass(frozen=True, slots=True)
class HandleCompletions:
    protected: ProductionRegionCall
    routes: tuple[CompletionRoute, ...]


@dataclass(frozen=True, slots=True)
class TransferCompletion:
    kind: LanguageCompletionKind
    target: ProductionControlTarget | None = None


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


ProductionInstruction = (EvaluateChild | ApplyLanguageAction | ReadCompilationOption | ApplyInplaceOperator | PublishAnnotation
    | ImportRequest | ImportMember | ImportStar
    | ApplyPythonProtocol | ApplyDelegationProtocol | AccessBinding | ConstructValue | DefineLiteral
    | BuildFunctionAnnotations | BuildFunction | ApplyDecorator | TranslateEscapingException
    | EnterTypeParameters | InvokeTypeParameterFactory | BuildLazyExpression | CreateTypeParameter
    | SetTypeParameterDefault | BindTypeParameter | AttachTypeParameters
    | DeferClassBody | EnterClassBody | InitializeClassNamespace | FinalizeClassNamespace
    | ReadBuildClass | BuildClassBody | BuildGenericBase | BuildTypeAlias
    | ReadContextMethod | InvokeContextMethod | ContextAwaitable | EnterHandledException
    | RestoreHandledException | ContextExceptionArguments | PrepareReraise
    | MatchExceptionType | DeleteExceptionBinding
    | ReferenceIsNone | InvertCondition | SplitExceptionGroup | MergeExceptionGroup
    | ApplyRegion | BranchControl | LoopControl | DeferRegion | ReferenceEnvironment | EnterDeferredBody
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
    schema_version: int = 15
    authority: str = 'SOURCE_RECIPE_SHAPE_ONLY'


PRODUCTION_RECORD_TAGS = {cls: ('record_kind', cls.__name__) for cls in (
    ProductionOccurrence, SlotRef, ProductionParameter, ProductionResult,
    *ProductionInstruction.__args__,
    GlobalsEnvironment, ClosureEnvironment,
    ProductionResumeRoute, IterationCondition, RepeatCondition,
    CountBinding, ChoiceBinding, TypeBinding, TypesBinding)}
