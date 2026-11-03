"""C2b logical namespace templates; IDs are local material ordinals."""
from dataclasses import dataclass
from .source_roles import SlotRef


@dataclass(frozen=True, slots=True)
class NameRef:
    kind: str
    index: int | None = None
    symbol: str | None = None

    def __post_init__(self):
        if self.kind == 'SOURCE':
            valid = type(self.index) is int and self.index >= 0 and self.symbol is None
        else:
            valid = self.kind == 'LANGUAGE' and self.index is None and self.symbol in (
                '__class__', '__classdict__', '__conditional_annotations__')
        if not valid:
            raise ValueError('invalid source/language name reference')


@dataclass(frozen=True, slots=True)
class BindingCatalog:
    rule_version: str
    projection_phase: str
    f2_schema_sha256: str
    context_catalog_sha256: str
    declaration_catalog_sha256: str
    rules: tuple[str, ...]
    interface_kinds: tuple[str, ...]
    classifications: tuple[str, ...]
    port_dispositions: tuple[str, ...]
    activations: tuple[str, ...]
    capture_accesses: tuple[str, ...]
    binding_domains: tuple[str, ...]
    missing_outcomes: tuple[str, ...]
    content_sha256: str
    schema: str = 'scar.source-binding-catalog'
    schema_version: int = 1


@dataclass(frozen=True, slots=True)
class BindingSlot:
    """cell_required records a cross-source-scope capture obligation only.

    False does not rule out synthetic compiler cells. Neither value proves a
    physical allocation or the C3 compiler layout.
    """
    domain: str
    owner: int
    name: NameRef
    cell_required: bool
    evidence: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class EnvironmentInterface:
    """owner is a static environment template, never a runtime dictionary ID."""
    kind: str
    owner: int
    binding: int | None = None


@dataclass(frozen=True, slots=True)
class LookupStep:
    interface: int
    on_hit: str = 'RETURN_VALUE'
    on_miss: str = 'NEXT'
    on_exception: str = 'PROPAGATE'


@dataclass(frozen=True, slots=True)
class LookupPlan:
    """Key comes from its referencing port/implicit requirement's NameRef."""
    steps: tuple[LookupStep, ...]
    missing_outcome: str


@dataclass(frozen=True, slots=True)
class ScopeNameResolution:
    scope: int
    name: NameRef
    classification: str
    binding: int | None
    reason: str
    evidence: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class PortResolution:
    port: int
    disposition: str
    source_scope: int
    home: int
    name: NameRef | None
    declref: int | None
    resolution: int | None
    read_plan: int | None
    write_target: int | None
    delete_target: int | None
    activation: str
    analysis_visibility: str
    conflicts: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ForwardHop:
    """parent is the next shared hop ID, not a scope ID; None reaches owner."""
    scope: int
    binding: int
    parent: int | None


@dataclass(frozen=True, slots=True)
class CaptureDemand:
    requester: int
    binding: int
    access: str
    ports: tuple[int, ...]
    activation: str
    hop: int | None


@dataclass(frozen=True, slots=True)
class RootGlobalRequirement:
    name: NameRef
    ports: tuple[int, ...]
    rule: str


@dataclass(frozen=True, slots=True)
class ImplicitRequirement:
    scope: int
    region: int
    analysis_visibility: str
    name: NameRef
    rule: str
    anchor: SlotRef | None
    cause_ports: tuple[int, ...]
    binding: int | None
    resolution: int | None
    read_plan: int | None
    activation: str


@dataclass(frozen=True, slots=True)
class BindingConflict:
    code: str
    scope: int
    name: NameRef | None
    ports: tuple[int, ...]
    detail: str


@dataclass(frozen=True, slots=True)
class BindingFrontier:
    code: str
    port: int | None
    processed_ports: int
    detail: str


