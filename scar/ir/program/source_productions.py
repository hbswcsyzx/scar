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
    ROOT = 'ROOT'


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


class PatternCompletionKind(str, Enum):
    FAIL = 'PATTERN_FAIL'


class PatternActionKind(str, Enum):
    SEQUENCE_TEST = 'SEQUENCE_TEST'
    MAPPING_TEST = 'MAPPING_TEST'
    LENGTH_TEST = 'LENGTH_TEST'
    EQUAL = 'EQUAL'
    SEQUENCE_UNPACK = 'SEQUENCE_UNPACK'
    SEQUENCE_ITEM = 'SEQUENCE_ITEM'
    CLASS_EXTRACT = 'CLASS_EXTRACT'
    KEYS_EXTRACT = 'KEYS_EXTRACT'
    TUPLE_UNPACK = 'TUPLE_UNPACK'


class CompilationOption(str, Enum):
    ASSERTIONS_ENABLED = 'ASSERTIONS_ENABLED'
    DOCSTRINGS_ENABLED = 'DOCSTRINGS_ENABLED'


class NamespaceActionKind(str, Enum):
    STORE_NAME = 'STORE_NAME'
    STORE_GLOBAL = 'STORE_GLOBAL'
    ENSURE_ANNOTATIONS = 'ENSURE_ANNOTATIONS'


class ImplicitComparisonKind(str, Enum):
    GREATER = 'GREATER'


class CommonConstantKind(str, Enum):
    NOT_IMPLEMENTED_ERROR = 'NOT_IMPLEMENTED_ERROR'


class ClassProtocolActionKind(str, Enum):
    WRITE_VALUE = 'WRITE_VALUE'
    CELL_REFERENCE = 'CELL_REFERENCE'


class AnnotationPublicationKind(str, Enum):
    STRINGIZED = 'STRINGIZED'
    DEFERRED = 'DEFERRED'


class AnnotationLookupKind(str, Enum):
    LOCALS_CHAIN = 'LOCALS_CHAIN'
    GLOBALS_CHAIN = 'GLOBALS_CHAIN'
    CLASS_PROTOCOL_CELL = 'CLASS_PROTOCOL_CELL'


class AnnotationStateName(str, Enum):
    ANNOTATIONS = '__annotations__'
    CONDITIONAL = '__conditional_annotations__'


class CompilationContextStatus(str, Enum):
    VERIFIED = 'VERIFIED'
    NO_RETAINED_OWNER = 'NO_RETAINED_OWNER'
    OWNER_LAYOUT_UNVERIFIED = 'OWNER_LAYOUT_UNVERIFIED'


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
    native_symbols_sha256: str
    compiler_topology_sha256: str
    compiler_symbols_sha256: str


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
    kind: LanguageCompletionKind | PatternCompletionKind
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
    """Source descriptor, not an execution instruction.

    A deferred entry belongs to the original C1 annotation scope. Registering
    an unconditional class annotation is compile metadata; conditional class
    and all module annotations also record that this declaration was reached.
    Stringized publication instead writes the compiled string immediately.
    Runtime publication is expanded into namespace reads and mutations.
    """
    annotation: SlotRef
    name: SlotRef
    publication: AnnotationPublicationKind
    conditional_registration: bool
    exception_abi: ExceptionABI


@dataclass(frozen=True, slots=True)
class AnnotationStateAccess:
    """Namespace/cell lookup in the current activation/world.

    LOCALS_CHAIN and GLOBALS_CHAIN require alias evidence before merging.
    A class protocol cell uses original C2 binding/implicit/read-plan IDs.
    """
    scope: int
    lookup: AnnotationLookupKind
    name: AnnotationStateName
    binding: int | None = None
    implicit_requirement: int | None = None
    read_plan: int | None = None


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
class DerivedCaptureRef:
    """Unit-scoped shared hop key; never an ordinal in the original F3 table."""
    scope: int
    binding: int


CaptureReference = int | DerivedCaptureRef


@dataclass(frozen=True, slots=True)
class CaptureTransport:
    reference: DerivedCaptureRef
    parent: CaptureReference | None
    compiler_slots: tuple[int, ...]
    implicit_requirements: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class DeferredEnvironment:
    scope: int
    globals_scope: int
    parameters: tuple[DeferredParameter, ...]
    # Original active C2b hops or explicit compiler-witnessed supplement keys.
    # These are cell handles, not values or a native co_freevars ordering.
    captures: tuple[CaptureReference, ...]
    kind: DeferredBodyKind
    world: GroundType
    exception_abi: ExceptionABI
    owned_cells: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class FunctionAnnotationEntry:
    parameter: SlotRef | None
    name: str
    value: SlotRef


