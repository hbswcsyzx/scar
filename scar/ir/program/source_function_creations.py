"""Source factory declarations, distinct from selected runtime callables."""
from dataclasses import dataclass
from enum import Enum

from . import normal_links as F, normal_targets as T, source_productions as P
from .providers import ProviderArtifact, ProviderFactReference
from .source_template_links import SourceTemplateKey, SourceTemplateOrigin


class FunctionFactoryKind(str, Enum):
    BUILD_FUNCTION = 'BUILD_FUNCTION'
    MAKE_LAMBDA_FUNCTION = 'MAKE_LAMBDA_FUNCTION'
    MAKE_GENEXPR_FUNCTION = 'MAKE_GENEXPR_FUNCTION'
    MAKE_NESTED_FUNCTION = 'MAKE_NESTED_FUNCTION'


class AnnotationOperandKind(str, Enum):
    ANNOTATE_CALLABLE = 'ANNOTATE_CALLABLE'
    ANNOTATION_CODE = 'ANNOTATION_CODE'


@dataclass(frozen=True, slots=True)
class FunctionDefaultCapture:
    """Actual factory input and original expression stay separate.

    A generic factory may forward the expression through a parameter. Neither
    endpoint denotes the current __defaults__/__kwdefaults__ slot or proves its
    present contents. ``parameter`` indexes DeferredEnvironment.parameters.
    """
    parameter: int
    default_source: P.SlotRef
    operand_ordinal: int
    operand: T.GlobalPort
    expression: T.GlobalPort | None


@dataclass(frozen=True, slots=True)
class FunctionCellCapture:
    """Retained cell handle, never a snapshot or alias of the cell contents."""
    relay: P.CaptureReference
    operand_ordinal: int
    operand: T.GlobalPort


@dataclass(frozen=True, slots=True)
class SourceFunctionCreation:
    function_fact: ProviderFactReference
    factory: FunctionFactoryKind
    origin: SourceTemplateOrigin
    site: T.GlobalPort
    function: T.GlobalPort
    code: T.GlobalPort
    body: T.Body
    body_scope: F.CodeScopeWitness
    creator: F.CodeScopeWitness
    environment: P.DeferredEnvironment
    globals: T.GlobalPort
    defaults: tuple[FunctionDefaultCapture, ...]
    captures: tuple[FunctionCellCapture, ...]
    capture_transports: tuple[P.CaptureTransport, ...]
    annotation: T.GlobalPort | None
    annotation_kind: AnnotationOperandKind | None
    annotations: P.FunctionAnnotationInterface | None
    world_before: T.GlobalPort
    world_after: T.GlobalPort
    # MAKE_GENEXPR_FUNCTION has five original reference outputs. Their ordered
    # ports are retained without declaring them reference aliases of inputs.
    factory_results: tuple[T.GlobalPort, ...]
    conditions: tuple[str, ...] = ('SOURCE_CREATOR_CONTEXT_AND_FACTORY_NORMAL_COMPLETION_SELECTED',)


@dataclass(frozen=True, slots=True)
class FunctionCreationObligation:
    function_fact: ProviderFactReference
    function: T.GlobalPort
    template: SourceTemplateKey
    site: T.GlobalPort | None
    rule: str


@dataclass(frozen=True, slots=True)
class SourceFunctionCreationGraph:
    unit: str
    source_templates: ProviderArtifact
    templates: tuple[SourceTemplateKey, ...]
    creations: tuple[SourceFunctionCreation, ...]
    obligations: tuple[FunctionCreationObligation, ...]
    runtime_function_instances_proven: bool = False
    current_defaults_proven: bool = False
    source_scopes_activated: bool = False
    effects_closed: bool = False
    loops_unrolled: bool = False
    target_executed: bool = False
    first_stage_complete: bool = False
    semantics: str = 'SOURCE_FACTORY_OPERANDS_AND_CELL_HANDLES_NOT_CURRENT_CALLABLE_OR_CONTENT_VERSIONS'