@dataclass(frozen=True, slots=True)
class ScopeBindings:
    scope: int
    resolutions: tuple[int, ...]
    captures: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class SourceBindingsInput:
    f0_document_sha256: str
    f1_document_sha256: str
    f2_document_sha256: str
    f3b_document_sha256: str
    c1_document_sha256: str
    c2a_document_sha256: str
    path: str
    mode: str
    c2a_status: str
    port_count: int
    scope_count: int


@dataclass(frozen=True, slots=True)
class SourceBindingsProfile:
    rule_version: str
    projection_phase: str
    f2_schema_sha256: str
    context_catalog_sha256: str
    declaration_catalog_sha256: str
    binding_catalog_sha256: str
    implementation_sha256: str
    ordering_policy: str = 'SOURCE_FIRST_DEMAND_NOT_RUNTIME_OR_NATIVE_LAYOUT'


@dataclass(frozen=True, slots=True)
class SourceBindingsMaterial:
    input: SourceBindingsInput
    profile: SourceBindingsProfile
    max_bindings: int
    max_interfaces: int
    max_plans: int
    max_plan_steps: int
    max_captures: int
    max_relays: int
    max_search_steps: int
    max_conflicts: int
    status: str
    bindings: tuple[BindingSlot, ...]
    interfaces: tuple[EnvironmentInterface, ...]
    plans: tuple[LookupPlan, ...]
    ports: tuple[PortResolution, ...]
    resolutions: tuple[ScopeNameResolution, ...]
    scopes: tuple[ScopeBindings, ...]
    captures: tuple[CaptureDemand, ...]
    relays: tuple[ForwardHop, ...]
    root_globals: tuple[RootGlobalRequirement, ...]
    implicit: tuple[ImplicitRequirement, ...]
    conflicts: tuple[BindingConflict, ...]
    frontiers: tuple[BindingFrontier, ...]
    search_steps: int
    authority: str = 'SOURCE_NAMESPACE_TEMPLATES'
    runtime_binding: str = 'NOT_OBSERVED'
    compiler_projection: str = 'NOT_COMPUTED_IN_C2B'
    schema: str = 'scar.source-bindings'
    schema_version: int = 1

    def __post_init__(self):
        limits = (self.max_bindings, self.max_interfaces, self.max_plans, self.max_plan_steps,
            self.max_captures, self.max_relays, self.max_search_steps, self.max_conflicts)
        if (self.schema != 'scar.source-bindings' or type(self.schema_version) is not int or self.schema_version != 1
                or self.authority != 'SOURCE_NAMESPACE_TEMPLATES' or self.runtime_binding != 'NOT_OBSERVED'
                or self.compiler_projection != 'NOT_COMPUTED_IN_C2B'
                or any(type(n) is not int or n < 0 for n in limits)
                or type(self.search_steps) is not int or not 0 <= self.search_steps <= self.max_search_steps
                or len(self.bindings) > self.max_bindings or len(self.interfaces) > self.max_interfaces
                or len(self.plans) > self.max_plans or sum(len(p.steps) for p in self.plans) > self.max_plan_steps
                or len(self.captures) > self.max_captures or len(self.relays) > self.max_relays
                or len(self.conflicts) > self.max_conflicts):
            raise ValueError('invalid C2b namespace envelope/budgets')
        tables = (self.bindings, self.interfaces, self.plans, self.ports, self.resolutions,
            self.scopes, self.captures, self.relays, self.root_globals, self.implicit, self.conflicts)
        if self.status in ('RESOLVED', 'RESOLVED_WITH_CONFLICTS'):
            valid = (len(self.ports) == self.input.port_count and len(self.scopes) == self.input.scope_count
                and not self.frontiers and bool(self.conflicts) == (self.status == 'RESOLVED_WITH_CONFLICTS'))
        else:
            valid = (self.status in ('UPSTREAM_NOT_DECLARED', 'BUDGET_STOPPED') and not any(tables)
                and bool(self.frontiers) == (self.status == 'BUDGET_STOPPED'))
        if not valid:
            raise ValueError('C2b status and namespace tables disagree')
