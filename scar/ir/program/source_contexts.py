"""C1 static owners, source environments and evaluation eligibility templates."""
from dataclasses import dataclass
from enum import Enum

from .source_roles import SlotRef


class SourceOwnerKind(str, Enum):
    # _Router root/private/prepare/annotation/transfer paths and C3 owner roles.
    ROOT = 'ROOT'
    CLASS_DECLARATION = 'CLASS_DECLARATION'
    FUNCTION_BODY = 'FUNCTION_BODY'
    LAMBDA_BODY = 'LAMBDA_BODY'
    CLASS_BODY = 'CLASS_BODY'
    FORMAL_INTERFACE = 'FORMAL_INTERFACE'
    TYPE_PARAMETERS = 'TYPE_PARAMETERS'
    HEADER_ANNOTATIONS = 'HEADER_ANNOTATIONS'
    VARIABLE_ANNOTATIONS = 'VARIABLE_ANNOTATIONS'
    TYPE_ALIAS_VALUE = 'TYPE_ALIAS_VALUE'
    TYPE_PARAMETER_BOUND = 'TYPE_PARAMETER_BOUND'
    TYPE_PARAMETER_DEFAULT = 'TYPE_PARAMETER_DEFAULT'
    COMPREHENSION = 'COMPREHENSION'
    GENERATOR_EXPRESSION = 'GENERATOR_EXPRESSION'


class SourceScopeKind(str, Enum):
    # Every kind passed to _Router.scope, including all root parser modes.
    ROOT_EXEC = 'ROOT_EXEC'
    ROOT_EVAL = 'ROOT_EVAL'
    ROOT_INTERACTIVE = 'ROOT_INTERACTIVE'
    TYPE_GRAMMAR = 'TYPE_GRAMMAR'
    FUNCTION = 'FUNCTION'
    LAMBDA = 'LAMBDA'
    CLASS = 'CLASS'
    TYPE_PARAMETERS = 'TYPE_PARAMETERS'
    ANNOTATION = 'ANNOTATION'
    TYPE_ALIAS = 'TYPE_ALIAS'
    TYPE_PARAMETER_EVALUATOR = 'TYPE_PARAMETER_EVALUATOR'
    COMPREHENSION = 'COMPREHENSION'
    GENERATOR_EXPRESSION = 'GENERATOR_EXPRESSION'


class EvaluationRegionKind(str, Enum):
    # Every _Router.region path; later yield processing changes trigger only.
    ROOT = 'ROOT'
    TYPE_GRAMMAR = 'TYPE_GRAMMAR'
    FUNCTION_BODY = 'FUNCTION_BODY'
    LAMBDA_BODY = 'LAMBDA_BODY'
    CLASS_BODY = 'CLASS_BODY'
    FORMAL_INTERFACE = 'FORMAL_INTERFACE'
    DECLARATION_TIME = 'DECLARATION_TIME'
    TYPE_PARAMETERS = 'TYPE_PARAMETERS'
    FUNCTION_ANNOTATION = 'FUNCTION_ANNOTATION'
    VARIABLE_ANNOTATION = 'VARIABLE_ANNOTATION'
    TYPE_ALIAS_VALUE = 'TYPE_ALIAS_VALUE'
    TYPE_PARAMETER_BOUND = 'TYPE_PARAMETER_BOUND'
    TYPE_PARAMETER_DEFAULT = 'TYPE_PARAMETER_DEFAULT'
    COMPREHENSION = 'COMPREHENSION'
    GENERATOR_EXPRESSION = 'GENERATOR_EXPRESSION'


def _normalize_kind(record, kind_type):
    value = record.kind
    if type(value) is kind_type:
        return
    if type(value) is not str:
        raise ValueError('classification requires its exact Enum or a declared string value')
    # Exact strings preserve source-router compatibility; other Enums and
    # string subclasses cannot cross classification domains implicitly.
    object.__setattr__(record, 'kind', kind_type(value))


@dataclass(frozen=True, slots=True)
class OwnerRef:
    occurrence: int
    kind: SourceOwnerKind

    def __post_init__(self):
        _normalize_kind(self, SourceOwnerKind)
        if type(self.occurrence) is not int or self.occurrence < 0:
            raise ValueError('invalid static evaluation owner')


@dataclass(frozen=True, slots=True)
class ContextState:
    """owner is a static evaluation unit, never an invocation or runtime frame.

    declaration_route is an edge-local target qualifier, not a storage binding.
    """
    owner: OwnerRef
    environment: int
    region: int
    private_context: int
    declaration_route: str = 'CURRENT_ENV'

    def __post_init__(self):
        if any(type(n) is not int or n < 0 for n in (self.environment, self.region, self.private_context)):
            raise ValueError('invalid local context reference')


@dataclass(frozen=True, slots=True)
class SourceScope:
    kind: SourceScopeKind
    owner: OwnerRef
    anchor: SlotRef | None
    parent: int | None
    lookup_policy: str

    def __post_init__(self):
        _normalize_kind(self, SourceScopeKind)