@dataclass(frozen=True, slots=True)
class FunctionAnnotationInterface:
    scope: int
    captures: tuple[CaptureReference, ...]
    entries: tuple[FunctionAnnotationEntry, ...]
    stringized: bool


@dataclass(frozen=True, slots=True)
class AnnotationRegistration:
    """Compiler conditional index scoped by original annotation scope/profile."""
    scope: int
    optimization_level: int
    index: int


@dataclass(frozen=True, slots=True)
class ScopeAnnotationEntry:
    source: SlotRef
    name: SlotRef
    key: str
    registration: AnnotationRegistration | None


@dataclass(frozen=True, slots=True)
class ScopeAnnotationVariant:
    optimization_level: int
    entries: tuple[ScopeAnnotationEntry, ...]
    emitted_in_original_unit: bool = True


@dataclass(frozen=True, slots=True)
class ScopeAnnotationInterface:
    source: SlotRef
    scope: int
    creator_scope: int
    captures: tuple[CaptureReference, ...]
    variants: tuple[ScopeAnnotationVariant, ...]


@dataclass(frozen=True, slots=True)
class AnnotationEmissionVariant:
    optimization_level: int
    registrations: tuple[AnnotationRegistration, ...]
    emitted_in_original_unit: bool
    producer_sites: tuple['AnnotationEmissionSite', ...]
    context_status: CompilationContextStatus
    unverified_owner_paths: tuple[tuple[int, ...], ...] = ()


@dataclass(frozen=True, slots=True)
class CompiledCodeReference:
    """Unit-scoped original code version, never joined by name or line."""
    optimization_level: int
    constant_path: tuple[int, ...]
    code_sha256: str
    bytecode_size: int
    digest_kind: str = 'SCAR_COMPILED_CODE_V1'


@dataclass(frozen=True, slots=True)
class AnnotationEmissionSite:
    registration: AnnotationRegistration
    code: CompiledCodeReference
    lookup_offset: int
    index_offset: int
    insert_offset: int
    discard_offset: int


@dataclass(frozen=True, slots=True)
class AnnotationEmissionParameter:
    """Compiler-context input with a complete finite source-bound domain.

    Alternatives are not simultaneous writes or a runtime random choice.
    Binding a shared template to its emission context is a later obligation.
    A singleton numeric domain can be a literal.
    """
    publication: PublishAnnotation
    variants: tuple[AnnotationEmissionVariant, ...]


@dataclass(frozen=True, slots=True)
class BuildFunctionAnnotations:
    """Create the later annotation-request callable, without evaluating values."""
    annotations: FunctionAnnotationInterface
    exception_abi: ExceptionABI
    body: ProductionRegionID


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
    captures: tuple[CaptureReference, ...]
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
    captures: tuple[CaptureReference, ...]
    parameters: tuple[TypeParameterSpec, ...]
    inputs: tuple[SlotRef, ...]
    world: GroundType
    exception_abi: ExceptionABI
    owned_cells: tuple[int, ...] = ()


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
    body: ProductionRegionID


@dataclass(frozen=True, slots=True)
class EvaluationRequestEnvironment:
    """Admitted captured environment, format argument and fresh world.

    The synthetic format parameter is a logical request port, not an invented
    source Name or a claimed native frame slot. None means no initial default.
    """
    source: SlotRef
    scope: int
    globals_scope: int
    captures: tuple[CaptureReference, ...]
    format_default: int | None
    world: GroundType
    exception_abi: ExceptionABI
    owned_cells: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class EnterEvaluationRequest:
    environment: EvaluationRequestEnvironment


@dataclass(frozen=True, slots=True)
class ReadAnnotationRegistration:
    """Read the current conditional registry; lookup/contains may fail.

    Module lookup uses globals/builtins; class lookup uses the captured
    protocol cell. It neither reads a frozen set nor proves registration
    origins or native control-path selection.
    """
    registration: AnnotationRegistration
    exception_abi: ExceptionABI
    access: AnnotationStateAccess


@dataclass(frozen=True, slots=True)
class ReadAnnotationNamespace:
    access: AnnotationStateAccess
    exception_abi: ExceptionABI


@dataclass(frozen=True, slots=True)
class ReadCompilationAnnotationIndex:
    """Symbolic compiler input, not a runtime operation that picks an index."""
    parameter: AnnotationEmissionParameter


@dataclass(frozen=True, slots=True)
class AddAnnotationIndex:
    """PySet_Add boundary; preserve type errors and other failure effects.

    This does not dispatch a Python .add method or assume the loaded object
    still equals the empty set created at initialization.
    """
    publication: PublishAnnotation
    parameter: AnnotationEmissionParameter


