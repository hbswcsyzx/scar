"""C3-T source-anchored compiler scope templates, not runtime/code-object IDs."""
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TopologyFieldRule:
    id: int
    constructor: str
    group: str
    ordinal: int
    name: str
    dispatch: str


@dataclass(frozen=True, slots=True)
class TopologyConstructor:
    name: str
    dispatch: str
    fields: tuple[int, ...]
    attributes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class TopologyCatalog:
    rule_version: str
    f2_schema_sha256: str
    context_catalog_sha256: str
    constructors: tuple[TopologyConstructor, ...]
    fields: tuple[TopologyFieldRule, ...]
    origin_roles: tuple[str, ...]
    projections: tuple[str, ...]
    attachments: tuple[str, ...]
    scope_dispositions: tuple[str, ...]
    rewrite_rules: tuple[str, ...]
    content_sha256: str
    schema: str = 'scar.compiler-topology-catalog'
    schema_version: int = 1


@dataclass(frozen=True, slots=True)
class BlockOrigin:
    occurrence: int
    role: str

    def __post_init__(self):
        if type(self.occurrence) is not int or self.occurrence < 0 or type(self.role) is not str:
            raise ValueError('invalid compiler block source origin')


@dataclass(frozen=True, slots=True)
class CompilerBlock:
    origin: BlockOrigin
    parent: int | None
    children: tuple[int, ...]
    source_scope: int | None
    can_see_class_scope: bool
    attachment: str
    projection: str
    public_scope: int | None


@dataclass(frozen=True, slots=True)
class ProjectionStep:
    rule: str
    block: int
    parent: int | None


@dataclass(frozen=True, slots=True)
class SourceScopeProjection:
    scope: int
    block: int | None
    disposition: str


@dataclass(frozen=True, slots=True)
class TopologyFrontier:
    code: str
    origin: BlockOrigin | None
    detail: str


@dataclass(frozen=True, slots=True)
class CompilerTopologyInput:
    f0_document_sha256: str
    f1_document_sha256: str
    f2_document_sha256: str
    f3b_document_sha256: str
    c1_document_sha256: str
    f3a_document_sha256: str
    path: str
    mode: str
    c1_status: str
    f3a_status: str
    source_scope_count: int
    native_scope_count: int


@dataclass(frozen=True, slots=True)
class CompilerTopologyProfile:
    rule_version: str
    f2_schema_sha256: str
    context_catalog_sha256: str
    topology_catalog_sha256: str
    native_profile_sha256: str
    implementation_sha256: str


@dataclass(frozen=True, slots=True)
class CompilerTopologyMaterial:
    input: CompilerTopologyInput
    profile: CompilerTopologyProfile
    max_blocks: int
    max_rewrites: int
    max_visit_steps: int
    status: str
    blocks: tuple[CompilerBlock, ...]
    scopes: tuple[SourceScopeProjection, ...]
    rewrites: tuple[ProjectionStep, ...]
    frontiers: tuple[TopologyFrontier, ...]
    visit_steps: int
    authority: str = 'SOURCE_COMPILER_TOPOLOGY'
    symbol_origin_projection: str = 'NOT_COMPUTED_IN_C3T'
    parameter_projection: str = 'NOT_COMPUTED_IN_C3T'
    runtime_execution: str = 'NOT_OBSERVED'
    schema: str = 'scar.compiler-topology'
    schema_version: int = 1

    def __post_init__(self):
        if (self.schema != 'scar.compiler-topology' or type(self.schema_version) is not int or self.schema_version != 1
                or self.authority != 'SOURCE_COMPILER_TOPOLOGY'
                or self.symbol_origin_projection != 'NOT_COMPUTED_IN_C3T'
                or self.parameter_projection != 'NOT_COMPUTED_IN_C3T'
                or self.runtime_execution != 'NOT_OBSERVED'
                or any(type(n) is not int or n < 0 for n in (
                    self.max_blocks, self.max_rewrites, self.max_visit_steps, self.visit_steps))
                or len(self.blocks) > self.max_blocks or len(self.rewrites) > self.max_rewrites
                or self.visit_steps > self.max_visit_steps):
            raise ValueError('invalid C3-T topology envelope/budgets')
        if self.status == 'PROJECTED':
            valid = bool(self.blocks) and len(self.scopes) == self.input.source_scope_count and not self.frontiers
        elif self.status == 'SOURCE_ONLY_MODE':
            valid = (not self.blocks and not self.rewrites and not self.frontiers
                and len(self.scopes) == self.input.source_scope_count
                and all(row.block is None and row.disposition == 'GRAMMAR_ONLY' for row in self.scopes))
        else:
            valid = (self.status in ('UPSTREAM_NOT_CONTEXTUALIZED', 'UPSTREAM_NOT_CAPTURED',
                'BUDGET_STOPPED', 'PROJECTION_CONTRADICTION')
                and not (self.blocks or self.scopes or self.rewrites) and bool(self.frontiers))
        if not valid:
            raise ValueError('C3-T status contradicts topology coverage')
