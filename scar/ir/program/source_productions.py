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
    YIELD_FROM = 'YIELD_FROM'
    AWAIT = 'AWAIT'


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
class LoopControl:
    """One loop template, with invariant prefix and carried suffix input ports.

    Condition/body receive both groups. Only carried values return along the
    backedge; invariants stay connected to the original loop inputs.
    """
    condition: ProductionRegionID | IterationCondition
    body: ProductionRegionID
    otherwise: ProductionRegionID | None = None
    invariant_count: int = 0


@dataclass(frozen=True, slots=True)
class DeferRegion:
    """Declare code/captures without entering the body's execution path."""
    body: ProductionRegionID


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
class SuspendExecution:
    suspension: SuspensionKind
    resume: ProductionRegionID


ProductionInstruction = (EvaluateChild | ApplyLanguageAction | ApplyPythonProtocol | AccessBinding | ConstructValue | DefineLiteral
    | ApplyRegion | BranchControl | LoopControl | DeferRegion | CleanupControl
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
    schema_version: int = 1
    authority: str = 'SOURCE_RECIPE_SHAPE_ONLY'


PRODUCTION_RECORD_TAGS = {cls: ('record_kind', cls.__name__) for cls in (
    ProductionOccurrence, SlotRef, ProductionParameter, ProductionResult,
    EvaluateChild, ApplyLanguageAction, ApplyPythonProtocol, AccessBinding, ConstructValue, DefineLiteral, ApplyRegion,
    BranchControl, LoopControl, DeferRegion, CleanupControl, HandleCompletions,
    TransferCompletion, SuspendExecution, IterationCondition, CountBinding, ChoiceBinding, TypeBinding, TypesBinding)}