@dataclass(frozen=True, slots=True)
class ApplyImplicitComparison:
    operator: ImplicitComparisonKind
    exception_abi: ExceptionABI


@dataclass(frozen=True, slots=True)
class ReadCommonConstant:
    constant: CommonConstantKind


@dataclass(frozen=True, slots=True)
class DefineAnnotationString:
    source: SlotRef
    value: str


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
    captures: tuple[CaptureReference, ...]
    protocol_bindings: tuple[int, ...]
    docstring: SlotRef | None
    type_parameters: SlotRef | None
    world: GroundType
    exception_abi: ExceptionABI
    owned_cells: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class DeferClassBody:
    body: ProductionRegionID
    interface: ClassBodyInterface


@dataclass(frozen=True, slots=True)
class EnterClassBody:
    """Admit closure environment and the namespace supplied by the builder."""
    interface: ClassBodyInterface


@dataclass(frozen=True, slots=True)
class AccessClassName:
    """Implicit compiler name access, distinct from a guessed dict operation.

    Original F3 resolution selects mapping/global/free-cell behavior. None
    means the ordinary class-name rule, not an unknown effect or absent read.
    Hidden capture transport and native lookup expansion remain obligations.
    """
    interface: ClassBodyInterface
    name: str
    action: BindingActionKind
    resolution: int | None


@dataclass(frozen=True, slots=True)
class AccessClassProtocol:
    """Original hidden protocol binding, separate from a same-spelled key."""
    interface: ClassBodyInterface
    binding: int
    action: ClassProtocolActionKind


@dataclass(frozen=True, slots=True)
class ReadClassTypeParameters:
    """Read the type tuple supplied when creating this class callback."""
    interface: ClassBodyInterface


@dataclass(frozen=True, slots=True)
class BuildClassAnnotations:
    """Create the later class-variable annotation callable, not its results."""
    interface: ClassBodyInterface
    annotations: ScopeAnnotationInterface
    body: ProductionRegionID


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
class ReferenceIdentical:
    """Object identity, without equality/truth callbacks or state transition."""
    pass


@dataclass(frozen=True, slots=True)
class RootBodyInterface:
    """An external admitted globals/locals pair, not necessarily one mapping.

    Admission by exec/eval/import machinery precedes this interface. No
    dictionary allocation, __builtins__ injection or physical frame is implied.
    """
    source: ProductionOccurrence
    scope: int
    world: GroundType
    exception_abi: ExceptionABI


@dataclass(frozen=True, slots=True)
class EnterRootBody:
    interface: RootBodyInterface


@dataclass(frozen=True, slots=True)
class ApplyNamespaceAction:
    """STORE_NAME uses mapping assignment; STORE_GLOBAL uses dictionary API.

    ENSURE_ANNOTATIONS implements the SETUP_ANNOTATIONS presence check on
    locals. Existing values are retained; missing-key and other errors differ.
    None of these boundaries is certified effect-free.
    """
    kind: NamespaceActionKind
    exception_abi: ExceptionABI


@dataclass(frozen=True, slots=True)
class BuildScopeAnnotations:
    """Create the module annotation callable before user statements.

    The explicit deferred body is not called by creation.
    """
    interface: RootBodyInterface
    annotations: ScopeAnnotationInterface
    body: ProductionRegionID


@dataclass(frozen=True, slots=True)
class DisplayExpression:
    """Interactive intrinsic print, including displayhook effects/failures."""
    exception_abi: ExceptionABI


@dataclass(frozen=True, slots=True)
class ApplyPatternAction:
    """Finite native boundary with result arity rederived from original source.

    Type tests read flags; length/item/split/compare may call user code.
    CLASS_EXTRACT and KEYS_EXTRACT return an exact tuple or None. Suffix
    SEQUENCE_ITEM reads current length, not a saved earlier length.
    """
    kind: PatternActionKind
    source: ProductionSource
    reference_results: int
    exception_abi: ExceptionABI


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
    relay: CaptureReference


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
    kind: LanguageCompletionKind | PatternCompletionKind
    target: ProductionControlTarget | None
    handler: ProductionRegionID
    captures: tuple[ProductionValue, ...] = ()


@dataclass(frozen=True, slots=True)
class HandleCompletions:
    protected: ProductionRegionCall
    routes: tuple[CompletionRoute, ...]


@dataclass(frozen=True, slots=True)
class TransferCompletion:
    kind: LanguageCompletionKind | PatternCompletionKind
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


