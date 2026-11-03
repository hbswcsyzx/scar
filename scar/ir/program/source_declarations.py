"""C2a name projection and whole-source-scope contribution ledgers."""
from dataclasses import dataclass

from .source_roles import SlotRef
from .source_contexts import OwnerRef


@dataclass(frozen=True, slots=True)
class LexicalField:
    constructor: str
    name: str


@dataclass(frozen=True, slots=True)
class DeclarationCatalog:
    rule_version: str
    projection_phase: str
    f2_schema_sha256: str
    role_catalog_sha256: str
    context_catalog_sha256: str
    lexical_fields: tuple[LexicalField, ...]
    operations: tuple[str, ...]
    visit_flags: tuple[str, ...]
    content_sha256: str
    schema: str = 'scar.source-declaration-catalog'
    schema_version: int = 1


@dataclass(frozen=True, slots=True)
class NameKey:
    value: str
    phase: str = 'SYMBOL_VISIT_PROJECTION'

    def __post_init__(self):
        if type(self.value) is not str or self.phase != 'SYMBOL_VISIT_PROJECTION':
            raise ValueError('invalid source name projection phase')


@dataclass(frozen=True, slots=True)
class NameProjection:
    value_rule: str
    private_mode: str
    class_owner: OwnerRef | None
    parameter_group: int | None
    prefix_count: int | None
    phase: str = 'SYMBOL_VISIT_PROJECTION'


@dataclass(frozen=True, slots=True)
class PortDisposition:
    port: int
    disposition: str
    source_scope: int
    region: int
    name: int | None
    projection: NameProjection
    contribution: int | None


@dataclass(frozen=True, slots=True)
class DeclarationContribution:
    """operations are syntax intent; visit_flags apply to home, not source_scope.

    A walrus can have different source_scope/home. Its compiler-generated
    origin directives are not inferred here. No field represents an execution.
    """
    port: int
    site: SlotRef
    source_scope: int
    home: int
    name: int
    operations: tuple[str, ...]
    visit_flags: tuple[str, ...]
    reason: str
    region: int
    analysis_visibility: str
    cleanup_policy: str


@dataclass(frozen=True, slots=True)
class ScopeDeclarations:
    """First-port order is a source ledger order, never native varnames layout."""
    scope: int
    names: tuple[int, ...]
    contributions: tuple[int, ...]
    directives: tuple[int, ...]
    wildcards: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class DeclarationConflict:
    code: str
    scope: int
    name: int | None
    ports: tuple[int, ...]
    detail: str


@dataclass(frozen=True, slots=True)
class DeclarationFrontier:
    code: str
    port: int | None
    processed_ports: int
    detail: str


@dataclass(frozen=True, slots=True)
class SourceDeclarationsInput:
    f0_document_sha256: str
    f1_document_sha256: str
    f2_document_sha256: str
    f3b_document_sha256: str
    c1_document_sha256: str
    path: str
    mode: str
    c1_status: str
    port_count: int


@dataclass(frozen=True, slots=True)
class SourceDeclarationsProfile:
    rule_version: str
    projection_phase: str
    f2_schema_sha256: str
    role_catalog_sha256: str
    context_catalog_sha256: str
    declaration_catalog_sha256: str
    implementation_sha256: str
    ordering_policy: str = 'B_PORT_FIRST_MENTION_NOT_RUNTIME_OR_NATIVE_LAYOUT'


@dataclass(frozen=True, slots=True)
class SourceDeclarationsMaterial:
    input: SourceDeclarationsInput
    profile: SourceDeclarationsProfile
    max_names: int
    max_contributions: int
    max_conflicts: int
    status: str
    names: tuple[NameKey, ...]
    ports: tuple[PortDisposition, ...]
    contributions: tuple[DeclarationContribution, ...]
    scopes: tuple[ScopeDeclarations, ...]
    conflicts: tuple[DeclarationConflict, ...]
    frontiers: tuple[DeclarationFrontier, ...]
    authority: str = 'SOURCE_NAME_DECLARATIONS'
    lookup_resolution: str = 'NOT_COMPUTED_IN_C2A'
    schema: str = 'scar.source-declarations'
    schema_version: int = 1

    def __post_init__(self):
        if (self.schema != 'scar.source-declarations' or type(self.schema_version) is not int or self.schema_version != 1
                or self.authority != 'SOURCE_NAME_DECLARATIONS' or self.lookup_resolution != 'NOT_COMPUTED_IN_C2A'
                or self.status not in ('DECLARED', 'UPSTREAM_NOT_CONTEXTUALIZED', 'BUDGET_STOPPED')
                or any(type(n) is not int or n < 0 for n in (self.max_names, self.max_contributions, self.max_conflicts))
                or len(self.names) > self.max_names or len(self.contributions) > self.max_contributions
                or len(self.conflicts) > self.max_conflicts):
            raise ValueError('invalid C2a declaration envelope')
        if self.status == 'DECLARED':
            valid = len(self.ports) == self.input.port_count and not self.frontiers
        else:
            valid = not (self.names or self.ports or self.contributions or self.scopes or self.conflicts)
            valid = valid and bool(self.frontiers) == (self.status == 'BUDGET_STOPPED')
        if not valid:
            raise ValueError('C2a status and coverage tables disagree')