@dataclass(frozen=True, slots=True)
class EvaluationRegion:
    """ELIGIBLE means no C1 suppression; legality/reachability are not proven."""
    kind: EvaluationRegionKind
    owner: OwnerRef
    anchor: SlotRef | None
    parent: int | None
    trigger: str
    eligibility: str
    suppression_origin: SlotRef | None
    suppression_reason: str | None

    def __post_init__(self):
        _normalize_kind(self, EvaluationRegionKind)
        if (self.eligibility not in ('ELIGIBLE', 'SUPPRESSED')
                or (self.suppression_reason is None) != (self.eligibility == 'ELIGIBLE')):
            raise ValueError('invalid evaluation eligibility template')


@dataclass(frozen=True, slots=True)
class PrivateContext:
    """parameter_group, when SELECTIVE, is a local SourceScope ordinal."""
    class_owner: OwnerRef | None
    mode: str
    parameter_group: int | None

    def __post_init__(self):
        if (self.mode not in ('NONE', 'ALL', 'SELECTIVE')
                or (self.class_owner is None) != (self.mode == 'NONE')
                or (self.parameter_group is not None) != (self.mode == 'SELECTIVE')):
            raise ValueError('invalid private-name policy reference')


@dataclass(frozen=True, slots=True)
class ContextRule:
    rule: int
    selector: str
    content_policy: str


@dataclass(frozen=True, slots=True)
class ContextCatalog:
    rule_version: str
    f2_schema_sha256: str
    role_catalog_sha256: str
    content_sha256: str
    rules: tuple[ContextRule, ...]
    schema: str = 'scar.source-context-catalog'
    schema_version: int = 1


@dataclass(frozen=True, slots=True)
class ContextBoundary:
    site: SlotRef
    selector: str
    state: ContextState
    content_policy: str


@dataclass(frozen=True, slots=True)
class ContextResolution:
    site: SlotRef
    slot_state: str
    selector: str
    content_policy: str
    state: ContextState


@dataclass(frozen=True, slots=True)
class RuleContextCount:
    rule: int
    slots: int
    absent: int
    none: int
    empty_list: int
    values: int
    boundaries: int

    def __post_init__(self):
        if (any(type(n) is not int or n < 0 for n in (self.rule, self.slots, self.absent,
                self.none, self.empty_list, self.values, self.boundaries))
                or self.absent + self.none + self.empty_list + self.values != self.slots):
            raise ValueError('context slot coverage partition is not closed')


@dataclass(frozen=True, slots=True)
class ContextFrontier:
    code: str
    site: SlotRef | None
    processed_slots: int
    detail: str


@dataclass(frozen=True, slots=True)
class SourceContextsProfile:
    rule_version: str
    f2_schema_sha256: str
    role_catalog_sha256: str
    context_catalog_sha256: str
    implementation_sha256: str


@dataclass(frozen=True, slots=True)
class SourceContextsInput:
    f0_document_sha256: str
    f1_document_sha256: str
    f2_document_sha256: str
    f3b_document_sha256: str
    path: str
    mode: str
    f2_status: str
    f3b_status: str


@dataclass(frozen=True, slots=True)
class SourceContextsMaterial:
    input: SourceContextsInput
    profile: SourceContextsProfile
    max_scopes: int
    max_regions: int
    max_boundaries: int
    max_slots: int
    status: str
    root_context: ContextState | None
    scopes: tuple[SourceScope, ...]
    regions: tuple[EvaluationRegion, ...]
    private_contexts: tuple[PrivateContext, ...]
    boundaries: tuple[ContextBoundary, ...]
    counts: tuple[RuleContextCount, ...]
    slots: int
    frontiers: tuple[ContextFrontier, ...]
    authority: str = 'SOURCE_CONTEXT_TEMPLATES'
    compiler_projection: str = 'NOT_COMPUTED_IN_C1'
    runtime_frames: str = 'NOT_RECORDED'
    schema: str = 'scar.source-contexts'
    schema_version: int = 1

    def __post_init__(self):
        if (self.schema != 'scar.source-contexts' or type(self.schema_version) is not int or self.schema_version != 1
                or self.authority != 'SOURCE_CONTEXT_TEMPLATES' or self.compiler_projection != 'NOT_COMPUTED_IN_C1'
                or self.runtime_frames != 'NOT_RECORDED'
                or self.status not in ('CONTEXTUALIZED', 'UPSTREAM_NOT_CLASSIFIED', 'BUDGET_STOPPED')
                or any(type(n) is not int or n < 0 for n in (self.max_scopes, self.max_regions,
                    self.max_boundaries, self.max_slots, self.slots))
                or tuple(c.rule for c in self.counts) != tuple(range(484))
                or sum(c.slots for c in self.counts) != self.slots
                or sum(c.boundaries for c in self.counts) != len(self.boundaries)
                or self.slots > self.max_slots or len(self.scopes) > self.max_scopes
                or len(self.regions) > self.max_regions or len(self.boundaries) > self.max_boundaries):
            raise ValueError('invalid C1 context envelope or coverage counters')
        if self.status == 'CONTEXTUALIZED':
            valid = self.root_context is not None and bool(self.scopes) and bool(self.regions) and bool(self.private_contexts) and not self.frontiers
        else:
            valid = self.root_context is None and not (self.scopes or self.regions or self.private_contexts or self.boundaries or self.slots)
            valid = valid and bool(self.frontiers) == (self.status == 'BUDGET_STOPPED')
        if not valid:
            raise ValueError('C1 status contradicts its context tables')