ProductionInstruction = (EvaluateChild | ApplyLanguageAction | ReadCompilationOption | ApplyInplaceOperator
    | ImportRequest | ImportMember | ImportStar
    | ApplyPythonProtocol | ApplyDelegationProtocol | AccessBinding | ConstructValue | DefineLiteral
    | BuildFunctionAnnotations | BuildFunction | ApplyDecorator | TranslateEscapingException
    | EnterTypeParameters | InvokeTypeParameterFactory | BuildLazyExpression | CreateTypeParameter
    | SetTypeParameterDefault | BindTypeParameter | AttachTypeParameters
    | DeferClassBody | EnterClassBody | AccessClassName | AccessClassProtocol | ReadClassTypeParameters | BuildClassAnnotations
    | ReadBuildClass | BuildClassBody | BuildGenericBase | BuildTypeAlias
    | ReadContextMethod | InvokeContextMethod | ContextAwaitable | EnterHandledException
    | RestoreHandledException | ContextExceptionArguments | PrepareReraise
    | MatchExceptionType | DeleteExceptionBinding
    | ReferenceIsNone | InvertCondition | SplitExceptionGroup | MergeExceptionGroup
    | ReferenceIdentical | ApplyPatternAction
    | EnterRootBody | ApplyNamespaceAction | BuildScopeAnnotations | DisplayExpression
    | EnterEvaluationRequest | ReadAnnotationRegistration | ReadAnnotationNamespace | ReadCompilationAnnotationIndex
    | AddAnnotationIndex | ApplyImplicitComparison | ReadCommonConstant | DefineAnnotationString
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


class CompilationPathKind(str, Enum):
    FIELD = 'FIELD'
    ITEM = 'ITEM'


class CompilationEdgeKind(str, Enum):
    CALL = 'CALL'
    CHILD = 'CHILD'
    CODE_DECLARATION = 'CODE_DECLARATION'
    TYPE_FACTORY = 'TYPE_FACTORY'
    LOOP_CONDITION = 'LOOP_CONDITION'
    LOOP_BODY = 'LOOP_BODY'
    LOOP_EXIT = 'LOOP_EXIT'
    COMPLETION_HANDLER = 'COMPLETION_HANDLER'
    RESUME = 'RESUME'


class CompilationTransition(str, Enum):
    QUALIFY_SITE = 'QUALIFY_SITE'
    ENTER_CODE = 'ENTER_CODE'


@dataclass(frozen=True, slots=True)
class CompilationPathPart:
    """Field ordinal in the pinned record schema, or tuple item ordinal."""
    kind: CompilationPathKind
    ordinal: int


@dataclass(frozen=True, slots=True)
class CompilationContextPort:
    region: ProductionRegionID
    source_scope: int
    code_scope: int


@dataclass(frozen=True, slots=True)
class CompilationChildTarget:
    field: SlotRef
    purpose: ProductionPurpose
    source_scope: int
    code_scope: int


@dataclass(frozen=True, slots=True)
class CompilationContextEdge:
    """Qualify the caller's symbolic environment at one static reference site.

    This is not an activation, runtime iteration or concrete bytecode binding.
    Declaration edges retain an environment for later entry; they do not call.
    """
    step: ProductionStepID
    path: tuple[CompilationPathPart, ...]
    kind: CompilationEdgeKind
    target: ProductionRegionID | CompilationChildTarget
    transition: CompilationTransition


@dataclass(frozen=True, slots=True)
class CompilationFactUse:
    step: ProductionStepID
    parameter: CompilationOption | SlotRef


@dataclass(frozen=True, slots=True)
class CompilationContextFlow:
    ports: tuple[CompilationContextPort, ...]
    edges: tuple[CompilationContextEdge, ...]
    uses: tuple[CompilationFactUse, ...]


@dataclass(frozen=True, slots=True)
class SourceProductionPlan:
    input: ProductionInput
    source: ProductionSource
    purpose: ProductionPurpose
    root: ProductionRegionID
    regions: tuple[ProductionRegion, ...]
    steps: tuple[ProductionStep, ...]
    slots: tuple[ProductionSlotDisposition, ...]
    capture_transports: tuple[CaptureTransport, ...] = ()
    compilation_flow: CompilationContextFlow | None = None
    schema: str = 'scar.source-production-plan'
    schema_version: int = 24
    authority: str = 'SOURCE_RECIPE_SHAPE_ONLY'


PRODUCTION_RECORD_TAGS = {cls: ('record_kind', cls.__name__) for cls in (
    ProductionOccurrence, SlotRef, ProductionParameter, ProductionResult,
    *ProductionInstruction.__args__,
    GlobalsEnvironment, ClosureEnvironment, DerivedCaptureRef,
    ProductionResumeRoute, IterationCondition, RepeatCondition,
    CountBinding, ChoiceBinding, TypeBinding, TypesBinding)}
